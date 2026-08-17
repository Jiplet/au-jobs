#!/usr/bin/env python3
"""
fetch.py - download the raw source files this project parses.

What it does:
    Reads sources.yaml (every external URL, with its release date and licence) and
    downloads each file into data/raw/<key>.xlsx. Skips a file if it is already on disk
    with a non-zero size, so reruns are cheap and safe. Government sites occasionally
    block requests without a normal browser User-Agent header, so this script sends one.

Inputs:
    sources.yaml in the repo root.

Outputs:
    data/raw/*.xlsx (gitignored, never committed). Prints one line per file: what it
    fetched, its size, and whether it was skipped because it already existed.

How to run it:
    uv run python fetch.py
    uv run python fetch.py --force        # re-download even if the file already exists
    uv run python fetch.py --only abs_eq08  # fetch a single source by its sources.yaml key
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent
SOURCES_FILE = REPO_ROOT / "sources.yaml"
RAW_DIR = REPO_ROOT / "data" / "raw"

# A normal desktop browser User-Agent. Both abs.gov.au and jobsandskills.gov.au have
# returned non-200 responses or empty bodies to requests with no User-Agent or an
# obviously scripted one (the default "python-requests/x.y" string), so this is not
# optional.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5


def load_sources() -> dict:
    with open(SOURCES_FILE, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def download(key: str, entry: dict, force: bool) -> None:
    dest = RAW_DIR / f"{key}.xlsx"
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"skip  {key:28s} already at {dest.relative_to(REPO_ROOT)} "
              f"({dest.stat().st_size:,} bytes)")
        return

    url = entry["url"]
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.content)
            print(f"fetch {key:28s} {len(response.content):>10,} bytes  -> "
                  f"{dest.relative_to(REPO_ROOT)}")
            return
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                print(f"retry {key:28s} attempt {attempt} failed ({exc}), "
                      f"waiting {RETRY_BACKOFF_SECONDS}s", file=sys.stderr)
                time.sleep(RETRY_BACKOFF_SECONDS)

    print(f"FAIL  {key:28s} {last_error}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if the file exists")
    parser.add_argument("--only", help="fetch a single source by its sources.yaml key")
    args = parser.parse_args()

    sources = load_sources()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    keys = [args.only] if args.only else list(sources.keys())
    unknown = [k for k in keys if k not in sources]
    if unknown:
        print(f"unknown source key(s): {unknown}. Known keys: {list(sources.keys())}", file=sys.stderr)
        sys.exit(1)

    for key in keys:
        download(key, sources[key], args.force)


if __name__ == "__main__":
    main()
