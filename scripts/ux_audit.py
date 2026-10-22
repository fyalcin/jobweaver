#!/usr/bin/env python3
"""scripts/ux_audit.py — On-Demand Exploratory UX & Visual Audit Harness.

Autonomously tests Jobweaver across Mobile (Pixel 9) and Desktop viewports,
executes realistic end-to-end user journeys, runs silent DOM and ergonomic
sensors (layout overflows, tap targets, console errors), captures screenshots,
and produces a structured diagnostic report with actionable CSS fixes.

Usage:
    uv run python scripts/ux_audit.py --device all
    uv run python scripts/ux_audit.py --device pixel9
    uv run python scripts/ux_audit.py --device desktop
    uv run python scripts/ux_audit.py --no-headless --slow-mo 0.5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from auth import SESSION_COOKIE_NAME, create_session_token
from db import get_user_by_username, init_db


# --- Configuration & Device Profiles ---

@dataclass
class DeviceProfile:
    name: str
    width: int
    height: int
    pixel_ratio: float = 1.0
    is_mobile: bool = False
    touch: bool = False
    user_agent: str | None = None


PROFILES: dict[str, DeviceProfile] = {
    "pixel9": DeviceProfile(
        name="Pixel 9",
        width=412,
        height=923,
        pixel_ratio=2.625,
        is_mobile=True,
        touch=True,
        user_agent=(
            "Mozilla/5.0 (Linux; Android 14; Pixel 9) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"
        ),
    ),
    "desktop": DeviceProfile(
        name="Desktop (Standard)",
        width=1440,
        height=900,
        pixel_ratio=1.0,
        is_mobile=False,
        touch=False,
        user_agent=None,
    ),
}


# --- Data Models for Audit Results ---

@dataclass
class OverflowAnomaly:
    tag: str
    class_name: str
    element_id: str | None
    left: int
    right: int
    width: int
    viewport_width: int
    overflow_px: int
    text_snippet: str


@dataclass
class TapTargetAnomaly:
    tag: str
    class_name: str
    element_id: str | None
    width: float
    height: float
    text_snippet: str
    aria_label: str | None


@dataclass
class A11yViolation:
    rule_id: str
    impact: str  # minor, moderate, serious, critical
    description: str
    help_url: str
    nodes_count: int
    selector: str
    html_snippet: str
    failure_summary: str


@dataclass
class StepResult:
    step_id: str
    title: str
    status: str  # PASS, WARN, FAIL
    duration_sec: float
    screenshot_path: str | None = None
    relative_screenshot_path: str | None = None
    overflows: list[OverflowAnomaly] = field(default_factory=list)
    tap_target_issues: list[TapTargetAnomaly] = field(default_factory=list)
    a11y_violations: list[A11yViolation] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class DeviceAuditReport:
    device_id: str
    device_name: str
    viewport: str
    start_time: str
    end_time: str
    total_duration_sec: float
    status: str
    steps: list[StepResult] = field(default_factory=list)
    total_overflows: int = 0
    total_tap_issues: int = 0
    total_a11y_violations: int = 0
    critical_a11y_violations: int = 0
    total_console_errors: int = 0


# --- Automated DOM & Ergonomic Sensors ---

JS_SNIFF_OVERFLOWS = """
const overflows = [];
const viewportWidth = window.innerWidth;
const allElements = document.querySelectorAll('*');

function hasScrollableAncestor(el) {
    let parent = el.parentElement;
    while (parent && parent !== document.body && parent !== document.documentElement) {
        const style = window.getComputedStyle(parent);
        if (['auto', 'scroll'].includes(style.overflowX)) {
            return true;
        }
        parent = parent.parentElement;
    }
    return false;
}

for (const el of allElements) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH', 'DEFS'].includes(el.tagName)) continue;
    if (el.offsetParent === null && el.tagName !== 'BODY' && el.tagName !== 'HTML') continue;
    
    // Ignore elements inside deliberately scrollable containers (e.g. quick views bar, table scroller)
    if (hasScrollableAncestor(el)) continue;

    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    
    // Check if bounds escape the viewport horizontally
    const leftOOB = rect.left < -1.5;
    const rightOOB = rect.right > (viewportWidth + 1.5);
    
    if (leftOOB || rightOOB) {
        let snippet = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 70);
        overflows.push({
            tag: el.tagName.toLowerCase(),
            class_name: (typeof el.className === 'string') ? el.className.trim() : '',
            element_id: el.id || null,
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
            viewport_width: viewportWidth,
            overflow_px: Math.round(Math.max(rect.right - viewportWidth, -rect.left)),
            text_snippet: snippet
        });
    }
}
// Return unique anomalies sorted by severity, capped at 15
const seen = new Set();
const unique = [];
for (const item of overflows) {
    const key = `${item.tag}.${item.class_name.split(' ')[0]}#${item.element_id}:${item.width}`;
    if (!seen.has(key)) {
        seen.add(key);
        unique.push(item);
    }
}
unique.sort((a, b) => b.overflow_px - a.overflow_px);
return unique.slice(0, 15);
"""

JS_SNIFF_TAP_TARGETS = """
const minSize = arguments[0] || 36;
const issues = [];
const clickables = document.querySelectorAll('button, a[href], select, input:not([type="hidden"]), [role="button"]');

for (const el of clickables) {
    if (el.offsetParent === null) continue; // Not visible
    
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    
    // Exclude inline text links inside paragraphs or list items if they naturally wrap
    if (el.tagName === 'A' && el.parentElement && ['P', 'SPAN', 'LI'].includes(el.parentElement.tagName) && rect.height >= 16) {
        continue;
    }
    
    if (rect.width < minSize || rect.height < minSize) {
        let snippet = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 50);
        issues.push({
            tag: el.tagName.toLowerCase(),
            class_name: (typeof el.className === 'string') ? el.className.trim() : '',
            element_id: el.id || null,
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
            text_snippet: snippet,
            aria_label: el.getAttribute('aria-label') || el.getAttribute('title') || null
        });
    }
}
const seen = new Set();
const unique = [];
for (const item of issues) {
    const key = `${item.tag}.${item.class_name.split(' ')[0]}#${item.element_id}:${item.width}x${item.height}`;
    if (!seen.has(key)) {
        seen.add(key);
        unique.push(item);
    }
}
return unique.slice(0, 20);
"""


class UXAuditHarness:
    def __init__(
        self,
        base_url: str = "http://localhost:5173",
        output_dir: Path | str = PROJECT_ROOT / "output" / "ux_audit",
        username: str = "admin",
        headless: bool = True,
        slow_mo: float = 0.2,
        enable_a11y: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.username = username
        self.headless = headless
        self.slow_mo = slow_mo
        self.enable_a11y = enable_a11y

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.user_id = self._resolve_user_id(username)
        self.axe_script = self._load_axe_script() if enable_a11y else None

    def _load_axe_script(self) -> str | None:
        candidates = [
            PROJECT_ROOT / "scripts" / "vendor" / "axe.min.js",
            PROJECT_ROOT / "webapp" / "node_modules" / "axe-core" / "axe.min.js",
        ]
        for c in candidates:
            if c.exists():
                try:
                    return c.read_text(encoding="utf-8")
                except Exception as e:
                    print(f"⚠️ Warning reading axe script from {c}: {e}")
        print("⚠️ Notice: axe.min.js not found in scripts/vendor or webapp/node_modules. Accessibility audit will be skipped.")
        return None

    def _resolve_user_id(self, username: str) -> int:
        init_db()
        user = get_user_by_username(username)
        if user and "id" in user:
            return user["id"]
        return 1  # default fallback

    def _create_driver(self, profile: DeviceProfile) -> webdriver.Chrome:
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-position=0,0")
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

        if profile.is_mobile:
            mobile_emulation = {
                "deviceMetrics": {
                    "width": profile.width,
                    "height": profile.height,
                    "pixelRatio": profile.pixel_ratio,
                    "touch": profile.touch,
                },
                "userAgent": profile.user_agent,
            }
            options.add_experimental_option("mobileEmulation", mobile_emulation)
        else:
            options.add_argument(f"--window-size={profile.width},{profile.height}")

        driver = webdriver.Chrome(options=options)
        if not profile.is_mobile:
            driver.set_window_size(profile.width, profile.height)
        return driver

    def _inject_auth(self, driver: webdriver.Chrome) -> None:
        token = create_session_token(self.user_id)
        # Load a static asset first so we establish origin without firing React unauth requests
        driver.get(f"{self.base_url}/vite.svg")
        cookie_domain = "localhost" if "localhost" in self.base_url else None
        cookie = {
            "name": SESSION_COOKIE_NAME,
            "value": token,
            "path": "/",
        }
        if cookie_domain:
            cookie["domain"] = cookie_domain
        driver.add_cookie(cookie)
        # Clear log buffer so the harness starts with clean console logs
        driver.get_log("browser")
        driver.get(self.base_url)
        time.sleep(0.8)

    def _run_axe(self, driver: webdriver.Chrome) -> list[A11yViolation]:
        if not self.enable_a11y or not self.axe_script:
            return []
        try:
            # Check if axe is already injected in current DOM context
            is_loaded = driver.execute_script("return typeof window.axe !== 'undefined';")
            if not is_loaded:
                driver.execute_script(self.axe_script)

            js_run_axe = """
            var callback = arguments[arguments.length - 1];
            if (typeof window.axe === 'undefined') {
                callback([]);
                return;
            }
            window.axe.run(document, {
                runOnly: {
                    type: 'tag',
                    values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']
                }
            }).then(function(results) {
                callback(results.violations || []);
            }).catch(function(err) {
                callback([]);
            });
            """
            raw_violations = driver.execute_async_script(js_run_axe) or []
            violations = []
            for v in raw_violations:
                nodes = v.get("nodes", [])
                first_target = ""
                first_html = ""
                first_summary = ""
                if nodes:
                    first_node = nodes[0]
                    target = first_node.get("target", [])
                    first_target = " > ".join(str(t) for t in target) if isinstance(target, list) else str(target)
                    first_html = (first_node.get("html", "") or "")[:120].strip()
                    first_summary = (first_node.get("failureSummary", "") or "")[:150].strip()

                violations.append(
                    A11yViolation(
                        rule_id=v.get("id", "unknown"),
                        impact=v.get("impact") or "moderate",
                        description=v.get("description", ""),
                        help_url=v.get("helpUrl", ""),
                        nodes_count=len(nodes),
                        selector=first_target,
                        html_snippet=first_html,
                        failure_summary=first_summary,
                    )
                )
            return violations
        except Exception:
            return []

    def _run_sensors(
        self,
        driver: webdriver.Chrome,
        profile: DeviceProfile,
        step_id: str,
        title: str,
    ) -> StepResult:
        t0 = time.time()
        time.sleep(self.slow_mo)

        # 1. Capture Screenshot
        device_slug = profile.name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        dev_screenshots_dir = self.screenshots_dir / device_slug
        dev_screenshots_dir.mkdir(parents=True, exist_ok=True)
        img_filename = f"{step_id}.png"
        img_path = dev_screenshots_dir / img_filename
        driver.save_screenshot(str(img_path))
        rel_img_path = f"screenshots/{device_slug}/{img_filename}"

        # 2. Sniff Layout Overflows
        raw_overflows = driver.execute_script(JS_SNIFF_OVERFLOWS) or []
        overflows = [OverflowAnomaly(**item) for item in raw_overflows]

        # 3. Sniff Tap Targets (mobile only)
        tap_issues = []
        if profile.is_mobile:
            raw_tap = driver.execute_script(JS_SNIFF_TAP_TARGETS, 36) or []
            tap_issues = [TapTargetAnomaly(**item) for item in raw_tap]

        # 4. Trapper Console Errors
        logs = driver.get_log("browser")
        console_errs = []
        for entry in logs:
            level = entry.get("level", "")
            msg = entry.get("message", "")
            if level in ("SEVERE", "ERROR"):
                # Filter out expected 401 on initial unauthed ping if any
                if "status of 401" in msg and "/auth/me" in msg:
                    continue
                console_errs.append(f"[{level}] {msg}")

        # 5. Accessibility Audit (WCAG 2.1 AA via Axe-core)
        a11y_violations = self._run_axe(driver)
        critical_a11y = [v for v in a11y_violations if v.impact == "critical"]

        # Determine step status
        status = "PASS"
        if console_errs or any(o.overflow_px > 10 for o in overflows) or critical_a11y:
            status = "FAIL"
        elif overflows or (profile.is_mobile and tap_issues) or a11y_violations:
            status = "WARN"

        duration = round(time.time() - t0, 2)
        return StepResult(
            step_id=step_id,
            title=title,
            status=status,
            duration_sec=duration,
            screenshot_path=str(img_path),
            relative_screenshot_path=rel_img_path,
            overflows=overflows,
            tap_target_issues=tap_issues,
            a11y_violations=a11y_violations,
            console_errors=console_errs,
        )

    # --- End-to-End User Journeys ---

    def audit_device(self, profile_key: str) -> DeviceAuditReport:
        profile = PROFILES[profile_key]
        print(f"\n🚀 Starting audit on {profile.name} ({profile.width}x{profile.height})...")

        driver = self._create_driver(profile)
        wait = WebDriverWait(driver, 10)
        report_start = datetime.now()
        steps: list[StepResult] = []

        try:
            # 1. Auth & Landing
            self._inject_auth(driver)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".app-nav, .login-screen")))

            res1 = self._run_sensors(driver, profile, "01_landing_jobs_view", "Authentication & Jobs Explorer Landing")
            res1.notes.append(f"Loaded {self.base_url} with user '{self.username}'.")
            steps.append(res1)

            # 2. Jobs Explorer Interactions (filters, timeframe dropdown, card/row inspection)
            # Verify timeframe filter default
            try:
                timeframe_select = driver.find_elements(By.CSS_SELECTOR, "select.filter-select, select.input-base")
                for sel in timeframe_select:
                    val = sel.get_attribute("value")
                    if val in ("recent", "all"):
                        res1.notes.append(f"Timeframe filter present with value: '{val}'.")
            except Exception as e:
                res1.notes.append(f"Filter inspection warning: {e}")

            # Try toggling a filter or clicking a job
            job_rows = driver.find_elements(By.CSS_SELECTOR, ".job-card, tr.job-row, .table-job-title")
            if job_rows:
                res1.notes.append(f"Found {len(job_rows)} job items on the active view.")

            res2 = self._run_sensors(driver, profile, "02_jobs_explorer_filtered", "Jobs Explorer & Filter Controls")
            steps.append(res2)

            # 3. Job Detail Cockpit (Job & Fit)
            # Find and click first job title or card to open JobDetailPage
            job_link = None
            candidate_selectors = [
                ".job-card-title-wrap",
                ".job-card-title",
                ".td-col-title",
                ".table-job-title",
            ]
            for sel in candidate_selectors:
                links = driver.find_elements(By.CSS_SELECTOR, sel)
                if links and links[0].is_displayed():
                    job_link = links[0]
                    break

            if job_link:
                driver.execute_script("arguments[0].click();", job_link)
                time.sleep(1.2)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".job-detail-page, .job-detail-container")))

                res3 = self._run_sensors(driver, profile, "03_job_cockpit_fit", "Job Detail Cockpit (Job & Fit)")
                res3.notes.append("Successfully navigated into 2-column Job Cockpit.")
                steps.append(res3)

                # 4. In-Job Tailor Studio
                # Click the Tailor Studio subtab button
                tailor_subtab_btns = driver.find_elements(By.CSS_SELECTOR, ".job-subtab-btn")
                tailor_btn = None
                for btn in tailor_subtab_btns:
                    if "Tailor Studio" in btn.text:
                        tailor_btn = btn
                        break

                if tailor_btn:
                    driver.execute_script("arguments[0].click();", tailor_btn)
                    time.sleep(1.2)

                    # Look for cheat sheet button and toggle it
                    cheat_sheet_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Cheat Sheet')]")
                    if cheat_sheet_btns:
                        driver.execute_script("arguments[0].click();", cheat_sheet_btns[0])
                        time.sleep(0.4)

                    res4 = self._run_sensors(driver, profile, "04_tailor_studio_cockpit", "In-Job Tailor Studio Workspace")
                    res4.notes.append("Opened in-job LaTeX Tailor Studio & Job Cheat Sheet drawer.")
                    steps.append(res4)

                # Click Back to Jobs
                back_btns = driver.find_elements(By.CSS_SELECTOR, ".btn-back")
                if back_btns:
                    driver.execute_script("arguments[0].click();", back_btns[0])
                    time.sleep(0.8)
            else:
                res2.notes.append("Notice: No clickable job postings found in current database view.")

            # 5. CV Studio Workspace
            # Find and click CV Studio nav tab
            studio_nav_btn = None
            if profile.is_mobile:
                # Primary tab or in more menu
                nav_btns = driver.find_elements(By.CSS_SELECTOR, ".nav-tab")
                for btn in nav_btns:
                    if "CV Studio" in btn.text:
                        studio_nav_btn = btn
                        break
            else:
                nav_btns = driver.find_elements(By.CSS_SELECTOR, ".nav-tab")
                for btn in nav_btns:
                    if "CV Studio" in btn.text:
                        studio_nav_btn = btn
                        break

            if studio_nav_btn:
                driver.execute_script("arguments[0].click();", studio_nav_btn)
                time.sleep(1.0)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".studio-container, .studio-topbar, .studio-welcome")))

                # On mobile, test toggling between Editor and Preview if present
                if profile.is_mobile:
                    mobile_toggles = driver.find_elements(By.CSS_SELECTOR, ".mobile-toggle-btn")
                    for toggle in mobile_toggles:
                        if "Preview" in toggle.text:
                            driver.execute_script("arguments[0].click();", toggle)
                            time.sleep(0.5)
                            break

                # Open "New Document" modal
                new_doc_btns = driver.find_elements(By.CSS_SELECTOR, ".studio-btn-new")
                if new_doc_btns:
                    driver.execute_script("arguments[0].click();", new_doc_btns[0])
                    time.sleep(0.5)

                res5 = self._run_sensors(driver, profile, "05_cv_studio_modal", "CV Studio & Create Document Modal")
                steps.append(res5)

                # Dismiss modal with Escape
                try:
                    driver.switch_to.active_element.send_keys(Keys.ESCAPE)
                    time.sleep(0.3)
                except Exception:
                    pass

            # 6. Theme Switcher (open the menu only — never change the user's saved theme)
            theme_btn = driver.find_elements(By.CSS_SELECTOR, ".theme-switcher-btn")
            if theme_btn:
                driver.execute_script("arguments[0].click();", theme_btn[0])
                time.sleep(0.4)

                res6 = self._run_sensors(driver, profile, "06_theme_switcher_open", "Header Theme Switcher & Alignment")
                steps.append(res6)

                # Close without selecting anything so persisted preferences stay pristine
                try:
                    driver.switch_to.active_element.send_keys(Keys.ESCAPE)
                except Exception:
                    driver.execute_script("arguments[0].click();", theme_btn[0])
                time.sleep(0.3)

            # Navigate to Settings to check Typography gallery
            settings_btn = None
            if profile.is_mobile:
                # Open 'More' menu first
                more_btn = driver.find_elements(By.CSS_SELECTOR, ".mobile-more-trigger")
                if more_btn:
                    driver.execute_script("arguments[0].click();", more_btn[0])
                    time.sleep(0.3)
                    more_settings = driver.find_elements(By.XPATH, "//div[contains(@class, 'mobile-more-menu')]//button[contains(., 'Settings')]")
                    if more_settings:
                        settings_btn = more_settings[0]
            else:
                nav_btns = driver.find_elements(By.CSS_SELECTOR, ".nav-tab")
                for btn in nav_btns:
                    if "Settings" in btn.text:
                        settings_btn = btn
                        break

            if settings_btn:
                driver.execute_script("arguments[0].click();", settings_btn)
                time.sleep(0.8)

                res7 = self._run_sensors(driver, profile, "07_settings_typography", "Settings & Typography Specimens")
                steps.append(res7)

        except Exception as e:
            import traceback
            traceback.print_exc()
            err_step = StepResult(
                step_id="error_exception",
                title=f"Harness Exception during {profile.name} run",
                status="FAIL",
                duration_sec=0.0,
                notes=[f"Exception: {type(e).__name__}: {str(e)}"],
            )
            steps.append(err_step)
            print(f"❌ Error during {profile.name} audit: {e}")
        finally:
            driver.quit()

        report_end = datetime.now()
        total_duration = round((report_end - report_start).total_seconds(), 2)

        tot_overflows = sum(len(s.overflows) for s in steps)
        tot_tap = sum(len(s.tap_target_issues) for s in steps)
        tot_a11y = sum(len(s.a11y_violations) for s in steps)
        tot_crit_a11y = sum(1 for s in steps for v in s.a11y_violations if v.impact == "critical")
        tot_console = sum(len(s.console_errors) for s in steps)

        overall_status = "PASS"
        if any(s.status == "FAIL" for s in steps):
            overall_status = "FAIL"
        elif any(s.status == "WARN" for s in steps):
            overall_status = "WARN"

        print(f"🏁 Finished {profile.name}: {overall_status} ({total_duration}s) | "
              f"Overflows: {tot_overflows}, Tap Issues: {tot_tap}, "
              f"A11y (WCAG): {tot_a11y} ({tot_crit_a11y} crit), Console Errs: {tot_console}")

        return DeviceAuditReport(
            device_id=profile_key,
            device_name=profile.name,
            viewport=f"{profile.width}x{profile.height}",
            start_time=report_start.isoformat(),
            end_time=report_end.isoformat(),
            total_duration_sec=total_duration,
            status=overall_status,
            steps=steps,
            total_overflows=tot_overflows,
            total_tap_issues=tot_tap,
            total_a11y_violations=tot_a11y,
            critical_a11y_violations=tot_crit_a11y,
            total_console_errors=tot_console,
        )

    # --- Structured Markdown & JSON Reporting ---

    def generate_reports(self, reports: list[DeviceAuditReport]) -> Path:
        json_path = self.output_dir / "report.json"
        md_path = self.output_dir / "UX_AUDIT_REPORT.md"

        # Serialize JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in reports], f, indent=2)

        # Build Markdown
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "# Exploratory UX, Visual & Accessibility Audit Report",
            f"> Generated autonomously on **{now_str}** by `scripts/ux_audit.py` with Axe-core & Chrome DevTools.",
            "",
            "## 1. Executive Master Summary",
            "",
            "| Device Profile | Viewport | Status | Duration | Layout Overflows | Tap Target Warnings (<36px) | WCAG A11y (Axe) | Console Errors |",
            "|---|---|---|---|---|---|---|---|",
        ]

        for r in reports:
            badge = "🟢 PASS" if r.status == "PASS" else ("🟡 WARN" if r.status == "WARN" else "🔴 FAIL")
            a11y_str = f"{r.total_a11y_violations}" + (f" (**{r.critical_a11y_violations} crit**)" if r.critical_a11y_violations else "")
            lines.append(
                f"| **{r.device_name}** | `{r.viewport}` | {badge} | {r.total_duration_sec}s | "
                f"{r.total_overflows} | {r.total_tap_issues} | {a11y_str} | {r.total_console_errors} |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 2. Journey Milestones & Visual Verification",
            "",
        ])

        for r in reports:
            lines.append(f"### Viewport: {r.device_name} (`{r.viewport}`)\n")
            for s in r.steps:
                s_badge = "🟢" if s.status == "PASS" else ("🟡" if s.status == "WARN" else "🔴")
                lines.append(f"#### {s_badge} {s.title} (`{s.step_id}`)")
                if s.notes:
                    for note in s.notes:
                        lines.append(f"- *{note}*")
                if s.relative_screenshot_path:
                    lines.append(f"\n![{s.title}]({s.relative_screenshot_path})\n")

                if s.overflows:
                    lines.append("<details><summary><b>⚠️ Detected Layout Overflows (" + str(len(s.overflows)) + ")</b></summary>\n")
                    lines.append("| Tag | Class / ID | Overflow | Rect [L, R, W] | Content Snippet |")
                    lines.append("|---|---|---|---|---|")
                    for o in s.overflows:
                        cid = f"`{o.element_id}`" if o.element_id else (f"`.{o.class_name[:25]}`" if o.class_name else "-")
                        lines.append(f"| `{o.tag}` | {cid} | **+{o.overflow_px}px** | `[{o.left}, {o.right}, {o.width}]` | `{o.text_snippet[:40]}` |")
                    lines.append("\n</details>\n")

                if s.tap_target_issues:
                    lines.append("<details><summary><b>🔍 Tap Target Warnings (" + str(len(s.tap_target_issues)) + ")</b></summary>\n")
                    lines.append("| Tag | Class / ID | Size (W×H) | Aria / Title | Snippet |")
                    lines.append("|---|---|---|---|---|")
                    for t in s.tap_target_issues:
                        cid = f"`{t.element_id}`" if t.element_id else (f"`.{t.class_name[:25]}`" if t.class_name else "-")
                        lines.append(f"| `{t.tag}` | {cid} | `{t.width}×{t.height}px` | {t.aria_label or '-'} | `{t.text_snippet[:35]}` |")
                    lines.append("\n</details>\n")

                if s.a11y_violations:
                    lines.append("<details><summary><b>♿ WCAG Accessibility Violations (" + str(len(s.a11y_violations)) + ")</b></summary>\n")
                    lines.append("| Rule ID | Impact | Description | Selector / Target | Help |")
                    lines.append("|---|---|---|---|---|")
                    for v in s.a11y_violations:
                        impact_badge = f"**{v.impact.upper()}**" if v.impact in ("critical", "serious") else v.impact
                        sel = f"`{v.selector[:45]}`" if v.selector else "-"
                        help_link = f"[{v.rule_id}]({v.help_url})" if v.help_url else v.rule_id
                        lines.append(f"| `{v.rule_id}` | {impact_badge} | {v.description} | {sel} | {help_link} |")
                    lines.append("\n</details>\n")

                if s.console_errors:
                    lines.append("<details><summary><b>❌ Console Errors (" + str(len(s.console_errors)) + ")</b></summary>\n")
                    for ce in s.console_errors:
                        lines.append(f"```\n{ce}\n```")
                    lines.append("</details>\n")

                lines.append("")

        # Section 3: Recommendations
        lines.extend([
            "---",
            "",
            "## 3. Prioritized Action Plan",
            "",
        ])

        all_overflows = [o for r in reports for s in r.steps for o in s.overflows]
        all_taps = [t for r in reports for s in r.steps for t in s.tap_target_issues]
        all_a11y = [v for r in reports for s in r.steps for v in s.a11y_violations]
        all_errs = [e for r in reports for s in r.steps for e in s.console_errors]

        if not all_overflows and not all_taps and not all_a11y and not all_errs:
            lines.append("🎉 **No layout breaks, accessibility defects, or console exceptions detected.** Both mobile and desktop viewports are clean!")
        else:
            lines.append("### ⚡ Prioritized Remediation")
            if any(v.impact == "critical" for v in all_a11y):
                crit_rules = set(v.rule_id for v in all_a11y if v.impact == "critical")
                lines.append(f"- **Critical Accessibility**: Address critical WCAG violations immediately: `{', '.join(crit_rules)}`.")
            if any(v.rule_id == "color-contrast" for v in all_a11y):
                lines.append("- **Color Contrast (WCAG AA)**: Some text tokens fail the 4.5:1 ratio against their background in current theme palette. Review subdued text colors (`--text-secondary`, `--text-muted`).")
            if any(t.height < 32 for t in all_taps):
                lines.append("- **Compact Mobile Buttons**: Some interactive icon buttons are sized <32px. Consider adding `min-width: 36px; min-height: 36px;` or touch padding (`padding: 0.35rem`) for easier thumb targeting.")
            if any(o.overflow_px > 0 for o in all_overflows):
                lines.append("- **Contain Horizontal Bounds**: Ensure parent containers have `max-width: 100vw; overflow-x: hidden;` or `minmax(0, 1fr)` to prevent subtle right-edge bleeding.")
            if all_errs:
                lines.append("- **Console Log Diagnostics**: Review flagged JavaScript console exceptions above.")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        print(f"\n📊 Audit reports generated:")
        print(f"  - Markdown: {md_path}")
        print(f"  - JSON:     {json_path}")
        return md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Jobweaver On-Demand Exploratory UX & Visual Audit")
    parser.add_argument(
        "--device", "-d",
        choices=["pixel9", "desktop", "all"],
        default="all",
        help="Device viewport profile to audit (default: all)",
    )
    parser.add_argument("--base-url", default="http://localhost:5173", help="Base webapp URL")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "output" / "ux_audit"), help="Output directory")
    parser.add_argument("--user", default="admin", help="Username for authenticated session")
    parser.add_argument("--headless", action="store_true", default=True, help="Run in headless mode (default: True)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run browser visibly")
    parser.add_argument("--slow-mo", type=float, default=0.2, help="Seconds delay between actions for animations")
    parser.add_argument("--no-a11y", dest="enable_a11y", action="store_false", default=True, help="Disable axe-core accessibility auditing")
    parser.add_argument("--fail-on-critical-a11y", action="store_true", default=False, help="Exit with code 1 if any critical WCAG violation is found")

    args = parser.parse_args()

    harness = UXAuditHarness(
        base_url=args.base_url,
        output_dir=args.output_dir,
        username=args.user,
        headless=args.headless,
        slow_mo=args.slow_mo,
        enable_a11y=args.enable_a11y,
    )

    devices_to_run = ["pixel9", "desktop"] if args.device == "all" else [args.device]
    results = []
    for dev in devices_to_run:
        res = harness.audit_device(dev)
        results.append(res)

    harness.generate_reports(results)

    if args.fail_on_critical_a11y:
        total_crit = sum(r.critical_a11y_violations for r in results)
        if total_crit > 0:
            print(f"\n❌ Audit failed: {total_crit} critical accessibility violations detected.")
            sys.exit(1)


if __name__ == "__main__":
    main()
