// ==============================================================================
// JOBWEAVER TYPST CV TEMPLATE (moderner-cv)
// User-agnostic base template based on LaTeX moderncv package.
// Per-user overrides can be placed in:
// profiles/<user>/base-typst/base-cv-moderner.typ
// ==============================================================================

#import "@preview/moderner-cv:0.2.1": *

#show: moderner-cv.with(
  name: "Alex Muster, BSc",
  subtitle: text(size: 14pt)[Software Developer],
  color: rgb("#004f90"),
  margin: (
    top: 15mm,
    bottom: 15mm,
    left: 15mm,
    right: 15mm,
  ),
  lang: "en",
  show-footer: false,
  social: (
    email: "alex.muster@example.com",
    github: "alexmuster",
    linkedin: "alex-muster",
    address: "Vienna, Austria",
  ),
)

// Breathing room between header and first section
#v(0.5cm)

= Professional Summary
#cv-line([], [
  Results-oriented software developer with over 5 years of experience building reliable backend systems, workflow automations, and data pipelines on Linux platforms.
])

= Technical Skills
#cv-line([*Languages*], [Python, Bash, SQL, JavaScript, HTML/CSS])
#cv-line([*Frameworks*], [FastAPI, Flask, pandas, NumPy])
#cv-line([*Infrastructure*], [Linux, Docker, Git, CI/CD, Slurm, Cloud Services])
#cv-line([*Databases*], [PostgreSQL, SQLite, MongoDB])

= Experience

#cv-entry-multiline(
  date: [2022 -- Present],
  employer: [Example Tech GmbH],
  title: [Senior Python Developer],
  [
    - Architected and maintained scalable RESTful APIs serving 50k+ daily requests.
    - Automated critical data ingestion pipelines, reducing processing latency by 65%.
    - Containerized legacy microservices using Docker and streamlined deployment workflows.
  ]
)

#cv-entry-multiline(
  date: [2019 -- 2022],
  employer: [Data Solutions OG],
  title: [Software Developer],
  [
    - Developed internal automation scripts and monitoring utilities in Python and Bash.
    - Maintained automated testing suites and CI/CD pipelines ensuring high code quality.
  ]
)

= Education

#cv-entry(
  date: [2016 -- 2019],
  employer: [University of Vienna],
  title: [BSc in Computer Science],
)[GPA: 3.8/4.0 | Focus: Software Engineering & Distributed Systems]
