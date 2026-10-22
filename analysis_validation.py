"""Ground extraction against raw postings; retain bounded, private failure metadata.

Never persist model prose, candidate analysis, prompts, or ungrounded quotes.
Rejected free text is represented by length/hash, not a reversible excerpt.
"""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import time
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from job_policy import Constraint, Extraction

logger = logging.getLogger(__name__)
MAX_RECORDS = 200
MAX_AGE_SECONDS = 30 * 86400
MAX_ITEMS = 64


def grounded_span(source, quote):
    """Exact first; otherwise whitespace-only matching with raw span recovery."""
    if not quote or not quote.strip():
        return None
    if quote in source:
        return quote
    # Every non-whitespace character remains case/punctuation sensitive.
    # Match a contiguous span: no skipping words or joining separate excerpts.
    pattern = r'\s+'.join(re.escape(part) for part in quote.split())
    match = re.search(pattern, source)
    return match.group(0) if match else None


class AnalysisValidationError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('AI extraction validation failed: ' + '; '.join(
            f"{issue['path']}: {issue['message']}" for issue in issues[:MAX_ITEMS]))


def _safe_path(location):
    allowed = set(Extraction.model_fields) | {'kind', 'strength', 'value', 'evidence',
                                            'tier', 'synthesis', 'strengths', 'gaps', 'tips', 'title', 'detail'}
    return '.'.join(str(part) if isinstance(part, int) or part in allowed else '<unknown>'
                    for part in location)


def validate_extraction(data, source, matching):
    try:
        validated = Extraction.model_validate(data)
    except ValidationError as error:
        # Exclude input/context: both may contain echoed CV prose or unknown keys.
        issues = [{'path': _safe_path(item['loc']), 'message': item['msg'], 'type': item['type']}
                  for item in error.errors(include_input=False, include_context=False, include_url=False)]
        raise AnalysisValidationError(issues) from None
    issues = []
    if matching and validated.match_score is None:
        issues.append({'path': 'match_score', 'message': 'Matching returned no score; analysis remains pending',
                       'type': 'missing_score'})
    quotes = [('german_evidence', validated.german_evidence, validated.german_strength, validated)]
    quotes += [(f'constraints.{i}.evidence', c.evidence, c.strength, c)
               for i, c in enumerate(validated.constraints)]
    for path, quote, strength, target in quotes:
        if not quote.strip():
            if strength in ('required', 'preferred'):
                issues.append({'path': path, 'message': 'Requirement needs a quote from the posting',
                               'type': 'missing_evidence'})
            elif quote:
                # Whitespace alone is not evidence.
                issues.append({'path': path, 'message': 'Evidence must not be whitespace only',
                               'type': 'missing_evidence'})
            continue
        span = grounded_span(source, quote)
        if span is None:
            issues.append({'path': path, 'message': 'Requirement evidence is absent from the original posting',
                           'type': 'ungrounded_evidence'})
        elif isinstance(target, Extraction):
            target.german_evidence = span
        elif isinstance(target, Constraint):
            target.evidence = span
    if issues:
        raise AnalysisValidationError(issues)
    return validated


def _text_metadata(value):
    if not isinstance(value, str):
        return {'type': type(value).__name__}
    return {'length': len(value), 'sha256': hashlib.sha256(value.encode()).hexdigest()}


def _constraint_metadata(item):
    if not isinstance(item, dict):
        return {'type': type(item).__name__}
    result = {key: _text_metadata(item.get(key)) for key in ('kind', 'strength', 'value', 'evidence')}
    for key, permitted in (('kind', ('german', 'work_country', 'work_authorization', 'other')),
                           ('strength', ('required', 'preferred', 'unknown', 'none'))):
        if item.get(key) in permitted:
            result[key] = item[key]  # Include the known invalid 'none' for diagnosis, not acceptance.
    return result


def save_failure(source, model, attempt, data, response, issues):
    """Best effort; unique 0600 files, private directory, age/count retention.

    Allowlist schema enum/numeric values. All free text (even constraint values
    and rejected evidence) is hashed: a model can echo candidate secrets in ANY
    field, so field names alone are not a safe redaction boundary. Response hash
    correlates the initial rejected extraction without storing its unsafe body.
    """
    try:
        directory = Path(os.environ.get('JOBWEAVER_ANALYSIS_DIAGNOSTICS_DIR',
                                       str(Path(__file__).resolve().parent / 'logs' / 'analysis-failures')))
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError('Diagnostics directory is not private/owned')
        directory.chmod(0o700)
        extraction = {}
        if isinstance(data, dict):
            for key in ('german_level', 'german_strength', 'salary_currency', 'salary_period', 'work_model'):
                value = data.get(key)
                # Only schema-permitted enum tokens, never arbitrary model strings.
                permitted = {
                    'german_level': ('none', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2', 'native', 'unknown'),
                    'german_strength': ('required', 'preferred', 'none', 'unknown'),
                    'salary_currency': ('EUR', 'USD', 'GBP', 'CHF', 'unknown'),
                    'salary_period': ('month', 'year', None),
                    'work_model': ('Full-time', 'Part-time', 'Hybrid (Home Office)', 'Remote', 'On-site', 'Unknown'),
                }[key]
                if value in permitted:
                    extraction[key] = value
            extraction['german_evidence'] = _text_metadata(data.get('german_evidence'))
            constraints = data.get('constraints')
            if isinstance(constraints, list):
                extraction['constraints_count'] = len(constraints)
                extraction['constraints'] = [_constraint_metadata(item) for item in constraints[:MAX_ITEMS]]
            score = data.get('match_score')
            extraction['match_score'] = score if type(score) is int and 0 <= score <= 100 else _text_metadata(score)
        record = {'timestamp': datetime.now(timezone.utc).isoformat(), 'attempt': attempt,
                  'model': model[:200], 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
                  'response': _text_metadata(response), 'extraction': extraction,
                  'issues': issues[:MAX_ITEMS]}
        name = directory / f'failure-{time.time_ns()}-{uuid.uuid4().hex}.json'
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=True)
        records = sorted(directory.glob('failure-*.json'), key=lambda p: p.name, reverse=True)
        cutoff = time.time() - MAX_AGE_SECONDS
        for index, path in enumerate(records):
            try:
                if index >= MAX_RECORDS or path.lstat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                pass  # Concurrent writers/pruners may already have removed it.
    except (OSError, ValueError, TypeError):
        logger.warning('Could not save private AI validation diagnostics')
