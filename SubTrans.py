#!/usr/bin/env python3
"""
Move all courses from one subaccount to another, verify they moved,
then delete the source subaccount (only if Canvas will allow it).

Features included (current state):
- Hard-coded Canvas URL + token
- Recursive subaccount search (handles subaccounts-of-subaccounts)
- Optional hard-coded SOURCE_SUBACCOUNT_ID / DEST_SUBACCOUNT_ID to avoid name ambiguity
- Correct update parameter: course[account_id]
- Verifies move by checking returned account_id
- Course listing uses state[]=all to catch everything Canvas might count
- Correct delete endpoint for subaccounts: /accounts/:root/sub_accounts/:id
- Prints helpful error bodies (esp. 409 conflicts)
"""

import sys
import csv
import time
import requests
from urllib.parse import urljoin

# =======================
# HARD-CODED CONFIG
# =======================

CANVAS_BASE_URL = "https://grayson.instructure.com"
CANVAS_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"

ROOT_ACCOUNT_ID = "1"




SOURCE_SUBACCOUNT_ID = 165  # e.g. 18 or 107
DEST_SUBACCOUNT_ID = 1083     # optional, e.g. 1082

# SAFETY SWITCH
DRY_RUN = False

# Log file
LOG_CSV = "canvas_move_and_delete_log.csv"

# API throttle
SLEEP_SECONDS = 0.15

# Limit recursion depth when walking subaccount tree
MAX_SUBACCOUNT_DEPTH = 25


# =======================
# API HELPERS
# =======================
def canvas_headers():
    return {"Authorization": f"Bearer {CANVAS_TOKEN}"}


def api_get(path, params=None):
    url = urljoin(CANVAS_BASE_URL, path)
    r = requests.get(url, headers=canvas_headers(), params=params)
    if not r.ok:
        print("GET failed:", r.status_code, r.reason, "|", r.url)
        try:
            print("Body:", r.json())
        except Exception:
            print("Body:", r.text[:500])
    r.raise_for_status()
    return r


def api_put(path, data=None):
    url = urljoin(CANVAS_BASE_URL, path)
    r = requests.put(url, headers=canvas_headers(), data=data)
    if not r.ok:
        print("PUT failed:", r.status_code, r.reason, "|", r.url)
        try:
            print("Body:", r.json())
        except Exception:
            print("Body:", r.text[:500])
    r.raise_for_status()
    return r


def api_delete(path):
    url = urljoin(CANVAS_BASE_URL, path)
    r = requests.delete(url, headers=canvas_headers())
    if not r.ok:
        print("DELETE failed:", r.status_code, r.reason, "|", r.url)
        try:
            print("Body:", r.json())
        except Exception:
            print("Body:", r.text[:500])
    r.raise_for_status()
    return r


def paginate_get(path, params=None):
    """Yield items across all pages for a Canvas collection endpoint."""
    params = dict(params or {})
    url = urljoin(CANVAS_BASE_URL, path)

    while url:
        r = requests.get(url, headers=canvas_headers(), params=params)
        if not r.ok:
            print("PAGINATED GET failed:", r.status_code, r.reason, "|", r.url)
            try:
                print("Body:", r.json())
            except Exception:
                print("Body:", r.text[:500])
        r.raise_for_status()

        data = r.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        for item in data:
            yield item

        # Canvas pagination via Link header
        next_url = None
        link = r.headers.get("Link", "")
        if link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    next_url = part[part.find("<") + 1 : part.find(">")]
                    break

        url = next_url
        params = None  # next_url already has its own params


# =======================
# CANVAS OPERATIONS
# =======================
def find_subaccount_by_name_recursive(root_id, target_name, exact=True, max_depth=25):
    """
    Recursively search the entire subaccount tree under root_id for a name match.
    exact=True uses exact string match; exact=False uses case-insensitive contains.
    """
    target_cmp = target_name if exact else target_name.lower()

    # BFS queue: start at root_id
    queue = [(str(root_id), 0)]
    matches = []

    while queue:
        acct_id, depth = queue.pop(0)
        if depth > max_depth:
            continue

        for acct in paginate_get(f"/api/v1/accounts/{acct_id}/sub_accounts", params={"per_page": 100}):
            name = acct.get("name", "")

            if exact:
                if name == target_name:
                    matches.append(acct)
            else:
                if target_cmp in name.lower():
                    matches.append(acct)

            queue.append((str(acct.get("id")), depth + 1))

    return matches


def list_courses(account_id):
    """
    List courses in an account/subaccount. Using state[]=all avoids missing "hidden" states
    that Canvas still counts for deletion.
    """
    params = {
        "per_page": 100,
        "include[]": ["term"],
        "state[]": ["all"],
    }
    return list(paginate_get(f"/api/v1/accounts/{account_id}/courses", params=params))


def list_child_subaccounts(account_id):
    return list(paginate_get(f"/api/v1/accounts/{account_id}/sub_accounts", params={"per_page": 100}))


def move_course(course_id, dest_account_id):
    """
    Canvas expects nested params for course updates.
    """
    return api_put(
        f"/api/v1/courses/{course_id}",
        data={"course[account_id]": str(dest_account_id)},
    ).json()


# =======================
# MAIN
# =======================
def main():
    if not CANVAS_TOKEN.strip() or "PASTE_YOUR_LONG_CANVAS_TOKEN_HERE" in CANVAS_TOKEN:
        print("ERROR: Paste your real Canvas token into CANVAS_TOKEN.")
        sys.exit(1)

    print("Canvas cleanup starting…")
    print(f"Canvas URL:        {CANVAS_BASE_URL}")
    print(f"ROOT_ACCOUNT_ID:   {ROOT_ACCOUNT_ID}")
    print(f"Source subaccount: {SOURCE_SUBACCOUNT_NAME}" if SOURCE_SUBACCOUNT_ID is None else f"Source subaccount id (forced): {SOURCE_SUBACCOUNT_ID}")
    print(f"Destination:       {DEST_SUBACCOUNT_NAME}" if DEST_SUBACCOUNT_ID is None else f"Destination subaccount id (forced): {DEST_SUBACCOUNT_ID}")
    print(f"DRY_RUN:           {DRY_RUN}")
    print()

    # Token check
    me = api_get("/api/v1/users/self/profile").json()
    print("Token OK. Authenticated as:", me.get("name"), "| id:", me.get("id"))
    print()

    # Account access check
    accs = api_get("/api/v1/accounts", params={"per_page": 100}).json()
    print("Accounts accessible to this token:")
    for a in accs:
        print(" - id:", a.get("id"), "|", a.get("name"))
    print("\n--- Starting subaccount resolution ---\n")

    # Resolve source ID
    if SOURCE_SUBACCOUNT_ID is not None:
        src_id = int(SOURCE_SUBACCOUNT_ID)
        print("Source subaccount id:", src_id, "(forced)")
    else:
        src_matches = find_subaccount_by_name_recursive(
            ROOT_ACCOUNT_ID, SOURCE_SUBACCOUNT_NAME, exact=True, max_depth=MAX_SUBACCOUNT_DEPTH
        )
        if len(src_matches) != 1:
            print(f"ERROR: Expected exactly 1 match for source '{SOURCE_SUBACCOUNT_NAME}', got {len(src_matches)}")
            print("Source matches:", src_matches)
            print("\nFix: set SOURCE_SUBACCOUNT_ID to the one you want (e.g., 18 or 107).")
            return
        src_id = src_matches[0]["id"]
        print("Source subaccount id:", src_id)

    # Resolve destination ID
    if DEST_SUBACCOUNT_ID is not None:
        dst_id = int(DEST_SUBACCOUNT_ID)
        print("Dest subaccount id:", dst_id, "(forced)")
    else:
        dst_matches = find_subaccount_by_name_recursive(
            ROOT_ACCOUNT_ID, DEST_SUBACCOUNT_NAME, exact=True, max_depth=MAX_SUBACCOUNT_DEPTH
        )
        if len(dst_matches) != 1:
            print(f"ERROR: Expected exactly 1 match for destination '{DEST_SUBACCOUNT_NAME}', got {len(dst_matches)}")
            print("Dest matches:", dst_matches)
            return
        dst_id = dst_matches[0]["id"]
        print("Dest subaccount id:  ", dst_id)

    print()

    # List courses in source
    courses = list_courses(src_id)
    print(f"Found {len(courses)} course(s) to move.")

    # Open CSV log
    with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "action", "course_id", "course_name", "status", "message"])

        # Move loop
        for c in courses:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            cid = c.get("id")
            cname = c.get("name") or c.get("course_code") or ""
            state = c.get("workflow_state")

            print(f"Moving: {cid} — {cname} (state={state})")

            if DRY_RUN:
                writer.writerow([ts, "MOVE", cid, cname, "DRY_RUN", "Not moved"])
                continue

            try:
                result = move_course(cid, dst_id)
                new_acct = result.get("account_id")

                # Verify move actually applied
                if str(new_acct) == str(dst_id):
                    writer.writerow([ts, "MOVE", cid, cname, "OK", f"Moved to account_id={new_acct}"])
                else:
                    writer.writerow(
                        [ts, "MOVE", cid, cname, "ERROR",
                         f"Move did not apply. Returned account_id={new_acct}, expected {dst_id}"]
                    )
                    print(f"WARNING: Course {cid} did NOT move (returned account_id={new_acct}).")

            except Exception as e:
                writer.writerow([ts, "MOVE", cid, cname, "ERROR", str(e)])
                print(f"ERROR moving course {cid}: {e}")

            time.sleep(SLEEP_SECONDS)

        # Re-check remaining courses (state[]=all)
        remaining = list_courses(src_id)
        print(f"\nRemaining courses in source (state=all): {len(remaining)}")
        if remaining:
            print("Courses still in source:")
            for c in remaining[:50]:
                print(" -", c.get("id"), c.get("name"), "state=", c.get("workflow_state"))
            if len(remaining) > 50:
                print(f" ... and {len(remaining) - 50} more")

        # Check child subaccounts
        children = list_child_subaccounts(src_id)
        print(f"\nChild subaccounts under source ({src_id}): {len(children)}")
        for ch in children:
            print(" -", ch.get("id"), ch.get("name"), "state=", ch.get("workflow_state"))

        # Stop conditions
        if DRY_RUN:
            print("\nDRY_RUN=True: not deleting source subaccount.")
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "DELETE_ACCOUNT", "", "", "SKIPPED", "DRY_RUN=True"])
            return

        if len(remaining) > 0:
            print("\nNot deleting: source still has courses (Canvas counts these).")
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "DELETE_ACCOUNT", "", "", "SKIPPED", "Courses still present"])
            return

        if len(children) > 0:
            print("\nNot deleting: source has child subaccounts. Delete/move them first (bottom-up).")
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "DELETE_ACCOUNT", "", "", "SKIPPED", "Child subaccounts exist"])
            return

        # Delete source subaccount (correct endpoint)
        print("\nDeleting source subaccount…")
        try:
            api_delete(f"/api/v1/accounts/{ROOT_ACCOUNT_ID}/sub_accounts/{src_id}")
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "DELETE_ACCOUNT", "", "", "OK", f"Deleted subaccount {src_id}"])
            print("Done.")
        except Exception as e:
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), "DELETE_ACCOUNT", "", "", "ERROR", str(e)])
            print("Delete failed:", e)


if __name__ == "__main__":
    main()
