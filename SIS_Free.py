#!/usr/bin/env python3
import argparse
import json
import sys
import requests
from typing import Any, Dict, List, Optional, Tuple

CANVAS_BASE_URL = "paste in domain"
CANVAS_TOKEN = "paste token here"
ROOT_ACCOUNT_ID = 1
TIMEOUT = 30


def die(msg: str, code: int = 1) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def headers() -> Dict[str, str]:
    if not CANVAS_TOKEN or "PASTE_YOUR_CANVAS_TOKEN_HERE" in CANVAS_TOKEN:
        die("Paste your real Canvas token into CANVAS_TOKEN first.")
    return {"Authorization": f"Bearer {CANVAS_TOKEN}", "Accept": "application/json"}


def req(method: str, url: str, *, params=None, json_body=None) -> Tuple[int, Any, Dict[str, str]]:
    try:
        r = requests.request(method, url, headers=headers(), params=params, json=json_body, timeout=TIMEOUT)
    except requests.RequestException as e:
        die(f"Network error: {e}")
    try:
        data = r.json() if r.text.strip() else None
    except Exception:
        data = r.text
    return r.status_code, data, dict(r.headers)


def paginate(url: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
    out: List[Any] = []
    next_url = url
    next_params = params

    while next_url:
        status, data, hdrs = req("GET", next_url, params=next_params)
        if status >= 400:
            die(f"Canvas API error {status} for {next_url}\nResponse: {data}")
        if not isinstance(data, list):
            die(f"Unexpected list response for {next_url}: {data}")
        out.extend(data)

        link = hdrs.get("Link", "")
        next_link = None
        if link:
            for part in [p.strip() for p in link.split(",")]:
                if 'rel="next"' in part:
                    lt, gt = part.find("<"), part.find(">")
                    if lt != -1 and gt != -1 and gt > lt:
                        next_link = part[lt + 1 : gt]
                    break
        next_url = next_link
        next_params = None

    return out


def whoami() -> Dict[str, Any]:
    url = f"{CANVAS_BASE_URL}/api/v1/users/self/profile"
    s, d, _ = req("GET", url)
    if s >= 400 or not isinstance(d, dict):
        die(f"Auth check failed ({s}): {d}")
    return d


def list_accounts() -> List[Dict[str, Any]]:
    return paginate(f"{CANVAS_BASE_URL}/api/v1/accounts", params={"per_page": 100})


def get_user(user_id: int) -> Dict[str, Any]:
    s, d, _ = req("GET", f"{CANVAS_BASE_URL}/api/v1/users/{user_id}", params={"include[]": ["email"]})
    if s >= 400 or not isinstance(d, dict):
        die(f"Could not read user {user_id}: {d}")
    return d


def update_user_sis(user_id: int, sis: Optional[str]) -> None:
    s, d, _ = req("PUT", f"{CANVAS_BASE_URL}/api/v1/users/{user_id}", json_body={"user": {"sis_user_id": sis}})
    if s >= 400:
        die(f"Failed to update user {user_id} sis_user_id -> {sis!r}\nResponse: {d}")


def direct_profile_by_sis(sis: str) -> Optional[Dict[str, Any]]:
    # This is the most authoritative test.
    url = f"{CANVAS_BASE_URL}/api/v1/users/sis_user_id:{sis}/profile"
    s, d, _ = req("GET", url)
    if s == 404:
        return None
    if s >= 400:
        # Permission issues show up here as 401/403
        die(f"Direct SIS profile lookup failed ({s}): {d}")
    if isinstance(d, dict) and d.get("id"):
        return d
    return None


def search_users_in_account(account_id: int, term: str) -> List[Dict[str, Any]]:
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{account_id}/users"
    return paginate(url, params={"search_term": term, "per_page": 100})


def search_logins_in_account(account_id: int, term: str) -> List[Dict[str, Any]]:
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{account_id}/logins"
    s, d, _ = req("GET", url, params={"search_term": term, "per_page": 100})
    if s == 404:
        return []
    if s >= 400 or not isinstance(d, list):
        return []
    return d


def sis_in_login_obj(login_obj: Dict[str, Any], sis: str) -> bool:
    # Only treat as match if sis appears in SIS fields
    for k in ("sis_user_id", "sis_login_id"):
        v = login_obj.get(k)
        if v is not None and str(v).strip() == sis:
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sis", required=True)
    ap.add_argument("--target-user-id", required=True, type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-free", action="store_true")
    ap.add_argument("--free-mode", choices=["clear", "archive"], default="archive")
    args = ap.parse_args()

    sis = args.sis.strip()
    target_id = int(args.target_user_id)

    me = whoami()
    print(f"Authenticated as: {me.get('name')} (id={me.get('id')})")
    print(f"Canvas: {CANVAS_BASE_URL}")
    print(f"Target Canvas user_id: {target_id}")
    print(f"Desired SIS: {sis}")

    target = get_user(target_id)
    print("\nTarget user record:")
    print(json.dumps(
        {
            "id": target.get("id"),
            "name": target.get("name"),
            "login_id": target.get("login_id"),
            "email": target.get("email"),
            "sis_user_id": target.get("sis_user_id"),
            "workflow_state": target.get("workflow_state"),
        },
        indent=2,
    ))

    # 1) Direct check: does Canvas know a user by this SIS?
    print("\nDirect lookup by SIS profile endpoint...")
    direct = direct_profile_by_sis(sis)
    if direct:
        holder_user_id = int(direct["id"])
        print(f"FOUND via direct SIS lookup: user_id={holder_user_id}")
        print(json.dumps(direct, indent=2))
    else:
        holder_user_id = None
        print("No user returned by direct SIS lookup (404).")

    # 2) Broader search across accessible accounts
    print("\nSearching accounts for SIS usage (users + logins)...")
    accounts = list_accounts()
    user_hits: List[Dict[str, Any]] = []
    login_hits: List[Dict[str, Any]] = []

    # search terms that sometimes help Canvas search:
    terms = [sis, f"sis_user_id:{sis}"]

    for acct in accounts:
        acct_id = int(acct["id"])
        for term in terms:
            # users
            users = search_users_in_account(acct_id, term)
            for u in users:
                if str(u.get("sis_user_id") or "").strip() == sis:
                    u["_found_in_account_id"] = acct_id
                    user_hits.append(u)

            # logins
            logins = search_logins_in_account(acct_id, sis)
            for l in logins:
                if sis_in_login_obj(l, sis):
                    l["_found_in_account_id"] = acct_id
                    login_hits.append(l)

    # de-dupe
    seen_u = {int(u["id"]): u for u in user_hits if u.get("id")}
    user_hits = list(seen_u.values())
    seen_l = {int(l["id"]): l for l in login_hits if l.get("id")}
    login_hits = list(seen_l.values())

    print("\n=== RESULTS ===")
    if user_hits:
        print("User records holding SIS:")
        for u in user_hits:
            print(
                f"- user_id={u.get('id')} name={u.get('name')} login_id={u.get('login_id')} "
                f"sis_user_id={u.get('sis_user_id')} (account={u.get('_found_in_account_id')})"
            )
    if login_hits:
        print("Login records holding SIS:")
        for l in login_hits:
            print(
                f"- login_id={l.get('id')} user_id={l.get('user_id')} unique_id={l.get('unique_id')} "
                f"sis_user_id={l.get('sis_user_id')} sis_login_id={l.get('sis_login_id')} (account={l.get('_found_in_account_id')})"
            )

    # Prefer holder from direct lookup; otherwise from user_hits; otherwise login_hits only
    if holder_user_id is None and user_hits:
        holder_user_id = int(user_hits[0]["id"])

    if args.dry_run:
        print("\nDRY RUN enabled. No changes made.")
        return

    if holder_user_id is None and not login_hits:
        die(
            "Canvas reports the SIS is in use, but it was not found via direct SIS lookup nor via account searches.\n"
            "That strongly indicates the SIS is held in a scope your token cannot see (different root account / insufficient permissions),\n"
            "or it is held on a login in a way this instance doesn't expose via API.\n"
            "Next step: locate it via Provisioning Report (users.csv + logins.csv) across the whole instance or ask Canvas Support to lookup SIS=1011102374."
        )

    # If held by another user record, free it
    if holder_user_id is not None and holder_user_id != target_id:
        print(f"\nSIS is held by user_id={holder_user_id}.")
        if not args.force_free:
            resp = input("Type FREE to free it from the current holder, or anything else to abort: ").strip().upper()
            if resp != "FREE":
                die("Aborted.")
        if args.free_mode == "clear":
            update_user_sis(holder_user_id, None)
        else:
            update_user_sis(holder_user_id, f"OLD_{sis}_MOVED_TO_{target_id}")
        print("Freed SIS from holder user record.")

    # If held only at login level, warn and stop (safer)
    if holder_user_id is None and login_hits:
        die(
            "SIS appears to be held only on a LOGIN record (sis_login_id/sis_user_id on login).\n"
            "Your instance may not allow freeing that via API with your current permissions.\n"
            "Fix: update via SIS import (logins.csv) to change that login's SIS field, then assign to target."
        )

    # Assign to target
    print(f"\nAssigning SIS {sis} to target user_id={target_id}...")
    update_user_sis(target_id, sis)

    # Verify
    target2 = get_user(target_id)
    print("\nTarget user AFTER:")
    print(json.dumps(
        {
            "id": target2.get("id"),
            "name": target2.get("name"),
            "login_id": target2.get("login_id"),
            "email": target2.get("email"),
            "sis_user_id": target2.get("sis_user_id"),
            "workflow_state": target2.get("workflow_state"),
        },
        indent=2,
    ))

    if str(target2.get("sis_user_id") or "").strip() != sis:
        die("Assignment did not stick. SIS may still be held elsewhere or permissions blocked the update.")
    print("\nDONE.")


if __name__ == "__main__":
    main()

