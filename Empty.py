#!/usr/bin/env python3
"""
List Canvas subaccounts that are "truly empty" (compatible approach).

"Truly empty" definition:
- no courses in the account (GET /accounts/{id}/courses?per_page=1)
- no direct child subaccounts (GET /accounts/{id}/sub_accounts?per_page=1)
- no users in the account (GET /accounts/{id}/users?per_page=1)
- no admins in the account (GET /accounts/{id}/admins?per_page=1)
- no groups in the account (GET /accounts/{id}/groups?per_page=1)

Hard-coded domain: https://grayson.instructure.com
Token is hard-coded (paste yours into TOKEN).
Root account defaults to 1 (change ROOT_ACCOUNT_ID if needed).
"""

import time
import sys
import requests


# ====== HARD-CODE THESE ======
CANVAS_DOMAIN = "https://grayson.instructure.com"
TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"  # <-- paste token
ROOT_ACCOUNT_ID = 1  # <-- change if your root account is not 1
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
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    time.sleep(float(retry_after))
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

    parts = [p.strip() for p in link.split(",")]
    for part in parts:
        if 'rel="next"' in part:
            start = part.find("<") + 1
            end = part.find(">")
            if start > 0 and end > start:
                return part[start:end]
    return None


def iter_all_subaccounts(root_account_id: int):
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{root_account_id}/sub_accounts"
    params = {"recursive": 1, "per_page": 100}

    while url:
        resp = canvas_request("GET", url, params=params)
        params = None

        if not resp.ok:
            print(f"ERROR fetching subaccounts: {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)

        for acct in resp.json():
            yield acct

        url = get_next_link(resp)


def endpoint_has_any_items(url: str, params: dict, *, endpoint_name: str, allow_404_fallback: bool = False) -> tuple[bool, str | None]:
    """
    Returns (has_any, warning_message)
    - If allow_404_fallback=True and endpoint returns 404, we return (False, warning)
      so the script can proceed but you’ll be informed that a check was skipped.
    """
    resp = canvas_request("GET", url, params=params)

    if resp.status_code in (401, 403):
        raise RuntimeError(f"{endpoint_name} not permitted (HTTP {resp.status_code})")

    if resp.status_code == 404 and allow_404_fallback:
        return (False, f"Skipped check '{endpoint_name}' (endpoint returned 404)")

    if not resp.ok:
        # If HTML slipped through, resp.text will be HTML — include status only to avoid wall of text
        raise RuntimeError(f"{endpoint_name} failed (HTTP {resp.status_code})")

    data = resp.json()
    return (len(data) > 0, None)


def has_any_courses(account_id: int) -> tuple[bool, str | None]:
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{account_id}/courses"
    return endpoint_has_any_items(url, {"per_page": 1}, endpoint_name="courses")


def has_any_child_subaccounts(account_id: int) -> tuple[bool, str | None]:
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{account_id}/sub_accounts"
    return endpoint_has_any_items(url, {"per_page": 1}, endpoint_name="child subaccounts")


def has_any_users(account_id: int) -> tuple[bool, str | None]:
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{account_id}/users"
    # Some instances can be picky; if this 404s (unlikely), we can safely skip with a warning
    return endpoint_has_any_items(url, {"per_page": 1}, endpoint_name="users", allow_404_fallback=True)


def has_any_admins(account_id: int) -> tuple[bool, str | None]:
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{account_id}/admins"
    # If this 404s (older/odd setups), skip with warning
    return endpoint_has_any_items(url, {"per_page": 1}, endpoint_name="admins", allow_404_fallback=True)


def has_any_groups(account_id: int) -> tuple[bool, str | None]:
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{account_id}/groups"
    return endpoint_has_any_items(url, {"per_page": 1}, endpoint_name="groups", allow_404_fallback=True)


def main():
    print(f"Canvas: {CANVAS_DOMAIN}")
    print(f"Root account ID: {ROOT_ACCOUNT_ID}")
    print("-" * 120)

    checked = 0
    failed = 0
    truly_empty = []
    warnings_seen = set()

    for acct in iter_all_subaccounts(ROOT_ACCOUNT_ID):
        acct_id = acct.get("id")
        name = acct.get("name") or ""
        parent_id = acct.get("parent_account_id")

        if acct_id is None:
            continue

        checked += 1

        try:
            acct_id = int(acct_id)

            any_courses, w = has_any_courses(acct_id)
            if w: warnings_seen.add(w)
            if any_courses:
                continue

            any_children, w = has_any_child_subaccounts(acct_id)
            if w: warnings_seen.add(w)
            if any_children:
                continue

            any_users, w = has_any_users(acct_id)
            if w: warnings_seen.add(w)
            if any_users:
                continue

            any_admins, w = has_any_admins(acct_id)
            if w: warnings_seen.add(w)
            if any_admins:
                continue

            any_groups, w = has_any_groups(acct_id)
            if w: warnings_seen.add(w)
            if any_groups:
                continue

            truly_empty.append((acct_id, name, parent_id))

        except Exception as e:
            failed += 1
            print(f"FAILED: account {acct_id} ({name}) -> {e}", file=sys.stderr)

    print(f"Checked subaccounts: {checked} | failures: {failed}")
    print("-" * 120)

    if warnings_seen:
        print("Warnings (compatibility skips):")
        for w in sorted(warnings_seen):
            print(f"  - {w}")
        print("-" * 120)

    print("TRULY EMPTY subaccounts (no courses, no child subaccounts, no users, no admins, no groups):")
    print("-" * 120)

    for acct_id, name, parent_id in sorted(truly_empty, key=lambda x: (x[2] or 0, x[1].lower(), x[0])):
        print(f"{acct_id}\tparent={parent_id}\t{name}")

    print("-" * 120)
    print(f"Truly empty found: {len(truly_empty)}")

    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()