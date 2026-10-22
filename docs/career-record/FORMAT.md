# Career record format (version 1)

The career record is one YAML file holding everything documents may say about a user (ADR-0004,
terms in `GLOSSARY.md`, design decisions in `2026-10-13-design.md`). Jobweaver owns this format; the
real file lives outside the repository. A complete fictional example: `examples/career_record.example.yaml`.

Check a record (prints `PATH:LINE: message` per problem; exit code 0 means accepted):

    uv run python career_record.py check PATH

## Top level

| Field | Required | Content |
|---|---|---|
| `format` | yes | `1` |
| `name` | yes | the name as it heads the CV |
| `applicant_facts` | no | list of `{id, text, de?, link?}`: permit, location, languages, contact. The CV header uses the ids `location`, `phone`, `email`, `github`, `linkedin` and `permit`; the Languages section uses `languages` |
| `application_policies` | no | list of `{id, rule}`: salary ask, talent pool, notice |
| `role_families` | yes | list of `{id, label, headline, headline_de?, terms?}`, at least one. A job gets the family whose `terms` (lowercase words or phrases) appear most often in its title and description; with no match, the first family |
| `entries` | yes | list of entries (below), in CV order |
| `forbidden_phrases` | no | phrases no headline, angle, claim or stretch may contain (excluded claims may; descriptions may, to say what something is not) |

## Personal context in applicant facts

Applicant facts whose ids start with `personal-` hold approved interests, motivations
or project reflections, for example `{id: personal-debugging, text: "I enjoy finding
the cause of an unexpected failure."}`. They stay out of job-scoring text and CVs.
The letter writer may cite zero or one such fact, briefly and only when relevant;
it cannot replace the planned work evidence. Employer perks do not establish a
shared interest or cultural compatibility. German letters receive only facts with
approved `de` wording. Other applicant facts remain available only to their existing
consumers; the prefix does not expose unrelated form answers to letter writing.

Work achievements and skills still belong in entry claims. A concrete debugging
episode is work evidence; enjoying debugging is personal context.

## Entries

| Field | Required | Content |
|---|---|---|
| `id` | yes | lowercase letters, digits, dashes; unique in the whole record |
| `type` | yes | `role`, `project`, `contribution`, `education`, `publication`, `skills` or `other` |
| `title` | yes | e.g. job title or project name |
| `organisation`, `period` | no | employer or institution; time span |
| `title_de`, `organisation_de`, `period_de` | no | German versions (a German CV needs `title_de` for roles, projects, contributions and `other` entries it shows) |
| `description` | yes | what the thing is, in a few sentences (helps match it to a role; never quoted as a claim) |
| `links` | no | list of web addresses shown with the entry (repository, package page) |
| `angles` | no | `{role-family-id: sentence}`: why this entry matters for that kind of role |
| `angles_de` | no | German angles, only for families that have an English angle |
| `claims` | yes | list of claims (below), in CV order |

## Claims

| Field | Required | Content |
|---|---|---|
| `id` | yes | unique in the whole record |
| `text` | yes | the plain wording |
| `de` | no | approved German wording |
| `ownership` | yes | `own`, `adapted`, `steered`, `basics` or `cut` |
| `cv` | no | `true` to show it on every CV, a list of role family ids to show it only on those families' CVs, or `false` (default: letter-only) |
| `evidence` | yes, except `cut` | what would show the claim is true |
| `reason` | only `cut` | why it is excluded |
| `stretches` | no | at most two `{text, defence, de?}` |

## Rules the checker enforces

- **cut:** needs a `reason`; never on the CV; no stretches.
- **basics:** never on the CV (said only on request); no stretches.
- **adapted:** the wording and every stretch say "adapted".
- **steered** (AI-built to the user's specification): says "specified" or "operate"; no wording or stretch
  says built, wrote, developed, implemented, coded or authored ("AI-built" is fine).
- **Stretch:** differs from the plain wording; adds no number and names no tool that the plain wording does
  not; needs a `defence` (what the user says if an interviewer asks).
- **Angles** name existing role families. Ids are unique across the whole record.
- **German wordings** (`de` of claims and stretches) keep the English wording's numbers and tool names; an
  adapted claim's German says "angepasst", a steered claim's German says "spezifiziert" or "betreibe".

The stretch rule beyond what a checker can see: a stretch may change verb strength, generality and the
emphasis on outcomes, never the ownership kind, tools, numbers, the kind of work or seniority.

## Warnings (never block)

- A role family without any angle.
- CV claims without German wording (no German CV until all have one).

## Language

Documents are English unless German is asked for (`generate_for_job.py --language de`, `language` in the web
API, or the user setting `document_language`: `en`, `de` or `posting`). In German, letters use only claims,
stretches and angles with German wording; a German CV needs German for everything it shows and otherwise names
what is missing.
