#!/usr/bin/env python3
"""
Move all Canvas courses whose course_code starts with "HUMA" into subaccount ID 169,
and VERIFY each move by re-reading the course and checking account_id.
You will need to go into the script and edit the text as well as the sub account you wish to move the 
class into.  Use "find text" in your IDE to search for HUMA and change it

"""

import sys
import time
import requests

# ====== HARD-CODE THESE ======
CANVAS_DOMAIN = "paste domain here"
TOKEN = "paste token here"
TARGET_SUBACCOUNT_ID = 000  #paste in the target sub
ROOT_ACCOUNT_ID = 1  # change if needed
# ============================

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
})

def _sleep_backoff(attempt: int) -> None:
    time.sleep(min(2 ** attempt, 30))

def canvas_request(method: str, url: str, **kwargs) -> requests.Response:
    for attempt in range(0, 8):
        resp = SESSION.request(method, url, timeout=60, **kwargs)

        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    time.sleep(float(ra))
                except ValueError:
                    _sleep_backoff(attempt)
            else:
                _sleep_backoff(attempt)
            continue

        if 500 <= resp.status_code <= 599:
            _sleep_backoff(attempt)
            continue

        return resp

    return resp

def get_next_link(resp: requests.Response) -> str | None:
    link = resp.headers.get("Link")
    if not link:
        return None
    for part in [p.strip() for p in link.split(",")]:
        if 'rel="next"' in part:
            start = part.find("<") + 1
            end = part.find(">")
            if start > 0 and end > start:
                return part[start:end]
    return None

def iter_courses_search_huma(root_account_id: int):
    """
    Pull courses under the root account with search_term=HUMA,
    then strictly filter by course_code.startswith("HUMA").
    """
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{root_account_id}/courses"
    params = {
        "search_term": "HUMA",
        "per_page": 100,
    }

    while url:
        resp = canvas_request("GET", url, params=params)
        params = None
        if not resp.ok:
            print(f"ERROR fetching courses: {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)

        for c in resp.json():
            code = (c.get("course_code") or "").strip()
            if code.startswith("HUMA"):
                yield c

        url = get_next_link(resp)

def get_course(course_id: int) -> dict:
    url = f"{CANVAS_DOMAIN}/api/v1/courses/{course_id}"
    resp = canvas_request("GET", url)
    if not resp.ok:
        raise RuntimeError(f"GET course failed {course_id}: HTTP {resp.status_code}")
    return resp.json()

def move_course_to_subaccount(course_id: int, target_subaccount_id: int) -> dict:
    """
    IMPORTANT: Use course[account_id] (nested param) to move course to another account.
    """
    url = f"{CANVAS_DOMAIN}/api/v1/courses/{course_id}"
    data = {
        "course[account_id]": target_subaccount_id
    }
    resp = canvas_request("PUT", url, data=data)
    if not resp.ok:
        raise RuntimeError(f"PUT move failed {course_id}: HTTP {resp.status_code} {resp.text}")
    return resp.json()

def count_courses_in_account(account_id: int) -> int:
    """
    Count courses directly in an account via pagination.
    """
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{account_id}/courses"
    params = {"per_page": 100}
    total = 0
    while url:
        resp = canvas_request("GET", url, params=params)
        params = None
        if not resp.ok:
            raise RuntimeError(f"Count courses failed for account {account_id}: HTTP {resp.status_code}")
        data = resp.json()
        total += len(data)
        url = get_next_link(resp)
    return total

def main():
    dry_run = "--dry-run" in sys.argv

    print(f"Canvas: {CANVAS_DOMAIN}")
    print(f"Root account ID: {ROOT_ACCOUNT_ID}")
    print(f"Target subaccount ID: {TARGET_SUBACCOUNT_ID}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE MOVE + VERIFY'}")
    print("-" * 80)

    matched = 0
    already_there = 0
    moved_ok = 0
    moved_failed_verify = 0
    failed = 0

    for course in iter_courses_search_huma(ROOT_ACCOUNT_ID):
        course_id = int(course["id"])
        name = course.get("name") or ""
        code = course.get("course_code") or ""
        current_account_id = course.get("account_id")

        matched += 1

        if current_account_id == TARGET_SUBACCOUNT_ID:
            print(f"SKIP (already in 169): {course_id} | {code} | {name}")
            already_there += 1
            continue

        print(f"MOVE: {course_id} | {code} | {name} | {current_account_id} -> {TARGET_SUBACCOUNT_ID}")

        if dry_run:
            continue

        try:
            move_course_to_subaccount(course_id, TARGET_SUBACCOUNT_ID)

            # VERIFY
            fresh = get_course(course_id)
            new_account_id = fresh.get("account_id")

            if new_account_id == TARGET_SUBACCOUNT_ID:
                moved_ok += 1
            else:
                moved_failed_verify += 1
                print(f"VERIFY FAILED: course {course_id} account_id is still {new_account_id}", file=sys.stderr)

        except Exception as e:
            failed += 1
            print(f"FAILED: {course_id} | {code} | {e}", file=sys.stderr)

    print("-" * 80)
    print(f"Matched HUMA*: {matched}")
    print(f"Already in 169: {already_there}")
    if not dry_run:
        print(f"Moved + verified OK: {moved_ok}")
        print(f"Moved but verify failed: {moved_failed_verify}")
        print(f"Errors: {failed}")

        try:
            n169 = count_courses_in_account(TARGET_SUBACCOUNT_ID)
            print(f"API now sees {n169} course(s) directly in account {TARGET_SUBACCOUNT_ID}.")
        except Exception as e:
            print(f"Could not count courses in 169 via API: {e}", file=sys.stderr)

    if failed or moved_failed_verify:
        sys.exit(2)

if __name__ == "__main__":

    main()

