#!/usr/bin/env python3
"""
Canvas: Export admins sorted by subaccount (account + all subaccounts).

Outputs a CSV with one row per (subaccount, admin).

Requires: requests
    pip install requests
"""

from __future__ import annotations

import csv
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

import requests


# =========================
# CONFIG (EDIT THESE)
# =========================
CANVAS_BASE_URL = "paste domain here"  # e.g. https://yourcollege.instructure.com
ACCESS_TOKEN = "paste token here"
ROOT_ACCOUNT_ID = 1  # change if your root account id is not 1
OUTPUT_CSV = "canvas_admins_by_subaccount.csv"

# If you hit rate limits, increase this slightly (Canvas is usually fine without it, but safe to keep tiny sleep)
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
    """
    Parses Canvas-style Link headers.
    Returns dict of rel -> url (e.g. {"next": "...", "current": "..."}).
    """
    if not link_header:
        return {}

    links: Dict[str, str] = {}
    parts = [p.strip() for p in link_header.split(",")]
    for part in parts:
        # <url>; rel="next"
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
    """
    Generator yielding items across Canvas paginated endpoints.
    """
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
            # Some endpoints return dicts; yield as single
            yield data

        links = _parse_link_header(resp.headers.get("Link"))
        next_url = links.get("next")
        params = None  # only apply params to first request

        if REQUEST_SLEEP_SECONDS:
            time.sleep(REQUEST_SLEEP_SECONDS)


# =========================
# CANVAS API CALLS
# =========================
def get_all_accounts(root_account_id: int) -> List[dict]:
    """
    Returns list including the root account entry plus all subaccounts (recursive).
    """
    # Root account details
    root_url = f"{CANVAS_BASE_URL}/api/v1/accounts/{root_account_id}"
    root = next(canvas_get_paginated(root_url))

    # Subaccounts recursive
    subs_url = f"{CANVAS_BASE_URL}/api/v1/accounts/{root_account_id}/sub_accounts"
    subs = list(canvas_get_paginated(subs_url, params={"recursive": "true", "per_page": 100}))

    return [root] + subs


def get_admins_for_account(account_id: int) -> List[dict]:
    """
    Account admins for a given account/subaccount.
    """
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{account_id}/admins"
    return list(canvas_get_paginated(url, params={"per_page": 100}))


# =========================
# MAIN
# =========================
def main() -> int:
    if "PASTE_YOUR_TOKEN_HERE" in ACCESS_TOKEN or not ACCESS_TOKEN.strip():
        print("ERROR: Please set ACCESS_TOKEN at the top of the script.")
        return 2

    print(f"Fetching accounts (root={ROOT_ACCOUNT_ID}) ...")
    accounts = get_all_accounts(ROOT_ACCOUNT_ID)

    # Map account_id -> readable name
    acct_name: Dict[int, str] = {}
    acct_parent: Dict[int, Optional[int]] = {}

    for a in accounts:
        acct_name[int(a["id"])] = a.get("name") or f'Account {a["id"]}'
        acct_parent[int(a["id"])] = a.get("parent_account_id")

    # Build "path" like Root / Child / Grandchild (best-effort)
    def build_path(account_id: int) -> str:
        seen = set()
        parts = []
        cur = account_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            parts.append(acct_name.get(cur, str(cur)))
            cur = acct_parent.get(cur)
        return " / ".join(reversed(parts))

    rows: List[Dict[str, str]] = []

    print(f"Fetching admins for {len(accounts)} accounts/subaccounts ...")
    for idx, a in enumerate(accounts, start=1):
        aid = int(a["id"])
        aname = acct_name[aid]
        apath = build_path(aid)

        try:
            admins = get_admins_for_account(aid)
        except Exception as e:
            print(f"WARNING: failed to fetch admins for account {aid} ({aname}): {e}", file=sys.stderr)
            continue

        for adm in admins:
            user = adm.get("user") or {}
            rows.append(
                {
                    "subaccount_id": str(aid),
                    "subaccount_name": aname,
                    "subaccount_path": apath,
                    "admin_user_id": str(user.get("id", "")),
                    "admin_name": user.get("name", "") or "",
                    "admin_login_id": user.get("login_id", "") or "",
                    "admin_role": adm.get("role", "") or "",
                    "admin_role_id": str(adm.get("role_id", "")),
                    "workflow_state": adm.get("workflow_state", "") or "",
                }
            )

        if idx % 25 == 0:
            print(f"  processed {idx}/{len(accounts)} ...")

    # Sort by subaccount path then admin name then role
    rows.sort(key=lambda r: (r["subaccount_path"].lower(), r["admin_name"].lower(), r["admin_role"].lower()))

    # Write CSV
    fieldnames = [
        "subaccount_path",
        "subaccount_id",
        "subaccount_name",
        "admin_name",
        "admin_login_id",
        "admin_user_id",
        "admin_role",
        "admin_role_id",
        "workflow_state",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\nDone. Wrote {len(rows)} rows to: {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":

    raise SystemExit(main())
