"""Check intended release files for credentials and private workspace references. Never print matched values."""
import json
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "provider token": rb"(?:sk-or-v1-[a-f0-9]{32,}|github_pat_[A-Za-z0-9_]{40,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16})",
    "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-pattern", help="Additional regular expression for private names, addresses or host paths.")
    args = parser.parse_args()
    patterns = dict(PATTERNS)
    if args.private_pattern:
        patterns["personal workspace reference"] = args.private_pattern.encode()
    paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).split(b"\0")
    findings, count = [], 0
    for raw in sorted(set(paths)):
        if not raw:
            continue
        relative = raw.decode()
        path = ROOT / relative
        if not path.is_file():
            continue
        count += 1
        for category, pattern in patterns.items():
            if re.search(pattern, path.read_bytes(), re.I):
                findings.append({"file": relative, "category": category})
        if relative == ".env" or relative.startswith("profiles/") or path.suffix == ".db" or path.name == ".session_secret":
            findings.append({"file": relative, "category": "user state included"})
    print(json.dumps({"files_checked": count, "findings": findings,
                      "scope": "Current intended files only. Targeted patterns, not a complete security audit. Development history is excluded."}, indent=2))
    return bool(findings)


if __name__ == "__main__":
    sys.exit(main())
