#!/usr/bin/env python3
"""Render a CV from a career record (ADR-0004, build step 3).

    uv run python -m jobweaver.career_cv RECORD --family ROLE_FAMILY [--language en|de] [--out cv.tex]

The layout is `base-cv-tex/career-record-cv.tex` (no facts in it). The CV shows the record's name, the role
family's headline, the header facts (`location`, `phone`, `email`, `github`, `linkedin`, `permit`), every CV
claim in record order (plus claims whose `cv` names this role family), and the `languages` fact. Only the
headline and family-specific claims differ between role families. `**text**` in the record prints in bold.
The record must pass `python -m jobweaver.career_record check` first; rendering refuses a record with errors.
"""
import argparse
import re
import sys
from pathlib import Path

from jobweaver import PROJECT_ROOT
from jobweaver import career_record

TEMPLATE = PROJECT_ROOT / 'base-cv-tex' / 'career-record-cv.tex'
PAGE_ONE = (('other', None), ('skills', 'skills'), ('role', 'experience'))
PAGE_TWO = (('project', 'software'), ('contribution', 'contributions'), ('education', 'education'),
            ('publication', 'publications'))
LABELS = {
    'en': {'skills': 'Technical Skills', 'experience': 'Experience', 'software': 'Selected Python Software',
           'contributions': 'Open-Source Python Contributions', 'education': 'Education',
           'publications': 'Publications', 'languages': 'Languages', 'page_two': 'Software, publications and education',
           'pulls': 'Merged pull requests'},
    'de': {'skills': 'Technische Kenntnisse', 'experience': 'Berufserfahrung', 'software': 'Ausgewählte Python-Projekte',
           'contributions': 'Open-Source-Beiträge', 'education': 'Ausbildung', 'publications': 'Publikationen',
           'languages': 'Sprachen', 'page_two': 'Softwareprojekte, Publikationen und Ausbildung',
           'pulls': 'Übernommene Pull Requests'},
}
HEADER_LINES = (('location', 'phone', 'email'), ('github', 'linkedin'))
LATEX_SPECIAL = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
                 '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
SEP = r' \enspace | \enspace '


def tex(text):
    """Escape LaTeX and turn **bold** into \\textbf{bold}."""
    escaped = ''.join(LATEX_SPECIAL.get(c, c) for c in str(text))
    return re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', escaped)


def shown(claim, family):
    cv = claim.get('cv', False)
    return cv is True or (isinstance(cv, list) and family in cv)


def _link_label(url):
    return re.sub(r'^https?://(www\.)?', '', url).rstrip('/')


def _href(url, label):
    return r'\href{' + url.replace('%', r'\%').replace('#', r'\#') + '}{' + label + '}'


def _fact(facts, key):
    fact = facts.get(key)
    if not fact:
        return None
    return _href(fact['link'], tex(fact['text'])) if fact.get('link') else tex(fact['text'])


def _items(claims):
    return [r'\begin{itemize}', *[r'\item ' + tex(c['text']) for c in claims], r'\end{itemize}']


def _entry(entry, claims):
    kind = entry['type']
    if kind in ('other', 'skills'):
        return []  # the section heading is the entry
    if kind == 'role':
        head = r'\textbf{' + tex(entry['title']) + '}'
        head += (r' \hfill ' + tex(entry['period'])) if entry.get('period') else ''
        head += (r'\\' + tex(entry['organisation'])) if entry.get('organisation') else ''
        return [head]
    if kind == 'project':
        lines = [r'\textbf{' + tex(entry['title']) + '}' + (r'\\' if entry.get('links') else '')]
        if entry.get('links'):
            lines.append(SEP.join(_href(url, tex(_link_label(url))) for url in entry['links']))
        return lines
    if kind == 'contribution':
        return [r'\textbf{' + tex(entry['title']) + '}' + ((r' \hfill ' + tex(entry['period'])) if entry.get('period') else '')]
    return []


def _section(kind, title, entries, family, labels=LABELS['en']):
    blocks = [(e, [c for c in e['claims'] if shown(c, family)]) for e in entries if e['type'] == kind]
    blocks = [(e, claims) for e, claims in blocks if claims]
    if not blocks:
        return []
    lines = []
    if kind == 'other':
        for entry, claims in blocks:  # free paragraphs, e.g. the profile
            lines += [r'\section{' + tex(entry['title']) + '}', *[tex(c['text']) for c in claims]]
        return lines
    lines.append(r'\section{' + title + '}')
    if kind == 'education':
        texts = [tex(c['text']) for _, claims in blocks for c in claims]
        return lines + ['\\\\[3pt]\n'.join(texts)]
    if kind == 'publication':
        lines.append(r'\begin{itemize}')
        for entry, claims in blocks:
            for claim in claims:
                text = tex(claim['text'])
                for url in entry.get('links', []):
                    if 'doi.org/' in url:
                        text = text.rstrip('.') + '. ' + _href(url, 'DOI: ' + tex(url.split('doi.org/', 1)[1])) + '.'
                lines.append(r'\item[\textbullet] ' + text)
        return lines + [r'\end{itemize}']
    for entry, claims in blocks:
        lines += _entry(entry, claims) + _items(claims)
        pulls = [u for u in entry.get('links', []) if re.search(r'/pull/\d+$', u)]
        if kind == 'contribution' and pulls:
            lines.append(labels['pulls'] + ': ' + ', '.join(_href(u, r'\#' + u.rsplit('/', 1)[1]) for u in pulls) + '.')
    return lines


def _family(record, family_id):
    families = {f['id']: f for f in record['role_families']}
    if family_id not in families:
        raise ValueError(f'unknown role family "{family_id}"; known: {", ".join(families)}')
    return families[family_id]


def header(record, family_id):
    """The identity block (name, headline, contact, permit) shared by the CV and the cover letter."""
    family = _family(record, family_id)
    facts = {f['id']: f for f in record.get('applicant_facts', [])}
    lines = [r'{\fontsize{28pt}{32pt}\selectfont\bfseries\color{ink} ' + tex(record['name']) + r'}\par', r'\vspace{4pt}',
             r'{\fontsize{11pt}{14pt}\selectfont' + tex(' ' + family['headline']) + r'\par}', r'\vspace{4pt}']
    contact = [SEP.join(f for f in (_fact(facts, key) for key in keys) if f) for keys in HEADER_LINES]
    lines.append(r'{\fontsize{11pt}{14pt}\selectfont' + '\n' + '\\\\\n'.join(c for c in contact if c) + r'\par}')
    if facts.get('permit'):
        lines += [r'\vspace{3pt}', r'{\fontsize{11pt}{14pt}\selectfont' + tex(' ' + facts['permit']['text']) + r'\par}']
    return lines


def document(record, family_id, body):
    """Wrap body lines in the layout template (preamble with the record's name and headline)."""
    family = _family(record, family_id)
    short = record['name'].split(',')[0].strip()
    bold = re.search(r'\*\*(.+?)\*\*', family['headline'])
    title = short + ' - ' + (bold.group(1) if bold else family['headline'].split('|')[0].strip())
    template = TEMPLATE.read_text(encoding='utf-8')
    return (template.replace('<<AUTHOR>>', tex(short)).replace('<<TITLE>>', tex(title))
            .replace('<<BODY>>', '\n'.join(body)))


def render(record, family_id, language='en'):
    """Return the CV's LaTeX source for one role family of a parsed, checked career record.

    language='de' needs German wording for everything this CV shows (ValueError lists what is missing).
    """
    from jobweaver import career_record
    _family(record, family_id)
    record = career_record.localise(record, language, cv_family=family_id)
    labels = LABELS[language]
    facts = {f['id']: f for f in record.get('applicant_facts', [])}
    entries = record['entries']
    short = record['name'].split(',')[0].strip()
    body = header(record, family_id)
    for kind, title in PAGE_ONE:
        body += _section(kind, labels.get(title), entries, family_id, labels)
    body += [r'\newpage', r'{\large\bfseries ' + tex(short) + ' | ' + labels['page_two'] + '}']
    for kind, title in PAGE_TWO:
        body += _section(kind, labels[title], entries, family_id, labels)
    if facts.get('languages'):
        body += [r'\section{' + labels['languages'] + '}', tex(facts['languages']['text']).replace(' | ', SEP)]
    return document(record, family_id, body)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m jobweaver.career_cv", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('record')
    parser.add_argument('--family', required=True)
    parser.add_argument('--language', default='en', choices=('en', 'de'))
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    errors = [p for p in career_record.check(args.record) if not p.warning]
    if errors:
        for problem in errors:
            print(f'{args.record}:{problem.line}: {problem.message}', file=sys.stderr)
        print('the career record has errors; run python -m jobweaver.career_record check first', file=sys.stderr)
        return 1
    record, _ = career_record.load(args.record)
    try:
        source = render(record, args.family, args.language)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(source, encoding='utf-8')
    else:
        sys.stdout.write(source)
    return 0


if __name__ == '__main__':
    sys.exit(main())
