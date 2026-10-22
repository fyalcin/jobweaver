# Every Source delivers Postings through one schema and one gate

Records from every Source pass one gate before storage: a Mapping turns the raw record into a Posting, the gate
checks the required fields (Source, the Source's own ID, URL, title, company, description), normalises the
rest (dates to ISO or empty, HTML to text, salary to numbers or empty) and drops every field the schema does not
name. Failures become Rejected records with a reason. Mappings are declarative and run without a model call;
an AI agent may draft one from sample records, and a person approves it.

We chose this over letting a model map each record (cost grows with every posting, results drift, and a
posting's text could steer the mapping) and over generated Python mappers (code written from untrusted sample
data). Before this, each Source had its own hand-written mapper, only company feeds checked required fields,
and two mappers invented random IDs when a record had none, so the same posting could be stored twice.

## Consequences

- A new Source needs only a Connector and a Mapping; the gate is the public plug-in contract.
- Field names are Jobweaver's own (`job_url`, `posted_date`), matching the database; a JSON-LD reader
  translates schema.org `JobPosting` into them. No migration: existing Jobs stay as they are.
- "Clean database" means only schema fields are stored. Descriptions are kept as written, contact lines
  included.
- A sudden rise in Rejected records from one Source means its shape changed; that is the signal to redraft
  its Mapping, not to loosen the gate.
