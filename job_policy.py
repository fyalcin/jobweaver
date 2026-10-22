"""Typed extraction and deterministic eligibility/ranking helpers."""
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from german import german_level_compatible, normalize_german_level


class AnalysisPoint(BaseModel):
    # Display-only prose, not grounded evidence: models sometimes add a key
    # (seen 09.10 and 12.10.2026), which is safe to drop rather than fail on.
    model_config = ConfigDict(extra='ignore')
    title: StrictStr
    detail: StrictStr


class MatchAnalysis(BaseModel):
    tier: StrictStr = ''  # Ignored: tier always comes from validated score.
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
    match_score: StrictInt | None = Field(default=None, ge=0, le=100)
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
        # With a CV the score and analysis must be present, not null.
        schema['properties']['match_score'] = {'type': 'integer'}
        schema['properties']['match_analysis'] = {'$ref': '#/$defs/MatchAnalysis'}
    else:
        for key in ('match_score', 'match_analysis'):
            schema['properties'].pop(key)
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


def tier(score):
    if score is None:
        return 'Not ranked'
    return 'Strong Match' if score >= 80 else 'Good Match' if score >= 65 else 'Moderate Match' if score >= 50 else 'Reach'


def fingerprint(cv, model, policy=None):
    return hashlib.sha256(json.dumps({'cv': cv or '', 'model': model, 'policy': policy or {}, 'schema': 1},
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
    score = job.get('match_score')
    # Pandas represents validated integer DB scores as floats beside nulls.
    if isinstance(score, float) and score.is_integer():
        score = int(score)
    return ((expected_fingerprint is None or job.get('analysis_fingerprint') == expected_fingerprint)
            and isinstance(score, int) and not isinstance(score, bool)
            and score > config.get('auto_generate', {}).get('min_match_score', 65)
            and eligibility(job, config)['state'] == 'eligible')
