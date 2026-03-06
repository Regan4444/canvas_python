#!/usr/bin/env python3
"""
Canvas: Find subaccounts with NO admins

- Pulls root account + all subaccounts (recursive)
- For each subaccount, calls /api/v1/accounts/{account_id}/admins
- Flags accounts where admins list is empty
- Writes CSV: subaccount_id, subaccount_name, subaccount_path, parent_account_id

Requires: requests
    pip install requests
"""

from __future__ import annotations

import csv
import sys
import time
from typing import Dict, Iterable, List, Optional

import requests


# =========================
# CONFIG (EDIT THESE)
# =========================
CANVAS_BASE_URL = "https://grayson.instructure.com"
ACCESS_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
ROOT_ACCOUNT_ID = 1  # change if your root account id is not 1
OUTPUT_CSV = "canvas_subaccounts_with_no_admins.csv"

# If you hit rate limits, increase slightly
REQUEST_SLEEP_SECONDS = 0.05


# =========================
# HTTP HELPERS
# =========================
def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {ACCESS_TOKEN}"}


def _raise_for_status(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        msg = f"HTTP {resp.status_code} for {resp.request.method} {resp.url}\nResponse:\n{resp.text[:2000]}"
        raise requests.HTTPError(msg) from e


def _parse_link_header(link_header: Optional[str]) -> Dict[str, str]:
    if not link_header:
        return {}
    links: Dict[str, str] = {}
    parts = [p.strip() for p in link_header.split(",")]
    for part in parts:
        if ";" not in part:
            continue
        url_part, *params = [x.strip() for x in part.split(";")]
        if not (url_part.startswith("<") and url_part.endswith(">")):
            continue
        url = url_part[1:-1]
        rel = None
        for param in params:
            if param.startswith("rel="):
                rel = param.split("=", 1)[1].strip().strip('"')
                break
        if rel:
            links[rel] = url
    return links


def canvas_get_paginated(url: str, params: Optional[Dict] = None) -> Iterable[dict]:
    session = requests.Session()
    session.headers.update(_headers())

    next_url = url
    while next_url:
        resp = session.get(next_url, params=params)
        _raise_for_status(resp)

        data = resp.json()
        if isinstance(data, list):
            for item in data:
                yield item
        else:
            yield data

        links = _parse_link_header(resp.headers.get("Link"))
        next_url = links.get("next")
        params = None  # only apply params to first request

        if REQUEST_SLEEP_SECONDS:
            time.sleep(REQUEST_SLEEP_SECONDS)


# =========================
# CANVAS API CALLS
# =========================
def get_root_account(root_account_id: int) -> dict:
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{root_account_id}"
    return next(canvas_get_paginated(url))


def get_all_subaccounts(root_account_id: int) -> List[dict]:
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{root_account_id}/sub_accounts"
    return list(canvas_get_paginated(url, params={"recursive": "true", "per_page": 100}))


def get_admins_for_account(account_id: int) -> List[dict]:
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{account_id}/admins"
    return list(canvas_get_paginated(url, params={"per_page": 100}))


# =========================
# MAIN
# =========================
def main() -> int:
    if "PASTE_YOUR_TOKEN_HERE" in ACCESS_TOKEN or not ACCESS_TOKEN.strip():
        print("ERROR: Please set ACCESS_TOKEN at the top of the script.")
        return 2

    root = get_root_account(ROOT_ACCOUNT_ID)
    subs = get_all_subaccounts(ROOT_ACCOUNT_ID)

    # Only "subaccounts" requested (exclude root). If you want to include root, add root to the list.
    accounts = subs

    # Name + parent maps to build a readable path
    acct_name: Dict[int, str] = {int(root["id"]): root.get("name") or f'Account {root["id"]}'}
    acct_parent: Dict[int, Optional[int]] = {int(root["id"]): root.get("parent_account_id")}

    for a in subs:
        aid = int(a["id"])
        acct_name[aid] = a.get("name") or f"Account {aid}"
        acct_parent[aid] = a.get("parent_account_id")

    def build_path(account_id: int) -> str:
        seen = set()
        parts = []
        cur: Optional[int] = account_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            parts.append(acct_name.get(cur, str(cur)))
            cur = acct_parent.get(cur)
        return " / ".join(reversed(parts))

    no_admin_rows: List[Dict[str, str]] = []

    print(f"Checking admins for {len(accounts)} subaccounts ...")
    for idx, a in enumerate(accounts, start=1):
        aid = int(a["id"])
        aname = acct_name[aid]
        parent_id = acct_parent.get(aid)

        try:
            admins = get_admins_for_account(aid)
        except Exception as e:
            # If you prefer, you can treat errors as "no admin" or log separately.
            print(f"WARNING: failed to fetch admins for subaccount {aid} ({aname}): {e}", file=sys.stderr)
            continue

        if len(admins) == 0:
            no_admin_rows.append(
                {
                    "subaccount_path": build_path(aid),
                    "subaccount_id": str(aid),
                    "subaccount_name": aname,
                    "parent_account_id": str(parent_id) if parent_id is not None else "",
                }
            )

        if idx % 50 == 0:
            print(f"  processed {idx}/{len(accounts)} ...")

    # Sort by path
    no_admin_rows.sort(key=lambda r: r["subaccount_path"].lower())

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["subaccount_path", "subaccount_id", "subaccount_name", "parent_account_id"],
        )
        w.writeheader()
        w.writerows(no_admin_rows)

    print(f"\nDone. Found {len(no_admin_rows)} subaccounts with NO admins.")
    print(f"Wrote: {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())