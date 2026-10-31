# Security policy

## Report a vulnerability

Do not open a public issue. Use [GitHub private vulnerability reporting](https://github.com/fyalcin/jobweaver/security/advisories/new).

Include these items:

- The affected commit or version.
- The steps to reproduce the problem.
- The effect that you observed.

Use fictional data in your report. Do not include real API keys, CVs, or personal data.

One person maintains Jobweaver, so a reply can take some time.

## Supported versions

Only the latest commit on `main` gets security fixes.

## Scope

These problems are in scope:

- Access to the data of another account.
- Authentication, session, and request-origin bypasses.
- Path traversal and escapes from the document compiler sandbox.
- Requests to private addresses through URL import.
- Leaks of API keys or personal data.

These problems are out of scope:

- Problems that exist only if you ignore the deployment guidance in the [README](README.md).
- Problems in model providers, job sites, and other third-party services.
- Problems in the fictional demo data.
