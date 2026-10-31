"""Typed extraction and deterministic eligibility/ranking helpers."""
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from german import german_level_compatible, normalize_german_level


class AnalysisPoint(BaseModel):
    # Display-only prose, not grounded evidence: models sometimes add a key
    # (seen 09.10 and 12.10.2026), which is safe to drop rather than fail on.
    model_config = ConfigDict(extra='ignore')
    title: StrictStr
    detail: StrictStr


class MatchAnalysis(BaseModel):
    tier: StrictStr = ''  # Legacy display key; overwritten by the deterministic rating.
    synthesis: StrictStr = ''
    strengths: list[AnalysisPoint] = Field(default_factory=list)
    gaps: list[AnalysisPoint] = Field(default_factory=list)
    tips: list[AnalysisPoint] = Field(default_factory=list)


class Constraint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['german', 'work_country', 'work_authorization', 'other']
    strength: Literal['required', 'preferred', 'unknown']
    value: StrictStr
    evidence: StrictStr


class RequirementCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requirement: StrictStr = Field(min_length=1, max_length=500, pattern=r'\S')
    importance: Literal['must', 'nice']
    posting_quote: StrictStr = Field(min_length=1, max_length=4000)
    coverage: Literal['shown', 'related', 'missing']
    cv_quote: StrictStr = Field(default='', max_length=4000)


class PreferenceConflict(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preference: StrictStr = Field(min_length=1, max_length=500, pattern=r'\S')
    notes_quote: StrictStr = Field(min_length=1, max_length=4000)
    posting_quote: StrictStr = Field(min_length=1, max_length=4000)
    severity: Literal['hard', 'soft']


class Extraction(BaseModel):
    german_level: Literal['none', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2', 'native', 'unknown']
    summary: StrictStr = Field(min_length=1)
    skills: StrictStr = 'Not Specified'
    minimum_salary: StrictStr = 'Not Specified'
    salary_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    salary_period: Literal['month', 'year'] | None = None
    salary_currency: Literal['EUR', 'USD', 'GBP', 'CHF', 'unknown'] = 'unknown'
    salary_payments: int | None = Field(default=None, ge=1, le=24)
    salary_country: StrictStr = ''
    match_checks: list[RequirementCheck] | None = Field(default=None, max_length=128)
    preference_conflicts: list[PreferenceConflict] = Field(default_factory=list, max_length=32)
    grounding_issues: list[dict] = Field(default_factory=list, exclude=True)
    match_analysis: MatchAnalysis | None = None
    tools_technologies: list[StrictStr] = Field(default_factory=list)
    requirements: list[StrictStr] = Field(default_factory=list)
    tasks: list[StrictStr] = Field(default_factory=list)
    work_model: Literal['Full-time', 'Part-time', 'Hybrid (Home Office)', 'Remote', 'On-site', 'Unknown'] = 'Unknown'
    experience_years: StrictStr = 'Not Specified'
    education_level: StrictStr = 'Not Specified'
    company_summary: StrictStr | None = None
    company_contact: StrictStr | None = None
    german_strength: Literal['required', 'preferred', 'none', 'unknown'] = 'unknown'
    german_evidence: StrictStr = ''
    constraints: list[Constraint] = Field(default_factory=list)


# Keywords kept when turning the pydantic schema into a strict structured-output
# schema. Numeric/length limits are dropped (not every provider supports them);
# validate_extraction still enforces them afterwards.
_SCHEMA_KEYS = {'type', 'enum', 'items', 'properties', 'anyOf', 'description'}


def _strict(node, defs):
    if '$ref' in node:
        return _strict(defs[node['$ref'].split('/')[-1]], defs)
    out = {k: v for k, v in node.items() if k in _SCHEMA_KEYS}
    if 'items' in out:
        out['items'] = _strict(out['items'], defs)
    if 'anyOf' in out:
        out['anyOf'] = [_strict(option, defs) for option in out['anyOf']]
    if 'properties' in out:
        out['properties'] = {k: _strict(v, defs) for k, v in out['properties'].items()}
        # Strict mode: every key present, no others.
        out['required'] = list(out['properties'])
        out['additionalProperties'] = False
    return out


def analysis_response_format(matching: bool, include_cleanup: bool) -> dict:
    """OpenRouter `response_format` for job analysis, generated from Extraction.

    The provider then guarantees valid JSON, allowed enum values and no extra
    keys. Evidence grounding is not something a schema can express and is still
    checked by validate_extraction.
    """
    schema = Extraction.model_json_schema()
    defs = schema.get('$defs', {})
    if matching:
        schema['properties']['match_checks'] = {'type': 'array', 'items': {'$ref': '#/$defs/RequirementCheck'}}
        schema['properties']['match_analysis'] = {'$ref': '#/$defs/MatchAnalysis'}
    else:
        for key in ('match_checks', 'preference_conflicts', 'match_analysis'):
            schema['properties'].pop(key)
    schema['properties'].pop('grounding_issues', None)
    defs['MatchAnalysis']['properties'].pop('tier', None)
    if include_cleanup:
        schema['properties']['cleaned_description'] = {'type': 'string'}
    return {'type': 'json_schema',
            'json_schema': {'name': 'job_analysis', 'strict': True, 'schema': _strict(schema, defs)}}


# Words that open an ad's requirements section (German and English). An ad text without any of them was most
# likely cut short by its scraper: the karriere.at browser scraper lost the second half of 14 % of its ads
# (1.9 % via the Apify actor, measured 15.10.2026), and that half is where the German requirement usually is.
_REQUIREMENTS_MARKER = re.compile(
    r"anforderung|qualifikation|dein profil|ihr profil|deine skills|das bringst du mit|das bringen sie mit|"
    r"was du mitbringst|was sie mitbringen|mitbringen|voraussetzung|requirements|qualifications|your profile|"
    r"what you bring|what we expect|who you are|must[- ]have|you have|you bring|dein background|"
    r"ihre kenntnisse|deine kenntnisse|kompetenzen|erfahrung", re.I)
INCOMPLETE_DESCRIPTION = 'Ad text may be cut off (no requirements section); check the full ad'


def description_incomplete(text):
    """True when a non-empty ad text has no requirements section, so its German level cannot be trusted."""
    return isinstance(text, str) and bool(text.strip()) and not _REQUIREMENTS_MARKER.search(text)


# Evidence-based match rating. The model only
# judges single requirements; this fixed rule turns the verified judgements into a label.
RATINGS = ('Poor', 'Stretch', 'Decent', 'Good', 'Great')
_COVERAGE = {'shown', 'related', 'missing'}
_SEVERITY = {'soft', 'hard'}


def _base_rating(checks):
    for check in checks:
        if check.get('coverage') not in _COVERAGE or check.get('importance') not in ('must', 'nice'):
            raise ValueError(f'Unknown requirement check: {check!r}')
    checks = deduplicate_checks(checks)
    must = [c for c in checks if c['importance'] == 'must']
    nice = [c for c in checks if c['importance'] == 'nice']
    pool = must or nice
    missing = sum(c['coverage'] == 'missing' for c in pool)
    related = sum(c['coverage'] == 'related' for c in pool)
    share = missing / len(pool)
    nice_covered = not nice or sum(c['coverage'] != 'missing' for c in nice) >= len(nice) / 2
    if share == 0 and related <= 1 and nice_covered:
        level = 4
    elif share == 0:
        level = 3
    elif missing == 1 and share <= 1 / 3:
        level = 2
    elif share <= 1 / 2:
        level = 1
    else:
        level = 0
    # A posting without firm requirements cannot earn the top label.
    return level if must else min(level, 3)


def match_rating(checks, conflicts=(), eligibility_state='eligible'):
    """Label from requirement checks, preference conflicts and the eligibility state."""
    for conflict in conflicts:
        if conflict.get('severity') not in _SEVERITY:
            raise ValueError(f'Unknown preference conflict: {conflict!r}')
    if eligibility_state == 'ineligible' or any(c['severity'] == 'hard' for c in conflicts):
        return 'Blocked'
    if not checks:
        return 'Unrated'
    soft = sum(c['severity'] == 'soft' for c in deduplicate_conflicts(conflicts))
    return RATINGS[max(0, _base_rating(checks) - soft)]


def judgement_calls(checks, conflicts=(), eligibility_state='eligible'):
    """Related must-haves whose downgrade to missing would change the label."""
    checks = deduplicate_checks(checks)
    label = match_rating(checks, conflicts, eligibility_state)
    if label not in RATINGS:
        return []
    calls = []
    for i, check in enumerate(checks):
        if check['importance'] != 'must' or check['coverage'] != 'related':
            continue
        changed = [dict(c, coverage='missing') if j == i else c for j, c in enumerate(checks)]
        alternative = match_rating(changed, conflicts, eligibility_state)
        if alternative != label:
            calls.append({'requirement': check['requirement'], 'if_missing': alternative})
    return calls


def _identity(text):
    return ' '.join(str(text).casefold().split()).strip(' .,;:!?')


def deduplicate_checks(checks):
    """Repeated evidence cannot improve the tally. Retain the stricter duplicate."""
    result = []
    for check in checks:
        previous = next((c for c in result if _identity(c['requirement']) == _identity(check['requirement'])), None)
        if previous is None:
            result.append(dict(check))
        else:
            if check['importance'] == 'must' and previous['importance'] != 'must':
                previous.update(importance='must', posting_quote=check['posting_quote'])
            if ('shown', 'related', 'missing').index(check['coverage']) > ('shown', 'related', 'missing').index(previous['coverage']):
                previous.update(coverage=check['coverage'], cv_quote=check.get('cv_quote', ''))
    return result


def deduplicate_conflicts(conflicts):
    result = []
    for conflict in conflicts:
        previous = next((c for c in result if _identity(c['preference']) == _identity(conflict['preference'])), None)
        if previous is None:
            result.append(dict(conflict))
        elif conflict['severity'] == 'hard' and previous['severity'] != 'hard':
            previous.update(severity='hard', notes_quote=conflict['notes_quote'],
                            posting_quote=conflict['posting_quote'])
    return result


def normalize_rating_config(config):
    """Read-time migration: old numeric thresholds deterministically become Good."""
    config = dict(config)
    auto = dict(config.get('auto_generate') or {})
    auto.pop('min_match_score', None)
    auto.setdefault('min_rating', 'good')
    config['auto_generate'] = auto
    return config


def analysis_current(job, expected_fingerprint):
    if job.get('analysis_fingerprint') or job.get('match_score') is not None or job.get('match_rating'):
        return (job.get('analysis_schema') == 2 and job.get('analysis_state') == 'complete'
                and bool(job.get('processed', 1)) and job.get('analysis_fingerprint') == expected_fingerprint)
    return None


def apply_rating(job, config, expected_fingerprint=None):
    """Refresh policy-dependent labels; preserve old numeric analyses as historical."""
    job['eligibility'] = eligibility(job, config)
    if expected_fingerprint is not None:
        job['analysis_current'] = analysis_current(job, expected_fingerprint)
    if job.get('analysis_schema') == 2:
        checks, conflicts = job.get('match_checks') or [], job.get('preference_conflicts') or []
        state = job['eligibility']['state']
        job['match_rating'] = match_rating(checks, conflicts, state)
        job['judgement_calls'] = judgement_calls(checks, conflicts, state)
    return job


def rating_sort_key(job):
    label = job.get('match_rating')
    rank = RATINGS.index(label) if job.get('analysis_current') is True and label in RATINGS else -1
    missing = sum(c.get('importance') == 'must' and c.get('coverage') == 'missing' for c in job.get('match_checks') or [])
    return rank, -missing, str(job.get('date_scraped') or '')


def fingerprint(cv, model, policy=None):
    return hashlib.sha256(json.dumps({'cv': cv or '', 'model': model, 'policy': policy or {}, 'schema': 2},
                                     sort_keys=True).encode()).hexdigest()


def eligibility(job, config):
    policy = config.get('eligibility_policy') or {}
    maximum = policy.get('german_level') or config.get('auto_generate', {}).get('max_german_level', 'B1')
    level = normalize_german_level(job.get('german_level'))
    strength = job.get('german_strength', 'unknown')
    blockers, unknowns = [], []
    if job.get('description_incomplete'):
        unknowns.append(INCOMPLETE_DESCRIPTION)
    if strength == 'required':
        if level == 'unknown':
            unknowns.append('Required German level is unclear')
        elif not german_level_compatible(level, maximum):
            blockers.append(f'German {level} required; policy allows {maximum}')
    elif strength == 'unknown':
        unknowns.append('German requirement needs review')
    for constraint in job.get('constraints') or []:
        if constraint.get('strength') == 'preferred':
            continue
        kind, value = constraint.get('kind'), constraint.get('value')
        if constraint.get('strength') == 'unknown':
            unknowns.append(f'Unclear requirement: {value}')
            continue
        if kind == 'german':
            continue
        allowed = policy.get('work_countries' if kind == 'work_country' else 'work_authorizations', [])
        if kind in ('work_country', 'work_authorization') and allowed:
            if value not in allowed:
                blockers.append(f'{kind}: {value} is outside your approved policy')
        else:
            unknowns.append(f'Review requirement: {value}')
    return {'state': 'ineligible' if blockers else 'needs_review' if unknowns else 'eligible',
            'blockers': blockers, 'unknowns': unknowns,
            'label': 'No known blocker' if not blockers and not unknowns else 'Eligibility needs review' if not blockers else 'Eligibility conflict'}


def qualifies(job, config, expected_fingerprint=None):
    config = normalize_rating_config(config)
    current = analysis_current(job, expected_fingerprint) if expected_fingerprint is not None else job.get('analysis_current')
    if current is not True or job.get('analysis_schema') != 2:
        return False
    state = eligibility(job, config)['state']
    label = match_rating(job.get('match_checks') or [], job.get('preference_conflicts') or [], state)
    minimum = config['auto_generate']['min_rating'].title()
    return state == 'eligible' and label in RATINGS and minimum in RATINGS and RATINGS.index(label) >= RATINGS.index(minimum)
