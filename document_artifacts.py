"""Validated PDFs and immutable source/build identities (no database imports)."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import uuid
from compiler_sandbox import run_tool
from operation_budget import check, current
from contextlib import contextmanager

MAX_PDF_BYTES = 12 * 1024 * 1024
BUILD_TIMEOUT = 45
_locks = {}
_guard = threading.Lock()


@contextmanager
def document_lock(path):
    with _guard:
        lock = _locks.setdefault(os.path.abspath(path), threading.RLock())
    shared = current()
    if shared is None:
        with lock:
            yield
        return
    while True:
        shared.check()
        if lock.acquire(timeout=min(.05, shared.remaining())):
            break
    try:
        shared.check()
        yield
    finally:
        lock.release()


def digest(value):
    return hashlib.sha256(value.encode('utf-8') if isinstance(value, str) else value).hexdigest()


def atomic_write(path, value):
    target = Path(path)
    if target.name == 'publication.json':
        check()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = value.encode('utf-8') if isinstance(value, str) else value
    fd, temp = tempfile.mkstemp(prefix='.write-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if target.name == 'publication.json':
            check()
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def inspect_pdf(path):
    """Validate a bounded PDF in isolation and return its hash and page count."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError('PDF is missing, empty or larger than 12 MiB')
    data = path.read_bytes()
    if not data.startswith(b'%PDF-'):
        raise ValueError('Uploaded/built file is not a PDF')
    with tempfile.TemporaryDirectory(prefix='pdf-inspect-') as temp:
        Path(temp, 'document.pdf').write_bytes(data)
        result = run_tool(['pdfinfo', 'document.pdf'], temp, timeout=10)
    info = result.stdout.decode('utf-8', errors='replace')
    pages = re.search(r'^Pages:\s+(\d+)', info, re.M)
    if result.returncode != 0 or not pages or not 0 < int(pages.group(1)) <= 30:
        raise ValueError('PDF cannot be parsed or exceeds 30 pages')
    if re.search(r'^Encrypted:\s+yes', info, re.M):
        raise ValueError('Encrypted PDFs are not supported')
    return {'hash': digest(data), 'pages': int(pages.group(1))}


def validate_pdf(path):
    return inspect_pdf(path)['hash']


def decode_pdf(encoded):
    if len(encoded) > ((MAX_PDF_BYTES + 2) // 3) * 4:
        raise ValueError('PDF upload exceeds 12 MiB')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid PDF base64') from exc
    with tempfile.TemporaryDirectory(prefix='pdf-check-') as temp:
        path = Path(temp) / 'upload.pdf'
        path.write_bytes(data)
        validate_pdf(path)
    return data


def record_build(pdf_path, source, engine, verified=True):
    record = {'revision': uuid.uuid4().hex, 'source_hash': digest(source),
              'pdf_hash': validate_pdf(pdf_path), 'engine': engine,
              'verified': verified}
    atomic_write(str(pdf_path) + '.build.json', json.dumps(record))
    atomic_write(str(pdf_path) + '.attempt.json', json.dumps({'success': True, 'source_hash': digest(source)}))
    return record


def matching_build(pdf_path, source):
    try:
        attempt = Path(str(pdf_path) + '.attempt.json')
        if attempt.exists() and not json.loads(attempt.read_text()).get('success'):
            return None
        record = json.loads(Path(str(pdf_path) + '.build.json').read_text())
        if record['source_hash'] != digest(source) or record['pdf_hash'] != validate_pdf(pdf_path):
            return None
        return record
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


def select_source(folder, prefix, safe_id, extension):
    """Record the active engine without deleting either engine's earlier source."""
    path = Path(folder, 'sources.json')
    selections = json.loads(path.read_text()) if path.exists() else {}
    selections[prefix] = extension
    atomic_write(path, json.dumps(selections))


def active_source(folder, prefix, safe_id):
    path = Path(folder, 'sources.json')
    extensions = ('typ', 'tex')
    if path.exists():
        selected = json.loads(path.read_text()).get(prefix)
        if selected in extensions:
            extensions = (selected,)
    return next((str(Path(folder, f'{prefix}_{safe_id}.{ext}')) for ext in extensions
                 if Path(folder, f'{prefix}_{safe_id}.{ext}').exists()), None)
