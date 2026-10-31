#!/usr/bin/env python3
"""
scripts/visual_heuristic_audit.py
=================================
Automated High-Resolution Visual & Heuristic UI/UX Audit Harness.
Captures retina-crisp screenshots of every major page, subtab, modal, and drawer
on desktop, while collecting DOM computed styles for buttons, typography, and
action bars to analyze visual inconsistencies, redundancies, and design rhythm.
"""

import json
import os
import sys
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jobweaver.auth import create_session_token, SESSION_COOKIE_NAME
from jobweaver.db import init_db, get_user_by_username

DOM_METRICS_JS = """
return (() => {
    const metrics = {
        buttons: [],
        headings: [],
        colors: new Set(),
    };

    // Analyze buttons and interactive elements
    const buttons = document.querySelectorAll('button, a.btn, select.input-base');
    buttons.forEach((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0 || window.getComputedStyle(el).display === 'none') return;
        const style = window.getComputedStyle(el);
        metrics.buttons.push({
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 35),
            classes: el.className || '',
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            padding: `${style.paddingTop} ${style.paddingRight} ${style.paddingBottom} ${style.paddingLeft}`,
            borderRadius: style.borderRadius,
            backgroundColor: style.backgroundColor,
            color: style.color,
            border: `${style.borderWidth} ${style.borderStyle} ${style.borderColor}`
        });
    });

    // Analyze headings
    const headings = document.querySelectorAll('h1, h2, h3, h4, h5');
    headings.forEach((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0 || window.getComputedStyle(el).display === 'none') return;
        const style = window.getComputedStyle(el);
        metrics.headings.push({
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || '').trim().slice(0, 45),
            classes: el.className || '',
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            margin: `${style.marginTop} ${style.marginRight} ${style.marginBottom} ${style.marginLeft}`,
            color: style.color
        });
    });

    metrics.colors = Array.from(metrics.colors);
    return metrics;
})();
"""


class VisualHeuristicAuditor:
    def __init__(
        self,
        base_url: str = "http://localhost:5173",
        output_dir: Path | str = PROJECT_ROOT / "output" / "visual_audit",
        username: str = "admin",
    ):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.username = username
        self.user_id = self._resolve_user_id(username)
        self.metrics_data = {}

    def _resolve_user_id(self, username: str) -> int:
        init_db()
        user = get_user_by_username(username)
        return user["id"] if user and "id" in user else 1

    def _create_driver(self) -> webdriver.Chrome:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1440,900")
        options.add_argument("--force-device-scale-factor=2")
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        driver = webdriver.Chrome(options=options)
        driver.set_window_size(1440, 900)
        return driver

    def _authenticate(self, driver: webdriver.Chrome) -> None:
        token = create_session_token(self.user_id)
        driver.get(f"{self.base_url}/vite.svg")
        cookie = {
            "name": SESSION_COOKIE_NAME,
            "value": token,
            "path": "/",
        }
        if "localhost" in self.base_url:
            cookie["domain"] = "localhost"
        driver.add_cookie(cookie)
        # Pre-seed Modern Dark theme in localStorage and API
        try:
            driver.execute_script("""
                localStorage.setItem('gj_active_theme', 'default');
                localStorage.setItem('gj_theme_admin', 'default');
                document.documentElement.removeAttribute('data-theme');
            """)
        except Exception:
            pass
        driver.get(self.base_url)
        time.sleep(1.0)
        try:
            driver.execute_script("""
                fetch('/api/preferences', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ theme: 'default' })
                });
                localStorage.setItem('gj_active_theme', 'default');
                localStorage.setItem('gj_theme_admin', 'default');
                document.documentElement.removeAttribute('data-theme');
            """)
            time.sleep(0.5)
            driver.get(self.base_url)
            time.sleep(1.0)
        except Exception:
            pass

    def _capture(self, driver: webdriver.Chrome, name: str, description: str) -> None:
        screenshot_path = self.screenshots_dir / f"{name}.png"
        driver.save_screenshot(str(screenshot_path))
        print(f"  📸 Captured: {name}.png ({description})")
        
        try:
            metrics = driver.execute_script(DOM_METRICS_JS)
            self.metrics_data[name] = {
                "description": description,
                "screenshot": str(screenshot_path.relative_to(PROJECT_ROOT)),
                "buttons": metrics.get("buttons", []),
                "headings": metrics.get("headings", []),
            }
        except Exception as e:
            print(f"  ⚠️ Could not extract DOM metrics for {name}: {e}")

    def run(self) -> None:
        print("\n🚀 Starting Comprehensive Visual & Heuristic Audit on Desktop (1440x900 @ 2x)...")
        driver = self._create_driver()
        wait = WebDriverWait(driver, 10)

        try:
            self._authenticate(driver)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".app-nav, .calm-jobs-toolbar")))
            time.sleep(0.8)

            # --- 1. Jobs Explorer Landing ---
            print("\n[1/17] Auditing Jobs Explorer (Main Table)")
            try:
                # Click 'All jobs' quick view for clean unconstrained table view
                all_jobs_btn = driver.find_elements(By.XPATH, "//div[contains(@class, 'jobs-stage-tabs')]//button[contains(., 'All')]")
                if all_jobs_btn:
                    all_jobs_btn[0].click()
                    time.sleep(0.5)
            except Exception:
                pass
            self._capture(driver, "01_jobs_explorer_main", "Jobs Explorer Main Table & Filtering Controls")

            # --- 2. Jobs Explorer Batch Multi-Select ---
            print("\n[2/17] Auditing Jobs Explorer Multi-Select Batch Actions")
            checkboxes = driver.find_elements(By.CSS_SELECTOR, ".calm-job-checkbox")
            for cb in checkboxes[:3]:
                try:
                    cb.click()
                    time.sleep(0.1)
                except Exception:
                    pass
            time.sleep(0.5)
            self._capture(driver, "02_jobs_explorer_batch_active", "Jobs Explorer with Multi-Select Batch Bar Active")

            # --- 3. Job Detail Cockpit (Job & Fit) ---
            print("\n[3/17] Auditing Job Detail Cockpit (Job & Fit Subtab)")
            job_links = driver.find_elements(By.CSS_SELECTOR, ".calm-job-title")
            if job_links:
                job_links[0].click()
                time.sleep(1.0)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".job-detail-page, .job-hero-card")))
            self._capture(driver, "03_job_cockpit_fit", "Job Detail Cockpit 2-Column Job Specification & Fit Analysis")

            # --- 4. Job Detail Analysis & Research Section ---
            print("\n[4/17] Auditing Job Detail Fit Analysis & Research Section")
            driver.execute_script("window.scrollBy(0, 350);")
            time.sleep(0.5)
            self._capture(driver, "04_job_cockpit_analysis_detail", "Job Detail Fit Synthesis, Strengths, Gaps, and Tips")
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.3)

            # --- 5. In-Job Tailor Studio (Simple Mode) ---
            print("\n[5/17] Auditing In-Job Tailor Studio (Simple Mode)")
            subtab_btns = driver.find_elements(By.XPATH, "//div[contains(@class, 'job-subtabs')]//button[contains(., 'Tailor Studio')]")
            if subtab_btns:
                subtab_btns[0].click()
                time.sleep(1.2)

            # Ensure in Simple mode
            simple_mode_btns = driver.find_elements(By.XPATH, "//button[contains(@class, 'studio-inline-mode-btn') and contains(., 'Simple')]")
            if simple_mode_btns:
                simple_mode_btns[0].click()
                time.sleep(0.8)

            # Expand all sections if button present
            expand_btn = driver.find_elements(By.XPATH, "//button[contains(@class, 'studio-jumpbar-fold') and contains(., 'Expand all')]")
            if expand_btn:
                expand_btn[0].click()
                time.sleep(0.5)

            self._capture(driver, "05_tailor_studio_simple", "In-Job Tailor Studio Simple Mode Form Cards & Live Preview")

            # --- 6. In-Job Tailor Studio (Advanced Mode) ---
            print("\n[6/17] Auditing In-Job Tailor Studio (Advanced Mode)")
            adv_mode_btns = driver.find_elements(By.XPATH, "//button[contains(@class, 'studio-inline-mode-btn') and contains(., 'Code')]")
            if adv_mode_btns:
                adv_mode_btns[0].click()
                time.sleep(0.8)
            self._capture(driver, "06_tailor_studio_advanced", "In-Job Tailor Studio Advanced Mode Code Editor & WASM Preview")

            # --- 7. In-Job Tailor Studio (Job Cheat Sheet Drawer) ---
            print("\n[7/17] Auditing In-Job Tailor Studio Cheat Sheet Drawer")
            cs_trigger = driver.find_elements(By.XPATH, "//button[contains(., 'Cheat Sheet')]")
            if cs_trigger:
                cs_trigger[0].click()
                time.sleep(0.8)
            self._capture(driver, "07_tailor_studio_cheatsheet_open", "In-Job Tailor Studio Slide-Out Job Cheat Sheet Drawer")

            # Close drawer
            cs_close = driver.find_elements(By.CSS_SELECTOR, ".studio-cheat-rail-header button")
            if cs_close:
                cs_close[0].click()
                time.sleep(0.4)

            # --- 8. Standalone CV Library (Simple Mode) ---
            print("\n[8/17] Auditing Standalone CV Library (Simple Mode)")
            cv_nav = driver.find_elements(By.XPATH, "//button[contains(@class, 'nav-tab') and (contains(., 'CV Studio') or contains(., 'CV Library'))]")
            if cv_nav:
                cv_nav[0].click()
                time.sleep(1.2)

            simple_studio_btn = driver.find_elements(By.XPATH, "//button[contains(@class, 'studio-inline-mode-btn') and contains(., 'Simple')]")
            if simple_studio_btn:
                simple_studio_btn[0].click()
                time.sleep(0.6)
            self._capture(driver, "08_cv_studio_simple", "Standalone CV Studio Simple Mode Structured Form Cards")

            # --- 9. Standalone CV Studio (Advanced Mode) ---
            print("\n[9/17] Auditing Standalone CV Studio (Advanced Mode)")
            adv_studio_btn = driver.find_elements(By.XPATH, "//button[contains(@class, 'studio-inline-mode-btn') and contains(., 'Code')]")
            if adv_studio_btn:
                adv_studio_btn[0].click()
                time.sleep(0.6)
            self._capture(driver, "09_cv_studio_advanced", "Standalone CV Studio Advanced Mode Code Editor & Topbar Actions")

            # --- 10. CV Studio Create Document Modal ---
            print("\n[10/17] Auditing CV Studio Create Document Modal")
            new_doc_btn = driver.find_elements(By.XPATH, "//button[contains(@class, 'btn') and contains(., 'New')]")
            if new_doc_btn:
                new_doc_btn[0].click()
                time.sleep(0.6)
            self._capture(driver, "10_cv_studio_create_modal", "CV Studio Create Document Modal & Starting Templates")

            # Close modal with Esc
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.4)

            # --- 11. Daily Matches Explorer ---
            print("\n[11/17] Auditing Daily Matches Explorer")
            daily_nav = driver.find_elements(By.XPATH, "//button[contains(@class, 'nav-tab') and contains(., 'Daily Matches')]")
            if daily_nav:
                daily_nav[0].click()
                time.sleep(0.8)
            self._capture(driver, "11_daily_matches", "Daily Matches Explorer Cards & Scraper Dispatch")

            # --- 12. Manual Add Job Form ---
            print("\n[12/17] Auditing Manual Job Addition Form")
            manual_nav = driver.find_elements(By.XPATH, "//button[contains(@class, 'nav-tab') and contains(., 'Add Job')]")
            if manual_nav:
                manual_nav[0].click()
                time.sleep(0.8)
            self._capture(driver, "12_manual_add_job", "Manual Add Job Form, URL Input & Description Denoiser")

            # --- 13. Scraper Configuration & Logs ---
            print("\n[13/17] Auditing Scraper Configuration & Live Logs")
            scraper_nav = driver.find_elements(By.XPATH, "//button[contains(@class, 'nav-tab') and contains(., 'Sources')]")
            if scraper_nav:
                scraper_nav[0].click()
                time.sleep(0.8)
            self._capture(driver, "13_scraper_config", "Scraper Execution Controls & Live Log Terminal")

            # --- 14. Analytics Dashboard ---
            print("\n[14/17] Auditing Analytics & Funnel Dashboard")
            stats_nav = driver.find_elements(By.XPATH, "//button[contains(@class, 'nav-tab') and contains(., 'Analytics')]")
            if stats_nav:
                stats_nav[0].click()
                time.sleep(0.8)
            self._capture(driver, "14_analytics_dashboard", "Analytics Summary Cards, Pipeline Funnel, and Skills Distribution")

            # --- 15. Personalize & Standing Notes ---
            print("\n[15/17] Auditing Personalize & Standing Notes")
            personalize_nav = driver.find_elements(By.XPATH, "//button[contains(@class, 'nav-tab') and contains(., 'Personalize')]")
            if personalize_nav:
                personalize_nav[0].click()
                time.sleep(0.8)
            self._capture(driver, "15_personalize_notes", "Personalize Scratchpad, Standing Notes, and Base CV Plaintext")

            # --- 16. Settings & Danger Zone ---
            print("\n[16/17] Auditing Settings & Danger Zone")
            settings_nav = driver.find_elements(By.XPATH, "//button[contains(@class, 'nav-tab') and contains(., 'Settings')]")
            if settings_nav:
                settings_nav[0].click()
                time.sleep(0.8)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            self._capture(driver, "16_settings_danger_zone", "Settings Tab Scraper Defaults & Danger Zone Actions")
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.3)

            # --- 17. Theme Switcher Gallery ---
            print("\n[17/17] Auditing Theme Switcher & Palette Selection")
            theme_btn = driver.find_elements(By.CSS_SELECTOR, ".theme-switcher-btn")
            if theme_btn:
                theme_btn[0].click()
                time.sleep(0.6)
            self._capture(driver, "17_theme_switcher_open", "Header Theme Switcher Popover & Visual Swatches")

            # Save metrics to JSON
            metrics_file = self.output_dir / "metrics.json"
            with open(metrics_file, "w", encoding="utf-8") as f:
                json.dump(self.metrics_data, f, indent=2)
            print(f"\n📊 Extracted DOM metrics saved to: {metrics_file}")

        finally:
            driver.quit()
            print("🏁 Visual audit browser session completed successfully.")


if __name__ == "__main__":
    auditor = VisualHeuristicAuditor()
    auditor.run()
