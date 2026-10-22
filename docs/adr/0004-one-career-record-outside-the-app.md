# One career record per user, kept outside the app

Everything documents may say about a user lives in one **career record** (a YAML file of entries, claims,
approved stretches with defence lines, angles per role family, applicant facts and application policies).
Jobweaver owns only its format, the checker and a fictional example; each user's real record lives wherever
they keep career material (for example a private repository of career material) and Jobweaver reads it from a path
in the user's settings. The CV, the plain-text CV used for scoring, claim checks and form-filling answers are
all generated from it.

We chose this over keeping the record inside Jobweaver (the app is meant to become public, and personal data
must not sit in its repository) and over one copy per consumer (the setup this replaces had eight places
holding statements about the user; one correction had to be made in four of them by hand).

## Consequences

- `profiles/<user>/approved/cv.tex` becomes a layout template without facts; the CV is rendered from claims.
- Overselling is bounded by data, not by prompts: documents may use only approved stretches, at most a set
  number per letter, and link work to a role only through approved angles. The verifier compares each sentence
  with the plain wording and the approved stretches.
- Generated documents are stale whenever the record changes (it is part of the generation fingerprint).
