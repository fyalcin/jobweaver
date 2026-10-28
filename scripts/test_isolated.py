"""Run unittest discovery in a disposable source copy without private state.

Uses the already installed environment, never installs dependencies. Run with
`uv run --offline --no-sync python scripts/test_isolated.py`.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="gimme-tests-") as temp:
        scratch = Path(temp)
        for path in root.glob("*.py"):
            shutil.copy2(path, scratch / path.name)
        for name in ("tests", "base-cv-tex", "base-cl-tex", "base-typst", "scripts", "examples"):
            shutil.copytree(root / name, scratch / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("CV-plaintext.txt", "scraper_config.json", "pyproject.toml", "uv.lock"):
            if (root / name).exists():
                shutil.copy2(root / name, scratch / name)
        # Static frontend files are needed by tests; no private profiles/history.
        shutil.copytree(root / "webapp" / "src", scratch / "webapp" / "src")
        shutil.copytree(root / "webapp" / "public" / "typst", scratch / "webapp" / "public" / "typst")
        (scratch / "profiles").mkdir()
        # Guard before discovery imports server; no dotenv/secrets or network calls.
        (scratch / "sitecustomize.py").write_text('''
import os, socket, logging
logging.disable(logging.CRITICAL)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
def denied(*args, **kwargs):
    raise RuntimeError("External network disabled in isolated tests")
socket.socket.connect = denied
socket.create_connection = denied
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
''')
        env = {k: v for k, v in os.environ.items()
               if not any(word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))
               and k not in ("JOBWEAVER_DATA_DIR", "JOBWEAVER_DEMO")}
        # Agent/cron shells may omit Homebrew although native compilers exist.
        # Prefer the caller's PATH; fall back only to an installed Typst binary.
        if shutil.which("typst", path=env.get("PATH", "")) is None:
            for bin_dir in (Path.home() / ".linuxbrew/bin",
                            Path("/home/linuxbrew/.linuxbrew/bin"),
                            Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
                binary = bin_dir / "typst"
                if binary.is_file() and os.access(binary, os.X_OK):
                    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
                    break
        env.update(GIMME_ISOLATED_TESTS="1", PYTHONPATH=str(scratch), PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(scratch),
                   JOBWEAVER_ALLOWED_HOSTS='testserver', JOBWEAVER_HTTPS_ONLY='0')
        # Direct installed interpreter avoids uv downloads or resolver writes.
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "tests", *sys.argv[1:]],
                                cwd=scratch, env=env)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
