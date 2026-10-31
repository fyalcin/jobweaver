/**
 * typstParser.js
 * Parses Typst source code into a structured data model for Simple Mode editing.
 * Supports:
 * 1. @preview/moderner-cv (base-cv-moderner.typ and user variants)
 * 2. Standard Typst CV (base-cv.typ using helper components)
 * 3. Standard Typst Cover Letter (base-cl.typ)
 */

/**
 * Extracts balanced brackets content: e.g. for [ ... ] or ( ... )
 */
export function extractBracketContent(str, startIndex, openChar = '[', closeChar = ']') {
  let depth = 0;
  let start = -1;
  for (let i = startIndex; i < str.length; i++) {
    if (str[i] === openChar) {
      if (depth === 0) start = i + 1;
      depth++;
    } else if (str[i] === closeChar) {
      depth--;
      if (depth === 0 && start !== -1) {
        return { content: str.slice(start, i), endIndex: i };
      }
    }
  }
  return null;
}

/**
 * Extracts balanced parenthesis content respecting string quotes and escapes
 */
export function extractParenContent(source, openParenIdx) {
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = openParenIdx; i < source.length; i++) {
    const ch = source[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (ch === '\\') {
      escape = true;
      continue;
    }
    if (ch === '"' && !inString) {
      inString = true;
      continue;
    } else if (ch === '"' && inString) {
      inString = false;
      continue;
    }
    if (!inString) {
      if (ch === '(') depth++;
      else if (ch === ')') {
        depth--;
        if (depth === 0) {
          return { content: source.slice(openParenIdx + 1, i), endIndex: i };
        }
      }
    }
  }
  return null;
}

/**
 * Helper to extract named bracket or quoted argument value:
 * e.g. extractNamedBracketArg(str, "date") extracts [2021 -- Present] -> "2021 -- Present"
 */
export function extractNamedBracketArg(paramsStr, argName) {
  const marker = `${argName}:`;
  const pos = paramsStr.indexOf(marker);
  if (pos === -1) return '';
  const openBracket = paramsStr.indexOf('[', pos);
  const quoteStart = paramsStr.indexOf('"', pos);

  // If quote comes before bracket or bracket doesn't exist
  if (quoteStart !== -1 && (openBracket === -1 || quoteStart < openBracket)) {
    const quoteEnd = paramsStr.indexOf('"', quoteStart + 1);
    if (quoteEnd !== -1) return paramsStr.slice(quoteStart + 1, quoteEnd).trim();
  }

  if (openBracket !== -1) {
    const bRes = extractBracketContent(paramsStr, openBracket);
    if (bRes) return bRes.content.trim();
  }
  return '';
}

/**
 * Detect template kind from Typst source
 */
export function detectTemplateKind(source) {
  if (!source || typeof source !== 'string') return 'unsupported';
  if (source.includes('@preview/moderner-cv') || source.includes('moderner-cv.with')) {
    return 'moderner-cv';
  }
  if (source.includes('#cv-section') || source.includes('#cv-skill-group')) {
    return 'standard-cv';
  }
  if (
    source.includes('Application for') ||
    source.includes('Dear Hiring Team') ||
    source.includes('Sehr geehrte') ||
    source.includes('Applicant Header') ||
    (source.includes('cl_template') || source.includes('Sincerely'))
  ) {
    return 'cover-letter';
  }
  return 'unsupported';
}

/**
 * Parses moderner-cv template
 */
export function parseModernerCv(source) {
  try {
    // 1. Basics / Header from moderner-cv.with(...)
    const basics = {
      name: '',
      subtitle: '',
      color: '#004f90',
      email: '',
      github: '',
      linkedin: '',
      address: '',
      phone: '',
      residence: '',
    };

    const nameMatch = source.match(/name:\s*"([^"]+)"/);
    if (nameMatch) basics.name = nameMatch[1].trim();

    // Subtitle can be subtitle: text(size: 14pt)[...] or subtitle: "..."
    const subtitleMatch = source.match(/subtitle:\s*(?:text\([^)]*\))?\[((?:\\[\s\S]|[^\]\\])*)\]/) || source.match(/subtitle:\s*"([^"]+)"/);
    if (subtitleMatch) basics.subtitle = unescapeMarkup(subtitleMatch[1]).trim();

    const colorMatch = source.match(/color:\s*rgb\("([^"]+)"\)/);
    if (colorMatch) basics.color = colorMatch[1];

    const emailMatch = source.match(/email:\s*"([^"]+)"/);
    if (emailMatch) basics.email = emailMatch[1].trim();

    const githubMatch = source.match(/github:\s*"([^"]+)"/);
    if (githubMatch) basics.github = githubMatch[1].trim();

    const linkedinMatch = source.match(/linkedin:\s*"([^"]+)"/);
    if (linkedinMatch) basics.linkedin = linkedinMatch[1].trim();

    const addressMatch = source.match(/address:\s*"([^"]+)"/);
    if (addressMatch) basics.address = addressMatch[1].trim();

    const phoneMatch = source.match(/phone:\s*"([^"]+)"/);
    if (phoneMatch) basics.phone = phoneMatch[1].trim();

    const residenceMatch = source.match(/residence:\s*\([^,]+,\s*[^,]+,\s*"([^"]+)"\)/);
    if (residenceMatch) basics.residence = residenceMatch[1].trim();

    // 2. Sections
    // Split document starting from first '= '
    const firstSectionIdx = source.indexOf('\n= ');
    const headerPreamble = firstSectionIdx !== -1 ? source.slice(0, firstSectionIdx) : '';
    const bodyText = firstSectionIdx !== -1 ? source.slice(firstSectionIdx) : '';

    const sections = [];
    const rawSections = bodyText.split(/\n=\s+/).filter(Boolean);

    for (const rawSec of rawSections) {
      const lines = rawSec.split('\n');
      const sectionTitle = lines[0].trim();
      const sectionBody = lines.slice(1).join('\n').trim();

      const lowerTitle = sectionTitle.toLowerCase();

      // Check if it's summary
      if (lowerTitle.includes('summary') || lowerTitle.includes('profile')) {
        let summaryText = '';
        const summaryLineMatch = sectionBody.match(/#cv-line\(\[\],\s*\[([\s\S]*?)\]\s*\)/);
        if (summaryLineMatch) {
          summaryText = summaryLineMatch[1].trim();
        } else {
          summaryText = sectionBody.trim();
        }
        sections.push({
          title: sectionTitle,
          type: 'summary',
          text: summaryText,
        });
        continue;
      }

      // Check if it's skills
      if (lowerTitle.includes('skill')) {
        const skillsGroups = [];
        const skillRegex = /#cv-line\(\[\*([^*]+)\*\]\s*,\s*\[([\s\S]*?)\]\s*\)/g;
        let sm;
        while ((sm = skillRegex.exec(sectionBody)) !== null) {
          skillsGroups.push({
            category: sm[1].trim(),
            skills: sm[2].trim(),
          });
        }
        sections.push({
          title: sectionTitle,
          type: 'skills',
          groups: skillsGroups,
        });
        continue;
      }

      // Check if it has cv-entry-multiline or cv-entry
      const entries = [];
      let emIdx = 0;
      let hasEntries = false;

      while ((emIdx = sectionBody.indexOf('#cv-entry', emIdx)) !== -1) {
        const isMulti = sectionBody.slice(emIdx, emIdx + 25).startsWith('#cv-entry-multiline');
        const parenStart = sectionBody.indexOf('(', emIdx);
        if (parenStart === -1) break;
        const pRes = extractParenContent(sectionBody, parenStart);
        if (!pRes) break;

        hasEntries = true;
        const paramsStr = pRes.content;
        let nextIdx = pRes.endIndex + 1;

        // Check for trailing bracket [ ... ] right after closing paren
        while (nextIdx < sectionBody.length && /\s/.test(sectionBody[nextIdx])) nextIdx++;
        let trailingBody = '';
        if (sectionBody[nextIdx] === '[') {
          const bRes = extractBracketContent(sectionBody, nextIdx);
          if (bRes) {
            trailingBody = bRes.content;
            nextIdx = bRes.endIndex + 1;
          }
        }

        const date = extractNamedBracketArg(paramsStr, 'date');
        const employer = extractNamedBracketArg(paramsStr, 'employer');
        const title = extractNamedBracketArg(paramsStr, 'title');

        // Check if there is an inner bracket [ ... ] after title: [...]
        let innerBody = '';
        const titlePos = paramsStr.indexOf('title:');
        let searchStart = 0;
        if (titlePos !== -1) {
          const openB = paramsStr.indexOf('[', titlePos);
          if (openB !== -1) {
            const bRes = extractBracketContent(paramsStr, openB);
            if (bRes) searchStart = bRes.endIndex + 1;
          }
        }
        const nextBracket = paramsStr.indexOf('[', searchStart);
        if (nextBracket !== -1) {
          const bRes = extractBracketContent(paramsStr, nextBracket);
          if (bRes) innerBody = bRes.content;
        }

        const rawContent = (innerBody || trailingBody || '').trim();
        const bullets = [];
        let note = '';

        if (isMulti) {
          const bulletLines = rawContent
            .split('\n')
            .map((l) => l.trim())
            .filter((l) => l.startsWith('- ') || l.startsWith('• ') || l.startsWith('* '));

          for (const bl of bulletLines) {
            bullets.push(bl.replace(/^[-•*]\s+/, '').trim());
          }
          if (bullets.length === 0 && rawContent) {
            note = rawContent;
          }
        } else {
          note = rawContent;
        }

        entries.push({
          title,
          employer,
          date,
          location: '',
          bullets,
          note,
        });

        emIdx = nextIdx;
      }

      if (hasEntries) {
        sections.push({
          title: sectionTitle,
          type: 'entries',
          entries,
        });
        continue;
      }

      // Check for standalone cv-line items (e.g. Projects / Technical Interests)
      const lineItems = [];
      const lineRegex = /#cv-line\(\[([^*\]]*|\*[^*]+\*)\]\s*,\s*\[([\s\S]*?)\]\s*\)/g;
      let lm;
      while ((lm = lineRegex.exec(sectionBody)) !== null) {
        const cat = lm[1].replace(/^\*|\*$/g, '').trim();
        lineItems.push({
          category: cat,
          content: lm[2].trim(),
        });
      }

      if (lineItems.length > 0) {
        sections.push({
          title: sectionTitle,
          type: 'lines',
          items: lineItems,
        });
        continue;
      }

      // Fallback: generic text section
      sections.push({
        title: sectionTitle,
        type: 'text',
        text: sectionBody.trim(),
      });
    }

    return {
      supported: true,
      kind: 'moderner-cv',
      data: {
        basics,
        sections,
      },
      rawPreamble: headerPreamble,
    };
  } catch (err) {
    console.error('Failed to parse moderner-cv:', err);
    return { supported: false, reason: err.message };
  }
}

function unescapeMarkup(value) {
  return value.replace(/\\([#@[\]<>$])/g, '$1');
}

/**
 * Finds the optional subtitle between the name and the contact block of a standard-cv header.
 */
export function locateStandardSubtitle(source) {
  const name = source.match(/#text\([^)]*weight:\s*"bold"\)\[[\s\S]*?\]/);
  const contact = source.match(/#text\(size:\s*9pt,\s*fill:\s*muted-color\)\[/);
  if (!name || !contact || contact.index < name.index) return { nameEnd: -1, subtitle: null };
  const nameEnd = name.index + name[0].length;
  const match = source.slice(nameEnd, contact.index).match(/#text\([^)]*\)\[((?:\\[\s\S]|[^\]\\])*)\]/);
  if (!match) return { nameEnd, subtitle: null };
  const start = nameEnd + match.index;
  const contentEnd = start + match[0].length - 1;
  return { nameEnd, subtitle: { start, end: contentEnd + 1, contentStart: contentEnd - match[1].length, contentEnd } };
}

// Index just past the bracket that closes the one at `open`, skipping escapes and nested links.
function closingBracket(source, open) {
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === '\\') i++;
    else if (source[i] === '[') depth++;
    else if (source[i] === ']' && --depth === 0) return i + 1;
  }
  return -1;
}

/**
 * Finds the contact block of a standard-cv header and the work authorization line below it.
 */
export function locateStandardContact(source) {
  const match = source.match(/#text\(size:\s*9pt,\s*fill:\s*muted-color\)\[/);
  if (!match) return null;
  const open = match.index + match[0].length - 1;
  const end = closingBracket(source, open);
  if (end < 0) return null;
  const sectionStart = source.indexOf('#cv-section("', end);
  const rest = source.slice(end, sectionStart < 0 ? undefined : sectionStart);
  const line = rest.match(/#text\(size:\s*9pt,\s*weight:\s*"bold"[^)]*\)\[((?:\\[\s\S]|[^\]\\])*)\]/);
  let residence = null;
  if (line) {
    const start = end + line.index;
    const contentEnd = start + line[0].length - 1;
    residence = { start, end: contentEnd + 1, contentStart: contentEnd - line[1].length, contentEnd };
  }
  return { contentStart: open + 1, contentEnd: end - 1, end, residence };
}

export const CONTACT_SEPARATOR = /\s*#h\([^)]*\)\s*•\s*#h\([^)]*\)\s*/;

// Names one item of the contact block, so it can be edited without touching the others.
export function contactItemKey(item, index) {
  if (/link\("mailto:/.test(item)) return 'email';
  if (/link\("https?:\/\/(?:www\.)?linkedin\.com\/in\//.test(item)) return 'linkedin';
  if (/link\("https?:\/\/(?:www\.)?github\.com\//.test(item)) return 'github';
  if (/^\+?\d[\d\s()/-]{6,}\d$/.test(item)) return 'phone';
  if (index === 0 && !item.includes('#') && !item.includes('http')) return 'address';
  return null;
}

/**
 * Parses standard-cv template (base-cv.typ)
 */
export function parseStandardCv(source) {
  try {
    const basics = {
      name: '',
      subtitle: '',
      color: '#004f90',
      email: '',
      github: '',
      linkedin: '',
      address: '',
      phone: '',
      residence: '',
    };

    // Name in #align(center)[ ... #text(..., size: 22pt, weight: "bold")[Name] ... ]
    const nameMatch = source.match(/#text\([^)]*weight:\s*"bold"\)\[([\s\S]*?)\]/);
    if (nameMatch) basics.name = unescapeMarkup(nameMatch[1]).trim();

    // Contact details: read only the header's contact block, never dates or links further down.
    const contact = locateStandardContact(source);
    const items = contact
      ? source.slice(contact.contentStart, contact.contentEnd).trim().split(CONTACT_SEPARATOR).map(item => item.trim())
      : [];
    items.forEach((item, index) => {
      const key = contactItemKey(item, index);
      if (key === 'email') basics.email = item.match(/link\("mailto:([^"]+)"\)/)?.[1].trim() || '';
      if (key === 'linkedin') basics.linkedin = item.match(/linkedin\.com\/in\/([^")]+)"\)/)?.[1].trim() || '';
      if (key === 'github') basics.github = item.match(/github\.com\/([^")]+)"\)/)?.[1].trim() || '';
      if (key === 'phone') basics.phone = item;
      if (key === 'address') basics.address = unescapeMarkup(item);
    });

    if (contact?.residence) {
      basics.residence = unescapeMarkup(source.slice(contact.residence.contentStart, contact.residence.contentEnd)).replace(/\*/g, '').trim();
    } else {
      const residenceMatch = source.match(/(\*?Eligible to work in the EU\*?|\*?Daueraufenthalt EU[^\n\]<]*)/);
      if (residenceMatch) basics.residence = residenceMatch[1].replace(/\*/g, '').trim();
    }

    const subtitle = locateStandardSubtitle(source).subtitle;
    if (subtitle) basics.subtitle = unescapeMarkup(source.slice(subtitle.contentStart, subtitle.contentEnd)).trim();

    // Split sections by #cv-section("...")
    const secSplit = source.split(/#cv-section\("([^"]+)"\)/);
    const sections = [];

    // secSplit[0] is preamble + header
    for (let i = 1; i < secSplit.length; i += 2) {
      const sectionTitle = secSplit[i].trim();
      const sectionBody = (secSplit[i + 1] || '').trim();
      const lowerTitle = sectionTitle.toLowerCase();

      // Skills section
      if (lowerTitle.includes('skill')) {
        const groups = [];
        const skillRegex = /#cv-skill-group\(\s*category:\s*"([^"]*)"\s*,\s*skills:\s*(?:"([^"]*)"|\[([\s\S]*?)\])\s*,?\s*\)/g;
        let sm;
        while ((sm = skillRegex.exec(sectionBody)) !== null) {
          groups.push({
            category: sm[1].trim(),
            skills: (sm[2] !== undefined ? sm[2] : sm[3] || '').trim(),
          });
        }
        sections.push({
          title: sectionTitle,
          type: 'skills',
          groups,
        });
        continue;
      }

      // Entries section
      const entries = [];
      let entryIdx = 0;
      let hasEntries = false;

      while ((entryIdx = sectionBody.indexOf('#cv-entry', entryIdx)) !== -1) {
        const parenStart = sectionBody.indexOf('(', entryIdx);
        if (parenStart === -1) break;
        const pRes = extractParenContent(sectionBody, parenStart);
        if (!pRes) break;

        hasEntries = true;
        const p = pRes.content;
        const nextIdx = pRes.endIndex + 1;

        const title = extractNamedBracketArg(p, 'title');
        const employer = extractNamedBracketArg(p, 'organization');
        const location = extractNamedBracketArg(p, 'location');
        const date = extractNamedBracketArg(p, 'date');

        const bullets = [];
        const hlMatch = p.match(/highlights:\s*\(([\s\S]*?)\)/);
        if (hlMatch) {
          const hlContent = hlMatch[1];
          const bulletMatches = hlContent.match(/\[([\s\S]*?)\]/g) || [];
          for (const bm of bulletMatches) {
            const raw = bm.slice(1, -1).trim();
            if (raw) bullets.push(raw);
          }
        }

        const descMatch = p.match(/description:\s*(?:"([^"]*)"|\[([\s\S]*?)\])/);
        const note = descMatch ? (descMatch[1] || descMatch[2] || '').trim() : '';

        entries.push({
          title,
          employer,
          location,
          date,
          bullets,
          note,
        });

        entryIdx = nextIdx;
      }

      if (hasEntries) {
        sections.push({
          title: sectionTitle,
          type: 'entries',
          entries,
        });
        continue;
      }

      // If plain text (Summary / Profile)
      sections.push({
        title: sectionTitle,
        type: 'summary',
        text: sectionBody.replace(/\/\/[^\n]*/g, '').trim(),
      });
    }

    return {
      supported: true,
      kind: 'standard-cv',
      data: {
        basics,
        sections,
      },
      rawPreamble: secSplit[0] || '',
    };
  } catch (err) {
    console.error('Failed to parse standard-cv:', err);
    return { supported: false, reason: err.message };
  }
}

/**
 * Parses Cover Letter template (base-cl.typ)
 */
export function parseCoverLetter(source) {
  try {
    const basics = {
      name: '',
      address: '',
      phone: '',
      email: '',
      linkedin: '',
      residence: '',
    };

    const nameMatch = source.match(/#text\([^)]*size:\s*20pt[^)]*\)\[([\s\S]*?)\]/) ||
                      source.match(/#text\(fill:\s*primary-color[^)]*\)\[([\s\S]*?)\]/);
    if (nameMatch) basics.name = nameMatch[1].trim();

    const emailMatch = source.match(/link\("mailto:([^"]+)"\)/);
    if (emailMatch) basics.email = emailMatch[1].trim();

    const linkedinMatch = source.match(/link\("https?:\/\/(?:www\.)?linkedin\.com\/in\/([^")]+)"\)/);
    if (linkedinMatch) basics.linkedin = linkedinMatch[1].trim();

    const phoneMatch = source.match(/(\+?\d[\d\s-]{7,}\d)/);
    if (phoneMatch) basics.phone = phoneMatch[1].trim();

    const residenceMatch = source.match(/(\*?Daueraufenthalt EU[^\n\]<]*|\*?Eligible to work[^\n\]<]*)/);
    if (residenceMatch) basics.residence = residenceMatch[1].replace(/\*/g, '').trim();

    const contactBlockMatch = source.match(/#text\(size:\s*9pt,\s*fill:\s*muted-color\)\[([\s\S]*?)\]/);
    if (contactBlockMatch) {
      const firstLine = contactBlockMatch[1].trim().split('\n')[0].replace(/#h\([^)]*\)/g, '').replace(/•/g, '').trim();
      if (firstLine && !firstLine.includes('http') && !firstLine.includes('@')) {
        basics.address = firstLine;
      }
    }

    // Recipient & Date
    const recipient = {
      contact: '',
      company: '',
      address: '',
      date: '',
    };

    const leftIdx = source.indexOf('align(left)[');
    const rightIdx = source.indexOf('align(right)[');
    if (leftIdx !== -1) {
      const leftBracket = extractBracketContent(source, leftIdx + 'align(left)'.length, '[', ']');
      if (leftBracket) {
        const recLines = leftBracket.content
          .split('\n')
          .map((l) => l.replace(/#text\([^)]*\)\[([\s\S]*?)\]/g, '$1').replace(/[\\\][]/g, '').trim())
          .filter(Boolean);
        if (recLines.length > 0) recipient.contact = recLines[0];
        if (recLines.length > 1) recipient.company = recLines[1];
        if (recLines.length > 2) recipient.address = recLines.slice(2).join(', ');
      }
    }

    if (rightIdx !== -1) {
      const rightBracket = extractBracketContent(source, rightIdx + 'align(right)'.length, '[', ']');
      if (rightBracket) {
        const dateRaw = rightBracket.content.trim();
        recipient.date = dateRaw.includes('datetime.today') ? 'Today' : dateRaw.replace(/[\][]/g, '').trim();
      }
    }

    // Subject
    let subject = '';
    const subjectMatch = source.match(/#text\(weight:\s*"bold",\s*size:\s*11pt\)\[([\s\S]*?)\]/);
    if (subjectMatch) subject = subjectMatch[1].trim();

    // Salutation
    let salutation = 'Dear Hiring Team,';
    const salutationMatch = source.match(/(Dear [^,\n]+,|Sehr geehrte[^,\n]+,)/);
    if (salutationMatch) salutation = salutationMatch[1].trim();

    // Sign-off
    let closing = 'Sincerely,';
    const closingMatch = source.match(/(Sincerely,|Mit freundlichen Grüßen,|Mit besten Grüßen,)/);
    if (closingMatch) closing = closingMatch[1].trim();

    const closeIdx = source.lastIndexOf(closing);
    let signer = basics.name;
    if (closeIdx !== -1) {
      const afterClosing = source.slice(closeIdx);
      const signerMatch = afterClosing.match(/#text\(weight:\s*"bold"\)\[([\s\S]*?)\]/);
      if (signerMatch) signer = signerMatch[1].trim();
    }

    // Body Paragraphs: between salutation and closing
    const paragraphs = [];
    const salIdx = source.indexOf(salutation);

    if (salIdx !== -1 && closeIdx !== -1 && closeIdx > salIdx) {
      const rawBody = source.slice(salIdx + salutation.length, closeIdx);
      const rawParas = rawBody
        .split(/\n\s*\n/)
        .map((p) => p.replace(/#v\([^)]*\)/g, '').trim())
        .filter(Boolean);

      for (const p of rawParas) {
        const cleaned = p.replace(/\/\/[^\n]*/g, '').trim();
        if (cleaned) paragraphs.push(cleaned);
      }
    }

    return {
      supported: true,
      kind: 'cover-letter',
      data: {
        basics,
        recipient,
        subject,
        salutation,
        paragraphs,
        closing,
        signer,
      },
      rawPreamble: '',
    };
  } catch (err) {
    console.error('Failed to parse cover-letter:', err);
    return { supported: false, reason: err.message };
  }
}

/**
 * Main parse entry point: detects template kind and parses into form state
 */
export function parseTypstDocument(source) {
  if (source?.includes('GIMME_APPROVED')) {
    return { supported: false, reason: 'Reviewed document: use Code mode to preserve its layout and evidence.' };
  }
  const kind = detectTemplateKind(source);
  if (kind === 'moderner-cv') {
    return parseModernerCv(source);
  }
  if (kind === 'standard-cv') {
    return parseStandardCv(source);
  }
  if (kind === 'cover-letter') {
    return { ...parseCoverLetter(source), rawPreamble: source };
  }
  return {
    supported: false,
    reason: 'Document uses an unrecognized or custom Typst layout.',
  };
}
