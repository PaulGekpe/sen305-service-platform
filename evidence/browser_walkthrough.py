"""Part J manual CRUD script, driven in a real Chrome browser, plus Part M screenshots.

Usage: python browser_walkthrough.py <base_url> <db_path> <out_dir>
Writes screenshots to <out_dir>/screenshots and a results table to <out_dir>/part_j_manual_results.json.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, DB, OUT = sys.argv[1].rstrip("/"), sys.argv[2], Path(sys.argv[3])
SHOTS = OUT / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
PASSWORD = "LabPass123!"
results = []


def row_count():
    con = sqlite3.connect(DB)
    try:
        return con.execute("select count(*) from requests_app_servicerequest").fetchone()[0]
    finally:
        con.close()


def record(no, action, expected, observed, ok):
    results.append({"no": no, "action": action, "expected": expected, "observed": observed, "pass": ok})
    print(f"[{'PASS' if ok else 'FAIL'}] {no}. {action}: {observed}")


def shot(page, name):
    page.screenshot(path=str(SHOTS / name), full_page=True)


def login(page, username):
    page.goto(f"{BASE}/accounts/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", PASSWORD)
    page.click("button[type=submit]:has-text('Sign in')")
    page.wait_for_load_state()


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox", "--no-proxy-server"])

    def new_page(viewport_h=800):
        ctx = browser.new_context(viewport={"width": 1100, "height": viewport_h})
        return ctx, ctx.new_page()

    # 1. Open /requests/ signed out -> 302 to login with next parameter
    ctx, page = new_page()
    raw = ctx.request.get(f"{BASE}/requests/", max_redirects=0)
    location = raw.headers.get("location", "")
    page.goto(f"{BASE}/requests/")
    shot(page, "01_signed_out_redirect_to_login.png")
    record(1, "Open /requests/ signed out", "302 redirect to login with next parameter",
           f"HTTP {raw.status} -> {location}; browser landed on {page.url.replace(BASE, '')}",
           raw.status == 302 and "next=/requests/" in location)

    # 2. Sign in as requester1
    page.fill("#id_username", "requester1")
    page.fill("#id_password", PASSWORD)
    page.click("button[type=submit]:has-text('Sign in')")
    page.wait_for_load_state()
    shot(page, "02_list_after_sign_in.png")
    record(2, "Sign in as requester1", "Request list loads",
           f"Landed on {page.url.replace(BASE, '')}; heading '{page.inner_text('h1')}'",
           page.url.endswith("/requests/") and "Service requests" in page.inner_text("h1"))

    # 3. Submit empty create form -> inline errors, no row created
    before = row_count()
    page.goto(f"{BASE}/requests/new/")
    page.click("button[type=submit]:has-text('Save request')")
    page.wait_for_load_state()
    errors = page.locator("p.error").all_inner_texts()
    after = row_count()
    shot(page, "03_create_form_validation_errors.png")
    record(3, "Submit empty create form", "Inline errors; no row created",
           f"{len(errors)} inline errors ({'; '.join(sorted(set(errors)))}); rows {before} -> {after}",
           len(errors) >= 4 and before == after)

    # 4. Create a valid HIGH-priority request
    page.select_option("#id_category", label="ICT Support")
    page.fill("#id_title", "Projector in Room B12 shows no image")
    page.fill("#id_description", "The projector powers on but reports no HDMI signal.\nCable was checked.")
    page.fill("#id_location", "Room B12")
    page.select_option("#id_priority", "HIGH")
    shot(page, "04a_create_form_filled.png")
    page.click("button[type=submit]:has-text('Save request')")
    page.wait_for_load_state()
    detail_url = page.url
    request_id = re.search(r"/requests/([0-9a-f-]{36})/", detail_url).group(1)
    msg = page.locator(".message.success").inner_text()
    shot(page, "04b_detail_after_create.png")
    record(4, "Create valid HIGH-priority request", "Redirect to detail; success message",
           f"Redirected to /requests/{request_id}/; message '{msg}'; priority '{page.locator('dd').nth(1).inner_text()}'",
           "Service request created." in msg and page.locator("dd").nth(1).inner_text() == "High")

    # 5. Edit title and location
    page.click("text=Edit request")
    page.wait_for_load_state()
    shot(page, "05a_edit_form.png")
    page.fill("#id_title", "Projector in Room B12 has no HDMI signal")
    page.fill("#id_location", "Room B12, Block B")
    page.click("button[type=submit]:has-text('Save request')")
    page.wait_for_load_state()
    body = page.inner_text("main")
    shot(page, "05b_detail_after_edit.png")
    record(5, "Edit title and location", "Detail shows new values",
           f"Detail shows title '{page.inner_text('h1')}' and location 'Room B12, Block B'; message '{page.locator('.message.success').inner_text()}'",
           "has no HDMI signal" in page.inner_text("h1") and "Room B12, Block B" in body)

    # 6. Add a comment
    page.fill("#id_body", "The same cable works on another projector.")
    page.click("button[type=submit]:has-text('Add comment')")
    page.wait_for_load_state()
    article = page.locator("article.comment").first
    shot(page, "06_comment_added.png")
    record(6, "Add a comment", "Author and timestamp displayed",
           f"Comment shows author '{article.locator('strong').inner_text()}' at '{article.locator('time').inner_text()}'",
           article.locator("strong").inner_text() == "requester1" and len(article.locator("time").inner_text()) > 8)

    # 7. requester2 pastes the detail URL
    ctx2, page2 = new_page()
    login(page2, "requester2")
    resp = page2.goto(detail_url)
    text = page2.inner_text("main")
    shot(page2, "07_requester2_gets_404.png")
    record(7, "As requester2 paste detail URL", "404; no owner data disclosed",
           f"HTTP {resp.status}; page text: '{' '.join(text.split())}'",
           resp.status == 404 and "requester1" not in text and "Projector" not in text)
    ctx2.close()

    # 8. technician1 opens the request
    ctx3, page3 = new_page(1000)
    login(page3, "technician1")
    resp = page3.goto(detail_url)
    shot(page3, "08_staff_sees_request_with_assign_form.png")
    record(8, "As technician1 open request", "Staff can see it",
           f"HTTP {resp.status}; sees '{page3.inner_text('h1')}' and the Assign technician form",
           resp.status == 200 and page3.locator("text=Assign technician").count() > 0)

    # 9. Back after a successful POST -> no duplicate row
    page.goto(f"{BASE}/requests/new/")
    page.select_option("#id_category", label="ICT Support")
    page.fill("#id_title", "Back button duplicate test")
    page.fill("#id_description", "Used to prove Post/Redirect/Get.")
    page.fill("#id_location", "Lab 2")
    page.select_option("#id_priority", "LOW")
    before = row_count()
    page.click("button[type=submit]:has-text('Save request')")
    page.wait_for_load_state()
    created = row_count()
    page.go_back()
    page.wait_for_load_state()
    after_back = row_count()
    page.go_forward()
    page.wait_for_load_state()
    page.reload()
    after_reload = row_count()
    shot(page, "09_after_back_and_reload_no_duplicate.png")
    record(9, "Use Back after successful POST", "No duplicate row created",
           f"rows before {before}, after submit {created}, after Back {after_back}, after reload {after_reload}",
           created == before + 1 and after_back == created and after_reload == created)

    # ---- Part M, Tasks 1-2 through the UI -------------------------------------------------------
    page3.select_option("#id_technician", label="technician1")
    page3.click("button[type=submit]:has-text('Assign')")
    page3.wait_for_load_state()
    shot(page3, "10_task1_staff_assigns_technician.png")
    assigned_msg = page3.locator(".message.success").inner_text()
    print("assign:", assigned_msg, "| status:", page3.locator("dd").first.inner_text())

    # the requester must not see the staff-only forms
    page.goto(detail_url)
    shot(page, "11_requester_view_has_no_staff_forms.png")
    print("requester sees assign/resolve forms:",
          page.locator("text=Assign technician").count() + page.locator("text=Resolve request").count())

    # a blank resolution is rejected through messages
    page3.goto(detail_url)
    # Switch off the browser's own "required" check so the SERVER-side rule is what responds.
    page3.evaluate("document.querySelector('form[action*=\"/resolve/\"]').noValidate = true")
    page3.click("button[type=submit]:has-text('Mark as resolved')")
    page3.wait_for_load_state()
    shot(page3, "12_task2_blank_notes_rejected.png")
    print("blank resolve:", page3.locator(".message.error").all_inner_texts())

    page3.fill("#id_work_notes", "Replaced the faulty HDMI cable and tested the projector.")
    page3.click("button[type=submit]:has-text('Mark as resolved')")
    page3.wait_for_load_state()
    shot(page3, "13_task2_resolved_with_work_order.png")
    print("resolve:", page3.locator(".message.success").inner_text(), "| status:", page3.locator("dd").first.inner_text())

    # ---- Task 3 and 4: filtered pagination and summary counts -------------------------------------
    page.goto(f"{BASE}/requests/")
    shot(page, "14_task4_summary_counts_requester.png")

    page.goto(f"{BASE}/requests/?q=printer&status=OPEN&page=2")
    shot(page, "15_task3_page2_filters_preserved.png")
    print("page 2 q value:", page.input_value("input[name=q]"), "| status:", page.input_value("select[name=status]"),
          "| pager:", page.inner_text("nav.pager").replace("\n", " "))

    page3.goto(f"{BASE}/requests/")
    shot(page3, "16_task4_summary_counts_staff.png")

    browser.close()

(OUT / "part_j_manual_results.json").write_text(json.dumps({"request_id": request_id, "steps": results}, indent=2))
failed = [r for r in results if not r["pass"]]
print(f"\n{len(results) - len(failed)}/{len(results)} manual steps passed")
sys.exit(1 if failed else 0)
