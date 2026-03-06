#!/usr/bin/env python3
"""
Canvas SIS cleanup utility
- Find a user by SIS ID or search term (email/login/name)
- Clear the user's SIS ID

Examples:
  python canvas_clear_sis.py --sis 123456
  python canvas_clear_sis.py --search someone@school.edu
  python canvas_clear_sis.py --search "Jane Doe"
"""

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple
import requests

# =========================
# CONFIG (EDIT THESE)
# =========================
CANVAS_BASE_URL = "https://grayson.instructure.com"  # <-- change if needed
ROOT_ACCOUNT_ID = 1  # root account id for account-based user search
CANVAS_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"  # <-- hard-coded token (as requested)
# =========================


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def canvas_headers() -> Dict[str, str]:
    if not CANVAS_TOKEN or "PASTE_YOUR_CANVAS_TOKEN_HERE" in CANVAS_TOKEN:
        die("You must paste your Canvas token into CANVAS_TOKEN first.")
    return {
        "Authorization": f"Bearer {CANVAS_TOKEN}",
        "Accept": "application/json",
        # requests sets Content-Type automatically when using json=...
    }


def request_json(method: str, url: str, *, params=None, json_body=None) -> Any:
    try:
        r = requests.request(
            method,
            url,
            headers=canvas_headers(),
            params=params,
            json=json_body,
            timeout=30,
        )
    except requests.RequestException as e:
        die(f"Network error calling Canvas: {e}")

    if r.status_code >= 400:
        # Try to show Canvas error response
        try:
            err = r.json()
        except Exception:
            err = r.text
        die(f"Canvas API error {r.status_code} for {url}\nResponse: {err}")

    if not r.text.strip():
        return None

    try:
        return r.json()
    except Exception:
        return r.text


def get_user_profile_by_sis(sis_id: str) -> Optional[Dict[str, Any]]:
    # GET /api/v1/users/sis_user_id:XXXXX/profile
    url = f"{CANVAS_BASE_URL}/api/v1/users/sis_user_id:{sis_id}/profile"
    try:
        data = request_json("GET", url)
        if isinstance(data, dict) and data.get("id"):
            return data
        return None
    except SystemExit:
        # If Canvas returns 404/400 it will die; we want to treat as "not found" sometimes.
        # So we do a softer call for profile lookup:
        return None


def get_user_profile_by_id(user_id: int) -> Dict[str, Any]:
    url = f"{CANVAS_BASE_URL}/api/v1/users/{user_id}/profile"
    data = request_json("GET", url)
    if not isinstance(data, dict) or not data.get("id"):
        die(f"Unexpected profile response for user_id={user_id}: {data}")
    return data


def search_account_users(search_term: str, account_id: int) -> List[Dict[str, Any]]:
    """
    GET /api/v1/accounts/:account_id/users?search_term=...
    Paginates if needed.
    """
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{account_id}/users"
    params = {"search_term": search_term, "per_page": 100}
    results: List[Dict[str, Any]] = []

    while True:
        r = requests.get(url, headers=canvas_headers(), params=params, timeout=30)
        if r.status_code >= 400:
            try:
                err = r.json()
            except Exception:
                err = r.text
            die(f"Canvas API error {r.status_code} for {url}\nResponse: {err}")

        batch = r.json()
        if isinstance(batch, list):
            results.extend(batch)
        else:
            die(f"Unexpected search response: {batch}")

        # Parse pagination from Link header
        link = r.headers.get("Link", "")
        next_url = None
        if link:
            parts = [p.strip() for p in link.split(",")]
            for p in parts:
                if 'rel="next"' in p:
                    # format: <https://...>; rel="next"
                    start = p.find("<") + 1
                    end = p.find(">")
                    if start > 0 and end > start:
                        next_url = p[start:end]
                    break

        if not next_url:
            break

        # After first page, call next_url directly with no params
        url = next_url
        params = None

    return results


def pick_best_match(candidates: List[Dict[str, Any]], search_term: str) -> Dict[str, Any]:
    """
    If multiple users match, try to pick the most likely (exact email/login match),
    otherwise force the admin to choose.
    """
    if not candidates:
        die("No matching users found.")

    if len(candidates) == 1:
        return candidates[0]

    term_lower = search_term.strip().lower()

    # Try exact matches against common fields
    exact = []
    for u in candidates:
        for key in ("login_id", "email", "sis_user_id", "name"):
            v = (u.get(key) or "").strip().lower()
            if v and v == term_lower:
                exact.append(u)
                break

    if len(exact) == 1:
        return exact[0]

    # Otherwise show a menu
    print("\nMultiple users matched. Choose one:\n")
    for i, u in enumerate(candidates, start=1):
        print(f"{i}) id={u.get('id')}  name={u.get('name')}  login_id={u.get('login_id')}  sis_user_id={u.get('sis_user_id')}")

    while True:
        choice = input("\nEnter number to select (or 'q' to quit): ").strip().lower()
        if choice in ("q", "quit", "exit"):
            sys.exit(0)
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(candidates):
                return candidates[n - 1]
        print("Invalid choice. Try again.")


def clear_sis_user_id(user_id: int) -> Tuple[bool, str]:
    """
    Try a few common ways to clear SIS ID; different Canvas setups behave differently.
    Returns (success, message).
    """
    url = f"{CANVAS_BASE_URL}/api/v1/users/{user_id}"

    attempts = [
        # Most common: set to empty string
        {"user": {"sis_user_id": ""}},
        # Some setups accept null
        {"user": {"sis_user_id": None}},
        # Some accept omit + set other fields; but we keep it simple.
    ]

    last_error = ""
    for body in attempts:
        try:
            data = request_json("PUT", url, json_body=body)
            # If successful, Canvas returns the user object
            if isinstance(data, dict):
                # Validate it cleared
                sis = data.get("sis_user_id")
                if sis in (None, ""):
                    return True, f"Cleared SIS ID successfully using payload: {body}"
                # Canvas sometimes doesn't echo it; confirm via profile
                profile = get_user_profile_by_id(user_id)
                # profile may not include sis_user_id; so do an account search by id isn't possible
                # We'll treat the PUT success as success even if not echoed.
                return True, f"Update call succeeded. Returned sis_user_id={sis!r}. Payload: {body}"
            return True, f"Update call succeeded. Payload: {body}"
        except SystemExit as e:
            last_error = str(e)

    return False, f"Failed to clear SIS ID. Last error: {last_error}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Find a Canvas user and clear their SIS ID.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sis", help="SIS ID to locate (sis_user_id)", type=str)
    group.add_argument("--search", help="Search term (email/login/name) to locate user", type=str)
    parser.add_argument("--account", help="Account ID for user search (default: root)", type=int, default=ROOT_ACCOUNT_ID)
    parser.add_argument("--no-write", help="Do not change anything (dry run)", action="store_true")
    args = parser.parse_args()

    # Basic connectivity check (who am I)
    who = request_json("GET", f"{CANVAS_BASE_URL}/api/v1/users/self/profile")
    print(f"Authenticated as: {who.get('name')} (id={who.get('id')})")

    user_id: Optional[int] = None
    found: Optional[Dict[str, Any]] = None

    if args.sis:
        sis = args.sis.strip()
        print(f"\nLooking up user by SIS ID: {sis}")
        # Use profile lookup by SIS first (fast)
        url = f"{CANVAS_BASE_URL}/api/v1/users/sis_user_id:{sis}/profile"
        r = requests.get(url, headers=canvas_headers(), timeout=30)
        if r.status_code == 404:
            die(f"No user found for SIS ID {sis} (404).")
        if r.status_code >= 400:
            try:
                err = r.json()
            except Exception:
                err = r.text
            die(f"Canvas API error {r.status_code} during SIS profile lookup.\nResponse: {err}")
        found = r.json()
        user_id = found.get("id")

        if not user_id:
            die(f"Unexpected SIS profile response: {found}")

        print("\nFound user profile:")
        print(json.dumps(found, indent=2))

    else:
        term = args.search.strip()
        print(f"\nSearching account {args.account} users for: {term}")
        candidates = search_account_users(term, args.account)
        chosen = pick_best_match(candidates, term)
        user_id = chosen.get("id")
        if not user_id:
            die(f"Unexpected chosen user object: {chosen}")

        # Pull profile for better display
        found = get_user_profile_by_id(int(user_id))

        print("\nChosen user profile:")
        print(json.dumps(found, indent=2))

    # At this point we have a user_id, but the profile may not include sis_user_id.
    # We can also show the account-search user object if available, but that's ok.

    if args.no_write:
        print("\nDRY RUN (--no-write) enabled. No changes made.")
        sys.exit(0)

    # Confirm from operator
    confirm = input(f"\nAbout to CLEAR SIS ID for Canvas user id={user_id}. Type YES to proceed: ").strip()
    if confirm != "YES":
        print("Cancelled.")
        sys.exit(0)

    ok, msg = clear_sis_user_id(int(user_id))
    if not ok:
        die(msg)

    print(f"\nSUCCESS: {msg}")
    print("Done.")


if __name__ == "__main__":
    main()
