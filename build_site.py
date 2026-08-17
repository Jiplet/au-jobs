#!/usr/bin/env python3
"""
build_site.py - merge occupations.csv and scores.json into the one JSON file the site loads.

What it does:
    Reads data/occupations.csv (from parse.py) and data/scores.json (from score.py) and
    writes a single compact JSON file the browser fetches at runtime: one array of
    occupation objects, plus a small metadata block (release dates, generated timestamp,
    counts). Numbers are rounded for a smaller file; nulls stay null rather than being
    turned into 0 or "" (the site's job is to show "not available", not to lie).

Inputs:
    data/occupations.csv, data/scores.json.

Outputs:
    docs/data.json - loaded by docs/app.js. Served relative to docs/index.html, so this
    works unmodified on GitHub Pages (Settings -> Pages -> deploy from branch main /docs).

How to run it:
    uv run python build_site.py
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CSV_PATH = REPO_ROOT / "data" / "occupations.csv"
SCORES_PATH = REPO_ROOT / "data" / "scores.json"
OUT_PATH = REPO_ROOT / "docs" / "data.json"


def num_or_none(value: str):
    if value is None or value == "":
        return None
    return float(value) if "." in value or "e" in value.lower() else int(value)


def build() -> dict:
    scores = {}
    if SCORES_PATH.exists():
        scores = json.loads(SCORES_PATH.read_text(encoding="utf-8"))

    occupations = []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = row["anzsco_code"]
            score_entry = scores.get(code)
            occupations.append({
                "code": int(code),
                "title": row["title"],
                "major_group_code": int(row["major_group_code"]) if row["major_group_code"] else None,
                "major_group": row["major_group"] or None,
                "employment_thousands": num_or_none(row["employment_thousands"]),
                "avg_weekly_earnings": num_or_none(row["avg_weekly_earnings"]),
                "growth_5y_pct": num_or_none(row["growth_5y_pct"]),
                "growth_10y_pct": num_or_none(row["growth_10y_pct"]),
                "shortage_rating": row["shortage_rating"] or None,
                "ai_exposure_score": score_entry["score"] if score_entry else None,
                "ai_exposure_rationale": score_entry["rationale"] if score_entry else None,
            })

    occupations.sort(key=lambda o: o["code"])

    scored_count = sum(1 for o in occupations if o["ai_exposure_score"] is not None)
    meta = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "occupation_count": len(occupations),
        "ai_exposure_scored_count": scored_count,
        "layers": {
            "employment": sum(1 for o in occupations if o["employment_thousands"] is not None),
            "earnings": sum(1 for o in occupations if o["avg_weekly_earnings"] is not None),
            "growth": sum(1 for o in occupations if o["growth_5y_pct"] is not None),
            "shortage": sum(1 for o in occupations if o["shortage_rating"] is not None),
            "ai_exposure": scored_count,
        },
    }

    return {"meta": meta, "occupations": occupations}


def main() -> None:
    payload = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}: {payload['meta']['occupation_count']} occupations, "
          f"{payload['meta']['ai_exposure_scored_count']} scored, {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
