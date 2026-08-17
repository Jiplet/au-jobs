#!/usr/bin/env python3
"""
make_prompt.py - bundle the whole dataset into one file you can paste into any LLM.

What it does:
    Reads docs/data.json (from build_site.py) and writes prompt.md: a short explanation of
    what the dataset is, summary stats, then every occupation as one line (code, title,
    major group, employment, earnings, growth, shortage, AI exposure score and rationale).
    The idea is you can drop this into a chat with any model and ask it questions about the
    Australian labour market grounded in real numbers, without running any code.

Inputs:
    docs/data.json (from build_site.py).

Outputs:
    prompt.md, at the repo root. Prints a rough token estimate (chars / 4) when done.

How to run it:
    uv run python make_prompt.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DATA_PATH = REPO_ROOT / "docs" / "data.json"
OUT_PATH = REPO_ROOT / "prompt.md"


def fmt(value, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value}{suffix}"


def build_prompt(payload: dict) -> str:
    meta = payload["meta"]
    occupations = payload["occupations"]

    lines = [
        "# The Australian labour market, one row per occupation",
        "",
        "This file is a bundle of the au-jobs dataset: every ANZSCO 4-digit occupation "
        "unit group in Australia, with employment, average earnings, projected growth, "
        "skills shortage rating, and an LLM-scored 'digital AI exposure' score (0 to 10, "
        "how much current AI is likely to reshape the day-to-day tasks of that occupation - "
        "NOT a job-loss forecast; see the note below). Built from public ABS and Jobs and "
        "Skills Australia data. Repo: https://github.com/Jiplet/au-jobs",
        "",
        "## What AI exposure is NOT",
        "",
        "It does not predict job loss or headcount change. It does not model demand "
        "elasticity, regulation, licensing, or people's preference for dealing with a human. "
        "A high score (e.g. software developers) can coexist with growing demand for that "
        "role: the score is about how much of the day-to-day work overlaps with what "
        "current AI tools do well, nothing else. Scores are rough model estimates from a "
        "title, major group, and (mostly) inferred typical tasks, not a validated survey.",
        "",
        "## Summary",
        "",
        f"- Occupations: {meta['occupation_count']}",
        f"- Employment data available: {meta['layers']['employment']}",
        f"- Earnings data available: {meta['layers']['earnings']}",
        f"- Growth projection data available: {meta['layers']['growth']}",
        f"- Skills shortage rating available: {meta['layers']['shortage']}",
        f"- AI exposure scored: {meta['layers']['ai_exposure']}",
        f"- Generated: {meta['generated_at']}",
        "",
        "## Data",
        "",
        "One line per occupation: code | title | major group | employment (thousands) | "
        "avg weekly earnings (AUD, mean not median) | 5yr growth % | 10yr growth % | "
        "shortage rating | AI exposure score (0-10) | AI exposure rationale",
        "",
    ]

    for occ in occupations:
        lines.append(
            f"{occ['code']} | {occ['title']} | {occ['major_group'] or 'n/a'} | "
            f"{fmt(occ['employment_thousands'])} | {fmt(occ['avg_weekly_earnings'])} | "
            f"{fmt(occ['growth_5y_pct'], '%')} | {fmt(occ['growth_10y_pct'], '%')} | "
            f"{fmt(occ['shortage_rating'])} | {fmt(occ['ai_exposure_score'])} | "
            f"{occ['ai_exposure_rationale'] or 'n/a'}"
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    text = build_prompt(payload)
    OUT_PATH.write_text(text, encoding="utf-8")
    token_estimate = len(text) // 4
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}: {len(text):,} chars, "
          f"~{token_estimate:,} tokens (rough estimate, chars / 4)")


if __name__ == "__main__":
    main()
