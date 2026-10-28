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
from job_policy import Constraint, Extraction, RequirementCheck, PreferenceConflict, deduplicate_checks, deduplicate_conflicts

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


def standing_notes(cv):
    """Only the explicit notes section is preference evidence, never arbitrary CV prose."""
    matches = list(re.finditer(
        r'(?im)^\s*(?P<hashes>#{1,6}\s*)?(?P<label>(?:Recent Experience & )?Standing Notes)\s*:?[^\S\n]*$', cv))
    if not matches:
        return ''
    match = matches[-1]
    tail = cv[match.end():]
    # load_effective_cv appends the separate notes file under this exact marker.
    # Its nested headings are still notes. A CV's own markdown section ends at
    # the next heading of the same or higher level.
    if match['label'].lower().startswith('recent experience'):
        return tail
    level = len((match['hashes'] or '').strip())
    heading_pattern = r'(?m)^#{1,' + str(level or 6) + r'}\s+\S'
    heading = re.search(heading_pattern, tail)
    return tail[:heading.start()] if heading else tail


_HARD_PREFERENCE = re.compile(r'\b(?:only|never|must|not willing|requires|ausschlie[ßs]lich|nur|niemals|muss)\b', re.I)


def ground_match_checks(checks, conflicts, posting, cv):
    grounded, kept, issues = [], [], []
    for i, item in enumerate(checks):
        item = dict(item)
        span = grounded_span(posting, item.get('posting_quote', ''))
        if span is None:
            # Reject instead of dropping a missing must-have and improving the rating.
            issues.append({'path': f'match_checks.{i}.posting_quote', 'type': 'ungrounded_requirement',
                           'message': 'Requirement quote is absent from the posting; correct the checklist'})
            continue
        item['posting_quote'] = span
        if item['coverage'] == 'missing':
            item['cv_quote'] = ''
        else:
            cv_span = grounded_span(cv, item.get('cv_quote', ''))
            if cv_span is None:
                issues.append({'path': f'match_checks.{i}.cv_quote', 'type': 'ungrounded_cv_quote',
                               'message': 'CV quote is absent from the CV; counted as missing'})
                item.update(coverage='missing', cv_quote='')
            else:
                item['cv_quote'] = cv_span
        grounded.append(item)
    notes_source = standing_notes(cv)
    for i, conflict in enumerate(conflicts):
        notes = grounded_span(notes_source, conflict.get('notes_quote', ''))
        post = grounded_span(posting, conflict.get('posting_quote', ''))
        if notes is None or post is None:
            issues.append({'path': f'preference_conflicts.{i}', 'type': 'ungrounded_conflict',
                           'message': 'Preference conflict lacks verified Standing Notes or posting evidence; omitted'})
            continue
        conflict = dict(conflict, notes_quote=notes, posting_quote=post)
        if conflict['severity'] == 'hard' and not _HARD_PREFERENCE.search(notes):
            conflict['severity'] = 'soft'
            issues.append({'path': f'preference_conflicts.{i}.severity', 'type': 'unverified_hard_preference',
                           'message': 'Standing Notes do not state a hard condition; counted as soft'})
        kept.append(conflict)
    return deduplicate_checks(grounded), deduplicate_conflicts(kept), issues


class AnalysisValidationError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('AI extraction validation failed: ' + '; '.join(
            f"{issue['path']}: {issue['message']}" for issue in issues[:MAX_ITEMS]))


def _safe_path(location):
    allowed = set(Extraction.model_fields) | {'kind', 'strength', 'value', 'evidence',
                                            'requirement', 'importance', 'posting_quote', 'coverage', 'cv_quote', 'preference', 'notes_quote', 'severity',
                                            'tier', 'synthesis', 'strengths', 'gaps', 'tips', 'title', 'detail'}
    return '.'.join(str(part) if isinstance(part, int) or part in allowed else '<unknown>'
                    for part in location)


def validate_extraction(data, source, matching, cv_text=''):
    try:
        validated = Extraction.model_validate(data)
    except ValidationError as error:
        # Exclude input/context: both may contain echoed CV prose or unknown keys.
        issues = [{'path': _safe_path(item['loc']), 'message': item['msg'], 'type': item['type']}
                  for item in error.errors(include_input=False, include_context=False, include_url=False)]
        raise AnalysisValidationError(issues) from None
    validated.grounding_issues = []  # Never accept model-supplied diagnostic prose.
    issues = []
    if matching and validated.match_checks is None:
        issues.append({'path': 'match_checks', 'message': 'Matching returned no checklist; analysis remains pending',
                       'type': 'missing_checklist'})
    if matching and validated.match_checks == [] and validated.requirements:
        issues.append({'path': 'match_checks', 'message': 'Stated requirements need a matching checklist',
                       'type': 'missing_checklist'})
    if matching and validated.match_checks is not None:
        checks, conflicts, grounding = ground_match_checks(
            [c.model_dump() for c in validated.match_checks],
            [c.model_dump() for c in validated.preference_conflicts], source, cv_text)
        issues.extend(i for i in grounding if i['type'] == 'ungrounded_requirement')
        validated.match_checks = [RequirementCheck.model_validate(c) for c in checks]
        validated.preference_conflicts = [PreferenceConflict.model_validate(c) for c in conflicts]
        validated.grounding_issues = grounding
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
            for collection, fields, enums in (
                ('match_checks', ('requirement', 'posting_quote', 'cv_quote'),
                 {'importance': ('must', 'nice'), 'coverage': ('shown', 'related', 'missing')}),
                ('preference_conflicts', ('preference', 'notes_quote', 'posting_quote'),
                 {'severity': ('hard', 'soft')}),
            ):
                values = data.get(collection)
                if isinstance(values, list):
                    extraction[collection + '_count'] = len(values)
                    extraction[collection] = [
                        {**{key: _text_metadata(item.get(key)) for key in fields},
                         **{key: item[key] for key, allowed in enums.items() if item.get(key) in allowed}}
                        if isinstance(item, dict) else {'type': type(item).__name__}
                        for item in values[:MAX_ITEMS]]
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
