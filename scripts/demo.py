"""Start a loopback-only demo with disposable data. Each run resets the demo."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--seed-only", type=Path, help="Create demo data in an empty directory, then exit.")
    args = parser.parse_args()
    if args.seed_only:
        from jobweaver.demo_data import seed
        seed(args.seed_only)
        return 0
    if not (ROOT / "webapp" / "dist" / "index.html").is_file():
        parser.error("Build the frontend first: npm --prefix webapp run build")
    # Fail before seeding if another app already uses the requested port.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    with tempfile.TemporaryDirectory(prefix="jobweaver-demo-") as data:
        subprocess.run([sys.executable, __file__, "--seed-only", data], cwd=ROOT, check=True)
        env = {k: v for k, v in os.environ.items()
               if not any(word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))}
        env.update(JOBWEAVER_DEMO="1", JOBWEAVER_DATA_DIR=data, PYTHON_DOTENV_DISABLED="1",
                   PYTHONDONTWRITEBYTECODE="1")
        print(f"Read-only demo: http://127.0.0.1:{args.port} (sign in: demo / demo)", flush=True)
        print("All applicant and company data is fictional. Ctrl+C stops the demo. Run again to reset.", flush=True)
        child = subprocess.Popen([sys.executable, "-m", "uvicorn", "jobweaver.server:app", "--host", "127.0.0.1",
                                  "--port", str(args.port)], cwd=ROOT, env=env)
        previous = signal.signal(signal.SIGTERM, lambda *_: child.terminate())
        try:
            try:
                return child.wait()
            except KeyboardInterrupt:
                return 0
        finally:
            signal.signal(signal.SIGTERM, previous)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
