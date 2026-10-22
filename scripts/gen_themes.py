#!/usr/bin/env python3
"""Generate webapp/src/themes.css from the design-experiment palettes.

Each theme = (1) app-wide CSS variables under [data-theme="id"], and
(2) the experiment's component overrides scoped under the same attribute.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ROOT / "design_experiments/mobile-polish/variants"
OUT = ROOT / "webapp/src/themes.css"

VARS = {
    "aurora": """  --bg-color: #08080f;
  --surface-bg: #0e0e18;
  --surface-color: #13131f;
  --surface-card: #13131f;
  --surface-hover: #1e1e30;
  --border-color: #26263c;
  --text-primary: #f2f2ff;
  --text-secondary: #a6a8cc;
  --text-muted: #70739a;
  --primary-color: #6366f1;
  --primary-hover: #4f46e5;
  --primary-light: #a5b4fc;
  --primary-text: #ffffff;
  --success-color: #34d399;
  --danger-color: #fb7185;
  --warning-color: #fbbf24;
  --brand-gradient: linear-gradient(135deg, #a5b4fc 0%, #818cf8 50%, #c084fc 100%);
  --brand-logo-bg: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  --nav-active-bg: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  --nav-active-text: #ffffff;
  --nav-active-shadow: 0 4px 16px rgba(99, 102, 241, 0.5);
  --editor-bg: #08080f;
  --editor-gutter: #05050a;
  --editor-gutter-text: #5b5e80;
  --editor-gutter-border: rgba(255, 255, 255, 0.07);
  --score-high-bg: rgba(52, 211, 153, 0.16);
  --score-high-text: #34d399;
  --score-high-border: rgba(52, 211, 153, 0.34);
  --score-med-bg: rgba(251, 191, 36, 0.16);
  --score-med-text: #fbbf24;
  --score-med-border: rgba(251, 191, 36, 0.34);
  --score-low-bg: rgba(251, 113, 133, 0.16);
  --score-low-text: #fb7185;
  --score-low-border: rgba(251, 113, 133, 0.34);
  --radius-sm: 8px;
  --radius-md: 16px;
  --radius-lg: 20px;
  --shadow-glow: 0 0 20px rgba(99, 102, 241, 0.4);
""",
    "ember": """  --bg-color: #100c09;
  --surface-bg: #16110d;
  --surface-color: #1b140f;
  --surface-card: #1d1712;
  --surface-hover: #2a2018;
  --border-color: #33251a;
  --text-primary: #f7ede0;
  --text-secondary: #b89b7e;
  --text-muted: #8a6f56;
  --primary-color: #f59e0b;
  --primary-hover: #d97706;
  --primary-light: #fcd9a8;
  --primary-text: #23140a;
  --success-color: #34d399;
  --danger-color: #fb7185;
  --warning-color: #fbbf24;
  --brand-gradient: linear-gradient(135deg, #f59e0b 0%, #fb7185 100%);
  --brand-logo-bg: linear-gradient(135deg, #f59e0b 0%, #fb7185 100%);
  --nav-active-bg: linear-gradient(135deg, #f59e0b 0%, #fb7185 100%);
  --nav-active-text: #23140a;
  --nav-active-shadow: 0 4px 16px rgba(245, 158, 11, 0.5);
  --editor-bg: #100c09;
  --editor-gutter: #0a0705;
  --editor-gutter-text: #7a6148;
  --editor-gutter-border: rgba(255, 224, 178, 0.07);
  --score-high-bg: rgba(52, 211, 153, 0.16);
  --score-high-text: #34d399;
  --score-high-border: rgba(52, 211, 153, 0.34);
  --score-med-bg: rgba(245, 158, 11, 0.18);
  --score-med-text: #fbbf24;
  --score-med-border: rgba(245, 158, 11, 0.38);
  --score-low-bg: rgba(251, 113, 133, 0.16);
  --score-low-text: #fb7185;
  --score-low-border: rgba(251, 113, 133, 0.34);
  --radius-sm: 8px;
  --radius-md: 16px;
  --radius-lg: 20px;
  --shadow-glow: 0 0 20px rgba(245, 158, 11, 0.35);
""",
    "neon": """  --bg-color: #05070b;
  --surface-bg: #080c11;
  --surface-color: #0a1017;
  --surface-card: #0a1017;
  --surface-hover: #0f1a24;
  --border-color: #12303a;
  --text-primary: #e8fdff;
  --text-secondary: #7fa9b3;
  --text-muted: #5d7a85;
  --primary-color: #22d3ee;
  --primary-hover: #06b6d4;
  --primary-light: #67e8f9;
  --primary-text: #04121a;
  --success-color: #34d399;
  --danger-color: #fb7185;
  --warning-color: #f0abfc;
  --brand-gradient: linear-gradient(135deg, #06b6d4 0%, #d946ef 100%);
  --brand-logo-bg: linear-gradient(135deg, #06b6d4 0%, #d946ef 100%);
  --nav-active-bg: linear-gradient(135deg, #06b6d4 0%, #d946ef 100%);
  --nav-active-text: #04121a;
  --nav-active-shadow: 0 0 18px rgba(34, 211, 238, 0.65);
  --editor-bg: #04060a;
  --editor-gutter: #020304;
  --editor-gutter-text: #4b6b75;
  --editor-gutter-border: rgba(34, 211, 238, 0.12);
  --score-high-bg: rgba(52, 211, 153, 0.16);
  --score-high-text: #34d399;
  --score-high-border: rgba(52, 211, 153, 0.34);
  --score-med-bg: rgba(240, 171, 252, 0.16);
  --score-med-text: #f0abfc;
  --score-med-border: rgba(240, 171, 252, 0.34);
  --score-low-bg: rgba(251, 113, 133, 0.16);
  --score-low-text: #fb7185;
  --score-low-border: rgba(251, 113, 133, 0.34);
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-glow: 0 0 18px rgba(34, 211, 238, 0.55);
""",
    "aurora-ember": """  --bg-color: #0b0a10;
  --surface-bg: #12101a;
  --surface-color: #17141f;
  --surface-card: #17141f;
  --surface-hover: #241f2e;
  --border-color: #2c2533;
  --text-primary: #f7ede0;
  --text-secondary: #b9a89a;
  --text-muted: #857469;
  --primary-color: #f59e0b;
  --primary-hover: #d97706;
  --primary-light: #fcd9a8;
  --primary-text: #23140a;
  --success-color: #34d399;
  --danger-color: #fb7185;
  --warning-color: #f59e0b;
  --brand-gradient: linear-gradient(135deg, #8b5cf6 0%, #f59e0b 55%, #fb7185 100%);
  --brand-logo-bg: linear-gradient(135deg, #8b5cf6 0%, #f59e0b 100%);
  --nav-active-bg: linear-gradient(135deg, #f59e0b 0%, #fb7185 100%);
  --nav-active-text: #23140a;
  --nav-active-shadow: 0 4px 16px rgba(245, 158, 11, 0.5);
  --editor-bg: #0b0a10;
  --editor-gutter: #080711;
  --editor-gutter-text: #6d6072;
  --editor-gutter-border: rgba(255, 224, 178, 0.07);
  --score-high-bg: rgba(52, 211, 153, 0.16);
  --score-high-text: #34d399;
  --score-high-border: rgba(52, 211, 153, 0.34);
  --score-med-bg: rgba(245, 158, 11, 0.18);
  --score-med-text: #fbbf24;
  --score-med-border: rgba(245, 158, 11, 0.38);
  --score-low-bg: rgba(251, 113, 133, 0.16);
  --score-low-text: #fb7185;
  --score-low-border: rgba(251, 113, 133, 0.34);
  --radius-sm: 8px;
  --radius-md: 16px;
  --radius-lg: 20px;
  --shadow-glow: 0 0 20px rgba(245, 158, 11, 0.4);
""",
    "aurora-neon": """  --bg-color: #07070f;
  --surface-bg: #0d0d18;
  --surface-color: #12121f;
  --surface-card: #12121f;
  --surface-hover: #1c1c30;
  --border-color: #242447;
  --text-primary: #eef0ff;
  --text-secondary: #a0a3d0;
  --text-muted: #6f73a8;
  --primary-color: #22d3ee;
  --primary-hover: #06b6d4;
  --primary-light: #67e8f9;
  --primary-text: #04121a;
  --success-color: #34d399;
  --danger-color: #fb7185;
  --warning-color: #f0abfc;
  --brand-gradient: linear-gradient(135deg, #22d3ee 0%, #8b5cf6 50%, #d946ef 100%);
  --brand-logo-bg: linear-gradient(135deg, #22d3ee 0%, #d946ef 100%);
  --nav-active-bg: linear-gradient(135deg, #22d3ee 0%, #d946ef 100%);
  --nav-active-text: #04121a;
  --nav-active-shadow: 0 0 18px rgba(34, 211, 238, 0.6);
  --editor-bg: #06060d;
  --editor-gutter: #04040a;
  --editor-gutter-text: #585d8f;
  --editor-gutter-border: rgba(34, 211, 238, 0.12);
  --score-high-bg: rgba(52, 211, 153, 0.16);
  --score-high-text: #34d399;
  --score-high-border: rgba(52, 211, 153, 0.34);
  --score-med-bg: rgba(240, 171, 252, 0.16);
  --score-med-text: #f0abfc;
  --score-med-border: rgba(240, 171, 252, 0.34);
  --score-low-bg: rgba(251, 113, 133, 0.16);
  --score-low-text: #fb7185;
  --score-low-border: rgba(251, 113, 133, 0.34);
  --radius-sm: 6px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --shadow-glow: 0 0 18px rgba(34, 211, 238, 0.5);
""",
    "amber-neon": """  --bg-color: #08090b;
  --surface-bg: #0e0f12;
  --surface-color: #121316;
  --surface-card: #141316;
  --surface-hover: #1e1f24;
  --border-color: #2a2a30;
  --text-primary: #f7ede0;
  --text-secondary: #b0a79c;
  --text-muted: #7d766e;
  --primary-color: #f59e0b;
  --primary-hover: #d97706;
  --primary-light: #fcd9a8;
  --primary-text: #1a1004;
  --success-color: #34d399;
  --danger-color: #fb7185;
  --warning-color: #fbbf24;
  --brand-gradient: linear-gradient(135deg, #f59e0b 0%, #22d3ee 100%);
  --brand-logo-bg: linear-gradient(135deg, #f59e0b 0%, #22d3ee 100%);
  --nav-active-bg: linear-gradient(135deg, #f59e0b 0%, #22d3ee 100%);
  --nav-active-text: #1a1004;
  --nav-active-shadow: 0 0 16px rgba(245, 158, 11, 0.55);
  --editor-bg: #08090b;
  --editor-gutter: #050607;
  --editor-gutter-text: #6f6a63;
  --editor-gutter-border: rgba(245, 158, 11, 0.1);
  --score-high-bg: rgba(52, 211, 153, 0.16);
  --score-high-text: #34d399;
  --score-high-border: rgba(52, 211, 153, 0.34);
  --score-med-bg: rgba(245, 158, 11, 0.18);
  --score-med-text: #fbbf24;
  --score-med-border: rgba(245, 158, 11, 0.38);
  --score-low-bg: rgba(34, 211, 238, 0.16);
  --score-low-text: #67e8f9;
  --score-low-border: rgba(34, 211, 238, 0.34);
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --shadow-glow: 0 0 18px rgba(245, 158, 11, 0.45);
""",
}

# Amber Neon has no experiment file — blend Ember (amber) with Neon (cyan) accents.
AMBER_NEON = """
.job-card {
  background:
    linear-gradient(rgba(245, 158, 11, 0.035) 1px, transparent 1px) 0 0 / 100% 24px,
    radial-gradient(120% 130% at 100% 0%, rgba(245, 158, 11, 0.15) 0%, rgba(34, 211, 238, 0.06) 45%, transparent 74%),
    linear-gradient(165deg, #17120e 0%, #100c09 70%, #0a0806 100%) !important;
  border: 1px solid rgba(245, 158, 11, 0.26) !important;
  border-radius: 12px !important;
  box-shadow: 0 16px 36px -24px rgba(0, 0, 0, 0.95), 0 0 20px -14px rgba(34, 211, 238, 0.9), inset 0 1px 0 rgba(255, 224, 178, 0.07) !important;
  padding: 1rem 1.1rem !important;
}
.job-card-title { color: #f7ede0 !important; font-weight: 700 !important; letter-spacing: -0.01em !important; font-size: 1.04rem !important; }
.job-card-company { color: #b89b7e !important; font-size: 0.85rem !important; }
.job-card-score { background: linear-gradient(135deg, #f59e0b, #22d3ee) !important; color: #101010 !important; border: none !important; border-radius: 999px !important; font-weight: 800 !important; box-shadow: 0 6px 18px -8px rgba(245, 158, 11, 0.9) !important; }
.table-tier-pill { border-radius: 999px !important; border-color: rgba(34, 211, 238, 0.35) !important; color: #9fe8f5 !important; background: rgba(34, 211, 238, 0.10) !important; }
.job-card-meta .job-card-tag { border-radius: 999px !important; background: rgba(255, 224, 178, 0.05) !important; border: 1px solid rgba(245, 158, 11, 0.18) !important; color: #e6cfb4 !important; }
.job-card-meta .job-card-date { color: #a98b6d !important; }
.job-card-status select { border-radius: 999px !important; background: rgba(245, 158, 11, 0.12) !important; border: 1px solid rgba(34, 211, 238, 0.4) !important; color: #fcd9a8 !important; font-weight: 600 !important; }
.job-card-actions { border-top: 1px solid rgba(245, 158, 11, 0.14) !important; }
.job-card-buttons { gap: 0.15rem !important; }
.job-card-buttons .btn { width: 31px !important; height: 31px !important; border-radius: 50% !important; background: rgba(255, 224, 178, 0.05) !important; border: 1px solid rgba(245, 158, 11, 0.18) !important; transition: transform 0.15s ease, background 0.15s ease, box-shadow 0.15s ease !important; }
.job-card-buttons .btn:hover { transform: translateY(-1px); background: rgba(34, 211, 238, 0.16) !important; box-shadow: 0 0 14px -2px rgba(34, 211, 238, 0.85) !important; }
.studio-topbar { background: linear-gradient(160deg, rgba(245, 158, 11, 0.11), rgba(34, 211, 238, 0.05) 55%, rgba(255, 255, 255, 0.02)) !important; border: 1px solid rgba(245, 158, 11, 0.24) !important; border-radius: 16px !important; padding: 0.7rem !important; }
.studio-select { border-radius: 999px !important; border-color: rgba(245, 158, 11, 0.24) !important; color: #f7ede0 !important; background: rgba(255, 224, 178, 0.04) !important; }
.studio-btn-new { border-radius: 999px !important; border-color: rgba(245, 158, 11, 0.3) !important; color: #fcd9a8 !important; }
.studio-title-text { font-size: 0.95rem !important; font-weight: 700 !important; color: #f7ede0 !important; }
.studio-title-display { border-radius: 999px !important; }
.studio-topbar .engine-badge { border-radius: 999px !important; }
.studio-btn-compile { background: linear-gradient(135deg, #f59e0b, #22d3ee) !important; border: none !important; border-radius: 999px !important; color: #101010 !important; box-shadow: 0 8px 20px -9px rgba(245, 158, 11, 0.95) !important; }
.studio-btn-save, .studio-btn-pdf { border-radius: 999px !important; border-color: rgba(34, 211, 238, 0.28) !important; }
.studio-mobile-switcher { border-radius: 999px !important; background: rgba(255, 224, 178, 0.04) !important; border-color: rgba(245, 158, 11, 0.18) !important; padding: 4px !important; }
.studio-mobile-tab-btn { border-radius: 999px !important; }
.studio-mobile-tab-btn.active { background: linear-gradient(135deg, #f59e0b, #22d3ee) !important; color: #101010 !important; box-shadow: 0 6px 16px -7px rgba(34, 211, 238, 0.9) !important; }
.studio-segmented-mode { border-radius: 999px !important; border-color: rgba(245, 158, 11, 0.18) !important; }
.studio-mode-btn { border-radius: 999px !important; }
.studio-mode-btn.active { background: rgba(245, 158, 11, 0.18) !important; color: #fcd9a8 !important; }
.studio-mode-pill { border-radius: 999px !important; }
.simple-toolbar-hint { background: rgba(245, 158, 11, 0.10) !important; border: 1px solid rgba(34, 211, 238, 0.28) !important; color: #fcd9a8 !important; border-radius: 999px !important; padding: 0.26rem 0.72rem !important; }
.simple-toolbar-btn { border-radius: 999px !important; padding: 0.24rem 0.72rem !important; background: rgba(255, 224, 178, 0.05) !important; color: #fcd9a8 !important; }
.simple-toolbar-sep { opacity: 0.35 !important; }
.btn-table-action { border-radius: 999px !important; }
.btn-table-pill { border-radius: 999px !important; }
select,
select.input-base,
.job-card-status select,
.studio-select {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23a1a1aa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E") !important;
  background-repeat: no-repeat !important;
  background-position: right 0.6rem center !important;
}
.job-card-buttons .btn:has(span) { width: auto !important; height: 31px !important; border-radius: 9999px !important; padding: 0 0.45rem !important; gap: 0.2rem !important; }
"""

SOURCES = {
    "aurora": (VARIANTS / "a.css").read_text(),
    "ember": (VARIANTS / "e.css").read_text(),
    "neon": (VARIANTS / "d.css").read_text(),
    "aurora-ember": (VARIANTS / "blend_ae.css").read_text(),
    "aurora-neon": (VARIANTS / "blend_ad.css").read_text(),
    "amber-neon": AMBER_NEON,
}


def scope(css: str, theme_id: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []
    for chunk in css.split("}"):
        if "{" not in chunk:
            continue
        selector, body = chunk.split("{", 1)
        selector = selector.strip()
        if not selector:
            continue
        scoped = ", ".join(
            f'[data-theme="{theme_id}"] {s.strip()}' for s in selector.split(",")
        )
        rules.append(f"{scoped} {{{body}}}")
    return "\n".join(rules)


parts = [
    "/* AUTO-GENERATED by scripts/gen_themes.py — do not edit by hand. */",
    "/* Palette themes (Aurora / Ember / Neon family). Component overrides are",
    "   scoped to [data-theme=\"<id>\"] so they only apply when that theme is active. */",
    "",
]
for tid, css in SOURCES.items():
    parts.append(f'/* ===== {tid} ===== */')
    parts.append(f'[data-theme="{tid}"] {{')
    parts.append(VARS[tid].rstrip("\n"))
    parts.append("}")
    parts.append(scope(css, tid))
    parts.append("")

OUT.write_text("\n".join(parts) + "\n")
print("wrote", OUT, OUT.stat().st_size, "bytes")
