#!/usr/bin/env python3
"""
List Canvas subaccounts that do NOT have an SIS ID (sis_account_id missing/blank).

Hard-coded domain: https://grayson.instructure.com
Token is hard-coded (paste yours into TOKEN).
Root account defaults to 1 (change ROOT_ACCOUNT_ID if needed).
"""

import sys
import time
import requests

# ====== HARD-CODE THESE ======
CANVAS_DOMAIN = "paste domain here"
TOKEN = "paste token here"  # <-- paste token
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


def iter_all_subaccounts(root_account_id: int):
    """
    Fetch all subaccounts under root (recursive).
    """
    url = f"{CANVAS_DOMAIN}/api/v1/accounts/{root_account_id}/sub_accounts"
    params = {"recursive": 1, "per_page": 100}

    while url:
        resp = canvas_request("GET", url, params=params)
        params = None

        if not resp.ok:
            print(f"ERROR fetching subaccounts: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)

        for acct in resp.json():
            yield acct

        url = get_next_link(resp)


def has_missing_sis_id(acct: dict) -> bool:
    """
    Canvas returns sis_account_id as null or a string.
    Treat null, empty string, or whitespace-only as missing.
    """
    sis = acct.get("sis_account_id")
    if sis is None:
        return True
    if isinstance(sis, str) and sis.strip() == "":
        return True
    return False


def main():
    print(f"Canvas: {CANVAS_DOMAIN}")
    print(f"Root account ID: {ROOT_ACCOUNT_ID}")
    print("-" * 100)
    print("Subaccounts missing SIS ID (sis_account_id is null/blank):")
    print("-" * 100)
    print("account_id\tparent_account_id\tsis_account_id\tname")

    count = 0
    for acct in iter_all_subaccounts(ROOT_ACCOUNT_ID):
        if has_missing_sis_id(acct):
            acct_id = acct.get("id")
            parent_id = acct.get("parent_account_id")
            name = (acct.get("name") or "").replace("\t", " ").strip()
            sis = acct.get("sis_account_id")
            sis_disp = "" if sis is None else str(sis).strip()
            print(f"{acct_id}\t{parent_id}\t{sis_disp}\t{name}")
            count += 1

    print("-" * 100)
    print(f"Total subaccounts missing SIS ID: {count}")


if __name__ == "__main__":

    main()
