#!/usr/bin/env python3
"""scripts/verify_typst_wasm.py — Headless browser test for Typst WASM Web Worker.

Spins up a local HTTP server serving webapp/dist, launches headless Chrome via Selenium,
opens test-typst-worker.html, and asserts that window.__TYPST_WASM_RESULT__.success is True.
"""

from __future__ import annotations

import functools
import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "webapp" / "dist"


def run_http_server(port: int, stop_event: threading.Event):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST_DIR))
    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        httpd.timeout = 0.5
        while not stop_event.is_set():
            httpd.handle_request()


import subprocess

def main():
    if not DIST_DIR.exists() or not (DIST_DIR / "test-typst-worker.html").exists():
        print(f"[Verify] {DIST_DIR / 'test-typst-worker.html'} not found. Running 'npm run build'...")
        subprocess.run(["npm", "--prefix", str(PROJECT_ROOT / "webapp"), "run", "build"], check=True)

    port = 5199
    stop_event = threading.Event()
    server_thread = threading.Thread(target=run_http_server, args=(port, stop_event), daemon=True)
    server_thread.start()
    time.sleep(0.5)

    print(f"[Verify] Serving {DIST_DIR} on http://127.0.0.1:{port}...")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        url = f"http://127.0.0.1:{port}/test-typst-worker.html"
        print(f"[Verify] Navigating to {url}...")
        driver.get(url)

        # Wait up to 15s for window.__TYPST_WASM_RESULT__ to appear
        def result_ready(d):
            res = d.execute_script("return window.__TYPST_WASM_RESULT__;")
            return res is not None

        WebDriverWait(driver, 15).until(result_ready)
        result = driver.execute_script("return window.__TYPST_WASM_RESULT__;")
        print("[Verify] Raw result from browser:", json.dumps(result, indent=2))

        # Check console logs
        logs = driver.get_log("browser")
        for entry in logs:
            if entry.get("level") in ("SEVERE", "WARNING"):
                print(f"[Console {entry.get('level')}] {entry.get('message')}")

        if result and result.get("success"):
            res = result.get("results", {})
            basic = res.get("basic", {})
            cv = res.get("cv", {})
            pdf = res.get("pdf", {})
            print(f"\n✅ SUCCESS: Typst WASM Web Worker Verified (Phases 1-4)!")
            print(f"   1. Basic compile: {basic.get('elapsed')}ms ({basic.get('length')} chars)")
            print(f"   2. Moderner-CV compile: {cv.get('elapsed')}ms ({cv.get('length')} chars, SVG: {cv.get('hasSvg')})")
            print(f"   3. Client-side PDF compile: {pdf.get('elapsed')}ms ({pdf.get('byteLength')} bytes, Valid: {pdf.get('isPdfValid')})")
            sys.exit(0)
        else:
            print(f"\n❌ FAILED: {result.get('error') if result else 'Unknown error'}")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Exception during verification: {e}")
        if driver:
            try:
                logs = driver.get_log("browser")
                print("Browser console logs:")
                for entry in logs:
                    print(f"  [{entry.get('level')}] {entry.get('message')}")
            except Exception:
                pass
        sys.exit(1)
    finally:
        if driver:
            driver.quit()
        stop_event.set()


if __name__ == "__main__":
    main()
