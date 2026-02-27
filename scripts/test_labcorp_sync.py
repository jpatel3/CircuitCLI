#!/usr/bin/env python3
"""Interactive test script for LabCorp browser sync.

Opens a visible browser, logs into LabCorp patient portal,
waits for manual 2FA entry, then extracts lab results via API.

Usage:
    .venv/bin/python scripts/test_labcorp_sync.py
"""

from __future__ import annotations

import json
import sys
import time

# Bootstrap the CircuitAI environment
sys.path.insert(0, "src")

from circuitai.services.sites.labcorp import LabCorpSite


def main():
    print("\n=== LabCorp Browser Sync Test ===\n")

    # Load credentials from keychain
    import keyring
    service = "circuitai:labcorp"
    username = keyring.get_password(service, "_username")
    password = keyring.get_password(service, username) if username else None
    if not username or not password:
        print("ERROR: No credentials stored. Run: circuit browse setup labcorp")
        return

    print(f"  Credentials found for: {username}")

    # Launch browser
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False, slow_mo=500)
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()

    print("  Browser launched.\n")

    # Create site adapter
    mock_svc = type("MockSvc", (), {"db": None})()
    site = LabCorpSite(page, mock_svc)

    # --- Step 1: Navigate to landing page ---
    print("[1/6] Navigating to LabCorp patient portal...")
    page.goto("https://patient.labcorp.com/", timeout=30_000, wait_until="domcontentloaded")
    time.sleep(3)
    print(f"  URL: {page.url}")

    # --- Step 2: Dismiss cookie banner ---
    print("[2/6] Dismissing cookie banner...")
    try:
        cookie_btn = page.query_selector('button:has-text("Accept All Cookies")')
        if cookie_btn and cookie_btn.is_visible():
            cookie_btn.click()
            time.sleep(1)
            print("  Cookie banner dismissed.")
        else:
            print("  No cookie banner found.")
    except Exception:
        print("  No cookie banner found.")

    # --- Step 3: Click Sign In ---
    print("[3/6] Clicking Sign In...")
    sign_in_clicked = False
    for sel in ['a:has-text("Sign In")', 'button:has-text("Sign In")']:
        els = page.query_selector_all(sel)
        for el in els:
            try:
                if el.is_visible():
                    el.click()
                    sign_in_clicked = True
                    break
            except Exception:
                continue
        if sign_in_clicked:
            break

    if not sign_in_clicked:
        print("  ERROR: Could not find Sign In button")
        browser.close()
        pw.stop()
        return

    time.sleep(3)
    print(f"  URL after Sign In: {page.url}")

    # --- Step 4: Okta login (email + password) ---
    print("[4/6] Filling Okta login form...")

    login_frame = page
    for frame in page.frames:
        if "login-patient.labcorp.com" in frame.url or "okta" in frame.url.lower():
            login_frame = frame
            print(f"  Found Okta iframe: {frame.url[:80]}...")
            break

    identifier_filled = False
    for sel in ["input[name='identifier']", "input[name='username']",
                "input[type='email']", "input[type='text']"]:
        el = login_frame.query_selector(sel)
        if el and el.is_visible():
            el.fill(username)
            identifier_filled = True
            print(f"  Email entered via: {sel}")
            break

    if not identifier_filled:
        print("  ERROR: Could not find email field")
        browser.close()
        pw.stop()
        return

    for sel in ["input[type='submit']", "button[type='submit']",
                "input[value='Next']", "button:has-text('Next')"]:
        el = login_frame.query_selector(sel)
        if el and el.is_visible():
            el.click()
            print(f"  Email submitted via: {sel}")
            break

    time.sleep(3)

    for frame in page.frames:
        if "login-patient.labcorp.com" in frame.url or "okta" in frame.url.lower():
            login_frame = frame
            break

    password_filled = False
    for sel in ["input[name='credentials.passcode']", "input[name='password']",
                "input[type='password']"]:
        el = login_frame.query_selector(sel)
        if el and el.is_visible():
            el.fill(password)
            password_filled = True
            print(f"  Password entered via: {sel}")
            break

    if not password_filled:
        print("  ERROR: Could not find password field")
        browser.close()
        pw.stop()
        return

    for sel in ["input[type='submit']", "button[type='submit']",
                "input[value='Verify']", "input[value='Sign in']",
                "button:has-text('Verify')", "button:has-text('Sign In')"]:
        el = login_frame.query_selector(sel)
        if el and el.is_visible():
            el.click()
            print(f"  Password submitted via: {sel}")
            break

    time.sleep(5)
    print(f"  URL after password: {page.url}")

    # --- Step 5: Handle 2FA / CAPTCHA ---
    print("[5/6] Checking for 2FA / CAPTCHA...")
    needs_manual = site.needs_2fa() or site.needs_captcha()

    # Also check if we're still on the login page (might need manual intervention)
    current_url = page.url.lower()
    if not needs_manual and ("login" in current_url or "oauth" in current_url or "callback" in current_url):
        # Still on auth pages — may need manual intervention
        needs_manual = True
        print("  Still on auth page — may need CAPTCHA or 2FA in the browser.")

    if needs_manual:
        if site.needs_2fa():
            print("\n  *** 2FA REQUIRED ***")
            print("  Please enter your Google Authenticator code in the browser window.")
        elif site.needs_captcha():
            print("\n  *** CAPTCHA DETECTED ***")
            print("  Please complete the CAPTCHA challenge in the browser window.")
        else:
            print("\n  *** MANUAL LOGIN STEP NEEDED ***")
            print("  Please complete any challenges in the browser window.")
        print("  Waiting for login to complete...")

        for i in range(90):
            time.sleep(2)
            current_url = page.url.lower()
            # Check if we've landed on an authenticated page
            if ("dashboard" in current_url or "results" in current_url or "portal" in current_url) and "login" not in current_url:
                print(f"\n  Login successful! URL: {page.url}")
                break
            try:
                if page.query_selector("text=Sign Out") or page.query_selector("a[href*='results']"):
                    print(f"\n  Login successful! URL: {page.url}")
                    break
            except Exception:
                pass
            if i % 5 == 0:
                print(f"  ... still waiting ({i * 2}s)")
        else:
            print("\n  TIMEOUT: Login did not complete within 180 seconds.")
            browser.close()
            pw.stop()
            return
    else:
        print("  No 2FA/CAPTCHA required.")

    # Wait for post-login redirect to settle
    time.sleep(3)

    # --- Step 6: Extract lab results via API ---
    print("\n[6/6] Extracting lab results via LabCorp API...")
    try:
        data = site.extract_billing()
        print(f"\n  Data type: {data.get('data_type')}")
        print(f"  Results found: {len(data.get('results', []))}")

        if data.get("error"):
            print(f"  Error: {data['error']}")

        total_panels = 0
        total_markers = 0
        total_flagged = 0

        for i, result in enumerate(data.get("results", []), 1):
            panels = result.get("panels", [])
            markers = sum(len(p.get("markers", [])) for p in panels)
            flagged = sum(
                1 for p in panels
                for m in p.get("markers", [])
                if m.get("flag", "normal") != "normal"
            )
            total_panels += len(panels)
            total_markers += markers
            total_flagged += flagged

            print(f"\n  --- Result {i}: {result.get('result_date', 'unknown')} ---")
            print(f"  Patient: {result.get('patient_name', '')}")
            print(f"  Physician: {result.get('ordering_physician', '')}")
            print(f"  Panels: {len(panels)}, Markers: {markers}, Flagged: {flagged}")
            for panel in panels:
                p_markers = panel.get("markers", [])
                p_flagged = [m for m in p_markers if m.get("flag", "normal") != "normal"]
                flag_info = f" [{len(p_flagged)} flagged]" if p_flagged else ""
                print(f"    {panel.get('panel_name', 'Unknown')}: {len(p_markers)} markers{flag_info}")

        print(f"\n  TOTAL: {len(data.get('results', []))} results, {total_panels} panels, {total_markers} markers, {total_flagged} flagged")

        # Save raw results
        output_path = "scripts/labcorp_extract_result.json"
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"  Full results saved to: {output_path}")

        # Import into database
        if data.get("results"):
            print("\n  Importing into CircuitAI database...")
            from circuitai.core.database import DatabaseConnection
            from circuitai.core.migrations import initialize_database
            from circuitai.services.lab_service import LabService

            db = DatabaseConnection()
            db.connect()
            initialize_database(db)
            lab_svc = LabService(db)

            new_count = 0
            dup_count = 0
            for result_data in data["results"]:
                r = lab_svc.import_lab_data(result_data, source="browser")
                if r.get("duplicate"):
                    dup_count += 1
                else:
                    new_count += 1
                    print(f"    Imported: {result_data.get('result_date', '?')} ({r['panels_imported']} panels, {r['markers_imported']} markers)")

            print(f"\n  Done: {new_count} new, {dup_count} duplicates skipped")

    except Exception as e:
        print(f"  ERROR during extraction: {e}")
        import traceback
        traceback.print_exc()

    print("\n  Press Enter to close the browser...")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass

    browser.close()
    pw.stop()
    print("\nDone.")


if __name__ == "__main__":
    main()
