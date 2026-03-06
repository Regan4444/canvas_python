#!/usr/bin/env python3
import argparse
import sys
import requests
from typing import Any, Dict, List, Optional, Tuple

CANVAS_BASE_URL = "paste domain here"
CANVAS_TOKEN = "paste token here"
ROOT_ACCOUNT_ID = 1
TIMEOUT = 30


def die(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def headers() -> Dict[str, str]:
    if "PASTE_YOUR_CANVAS_TOKEN_HERE" in CANVAS_TOKEN:
        die("Paste your real token into CANVAS_TOKEN first.")
    return {"Authorization": f"Bearer {CANVAS_TOKEN}", "Accept": "application/json"}


def raw_request(method: str, url: str, params=None, json_body=None) -> requests.Response:
    return requests.request(method, url, headers=headers(), params=params, json=json_body, timeout=TIMEOUT)


def get_json(r: requests.Response) -> Any:
    try:
        return r.json() if r.text.strip() else None
    except Exception:
        return r.text


def get_next_link(link_header: str) -> Optional[str]:
    if not link_header:
        return None
    parts = [p.strip() for p in link_header.split(",")]
    for p in parts:
        if 'rel="next"' in p:
            lt, gt = p.find("<"), p.find(">")
            if lt != -1 and gt != -1 and gt > lt:
                return p[lt + 1 : gt]
    return None


def whoami() -> Dict[str, Any]:
    url = f"{CANVAS_BASE_URL}/api/v1/users/self/profile"
    r = raw_request("GET", url)
    if r.status_code >= 400:
        die(f"Auth failed: {r.status_code} {r.text}")
    d = get_json(r)
    if not isinstance(d, dict):
        die(f"Unexpected whoami: {d}")
    return d


def get_user(user_id: int) -> Dict[str, Any]:
    url = f"{CANVAS_BASE_URL}/api/v1/users/{user_id}"
    r = raw_request("GET", url, params={"include[]": ["email"]})
    if r.status_code >= 400:
        die(f"Cannot read user {user_id}: {r.status_code} {r.text}")
    d = get_json(r)
    if not isinstance(d, dict):
        die(f"Unexpected user response: {d}")
    return d


def update_user_sis(user_id: int, sis: Optional[str]) -> None:
    url = f"{CANVAS_BASE_URL}/api/v1/users/{user_id}"
    r = raw_request("PUT", url, json_body={"user": {"sis_user_id": sis}})
    if r.status_code >= 400:
        die(f"Cannot update user {user_id} sis_user_id={sis!r}: {r.status_code} {r.text}")


def try_direct_sis_lookup(sis: str) -> Optional[int]:
    url = f"{CANVAS_BASE_URL}/api/v1/users/sis_user_id:{sis}/profile"
    r = raw_request("GET", url)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        die(f"Direct SIS lookup failed: {r.status_code} {r.text}")
    d = get_json(r)
    if isinstance(d, dict) and d.get("id"):
        return int(d["id"])
    return None


def scan_logins_for_sis(sis: str) -> Optional[Dict[str, Any]]:
    """
    Walk every login in the root account and look for sis_user_id == sis.
    This bypasses weak search_term behavior.
    """
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ROOT_ACCOUNT_ID}/logins?per_page=100"
    scanned = 0

    while url:
        r = raw_request("GET", url)
        if r.status_code == 403:
            die("403 Forbidden listing logins. Your token cannot enumerate account logins via API.")
        if r.status_code >= 400:
            die(f"Error listing logins: {r.status_code} {r.text}")

        data = get_json(r)
        if not isinstance(data, list):
            die(f"Unexpected logins page: {data}")

        for login in data:
            scanned += 1
            if str(login.get("sis_user_id") or "").strip() == sis:
                print(f"\nFOUND SIS on LOGIN after scanning {scanned} logins:")
                return login

        url = get_next_link(r.headers.get("Link", ""))

    print(f"\nScanned {scanned} logins: SIS not found on login records.")
    return None


def scan_users_for_sis(sis: str) -> Optional[Dict[str, Any]]:
    """
    Walk all users in the account (this can be big). Only do if needed.
    """
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ROOT_ACCOUNT_ID}/users?per_page=100"
    scanned = 0

    while url:
        r = raw_request("GET", url)
        if r.status_code == 403:
            die("403 Forbidden listing users. Token cannot enumerate account users via API.")
        if r.status_code >= 400:
            die(f"Error listing users: {r.status_code} {r.text}")

        data = get_json(r)
        if not isinstance(data, list):
            die(f"Unexpected users page: {data}")

        for u in data:
            scanned += 1
            if str(u.get("sis_user_id") or "").strip() == sis:
                print(f"\nFOUND SIS on USER after scanning {scanned} users:")
                return u

        url = get_next_link(r.headers.get("Link", ""))

    print(f"\nScanned {scanned} users: SIS not found on user records.")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Find a ghost SIS and assign it to a target Canvas user.")
    ap.add_argument("--sis", required=True)
    ap.add_argument("--target-user-id", required=True, type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--free-mode", choices=["clear", "archive"], default="archive")
    args = ap.parse_args()

    sis = args.sis.strip()
    target_id = int(args.target_user_id)

    me = whoami()
    print(f"Authenticated as: {me.get('name')} (id={me.get('id')})")
    print(f"Target user_id={target_id}  desired SIS={sis}")

    target = get_user(target_id)
    print("\nTarget BEFORE:")
    print(target)

    # 1) direct lookup
    holder = try_direct_sis_lookup(sis)
    if holder:
        print(f"\nDirect SIS lookup says holder user_id={holder}")
    else:
        print("\nDirect SIS lookup: no user (404).")

    # 2) scan logins
    login_holder = scan_logins_for_sis(sis)

    # 3) scan users if needed
    user_holder = None
    if holder is None and login_holder is None:
        print("\nSIS not found via direct lookup or login scan. Scanning users (can be large)...")
        user_holder = scan_users_for_sis(sis)

    if args.dry_run:
        print("\nDRY RUN: no changes will be made.")
        return

    # If we found a holder user_id from direct lookup, free it
    if holder and holder != target_id:
        if args.free_mode == "clear":
            print(f"\nFreeing SIS from holder user_id={holder} by clearing...")
            update_user_sis(holder, None)
        else:
            archival = f"OLD_{sis}_MOVED_TO_{target_id}"
            print(f"\nFreeing SIS from holder user_id={holder} by archiving -> {archival}")
            update_user_sis(holder, archival)

    # If we found it on a user list object
    if user_holder and int(user_holder.get("id")) != target_id:
        holder_id = int(user_holder["id"])
        if args.free_mode == "clear":
            update_user_sis(holder_id, None)
        else:
            update_user_sis(holder_id, f"OLD_{sis}_MOVED_TO_{target_id}")

    # Assign to target
    print(f"\nAssigning SIS {sis} to target user_id={target_id} ...")
    update_user_sis(target_id, sis)

    target_after = get_user(target_id)
    print("\nTarget AFTER:")
    print(target_after)

    if str(target_after.get("sis_user_id") or "").strip() != sis:
        die("SIS did not stick. The SIS is still held somewhere not visible/editable via this token.")
    print("\nDONE.")


if __name__ == "__main__":
    main()

