#!/usr/bin/env python3
"""Career record: the one file of everything documents may say about a user (ADR-0004).

    uv run python career_record.py check PATH
    uv run python career_record.py text PATH     # plain text for job scoring (no excluded claims)

The record is YAML (format: docs/career-record/FORMAT.md; terms: GLOSSARY.md). Jobweaver owns only
the format and this checker; a user's real record lives outside the repository and is read from a
path in their settings. `check` prints one line per problem as `PATH:LINE: message` and exits 1, or
a short summary and exits 0. Warnings (for example CV claims without German wording) never fail it.
"""
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

FORMAT_VERSION = 1
OWNERSHIP_KINDS = ('own', 'adapted', 'steered', 'basics', 'cut')
ENTRY_TYPES = ('role', 'project', 'contribution', 'education', 'publication', 'skills', 'other')
MAX_STRETCHES = 2
ID = re.compile(r'^[a-z0-9][a-z0-9-]*$')
# A steered claim is AI-built work the user specified and operates: it may not be worded as authorship.
# "AI-built" is the honest description and stays allowed.
AUTHORSHIP_WORDS = re.compile(r'(?<!AI-)(?<!ai-)(?<!KI-)\b(built|build|wrote|write|written|developed|develop|implemented|coded|'
                              r'authored|entwickelt\w*|geschrieben|programmiert\w*|gebaut\w*|implementiert\w*)\b', re.I)
STEERED_WORDS = re.compile(r'\b(specif\w*|operat\w*|spezifiz\w*|betreib\w*)\b', re.I)
ADAPTED_WORDS = re.compile(r'\b(adapt\w*|angepasst\w*)', re.I)

TOP_KEYS = {'format': True, 'name': True, 'applicant_facts': False, 'application_policies': False,
            'role_families': True, 'entries': True, 'forbidden_phrases': False}
FACT_KEYS = {'id': True, 'text': True, 'de': False, 'link': False}
POLICY_KEYS = {'id': True, 'rule': True}
FAMILY_KEYS = {'id': True, 'label': True, 'headline': True, 'headline_de': False, 'terms': False}
ENTRY_KEYS = {'id': True, 'type': True, 'title': True, 'title_de': False, 'organisation': False, 'organisation_de': False,
              'period': False, 'period_de': False, 'angles_de': False,
              'description': True, 'links': False, 'angles': False, 'claims': True}
CLAIM_KEYS = {'id': True, 'text': True, 'de': False, 'ownership': True, 'cv': False, 'evidence': False,
              'reason': False, 'stretches': False}
STRETCH_KEYS = {'text': True, 'defence': True, 'de': False}
STRUCTURAL = {'format', 'cv', 'claims', 'angles', 'angles_de', 'stretches', 'links', 'terms', 'applicant_facts', 'application_policies',
              'role_families', 'entries', 'forbidden_phrases'}  # fields that are not plain text


@dataclass
class Problem:
    line: int
    message: str
    warning: bool = False


def _lines(node, path=(), out=None):
    """Map each YAML path (tuple of keys and list indices) to its 1-based line number."""
    out = {} if out is None else out
    out[path] = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            out[path + (key.value,)] = key.start_mark.line + 1
            _lines(value, path + (key.value,), out)
            out[path + (key.value,)] = key.start_mark.line + 1
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            _lines(item, path + (index,), out)
    return out


def load(path):
    """Return (data, line map). Raises ValueError with a line number on YAML syntax errors."""
    text = Path(path).read_text(encoding='utf-8')
    try:
        node = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, 'problem_mark', None)
        raise ValueError(f'{mark.line + 1 if mark else 1}: YAML syntax error: '
                         f'{getattr(error, "problem", None) or error}') from None
    return data, (_lines(node) if node is not None else {(): 1})


class _Checker:
    def __init__(self, data, lines):
        self.data, self.lines, self.problems, self.ids = data, lines, [], {}

    def line(self, path):
        while path not in self.lines and path:
            path = path[:-1]
        return self.lines.get(path, 1)

    def error(self, path, message):
        self.problems.append(Problem(self.line(path), message))

    def warn(self, path, message):
        self.problems.append(Problem(self.line(path), message, warning=True))

    def fields(self, value, path, spec, what):
        """Check a mapping against {key: required}; return it (or {} when it is not a mapping)."""
        if not isinstance(value, dict):
            self.error(path, f'{what} must be a mapping of fields')
            return {}
        for key in value:
            if key not in spec:
                self.error(path + (key,), f'unknown field "{key}" in {what} (allowed: {", ".join(spec)})')
        for key, required in spec.items():
            if required and key not in value:
                self.error(path, f'{what} is missing "{key}"')
        for key in value:
            if key in spec and key not in STRUCTURAL \
                    and not (isinstance(value[key], str) and value[key].strip()
                             or isinstance(value[key], int) and not isinstance(value[key], bool)):  # e.g. period: 2025
                self.error(path + (key,), f'"{key}" in {what} must be non-empty text')
        return value

    def identifier(self, value, path, what):
        if not isinstance(value, str) or not ID.match(value):
            self.error(path, f'{what} id must be lowercase letters, digits and dashes, starting with a letter or digit')
            return
        if value in self.ids:
            self.error(path, f'id "{value}" is used twice (first on line {self.ids[value]})')
        else:
            self.ids[value] = self.line(path)

    def items(self, key, required=False):
        value = self.data.get(key, [] if not required else None)
        if value is None or not isinstance(value, list):
            self.error((key,), f'"{key}" must be a list')
            return []
        return value

    def run(self):
        if not isinstance(self.data, dict):
            self.error((), 'the career record must be a mapping with "format", "name", "role_families" and "entries"')
            return self.problems
        self.fields(self.data, (), TOP_KEYS, 'the career record')
        if self.data.get('format') != FORMAT_VERSION:
            self.error(('format',), f'"format" must be {FORMAT_VERSION}')
        for index, fact in enumerate(self.items('applicant_facts')):
            path = ('applicant_facts', index)
            self.identifier(self.fields(fact, path, FACT_KEYS, 'an applicant fact').get('id'), path + ('id',), 'applicant fact')
            link = fact.get('link') if isinstance(fact, dict) else None
            if link is not None and not (isinstance(link, str) and link.startswith(('http://', 'https://', 'mailto:'))):
                self.error(path + ('link',), '"link" must be a web address (https://...) or a mailto: address')
        for index, policy in enumerate(self.items('application_policies')):
            path = ('application_policies', index)
            self.identifier(self.fields(policy, path, POLICY_KEYS, 'an application policy').get('id'), path + ('id',),
                            'application policy')
        families = []
        for index, family in enumerate(self.items('role_families', required=True)):
            path = ('role_families', index)
            family = self.fields(family, path, FAMILY_KEYS, 'a role family')
            terms = family.get('terms', [])
            if not isinstance(terms, list) or not all(isinstance(t, str) and t.strip() for t in terms):
                self.error(path + ('terms',), '"terms" must be a list of words or phrases found in matching postings')
            self.identifier(family.get('id'), path + ('id',), 'role family')
            families.append(family.get('id'))
        if not families:
            self.error(('role_families',), 'at least one role family is needed (each has the CV headline for it)')
        forbidden = self.data.get('forbidden_phrases', [])
        if not isinstance(forbidden, list) or not all(isinstance(p, str) and p.strip() for p in forbidden):
            self.error(('forbidden_phrases',), '"forbidden_phrases" must be a list of non-empty text')
            forbidden = []
        self.forbidden, self.families = forbidden, families
        for index, family in enumerate(self.data.get('role_families') or []):
            if isinstance(family, dict):
                for key in ('headline', 'headline_de'):
                    self.phrases(family.get(key), ('role_families', index, key), 'headline')
        used_families = set()
        for index, entry in enumerate(self.items('entries', required=True)):
            used_families |= self.entry(entry, ('entries', index), families)
        for index, family in enumerate(families):
            if family and family not in used_families:
                self.warn(('role_families', index), f'role family "{family}" has no angles yet, so letters for it '
                                                     'cannot say why any entry matters')
        return self.problems

    def phrases(self, text, path, what):
        for phrase in self.forbidden:
            if isinstance(text, str) and re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text, re.I):
                self.error(path, f'{what} uses the forbidden phrase "{phrase}"')

    def entry(self, entry, path, families):
        entry = self.fields(entry, path, ENTRY_KEYS, 'an entry')
        self.identifier(entry.get('id'), path + ('id',), 'entry')
        if entry.get('type') is not None and entry.get('type') not in ENTRY_TYPES:
            self.error(path + ('type',), f'entry type must be one of {", ".join(ENTRY_TYPES)}')
        # Descriptions may name what an entry is not ("not a backend service"); they are never quoted.
        links = entry.get('links', [])
        if not isinstance(links, list) or not all(isinstance(link, str) and link.startswith(('http://', 'https://'))
                                                   for link in links):
            self.error(path + ('links',), '"links" must be a list of web addresses starting with https://')
        angles = entry.get('angles') or {}
        if not isinstance(angles, dict):
            self.error(path + ('angles',), '"angles" must map role family ids to one sentence each')
            angles = {}
        for family, angle in angles.items():
            if family not in families:
                self.error(path + ('angles', family), f'angle for unknown role family "{family}"')
            if not (isinstance(angle, str) and angle.strip()):
                self.error(path + ('angles', family), 'an angle must be one non-empty sentence')
            self.phrases(angle, path + ('angles', family), 'the angle')
        angles_de = entry.get('angles_de') or {}
        if not isinstance(angles_de, dict):
            self.error(path + ('angles_de',), '"angles_de" must map role family ids to one German sentence each')
            angles_de = {}
        for family, angle in angles_de.items():
            if family not in angles:
                self.error(path + ('angles_de', family), f'German angle for "{family}" without an English angle')
            if not (isinstance(angle, str) and angle.strip()):
                self.error(path + ('angles_de', family), 'an angle must be one non-empty sentence')
        claims = entry.get('claims')
        if not isinstance(claims, list) or not claims:
            self.error(path + ('claims',), 'an entry needs a list of at least one claim')
            claims = []
        for index, claim in enumerate(claims):
            self.claim(claim, path + ('claims', index))
        return {family for family in angles if family in families}

    def claim(self, claim, path):
        from reviewed_documents import TECH_TERMS, _numbers
        claim = self.fields(claim, path, CLAIM_KEYS, 'a claim')
        self.identifier(claim.get('id'), path + ('id',), 'claim')
        kind, text = claim.get('ownership'), claim.get('text') if isinstance(claim.get('text'), str) else ''
        on_cv = claim.get('cv', False)
        if isinstance(on_cv, list):
            # On the CV for the named role families only (e.g. steered AI work for applied-AI roles).
            unknown = [f for f in on_cv if f not in self.families]
            if not on_cv or unknown:
                self.error(path + ('cv',), '"cv" lists unknown role families: ' + ', '.join(map(str, unknown))
                           if unknown else '"cv" must name at least one role family')
            on_cv = True
        elif not isinstance(on_cv, bool):
            self.error(path + ('cv',), '"cv" must be true, false or a list of role family ids')
        if kind not in OWNERSHIP_KINDS:
            self.error(path + ('ownership',), f'ownership must be one of {", ".join(OWNERSHIP_KINDS)}')
        stretches = claim.get('stretches') or []
        if not isinstance(stretches, list):
            self.error(path + ('stretches',), '"stretches" must be a list')
            stretches = []
        if kind == 'cut':
            if 'reason' not in claim:
                self.error(path, 'an excluded (cut) claim needs a "reason", so nobody adds it back')
            if on_cv is True:
                self.error(path + ('cv',), 'an excluded (cut) claim can never be on the CV')
            if stretches:
                self.error(path + ('stretches',), 'an excluded (cut) claim cannot have stretches')
            return
        if 'evidence' not in claim:
            self.error(path, 'a claim needs "evidence": what would show it is true')
        self.phrases(text, path + ('text',), 'the claim')
        if kind == 'basics':
            if on_cv is True:
                self.error(path + ('cv',), 'a basics claim is said only on request, never on the CV')
            if stretches:
                self.error(path + ('stretches',), 'a basics claim cannot be stretched')
        if kind == 'adapted' and not ADAPTED_WORDS.search(text):
            self.error(path + ('text',), 'an adapted claim must say "adapted"')
        wordings = [(text, path + ('text',))]
        if isinstance(claim.get('de'), str):
            wordings.append((claim['de'], path + ('de',)))
            self.same_facts(text, claim['de'], path + ('de',))
            if kind == 'adapted' and not ADAPTED_WORDS.search(claim['de']):
                self.error(path + ('de',), 'the German wording of an adapted claim must say "angepasst"')
        if len(stretches) > MAX_STRETCHES:
            self.error(path + ('stretches',), f'at most {MAX_STRETCHES} stretches per claim')
        plain_numbers = _numbers(text)
        plain_terms = {term for term in TECH_TERMS if re.search(r'(?<![\w.#+])' + re.escape(term) + r'(?![\w#+])', text)}
        for index, stretch in enumerate(stretches):
            spath = path + ('stretches', index)
            stretch = self.fields(stretch, spath, STRETCH_KEYS, 'a stretch')
            wording = stretch.get('text') if isinstance(stretch.get('text'), str) else ''
            if wording.strip() == text.strip():
                self.error(spath + ('text',), 'a stretch must differ from the plain wording')
            added = sorted(_numbers(wording) - plain_numbers)
            if added:
                self.error(spath + ('text',), 'a stretch may not add numbers: ' + ', '.join(added))
            terms = sorted(term for term in TECH_TERMS if term not in plain_terms and
                           re.search(r'(?<![\w.#+])' + re.escape(term) + r'(?![\w#+])', wording))
            if terms:
                self.error(spath + ('text',), 'a stretch may not name tools the claim does not: ' + ', '.join(terms))
            if kind == 'adapted' and not ADAPTED_WORDS.search(wording):
                self.error(spath + ('text',), 'a stretch of an adapted claim must still say "adapted"')
            self.phrases(wording, spath + ('text',), 'the stretch')
            wordings.append((wording, spath + ('text',)))
            if isinstance(stretch.get('de'), str):
                wordings.append((stretch['de'], spath + ('de',)))
                self.same_facts(wording, stretch['de'], spath + ('de',))
        if kind == 'steered':
            for wording, wpath in wordings:
                if AUTHORSHIP_WORDS.search(wording):
                    self.error(wpath, 'a steered claim (AI-built to your specification) may not be worded as '
                                      f'authorship ("{AUTHORSHIP_WORDS.search(wording).group(0)}")')
            if not STEERED_WORDS.search(text):
                self.error(path + ('text',), 'a steered claim must say "specified" or "operate"')
            if isinstance(claim.get('de'), str) and not STEERED_WORDS.search(claim['de']):
                self.error(path + ('de',), 'the German wording of a steered claim must say "spezifiziert" or "betreibe"')

    def same_facts(self, english, german, path):
        """A German wording keeps the English wording's numbers and tool names (a translation, not a rewrite)."""
        from reviewed_documents import TECH_TERMS, _numbers
        digits = lambda text: {re.sub(r'[.,]', '', n) for n in _numbers(text)}
        if digits(english) != digits(german):
            self.error(path, 'the German wording must have the same numbers as the English: '
                             f'{", ".join(sorted(digits(english))) or "none"} vs {", ".join(sorted(digits(german))) or "none"}')
        tools = lambda text: {t for t in TECH_TERMS if re.search(r'(?<![\w.#+])' + re.escape(t) + r'(?![\w#+])', text)}
        if tools(english) != tools(german):
            self.error(path, 'the German wording must name the same tools as the English: '
                             + ', '.join(sorted(tools(english) ^ tools(german))))


def check(path):
    """Return a list of Problems (errors and warnings) for the career record at `path`."""
    try:
        data, lines = load(path)
    except ValueError as error:
        line, _, message = str(error).partition(': ')
        return [Problem(int(line), message)]
    except OSError as error:
        return [Problem(1, f'cannot read the file: {error.strerror}')]
    problems = _Checker(data, lines).run()
    if not any(not p.warning for p in problems):
        cv = [c for e in data['entries'] for c in e['claims'] if c.get('cv') is True]  # the CV every family gets
        missing = [c['id'] for c in cv if not c.get('de')]
        if missing:
            problems.append(Problem(lines.get(('entries',), 1), f'{len(missing)} of {len(cv)} CV claims have no '
                                    'German wording, so no German CV yet', warning=True))
    return sorted(problems, key=lambda p: (p.line, p.warning))


def path_for_user(username):
    """Where a user's career record is: `career_record` in their settings, else profiles/<user>/career_record.yaml."""
    import json
    from user_assets import resolve_user_path, user_profile_dir
    if not username:
        return None
    settings = Path(resolve_user_path(username, 'scraper_config.json'))
    configured = json.loads(settings.read_text()).get('career_record') if settings.exists() else None
    path = Path(configured).expanduser() if configured else Path(user_profile_dir(username), 'career_record.yaml')
    return path if path.exists() else None


def for_user(username):
    """(record, text) when the user has a career record, else (None, None). A record with errors raises."""
    path = path_for_user(username)
    if path is None:
        return None, None
    errors = [p for p in check(path) if not p.warning]
    if errors:
        raise ValueError(f'The career record {path} has errors (line {errors[0].line}: {errors[0].message}); '
                         'run career_record.py check')
    record, _ = load(path)
    return record, path.read_text(encoding='utf-8')


def _on_cv(claim, family):
    cv = claim.get('cv', False)
    return cv is True or (isinstance(cv, list) and family in cv)


def localise(record, language, cv_family=None):
    """The record in one language. English returns it unchanged.

    German swaps in the approved German wordings (`de`, `title_de`, `organisation_de`, `period_de`,
    `angles_de`, `headline_de`). Claims and stretches without German wording are dropped, so letters
    use only approved German. With `cv_family`, everything that family's CV shows must have German
    wording, otherwise ValueError lists what is missing.
    """
    import copy
    if language == 'en':
        return record
    if language != 'de':
        raise ValueError(f'unsupported document language "{language}" (use en or de)')
    rec, missing = copy.deepcopy(record), []
    for fact in rec.get('applicant_facts', []):
        if fact.get('de'):
            fact['text'] = fact['de']
        elif cv_family and fact['id'] in ('location', 'permit', 'languages'):
            missing.append(f'applicant fact {fact["id"]}')
    for family in rec['role_families']:
        if family.get('headline_de'):
            family['headline'] = family['headline_de']
        elif family['id'] == cv_family:
            missing.append(f'headline of {family["id"]}')
    for entry in rec['entries']:
        on_cv = cv_family and any(_on_cv(c, cv_family) for c in entry['claims'])
        if entry.get('title_de'):
            entry['title'] = entry['title_de']
        elif on_cv and entry['type'] in ('role', 'project', 'contribution', 'other'):
            missing.append(f'title of {entry["id"]}')
        for key in ('organisation', 'period'):
            if entry.get(key + '_de'):
                entry[key] = entry[key + '_de']
        entry['angles'] = dict(entry.get('angles_de') or {})
        kept = []
        for claim in entry['claims']:
            if claim['ownership'] == 'cut' or claim.get('de'):
                if claim.get('de'):
                    claim['text'] = claim['de']
                claim['stretches'] = [dict(s, text=s['de']) for s in claim.get('stretches') or [] if s.get('de')]
                kept.append(claim)
            elif cv_family and _on_cv(claim, cv_family):
                missing.append(f'claim {claim["id"]}')
        entry['claims'] = kept
    if missing:
        raise ValueError('A German CV needs German wording for: ' + ', '.join(missing))
    return rec


KIND_LABELS = {'own': '', 'adapted': ' [adapted from existing code]', 'steered': ' [AI-built to my specification]',
               'basics': ' [basic knowledge only]'}


def scoring_text(record):
    """Plain text of everything the user may claim, for job scoring: no excluded claims, kinds labelled."""
    lines = [record['name'].replace('**', '')]
    for fact in record.get('applicant_facts', []):
        if fact['id'] in ('location', 'permit', 'languages'):
            lines.append(fact['text'].replace('**', ''))
    for entry in record['entries']:
        claims = [c for c in entry['claims'] if c['ownership'] != 'cut']
        if not claims:
            continue
        head = ', '.join(str(entry[k]) for k in ('title', 'organisation', 'period') if entry.get(k))
        lines += ['', f'## {head}', ' '.join(entry['description'].split())]
        lines += [f'- {c["text"].replace("**", "")}{KIND_LABELS[c["ownership"]]}' for c in claims]
    return '\n'.join(lines) + '\n'


def summary(path):
    data, _ = load(path)
    claims = [c for e in data['entries'] for c in e['claims']]
    kinds = {kind: sum(c['ownership'] == kind for c in claims) for kind in OWNERSHIP_KINDS}
    return (f'{len(data["entries"])} entries, {len(claims)} claims '
            f'({sum(c.get("cv") is True for c in claims)} on every CV, '
            f'{sum(isinstance(c.get("cv"), list) for c in claims)} on some; '
            + ', '.join(f'{n} {kind}' for kind, n in kinds.items() if n) + '), '
            + (lambda n: f'{n} stretch{"" if n == 1 else "es"}, ')(sum(len(c.get('stretches') or []) for c in claims))
            + 
            f'{len(data["role_families"])} role families')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in ('check', 'text'):
        print('usage: career_record.py check PATH | career_record.py text PATH', file=sys.stderr)
        return 2
    path = argv[1]
    if argv[0] == 'text':  # the plain-text version used for job scoring
        if any(not p.warning for p in check(path)):
            print('the career record has errors; run career_record.py check', file=sys.stderr)
            return 1
        sys.stdout.write(scoring_text(load(path)[0]))
        return 0
    problems = check(path)
    for problem in problems:
        print(f'{path}:{problem.line}: {"warning: " if problem.warning else ""}{problem.message}')
    if any(not p.warning for p in problems):
        print(f'{sum(not p.warning for p in problems)} problem(s); the career record was not accepted')
        return 1
    print('OK: ' + summary(path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
