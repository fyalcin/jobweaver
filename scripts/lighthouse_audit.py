#!/usr/bin/env python3
"""scripts/lighthouse_audit.py — Authenticated Lighthouse CLI Audit Runner.

Runs Google Lighthouse CLI against Jobweaver (Vite / FastAPI) with an
authenticated session cookie, extracting Core Web Vitals, category scores
(Performance, Accessibility, Best Practices, SEO), and diagnostic opportunities.

Usage:
    uv run python scripts/lighthouse_audit.py --preset all
    uv run python scripts/lighthouse_audit.py --preset desktop
    uv run python scripts/lighthouse_audit.py --preset mobile
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from auth import SESSION_COOKIE_NAME, create_session_token
from db import get_user_by_username, init_db


def resolve_user_id(username: str) -> int:
    init_db()
    user = get_user_by_username(username)
    if user and "id" in user:
        return user["id"]
    return 1


def score_badge(score: float | None) -> str:
    if score is None:
        return "N/A"
    pct = int(round(score * 100))
    if pct >= 90:
        return f"🟢 {pct}"
    if pct >= 50:
        return f"🟡 {pct}"
    return f"🔴 {pct}"


def rating_badge(metric_name: str, val: float | None) -> str:
    if val is None:
        return "⚪ N/A"
    if metric_name == "lcp":
        # ms: Good <= 2500, Needs Improvement <= 4000
        if val <= 2500:
            return "🟢 Good"
        if val <= 4000:
            return "🟡 Needs Improvement"
        return "🔴 Poor"
    if metric_name == "fcp":
        # ms: Good <= 1800, Needs Improvement <= 3000
        if val <= 1800:
            return "🟢 Good"
        if val <= 3000:
            return "🟡 Needs Improvement"
        return "🔴 Poor"
    if metric_name == "tbt":
        # ms: Good <= 200, Needs Improvement <= 600
        if val <= 200:
            return "🟢 Good"
        if val <= 600:
            return "🟡 Needs Improvement"
        return "🔴 Poor"
    if metric_name == "cls":
        # score: Good <= 0.1, Needs Improvement <= 0.25
        if val <= 0.1:
            return "🟢 Good"
        if val <= 0.25:
            return "🟡 Needs Improvement"
        return "🔴 Poor"
    return "⚪ N/A"


def run_preset(
    preset_name: str,
    base_url: str,
    output_dir: Path,
    token: str,
    quiet: bool = True,
) -> dict[str, Any] | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_prefix = output_dir / preset_name

    # Extra headers with authentication cookie
    headers_json = json.dumps({"Cookie": f"{SESSION_COOKIE_NAME}={token}"})

    cmd = [
        "npx",
        "--yes",
        "lighthouse",
        base_url,
        "--chrome-flags=--headless=new --no-sandbox --disable-dev-shm-usage",
        f"--extra-headers={headers_json}",
        "--output=html,json",
        f"--output-path={report_prefix}",
    ]

    if preset_name == "desktop":
        cmd.append("--preset=desktop")
    if quiet:
        cmd.append("--quiet")

    print(f"🚀 Running Lighthouse for {preset_name.capitalize()} on {base_url}...")
    env = os.environ.copy()
    extra_paths = [
        os.path.expanduser("~/.local/share/mise/shims"),
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.cargo/bin"),
        "/usr/local/bin",
    ]
    env["PATH"] = ":".join(p for p in extra_paths if os.path.exists(p)) + ":" + env.get("PATH", "")

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            print(f"❌ Lighthouse failed for {preset_name}: {proc.stderr[:300]}")
            return None
    except subprocess.TimeoutExpired:
        print(f"❌ Lighthouse timed out after 180s on {preset_name}")
        return None
    except Exception as e:
        print(f"❌ Subprocess error on {preset_name}: {e}")
        return None

    # Load JSON report
    json_path = output_dir / f"{preset_name}.report.json"
    if not json_path.exists():
        alt_json = Path(f"{report_prefix}.json")
        if alt_json.exists():
            json_path = alt_json
        else:
            print(f"⚠️ Report JSON not found at {json_path}")
            return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Failed reading Lighthouse report: {e}")
        return None


def generate_markdown_summary(
    reports: dict[str, dict[str, Any]],
    output_dir: Path,
    base_url: str,
) -> Path:
    md_path = output_dir / "LIGHTHOUSE_REPORT.md"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Google Lighthouse UI/UX & Web Vitals Audit Report",
        f"> Audited on **{now_str}** against `{base_url}` using authenticated session.",
        "",
        "## 1. Master Category Scores",
        "",
        "| Preset | Performance | Accessibility | Best Practices | SEO |",
        "|---|---|---|---|---|",
    ]

    for name, data in reports.items():
        cats = data.get("categories", {})
        perf = score_badge(cats.get("performance", {}).get("score"))
        a11y = score_badge(cats.get("accessibility", {}).get("score"))
        bp = score_badge(cats.get("best-practices", {}).get("score"))
        seo = score_badge(cats.get("seo", {}).get("score"))
        lines.append(f"| **{name.capitalize()}** | {perf} | {a11y} | {bp} | {seo} |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Core Web Vitals",
        "",
        "| Preset | Metric | Value | Rating | Target (Good) |",
        "|---|---|---|---|---|",
    ])

    for name, data in reports.items():
        audits = data.get("audits", {})

        fcp = audits.get("first-contentful-paint", {})
        lcp = audits.get("largest-contentful-paint", {})
        tbt = audits.get("total-blocking-time", {})
        cls = audits.get("cumulative-layout-shift", {})
        si = audits.get("speed-index", {})

        lines.append(f"| **{name.capitalize()}** | **LCP** (Largest Contentful Paint) | `{lcp.get('displayValue', 'N/A')}` | {rating_badge('lcp', lcp.get('numericValue'))} | `≤ 2.5s` |")
        lines.append(f"| **{name.capitalize()}** | **FCP** (First Contentful Paint) | `{fcp.get('displayValue', 'N/A')}` | {rating_badge('fcp', fcp.get('numericValue'))} | `≤ 1.8s` |")
        lines.append(f"| **{name.capitalize()}** | **TBT** (Total Blocking Time) | `{tbt.get('displayValue', 'N/A')}` | {rating_badge('tbt', tbt.get('numericValue'))} | `≤ 200ms` |")
        lines.append(f"| **{name.capitalize()}** | **CLS** (Cumulative Layout Shift) | `{cls.get('displayValue', 'N/A')}` | {rating_badge('cls', cls.get('numericValue'))} | `≤ 0.10` |")
        lines.append(f"| **{name.capitalize()}** | **Speed Index** | `{si.get('displayValue', 'N/A')}` | - | `≤ 3.4s` |")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Top Optimization Opportunities",
        "",
    ])

    for name, data in reports.items():
        audits = data.get("audits", {})
        lines.append(f"### {name.capitalize()} Opportunities\n")

        opps = []
        for audit_id, audit in audits.items():
            if audit.get("details", {}).get("type") == "opportunity" and (audit.get("score") or 0) < 0.9:
                savings = audit.get("details", {}).get("overallSavingsMs")
                opps.append({
                    "title": audit.get("title", audit_id),
                    "score": audit.get("score", 0),
                    "display": audit.get("displayValue", ""),
                    "savings": savings or 0,
                    "description": audit.get("description", ""),
                })

        opps.sort(key=lambda x: x["savings"], reverse=True)
        if opps:
            for op in opps[:5]:
                lines.append(f"- **{op['title']}** ({op['display']})")
                if op["description"]:
                    lines.append(f"  *{op['description'][:120]}...*")
        else:
            lines.append("🎉 No major performance bottlenecks identified.")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 4. Interactive HTML Reports",
        "",
    ])
    for name in reports.keys():
        lines.append(f"- [{name.capitalize()} Interactive HTML Report]({name}.report.html)")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Jobweaver Lighthouse UI/UX Audit Runner")
    parser.add_argument(
        "--preset", "-p",
        choices=["desktop", "mobile", "all"],
        default="all",
        help="Lighthouse preset to run (default: all)",
    )
    parser.add_argument("--base-url", default="http://localhost:5173", help="Base webapp URL")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "output" / "ux_audit" / "lighthouse"),
        help="Output directory",
    )
    parser.add_argument("--user", default="admin", help="Username for authenticated session")

    args = parser.parse_args()

    user_id = resolve_user_id(args.user)
    token = create_session_token(user_id)
    output_dir = Path(args.output_dir)

    presets = ["desktop", "mobile"] if args.preset == "all" else [args.preset]
    reports: dict[str, dict[str, Any]] = {}

    for preset in presets:
        report = run_preset(
            preset_name=preset,
            base_url=args.base_url,
            output_dir=output_dir,
            token=token,
        )
        if report:
            reports[preset] = report

    if reports:
        md_file = generate_markdown_summary(reports, output_dir, args.base_url)
        print(f"\n📊 Lighthouse audit report generated at:\n  {md_file}")
    else:
        print("⚠️ No Lighthouse reports could be generated. Ensure the dev server is running.")


if __name__ == "__main__":
    main()
