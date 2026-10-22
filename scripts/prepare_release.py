"""Copy intended files into an empty directory without carrying Git history or user state."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        parser.error("Destination must be empty. Existing files will not be replaced.")
    paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).split(b"\0")
    count = 0
    for raw in sorted(set(paths)):
        if not raw:
            continue
        relative = Path(raw.decode())
        source = ROOT / relative
        if not source.is_file():
            continue
        if not source.resolve().is_relative_to(ROOT):
            parser.error(f"File resolves outside the checkout: {relative}")
        if relative.name == ".env" or relative.parts[0] == "profiles" or relative.suffix == ".db" or relative.name == ".session_secret":
            parser.error(f"User state must not enter the release: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    print(f"Copied {count} files to {destination}. No Git history, user state or ignored media was copied.")
    print("Review and approve release media before adding it. Initialize a fresh repository for publication.")


if __name__ == "__main__":
    main()
