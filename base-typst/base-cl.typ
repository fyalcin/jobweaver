// ==============================================================================
// JOBWEAVER TYPST COVER LETTER TEMPLATE
// User-agnostic base template. Per-user overrides can be placed in:
// profiles/<user>/base-typst/base-cl.typ
// ==============================================================================

#let primary-color = rgb("#004f90")
#let text-color = rgb("#1f2937")
#let muted-color = rgb("#4b5563")

#set page(
  paper: "a4",
  margin: (top: 2.2cm, bottom: 2.2cm, left: 2.2cm, right: 2.2cm),
)

#set text(
  font: ("Arial", "Helvetica Neue"),
  size: 10pt,
  fill: text-color,
  lang: "en",
)

#set par(justify: true, leading: 0.65em)

// --- Applicant Header ---
#block(width: 100%)[
  #text(fill: primary-color, size: 20pt, weight: "bold")[Alex Muster, BSc] \
  #v(0.1cm)
  #text(size: 9pt, fill: muted-color)[
    Vienna, Austria
    #h(0.5em) • #h(0.5em)
    +43 123 456789
    #h(0.5em) • #h(0.5em)
    #link("mailto:alex.muster@example.com")[alex.muster\@example.com]
    #h(0.5em) • #h(0.5em)
    #link("https://linkedin.com/in/alexmuster")[linkedin.com/in/alexmuster]
  ]
  #v(0.2cm)
  #line(length: 100%, stroke: 0.8pt + primary-color)
]

#v(0.6cm)

// --- Date & Recipient ---
#grid(
  columns: (1fr, auto),
  align(left)[
    #text(weight: "bold")[Hiring Team / Engineering Leadership] \
    Example Tech GmbH \
    Musterstraße 123 \
    1010 Vienna, Austria
  ],
  align(right)[
    #datetime.today().display("[day]. [month repr:long] [year]")
  ]
)

#v(0.6cm)

// --- Subject Line ---
#text(weight: "bold", size: 11pt)[Application for Senior Software Developer (Job ID: \#1042)]

#v(0.4cm)

// --- Salutation ---
Dear Hiring Team,

#v(0.2cm)

// --- Body Paragraphs ---
I am writing to express my strong enthusiasm for the Senior Software Developer position at Example Tech GmbH. With over six years of hands-on software engineering experience specializing in high-throughput Python backends, distributed data pipelines, and containerized architectures, I have long admired your team's dedication to engineering excellence and scalable infrastructure.

In my current role at Example Tech GmbH, I lead backend development for our core logistics platform, designing and maintaining FastAPI microservices that reliably process over 50,000 daily requests. By automating critical ETL data feeds with pandas and cron, I eliminated recurring data synchronisation delays and cut reporting turnaround times by 70%. Furthermore, introducing automated Docker-based CI/CD pipelines significantly reduced deployment overhead and elevated team release confidence.

What particularly excites me about Example Tech is your focus on modern, resilient systems and automated engineering workflows. My background combining rigorous backend architecture with pragmatic operational tooling directly aligns with your current scaling goals. I take great pride in writing clean, well-tested code, mentoring peers, and turning complex product requirements into robust production software.

I would welcome the opportunity to discuss how my technical expertise, problem-solving mindset, and dedication to high-quality code can contribute to the continued success of your team. Thank you for your time and consideration.

#v(0.4cm)

// --- Sign-off ---
Sincerely,

#v(0.6cm)

#text(weight: "bold")[Alex Muster, BSc]
