/**
 * typstSerializer.js
 * Serializes structured Simple Mode form data back into valid Typst source code.
 */
import { CONTACT_SEPARATOR, contactItemKey, locateStandardContact, locateStandardSubtitle, parseModernerCv, parseStandardCv } from './typstParser.js';

export function typstString(value) {
  return JSON.stringify(String(value ?? '')).slice(1, -1);
}

// Form fields are text. Existing emphasis is supported; code delimiters aren't.
export function typstMarkup(value) {
  return String(value ?? '').replace(/(?<!\\)[#@[\]<>$]/g, '\\$&');
}

// Drops the source line that held a removed header element, including its line break marker.
function removeHeaderLine(source, start, end) {
  const lineStart = source.lastIndexOf('\n', start) + 1;
  const lineEnd = source.indexOf('\n', end);
  return source.slice(0, lineStart) + source.slice(lineEnd + 1);
}

// The subtitle is optional, so Simple Mode can add, edit or remove it in place; other header styling stays exact.
function setStandardSubtitle(source, value) {
  const { nameEnd, subtitle } = locateStandardSubtitle(source);
  if (nameEnd < 0) return null;
  if (subtitle) {
    if (!value.trim()) return removeHeaderLine(source, subtitle.start, subtitle.end);
    return source.slice(0, subtitle.contentStart) + typstMarkup(value) + source.slice(subtitle.contentEnd);
  }
  const lineEnd = source.indexOf('\n', nameEnd);
  if (lineEnd < 0) return null;
  const indent = source.slice(source.lastIndexOf('\n', nameEnd) + 1).match(/^[ \t]*/)[0];
  return `${source.slice(0, lineEnd + 1)}${indent}#text(size: 11pt, fill: muted-color)[${typstMarkup(value)}] \\\n${source.slice(lineEnd + 1)}`;
}

function setStandardName(source, value) {
  const name = source.match(/(#text\([^)]*weight:\s*"bold"\)\[)(?:\\[\s\S]|[^\]\\])*\]/);
  if (!name) return null;
  return `${source.slice(0, name.index)}${name[1]}${typstMarkup(value)}]${source.slice(name.index + name[0].length)}`;
}

const CONTACT_ORDER = ['address', 'email', 'linkedin', 'github', 'phone'];

function contactItem(key, value) {
  const text = typstMarkup(value);
  if (key === 'email') return `#link("mailto:${typstString(value)}")[${text}]`;
  if (key === 'linkedin') return `#link("https://linkedin.com/in/${typstString(value)}")[linkedin.com/in/${text}]`;
  if (key === 'github') return `#link("https://github.com/${typstString(value)}")[github.com/${text}]`;
  return text;
}

// Edits one contact item in place; items we don't recognise and custom link labels stay as they are.
function setStandardContact(source, key, oldValue, value) {
  const contact = locateStandardContact(source);
  if (!contact) return null;
  const content = source.slice(contact.contentStart, contact.contentEnd);
  const indent = content.match(/\n([ \t]*)\S/)?.[1] ?? '';
  const items = content.trim() ? content.trim().split(CONTACT_SEPARATOR).map(item => item.trim()) : [];
  const keys = items.map(contactItemKey);
  const index = keys.indexOf(key);
  if (index >= 0 && !value) {
    items.splice(index, 1);
  } else if (index >= 0) {
    items[index] = key === 'address' || key === 'phone'
      ? contactItem(key, value)
      : items[index].split(typstMarkup(oldValue)).join(typstMarkup(value)).split(oldValue).join(typstString(value));
  } else if (value) {
    // New items keep the template's order relative to the ones we know about.
    const after = keys.reduce((last, itemKey, i) => (CONTACT_ORDER.indexOf(itemKey) >= 0 && CONTACT_ORDER.indexOf(itemKey) < CONTACT_ORDER.indexOf(key) ? i : last), -1);
    items.splice(after + 1, 0, contactItem(key, value));
  }
  const closing = content.match(/\n[ \t]*$/)?.[0] ?? '';
  const joined = items.join(`\n${indent}#h(0.5em) • #h(0.5em)\n${indent}`);
  return `${source.slice(0, contact.contentStart)}\n${indent}${joined}${closing}${source.slice(contact.contentEnd)}`;
}

function setStandardResidence(source, value) {
  const contact = locateStandardContact(source);
  if (!contact) return null;
  const { residence } = contact;
  if (residence) {
    if (value.trim()) return source.slice(0, residence.contentStart) + typstMarkup(value) + source.slice(residence.contentEnd);
    const spacing = source.slice(0, residence.start).match(/\n[ \t]*#v\([^)]*\)[ \t]*\n[ \t]*$/);
    const start = spacing ? spacing.index + 1 : residence.start;
    return removeHeaderLine(source, start, residence.end);
  }
  const lineEnd = source.indexOf('\n', contact.end);
  if (lineEnd < 0) return null;
  const indent = source.slice(source.lastIndexOf('\n', contact.end - 1) + 1).match(/^[ \t]*/)[0];
  const fill = source.includes('text-color') ? ', fill: text-color' : '';
  return `${source.slice(0, lineEnd + 1)}${indent}#v(0.1cm)\n${indent}#text(size: 9pt, weight: "bold"${fill})[${typstMarkup(value)}]\n${source.slice(lineEnd + 1)}`;
}

function setModernerSubtitle(source, value) {
  const existing = source.match(/subtitle:\s*(text\([^)]*\))?(?:\[(?:\\[\s\S]|[^\]\\])*\]|"[^"]*")\s*,/);
  if (existing) {
    const end = existing.index + existing[0].length;
    if (!value.trim()) return removeHeaderLine(source, existing.index, end);
    return `${source.slice(0, existing.index)}subtitle: ${existing[1] || ''}[${typstMarkup(value)}],${source.slice(end)}`;
  }
  const name = source.match(/^([ \t]*)name:\s*"[^"]*",[ \t]*\n/m);
  if (!name) return null;
  const end = name.index + name[0].length;
  return `${source.slice(0, end)}${name[1]}subtitle: text(size: 14pt)[${typstMarkup(value)}],\n${source.slice(end)}`;
}

function setModernerName(source, value) {
  const name = source.match(/name:\s*"(?:\\.|[^"\\])*"/);
  if (!name) return null;
  return `${source.slice(0, name.index)}name: "${typstString(value)}"${source.slice(name.index + name[0].length)}`;
}

function setModernerSocial(source, key, value) {
  const quoted = '"(?:\\\\.|[^"\\\\])*"';
  const pattern = key === 'residence' ? `residence:\\s*\\(${quoted},\\s*${quoted},\\s*${quoted}\\)\\s*,?` : `${key}:\\s*${quoted}\\s*,?`;
  const existing = source.match(new RegExp(pattern));
  const line = key === 'residence' ? `residence: ("id-card", "#", "${typstString(value)}"),` : `${key}: "${typstString(value)}",`;
  if (existing) {
    const end = existing.index + existing[0].length;
    return value.trim() ? source.slice(0, existing.index) + line + source.slice(end) : removeHeaderLine(source, existing.index, end);
  }
  const social = source.match(/social:\s*\(([ \t]*\n)([ \t]*)/);
  if (!social) return null;
  const at = social.index + social[0].length;
  return `${source.slice(0, at)}${line}\n${social[2]}${source.slice(at)}`;
}

// Built-in header fields are edited where they stand, so repeated text or an empty field can't block Simple Mode.
function setHeaderField(source, moderner, key, oldValue, value) {
  if (key === 'name') return moderner ? setModernerName(source, value) : setStandardName(source, value);
  if (key === 'subtitle') return moderner ? setModernerSubtitle(source, value) : setStandardSubtitle(source, value);
  if (CONTACT_ORDER.includes(key) || key === 'residence') {
    if (moderner) return setModernerSocial(source, key, value);
    return key === 'residence' ? setStandardResidence(source, value) : setStandardContact(source, key, oldValue, value);
  }
  return undefined;
}

function preservePreamble(original, generated, basics) {
  if (!original) return generated;
  const moderner = original.includes('moderner-cv');
  const parsed = moderner ? parseModernerCv(original) : parseStandardCv(original);
  const old = parsed.data?.basics || {};
  let result = original;
  for (const [key, value] of Object.entries(basics)) {
    if (value === old[key]) continue;
    if (!old[key] && !value) continue;
    const edited = setHeaderField(result, moderner, key, old[key], value);
    if (edited === null) throw new Error('This header change needs Code mode; the custom design has been preserved.');
    if (edited !== undefined) {
      result = edited;
      continue;
    }
    if (!old[key] || !result.includes(old[key])) {
      throw new Error('This header change needs Code mode; the custom design has been preserved.');
    }
    // Replace only existing header values; font/margins/language/macros stay exact.
    const encoded = typstString(old[key]);
    const occurrences = result.split(encoded).length - 1;
    if (occurrences !== 1) {
      throw new Error('This header value appears more than once. Use Code mode to preserve your design.');
    }
    result = result.replace(encoded, typstString(value));
  }
  return result;
}

// One blank line between header and body, however often a document is read and written.
function joinDocument(preamble, sections) {
  return `${preamble.trimEnd()}\n\n${sections}`.trim() + '\n';
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

  return joinDocument(preservePreamble(originalPreamble, headerPreamble, basics), sectionsMarkup);
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
    ${basics.subtitle ? `#text(size: 11pt, fill: muted-color)[${typstMarkup(basics.subtitle)}] \\\n    ` : ''}#v(0.15cm)
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

  return joinDocument(preservePreamble(originalPreamble, preamble, basics), sectionsMarkup);
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
    if (originalPreamble) throw new Error('Custom letter layout needs Code mode.');
    return serializeCoverLetter(data);
  }
  throw new Error(`Unsupported template kind for serialization: ${kind}`);
}
