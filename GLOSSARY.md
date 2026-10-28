# Jobweaver

A self-hosted tool that finds job postings, judges how well they fit a person, tracks
applications through a pipeline, and prepares tailored CVs and cover letters.

## Language

**User**:
A person with their own CV, preferences, jobs and documents. All data belongs to exactly one User.
_Avoid_: Account, profile (a profile is the User's files under `profiles/`)

**Job**:
A Posting stored for one User, with its Match rating and Stage. The same Posting stored for two Users is two Jobs.
_Avoid_: Listing, ad, vacancy

**Pipeline**:
The set of a User's Jobs organized by Stage.
_Avoid_: Kanban, funnel

**Stage**:
Where a Job currently sits in the Pipeline: `new`, `interested`, `applied`, `interview`, `offer`, `rejected` or `not_interested`.
_Avoid_: Status (the stored field is called `status`, but the concept is Stage)

**Match rating**:
A label derived from Requirement checks, Preference conflicts and Eligibility: Great, Good, Decent, Stretch, Poor or Blocked. It describes fit, not a hiring probability.
_Avoid_: Score, match percentage

**Requirement check**:
A posting requirement classified as firm or optional, with CV coverage judged shown, related or missing and quotations supporting the judgement.
_Avoid_: Skill score, checklist point

**Preference conflict**:
A conflict between a posting condition and a User's Standing Notes, supported by quotations from both. A hard conflict contradicts an explicit requirement; a soft conflict contradicts a preference.
_Avoid_: Penalty, negative score

**Judgement call**:
A related firm requirement whose treatment as missing would change the Match rating.
_Avoid_: Borderline score

**Eligibility**:
Whether a User may realistically take a Job (language, work permit, level). A known blocker prevents a positive Match rating.
_Avoid_: Fit

**Historical analysis**:
An analysis that has not been checked against the current CV, model and matching rules. Its conclusions need review before they guide a new application.
_Avoid_: Current match, verified fit

**Historical score**:
A numeric judgement of fit retained from the earlier scoring system. It is not a Match rating.
_Avoid_: Match percentage, converted rating

**Document set**:
The CV and cover letter generated for one Job, kept as immutable revisions.
_Avoid_: Application, package

## Where postings come from

**Source**:
A place postings come from: one employer's feed, an Apify actor, a pasted link, a User's own script.
_Avoid_: Site, platform, provider

**Connector**:
The part that fetches raw records from one Source, in whatever shape the Source uses.
_Avoid_: Scraper, reader, crawler

**Mapping**:
The rule set that turns one raw record from a Source into a Posting, field by field.
_Avoid_: Mapper, adapter, parser

**Posting**:
A record in Jobweaver's own shape that has every required field and nothing else, not yet stored for any User.
_Avoid_: Job (a Job belongs to a User), raw record, item

**Rejected record**:
A raw record that could not become a Posting, identified by its Source and rejection reason.
_Avoid_: Failed job, dropped row

## Ground truth about the applicant

**Career record**:
The one file of everything documents may say about a User: Entries, Claims, Stretches, Angles, Applicant facts and Application policies. Every other statement about the User is generated from it.
_Avoid_: Ground truth, profile, claim ledger, dossier, master CV

**Role family**:
A kind of role the User applies for (research software, Python/data engineering, applied AI), with its own Headline and Angles.
_Avoid_: CV profile, track, persona

**Angle**:
An approved sentence saying why one Entry matters for one Role family. Letters link work to a role only through Angles.
_Avoid_: Framing, pitch, relevance note

**Entry**:
One thing the User did or holds (a project, role, education, publication), with a short description of what it is. Holds Claims.
_Avoid_: Fact, item, section

**Claim**:
One atomic statement a document may make about the User, with its evidence. Documents say Claims and nothing else.
_Avoid_: Fact, bullet, evidence (evidence is what backs a Claim)

**Stretch**:
A stronger wording of one Claim that the User has approved. Documents may use it instead of the plain wording; nobody else may invent one.
_Avoid_: Overselling, framing, embellishment

**Ownership kind**:
How much of a Claim's work is the User's own: own, adapted, steered (AI-built to the User's specification), basics, or cut. Each kind fixes how the Claim may be worded.
_Avoid_: Claim class, category, OWN/STEER label

**Excluded claim**:
A Claim of kind cut: never said, kept with its reason so nobody adds it back.
_Avoid_: CUT list, forbidden claim

**CV claim**:
A Claim marked to appear on the CV; the others are letter-only. The CV shows all CV claims in a fixed order.
_Avoid_: Bullet, optional evidence

**Headline**:
The approved one-line title under the User's name on the CV, one per Role family.
_Avoid_: Title, tagline

**Applicant fact**:
A stable fact about the User that is not an achievement: work permit, location, languages, contact.
_Avoid_: Identity line, dossier entry

**Personal context**:
The User's approved interests, motivations and project reflections, optionally used in letters to explain their interest in the work. Personal context is not evidence of qualifications.
_Avoid_: Personality profile, cultural-fit score

**Application policy**:
A rule the User sets for answering applications: salary ask, talent-pool consent, notice period.
_Avoid_: Preference, dossier entry

## Agent access

**Agent client**:
An AI assistant that reads a User's Jobs through the MCP server.
_Avoid_: Bot, user (a User is the person whose data it is)
