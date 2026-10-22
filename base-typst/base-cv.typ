// ==============================================================================
// JOBWEAVER TYPST CV TEMPLATE
// User-agnostic base template. Per-user overrides can be placed in:
// profiles/<user>/base-typst/base-cv.typ
// ==============================================================================

#let primary-color = rgb("#004f90")
#let text-color = rgb("#1f2937")
#let muted-color = rgb("#4b5563")
#let border-color = rgb("#d1d5db")

#set page(
  paper: "a4",
  margin: (top: 1.8cm, bottom: 1.8cm, left: 1.8cm, right: 1.8cm),
)

#set text(
  font: ("Arial", "Helvetica Neue"),
  size: 9.5pt,
  fill: text-color,
  lang: "en",
)

#set par(justify: true, leading: 0.55em)

// --- Helper Components ---

#let cv-section(title) = {
  v(0.35cm)
  block(width: 100%)[
    #text(fill: primary-color, weight: "bold", size: 11.5pt, tracking: 0.02em)[#upper(title)]
    #v(-0.25cm)
    #line(length: 100%, stroke: 0.8pt + primary-color)
  ]
  v(0.15cm)
}

#let cv-entry(
  title: "",
  organization: "",
  location: "",
  date: "",
  highlights: (),
  description: none,
) = {
  block(width: 100%, breakable: false)[
    #grid(
      columns: (1fr, auto),
      gutter: 1em,
      align(left)[
        #if title != "" and organization != "" [
          *#title* #text(fill: muted-color)[@] *#organization*
        ] else if title != "" [
          *#title*
        ] else if organization != "" [
          *#organization*
        ]
      ],
      align(right)[
        #text(fill: muted-color, size: 9pt)[
          #if location != "" and date != "" [
            #location #h(0.4em) | #h(0.4em) #date
          ] else if date != "" [
            #date
          ] else if location != "" [
            #location
          ]
        ]
      ]
    )

    #if description != none [
      #v(0.1cm)
      #description
    ]

    #if highlights.len() > 0 [
      #v(0.08cm)
      #list(
        ..highlights.map(h => [
          #set text(size: 9.2pt)
          #h
        ]),
        marker: text(fill: primary-color)[•],
        spacing: 0.5em,
      )
    ]
  ]
  v(0.2cm)
}

#let cv-skill-group(category: "", skills: "") = {
  block(width: 100%)[
    #grid(
      columns: (130pt, 1fr),
      gutter: 0.5em,
      align(left)[*#category:*],
      align(left)[#skills]
    )
  ]
  v(0.12cm)
}

// ==============================================================================
// DOCUMENT CONTENT (Alex Muster Placeholder)
// ==============================================================================

// Header
#align(center)[
  #block(width: 100%)[
    #text(fill: primary-color, size: 22pt, weight: "bold")[Alex Muster, BSc] \
    #v(0.15cm)
    #text(size: 9pt, fill: muted-color)[
      Vienna, Austria
      #h(0.5em) • #h(0.5em)
      #link("mailto:alex.muster@example.com")[alex.muster\@example.com]
      #h(0.5em) • #h(0.5em)
      #link("https://linkedin.com/in/alexmuster")[linkedin.com/in/alexmuster]
      #h(0.5em) • #h(0.5em)
      #link("https://github.com/alexmuster")[github.com/alexmuster]
    ] \
    #v(0.1cm)
    #text(size: 9pt, weight: "bold", fill: text-color)[Eligible to work in the EU]
  ]
]

#v(0.15cm)

// Professional Profile
#cv-section("Professional Profile")
*Software developer* with over *6 years of experience* building web applications, data-processing pipelines, and automation tooling. Comfortable across the full stack: backend services, APIs, databases, and containerized Linux infrastructure. Seeking backend, automation, and full-stack software engineering roles.

// Technical Skills
#cv-section("Technical Skills")
#cv-skill-group(category: "Programming", skills: "Python, JavaScript, TypeScript, SQL, Bash")
#cv-skill-group(category: "Web & APIs", skills: "FastAPI, Flask, RESTful APIs, React, HTML5/CSS3")
#cv-skill-group(category: "Data & Databases", skills: "PostgreSQL, MySQL, SQLite, pandas, NumPy, ETL Pipelines")
#cv-skill-group(category: "DevOps & Tools", skills: "Docker, Docker Compose, Linux, Git, GitHub Actions, CI/CD")
#cv-skill-group(category: "Languages", skills: "English (Full Professional - C1), German (Professional - B2)")

// Experience
#cv-section("Work Experience")

#cv-entry(
  title: "Senior Software Developer",
  organization: "Example Tech GmbH",
  location: "Vienna, Austria",
  date: "2021 – Present",
  highlights: (
    [Built and maintain scalable REST APIs using FastAPI and PostgreSQL, serving 50k+ daily requests for an internal logistics platform.],
    [Engineered automated data pipelines in Python and pandas, consolidating multi-source telemetry data and reducing reporting latency by 70%.],
    [Containerized legacy monolithic services with Docker and introduced automated CI/CD workflows, cutting release cycle times from hours to minutes.],
    [Mentored 3 junior developers and established automated linting, testing, and pull-request review best practices.],
  )
)

#cv-entry(
  title: "Software Developer",
  organization: "Data Systems AG",
  location: "Linz, Austria",
  date: "2018 – 2020",
  highlights: (
    [Developed internal operations dashboard (Flask, React) used daily across warehouse teams to track fulfillment efficiency.],
    [Created Python automation scripts for scheduled invoice processing and CRM data reconciliation, saving 10+ hours per week.],
    [Refactored database query layer to optimize slow-running joins, achieving a 3x speedup on heavy reporting endpoints.],
  )
)

// Projects & Technical Interests
#cv-section("Projects & Technical Interests")

#cv-entry(
  title: "Home Lab & Automation",
  organization: "Self-Hosted",
  date: "Ongoing",
  highlights: (
    [Configured and manage self-hosted services via Docker Compose, including automated off-site backups, Prometheus metrics, and Grafana monitoring.],
  )
)

#cv-entry(
  title: "Open Source Contributions",
  organization: "GitHub",
  date: "Ongoing",
  highlights: (
    [Maintain a popular open-source CLI utility for data scraping and workflow automation; contribute patches to upstream Python libraries.],
  )
)

// Education
#cv-section("Education")

#cv-entry(
  title: "BSc Software Engineering & Networked Systems",
  organization: "TU Wien",
  location: "Vienna, Austria",
  date: "2014 – 2018",
  highlights: (
    [Focus areas: Distributed Systems, Database Architecture, Software Engineering Principles.],
    [Bachelor Thesis: Efficient Task Scheduling Strategies for Distributed Batch Data Processing.],
  )
)
