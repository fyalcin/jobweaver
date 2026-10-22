/**
 * typstSerializer.js
 * Serializes structured Simple Mode form data back into valid Typst source code.
 */
import { parseModernerCv, parseStandardCv } from './typstParser.js';

export function typstString(value) {
  return JSON.stringify(String(value ?? '')).slice(1, -1);
}

// Form fields are text. Existing emphasis is supported; code delimiters aren't.
export function typstMarkup(value) {
  return String(value ?? '').replace(/(?<!\\)[#@[\]<>$]/g, '\\$&');
}

function preservePreamble(original, generated, basics) {
  if (!original) return generated;
  const parsed = original.includes('moderner-cv') ? parseModernerCv(original) : parseStandardCv(original);
  const old = parsed.data?.basics || {};
  let result = original;
  for (const [key, value] of Object.entries(basics)) {
    if (value === old[key]) continue;
    if (!old[key] && !value) continue;
    if (!old[key] || !result.includes(old[key])) {
      throw new Error('This header change needs Advanced mode; the custom design has been preserved.');
    }
    // Replace only existing header values; font/margins/language/macros stay exact.
    const encoded = typstString(old[key]);
    const occurrences = result.split(encoded).length - 1;
    if (occurrences !== 1) {
      throw new Error('This header value appears more than once. Use Advanced mode to preserve your design.');
    }
    result = result.replace(encoded, typstString(value));
  }
  return result;
}

/**
 * Serializes moderner-cv document
 */
export function serializeModernerCv(data, originalPreamble = '') {
  const { basics, sections } = data;

  const headerPreamble = `// ==============================================================================
// JOBWEAVER TYPST CV TEMPLATE (moderner-cv)
// ==============================================================================

#import "@preview/moderner-cv:0.2.1": *

#show: moderner-cv.with(
  name: "${typstString(basics.name || 'Alex Muster')}",
  ${basics.subtitle ? `subtitle: text(size: 14pt)[${basics.subtitle}],` : ''}
  color: rgb("${typstString(basics.color || '#004f90')}"),
  margin: (
    top: 15mm,
    bottom: 15mm,
    left: 15mm,
    right: 15mm,
  ),
  lang: "en",
  show-footer: false,
  social: (
    ${basics.email ? `email: "${typstString(basics.email)}",\n    ` : ''}${basics.github ? `github: "${typstString(basics.github)}",\n    ` : ''}${basics.linkedin ? `linkedin: "${typstString(basics.linkedin)}",\n    ` : ''}${basics.address ? `address: "${typstString(basics.address)}",\n    ` : ''}${basics.phone ? `phone: "${typstString(basics.phone)}",\n    ` : ''}${basics.residence ? `residence: ("id-card", "#", "${typstString(basics.residence)}"),\n    ` : ''}  ),
)

// Breathing room between header and first section
#v(0.5cm)
`;

  const sectionsMarkup = sections
    .map((sec) => {
      let content = `= ${typstMarkup(sec.title)}\n`;

      if (sec.type === 'summary') {
        content += `#cv-line([], [\n  ${typstMarkup(sec.text.trim())}\n])\n`;
      } else if (sec.type === 'skills') {
        for (const grp of sec.groups || []) {
          content += `#cv-line([*${typstMarkup(grp.category)}*], [${typstMarkup(grp.skills)}])\n`;
        }
      } else if (sec.type === 'entries') {
        for (const ent of sec.entries || []) {
          const bullets = ent.bullets || [];
          if (bullets.length > 0) {
            const bulletsStr = bullets.map((b) => `    - ${typstMarkup(b)}`).join('\n');
            content += `\n#cv-entry-multiline(
  date: [${typstMarkup(ent.date)}],
  employer: [${typstMarkup(ent.employer)}],
  title: [${typstMarkup(ent.title)}],
  [
${bulletsStr}
  ]
)\n`;
          } else {
            content += `\n#cv-entry(
  date: [${typstMarkup(ent.date)}],
  employer: [${typstMarkup(ent.employer)}],
  title: [${typstMarkup(ent.title)}],
)${ent.note ? `[${typstMarkup(ent.note)}]` : ''}\n`;
          }
        }
      } else if (sec.type === 'lines') {
        for (const it of sec.items || []) {
          content += `#cv-line([*${typstMarkup(it.category)}*], [${typstMarkup(it.content)}])\n`;
        }
      } else if (sec.type === 'text') {
        content += `${typstMarkup(sec.text.trim())}\n`;
      }

      return content;
    })
    .join('\n');

  return (preservePreamble(originalPreamble, headerPreamble, basics) + '\n' + sectionsMarkup).trim() + '\n';
}

/**
 * Serializes standard-cv document
 */
export function serializeStandardCv(data, originalPreamble = '') {
  const { basics, sections } = data;

  // If we have an existing preamble with helper functions, we can preserve its helper declarations
  // or use the standard clean helper block
  const preamble = `// ==============================================================================
// JOBWEAVER TYPST CV TEMPLATE
// ==============================================================================

#let primary-color = rgb("${typstString(basics.color || '#004f90')}")
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
// DOCUMENT CONTENT
// ==============================================================================

// Header
#align(center)[
  #block(width: 100%)[
    #text(fill: primary-color, size: 22pt, weight: "bold")[${basics.name || 'Alex Muster'}] \\
    #v(0.15cm)
    #text(size: 9pt, fill: muted-color)[
      ${basics.address || 'Vienna, Austria'}
      ${basics.email ? `#h(0.5em) • #h(0.5em)\n      #link("mailto:${basics.email}")[${basics.email.replace('@', '\\@')}]` : ''}
      ${basics.linkedin ? `#h(0.5em) • #h(0.5em)\n      #link("https://linkedin.com/in/${basics.linkedin}")[linkedin.com/in/${basics.linkedin}]` : ''}
      ${basics.github ? `#h(0.5em) • #h(0.5em)\n      #link("https://github.com/${basics.github}")[github.com/${basics.github}]` : ''}
      ${basics.phone ? `#h(0.5em) • #h(0.5em)\n      ${basics.phone}` : ''}
    ] \\
    ${basics.residence ? `#v(0.1cm)\n    #text(size: 9pt, weight: "bold", fill: text-color)[${basics.residence}]` : ''}
  ]
]

#v(0.15cm)
`;

  const sectionsMarkup = sections
    .map((sec) => {
      let content = `#cv-section("${typstString(sec.title)}")\n`;

      if (sec.type === 'summary') {
        content += `${typstMarkup(sec.text.trim())}\n`;
      } else if (sec.type === 'skills') {
        for (const grp of sec.groups || []) {
          content += `#cv-skill-group(category: "${typstString(grp.category)}", skills: "${typstString(grp.skills)}")\n`;
        }
      } else if (sec.type === 'entries') {
        for (const ent of sec.entries || []) {
          const bullets = ent.bullets || [];
          const highlightsStr = bullets.length > 0
            ? `\n  highlights: (\n${bullets.map((b) => `    [${typstMarkup(b)}],`).join('\n')}\n  ),`
            : '';
          const descStr = ent.note ? `\n  description: [${typstMarkup(ent.note)}],` : '';

          content += `\n#cv-entry(
  title: "${typstString(ent.title)}",
  organization: "${typstString(ent.employer)}",${ent.location ? `\n  location: "${typstString(ent.location)}",` : ''}
  date: "${typstString(ent.date)}",${highlightsStr}${descStr}
)\n`;
        }
      } else if (sec.type === 'text') {
        content += `${typstMarkup(sec.text.trim())}\n`;
      }

      return content;
    })
    .join('\n');

  return (preservePreamble(originalPreamble, preamble, basics) + '\n' + sectionsMarkup).trim() + '\n';
}

/**
 * Serializes Cover Letter document
 */
export function serializeCoverLetter(data) {
  const { basics, recipient, subject, salutation, paragraphs, closing, signer } = data;

  const dateSnippet = recipient.date === 'Today' || !recipient.date
    ? '#datetime.today().display("[day]. [month repr:long] [year]")'
    : `[${recipient.date}]`;

  const paragraphsMarkup = (paragraphs || [])
    .map((p) => p.trim())
    .filter(Boolean)
    .join('\n\n');

  return `// ==============================================================================
// JOBWEAVER TYPST COVER LETTER TEMPLATE
// ==============================================================================

#let primary-color = rgb("${typstString(basics.color || '#004f90')}")
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
  #text(fill: primary-color, size: 20pt, weight: "bold")[${basics.name || 'Alex Muster'}] \\
  #v(0.1cm)
  #text(size: 9pt, fill: muted-color)[
    ${basics.address || 'Vienna, Austria'}
    ${basics.phone ? `#h(0.5em) • #h(0.5em)\n    ${basics.phone}` : ''}
    ${basics.email ? `#h(0.5em) • #h(0.5em)\n    #link("mailto:${basics.email}")[${basics.email.replace('@', '\\@')}]` : ''}
    ${basics.linkedin ? `#h(0.5em) • #h(0.5em)\n    #link("https://linkedin.com/in/${basics.linkedin}")[linkedin.com/in/${basics.linkedin}]` : ''}
  ]
  ${basics.residence ? `\n  #v(0.08cm)\n  #text(size: 8.5pt, fill: muted-color)[*${basics.residence}*]` : ''}
  #v(0.2cm)
  #line(length: 100%, stroke: 0.8pt + primary-color)
]

#v(0.6cm)

// --- Date & Recipient ---
#grid(
  columns: (1fr, auto),
  align(left)[
    ${recipient.contact ? `#text(weight: "bold")[${recipient.contact}] \\\n    ` : ''}${recipient.company ? `${recipient.company} \\\n    ` : ''}${recipient.address ? `${recipient.address}\n    ` : ''}  ],
  align(right)[
    ${dateSnippet}
  ]
)

#v(0.6cm)

// --- Subject Line ---
#text(weight: "bold", size: 11pt)[${subject || 'Application for Open Position'}]

#v(0.4cm)

// --- Salutation ---
${salutation || 'Dear Hiring Team,'}

#v(0.2cm)

// --- Body Paragraphs ---
${paragraphsMarkup}

#v(0.4cm)

// --- Sign-off ---
${closing || 'Sincerely,'}

#v(0.6cm)

#text(weight: "bold")[${signer || basics.name || 'Alex Muster'}]
`;
}

/**
 * Main serializer entry point
 */
export function serializeTypstDocument(kind, data, originalPreamble = '') {
  if (kind === 'moderner-cv') {
    return serializeModernerCv(data, originalPreamble);
  }
  if (kind === 'standard-cv') {
    return serializeStandardCv(data, originalPreamble);
  }
  if (kind === 'cover-letter') {
    if (originalPreamble) throw new Error('Custom letter layout needs Advanced mode.');
    return serializeCoverLetter(data);
  }
  throw new Error(`Unsupported template kind for serialization: ${kind}`);
}
