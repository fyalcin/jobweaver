"""Supervised model HTTP POSTs. Credentials travel only in the bounded stdin pipe.

The helper has no application imports, environment credentials, redirects or
ambient proxy/netrc authentication. Explicitly configured local endpoints work.
Each POST holds one shared model slot (`capacity.py`). The helper inherits the
slot descriptor and arms its own wall deadline, so a helper that outlives a
crashed parent keeps the slot until it terminates itself.

The parent refuses unattributed operations, enforces the owning User's daily
quota and records each attempt in the usage ledger (`model_usage.py`, imported
lazily so the helper never loads the database layer or dotenv).
"""
import base64
import json
import math
import os
import selectors
import signal
import subprocess
import sys

from jobweaver import PROJECT_ROOT
from jobweaver.operation_budget import current, operation, OperationTerminated, OperationExhausted, AttributionError

# Private seams for explicitly injected test fixtures (`tests/model_transport_fixture.py`).
# Production stays exec-only, records every POST in the durable ledger and refuses
# unattributed operations.
_post_impl = None
_ledger = None
_fixture_owner = None
_MAX_ENVELOPE = 14 * 1024 * 1024
_MAX_STDERR = 4096
# The parent kills first; this only bounds a helper whose parent died.
_HELPER_GRACE = 5.0
_MAX_HELPER_SECONDS = 7200


class ModelTransportError(OperationTerminated):
    """Dispatch outcome may be unknown; do not automatically retry."""


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


@operation()
def post_json(url, *, headers, json, timeout=300, label='model'):
    """One supervised POST, attributed, quota-checked and recorded in the usage ledger.

    Order: shared capacity slot, operation Budget reservation, durable quota
    reservation, dispatch. Busy (no slot) therefore consumes neither the operation
    allowance nor the daily quota. The Budget check is local and cheap, so the
    durable row is written only when dispatch follows immediately.
    """
    budget = current()
    if _fixture_owner is not None and budget.owner is None:
        budget.attribute(_fixture_owner, 'cli')
    if budget.owner is None:
        budget._stop(AttributionError('Model request refused: the operation has no owning User. Nothing was sent.'))
    body = _encode(json)
    prompt_size = sum(len(str(message.get('content', '')).encode('utf-8')) for message in json.get('messages', []))
    tokens = json.get('max_tokens', json.get('max_completion_tokens', 8000))
    envelope = _encode(dict(url=url, headers=headers, body=base64.b64encode(body).decode('ascii'),
                            timeout=min(timeout, budget.remaining()), limit=budget.limits.response_per_call))
    if len(envelope) > _MAX_ENVELOPE:
        raise OperationExhausted('Model request envelope exceeds transport limit.')
    from jobweaver import capacity
    ledger = _ledger if _ledger is not None else _usage_ledger()
    call = response = result = None
    try:
        # Busy raises before any reservation or dispatch; the slot outlives the helper.
        with capacity.acquire('model') as lease:
            budget.reserve(prompt_size, len(body), tokens)
            # One short transaction; no database connection stays open during the call.
            call = ledger.reserve(budget, url=url, payload=json, label=label, prompt_bytes=prompt_size,
                                  payload_bytes=len(body), output_tokens=tokens)
            if _post_impl is not None:
                response = _post_impl(url, headers=headers, json=json, timeout=min(timeout, budget.remaining()),
                                      allow_redirects=False)
                content = getattr(response, 'content', None)
                if not isinstance(content, (bytes, bytearray)):
                    content = _encode(response.json())  # Test fixture replies without raw bytes.
                status = getattr(response, 'status_code', None)
            else:
                result = _supervise(envelope, budget, lease)
                if 'error' in result:
                    raise ModelTransportError('Model transport failed; provider outcome may be unknown ('
                                              + result['error'] + ').')
                content, status = base64.b64decode(result['body'], validate=True), result['status']
    except BaseException:
        if call is not None:
            ledger.finish(call, 'unknown')  # Transport error, cancel or deadline: never zero.
        raise
    # Recorded before any response check, so fallbacks, 4xx and truncated replies all appear.
    ledger.finish(call, 'responded', ledger.response_fields(ledger.route_of(url)[0], status, content))
    if response is not None:
        # Test fixture responses retain their original public surface.
        budget.consume_response(len(content))
        return response
    import requests
    response = requests.Response()
    response.status_code = status
    response._content = content
    response._content_consumed = True
    response.encoding = 'utf-8'
    budget.consume_response(len(response.content))
    return response


def _usage_ledger():
    # Lazy and parent-only: the helper runs this module on its own and never loads db or dotenv.
    from jobweaver import model_usage
    return model_usage


def _supervise(envelope, budget, lease):
    """Kill and reap the helper on every path before the caller closes `lease`."""
    hard = min(budget.remaining() + _HELPER_GRACE, _MAX_HELPER_SECONDS)
    envelope = f'{hard:.3f}\n'.encode('ascii') + envelope
    cap = ((budget.limits.response_per_call + 2) // 3) * 4 + 4096
    environment = {key: value for key, value in os.environ.items()
                   if key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')}
    environment['PYTHON_DOTENV_DISABLED'] = '1'
    output, errors = bytearray(), bytearray()
    process = subprocess.Popen([sys.executable, '-m', 'jobweaver.model_transport', '--worker'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=PROJECT_ROOT, env=environment, pass_fds=(lease.fileno(),))
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, event in ((process.stdin, selectors.EVENT_WRITE), (process.stdout, selectors.EVENT_READ),
                                (process.stderr, selectors.EVENT_READ)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, event)
            offset = 0
            while selector.get_map():
                budget.check()
                for key, _ in selector.select(min(.05, budget.remaining())):
                    pipe = key.fileobj
                    if pipe is process.stdin:
                        count = os.write(pipe.fileno(), envelope[offset:offset + 65536])
                        offset += count
                        if offset == len(envelope):
                            selector.unregister(pipe)
                            pipe.close()
                    else:
                        chunk = os.read(pipe.fileno(), 65536)
                        if not chunk:
                            selector.unregister(pipe)
                            pipe.close()
                            continue
                        target, limit = (output, cap) if pipe is process.stdout else (errors, _MAX_STDERR)
                        if len(target) + len(chunk) > limit:
                            raise ModelTransportError('Model helper output exceeds transport limit.')
                        target.extend(chunk)
            while process.poll() is None:
                budget.wait(.01)
        budget.check()
        if process.returncode:
            raise ModelTransportError('Model helper failed; provider outcome may be unknown.')
        return json.loads(output)
    except OperationTerminated:
        raise
    except Exception as exc:
        raise ModelTransportError('Model transport failed; provider outcome may be unknown.') from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe and not pipe.closed:
                pipe.close()


def _worker():
    # Importing this file never loads server/db/dotenv or reads provider settings.
    # Arm the hard deadline before heavy imports or networking. Default SIGALRM
    # terminates the process; no Python exception handler can swallow it.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM})  # A blocked mask survives exec.
    try:
        seconds = float(sys.stdin.buffer.readline(64))
        if not (math.isfinite(seconds) and 0 < seconds <= _MAX_HELPER_SECONDS):
            raise ValueError('helper deadline')
    except ValueError:
        sys.stdout.buffer.write(_encode({'error': 'ValueError'}))
        return
    signal.setitimer(signal.ITIMER_REAL, seconds)
    import requests
    try:
        raw = sys.stdin.buffer.read(_MAX_ENVELOPE + 1)
        if len(raw) > _MAX_ENVELOPE:
            raise ValueError('request limit')
        options = json.loads(raw)
        from urllib.parse import urlsplit
        parsed = urlsplit(options['url'])
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('endpoint URL')
        limit = options['limit']
        if not isinstance(limit, int) or not 0 < limit <= 2 * 1024 * 1024:
            raise ValueError('response limit')
        with requests.Session() as session:
            session.trust_env = False
            headers = {**options['headers'], 'Accept-Encoding': 'identity'}
            with session.post(options['url'], headers=headers, data=base64.b64decode(options['body'], validate=True),
                              timeout=options['timeout'], stream=True, allow_redirects=False, verify=True) as response:
                if 300 <= response.status_code < 400:
                    raise ValueError('redirect refused')
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('encoded response refused')
                content = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    if len(content) + len(chunk) > limit:
                        raise ValueError('response limit')
                    content.extend(chunk)
                result = dict(status=response.status_code, body=base64.b64encode(content).decode('ascii'))
    except Exception as exc:
        # Exception text can contain URLs, headers or model prose. Never relay it.
        result = {'error': type(exc).__name__}
    sys.stdout.buffer.write(_encode(result))


if __name__ == '__main__':
    _worker()
