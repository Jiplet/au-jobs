#!/usr/bin/env python3
"""
score.py - score every occupation for "digital AI exposure" using an LLM, in batches.

What it does:
    Reads data/occupations.csv, groups occupations into batches of BATCH_SIZE, and sends
    each batch to a model with the rubric in prompts/ai-exposure.md. The model returns a
    JSON array of {code, score, rationale}. Results are cached per occupation code in
    data/scores.json, so a rerun only scores occupations that are not already cached
    (resume behaviour: safe to Ctrl-C and rerun, safe to rerun after a failure).

Two backends:
    --backend anthropic   (default) calls the Claude API directly with
                           claude-haiku-4-5-20251001, tracked against a hard USD cap
                           computed from real input/output token usage
                           ($1.00 / $5.00 per million tokens - anthropic.com/claude/haiku,
                           anthropic.com/news/claude-haiku-4-5). Needs ANTHROPIC_API_KEY
                           in the environment (see .env.example) or in a local .env file.
    --backend claude-cli   shells out to the Claude Code CLI (`claude -p "<prompt>"
                           --model haiku --output-format text`) instead of the API. Useful
                           if you have Claude Code installed and a subscription but no
                           spare API credit: billing goes through the subscription, no
                           API key needed, no per-token cost tracked (there isn't one).
                           Runs with --setting-sources "" and cwd set to a neutral temp
                           directory, so it does not pick up the operator's own user,
                           project, or local CLAUDE.md - scoring should reflect the
                           rubric alone, not whatever else is configured on the machine
                           running it.

Inputs:
    data/occupations.csv (from parse.py).
    prompts/ai-exposure.md (the rubric - edit this file and rerun to score a different
    question entirely, no code changes needed).

Outputs:
    data/scores.json - {code: {score, rationale, model, scored_at}}, keyed by ANZSCO code
    as a string (JSON object keys are always strings). Updated incrementally as batches
    complete, so a crash partway through does not lose earlier batches.

How to run it:
    uv run python score.py --backend claude-cli          # no API key needed
    uv run python score.py --backend anthropic            # needs ANTHROPIC_API_KEY
    uv run python score.py --backend claude-cli --limit 40   # score only the first 40
    uv run python score.py --dry-run                      # print 2 assembled prompts, no calls
    uv run python score.py --backend claude-cli --max-minutes 15   # wall-clock safety cap
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CSV_PATH = REPO_ROOT / "data" / "occupations.csv"
SCORES_PATH = REPO_ROOT / "data" / "scores.json"
RUBRIC_PATH = REPO_ROOT / "prompts" / "ai-exposure.md"

BATCH_SIZE = 18
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
PRICE_INPUT_PER_MTOK = 1.00   # USD, claude-haiku-4-5-20251001, anthropic.com/claude/haiku
PRICE_OUTPUT_PER_MTOK = 5.00  # USD, same source, checked 2026-08
DEFAULT_USD_CAP = 2.00
CLI_TIMEOUT_SECONDS = 180
MAX_RETRIES_PER_BATCH = 1  # one retry on a parse failure, then the batch is skipped


@dataclass
class OccRow:
    code: int
    title: str
    major_group: str
    tasks_text: str


def display_path(path: Path) -> str:
    """Relative to the repo root when possible (nicer to read); the absolute path
    otherwise (e.g. in tests, where paths are monkeypatched to a tmp_path outside
    the repo)."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_occupations() -> list[OccRow]:
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        rows = []
        for r in csv.DictReader(fh):
            rows.append(OccRow(
                code=int(r["anzsco_code"]),
                title=r["title"],
                major_group=r["major_group"] or "",
                tasks_text=r["tasks_text"] or "",
            ))
    return rows


def load_cache() -> dict:
    if SCORES_PATH.exists():
        return json.loads(SCORES_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCORES_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def build_prompt(rubric: str, batch: list[OccRow]) -> str:
    lines = [rubric, "", "## Occupations to score in this batch", ""]
    for occ in batch:
        task_note = occ.tasks_text.strip() if occ.tasks_text.strip() else "(no task text available - infer briefly, then score)"
        lines.append(f"- code {occ.code}: \"{occ.title}\" (major group: {occ.major_group}). Tasks: {task_note}")
    lines.append("")
    lines.append(f"Respond with ONLY a JSON array of exactly {len(batch)} objects, one per "
                  f"occupation above, in the same order, each with keys code, score, rationale.")
    return "\n".join(lines)


def extract_json_array(text: str) -> list[dict]:
    """Model output sometimes comes wrapped in a ```json ... ``` fence, or with a stray
    sentence before/after despite instructions. Strip fences, then find the first
    '[' to the matching last ']' and parse that slice."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON array found in response: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def house_style(text: str) -> str:
    """Models (Haiku included) reach for an em dash a lot. House style bans it
    everywhere in this repo, including in LLM-generated rationale text that ends up
    in data/scores.json, docs/data.json, and prompt.md - so normalise it here, once,
    at the point every rationale is validated, rather than downstream in every
    consumer."""
    return text.replace("\u2014", " - ").replace("\u2013", "-")  # em dash, en dash


def validate_batch_result(parsed: list[dict], batch: list[OccRow]) -> dict[int, dict]:
    expected_codes = {occ.code for occ in batch}
    result: dict[int, dict] = {}
    for item in parsed:
        code = int(item["code"])
        score = int(item["score"])
        if not (0 <= score <= 10):
            raise ValueError(f"score out of range for code {code}: {score}")
        rationale = house_style(str(item.get("rationale", "")).strip())
        result[code] = {"score": score, "rationale": rationale}
    missing = expected_codes - set(result.keys())
    if missing:
        raise ValueError(f"missing codes in response: {sorted(missing)}")
    return result


# --- backend: claude-cli ----------------------------------------------------------------

def call_claude_cli(prompt: str) -> str:
    # --setting-sources "" stops the CLI loading the operator's own user/project/local
    # CLAUDE.md files - without it, whatever personal or workspace context the person
    # running this happens to have configured can bleed into the scoring prompt and
    # skew results. Running from a neutral temp directory (not the repo) is the same
    # idea belt-and-braces: no project-local settings or CLAUDE.md to pick up either.
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", "haiku", "--output-format", "text",
         "--setting-sources", ""],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_SECONDS,
        cwd=tempfile.gettempdir(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr[:500]}")
    return result.stdout


# --- backend: anthropic API --------------------------------------------------------------

def call_anthropic_api(client, prompt: str) -> tuple[str, int, int]:
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    return text, response.usage.input_tokens, response.usage.output_tokens


# --- main scoring loop --------------------------------------------------------------------

def score_all(backend: str, limit: int | None, usd_cap: float, max_minutes: float | None,
              dry_run: bool, client=None) -> None:
    occupations = load_occupations()
    rubric = RUBRIC_PATH.read_text(encoding="utf-8")
    cache = load_cache()

    todo = [occ for occ in occupations if str(occ.code) not in cache]
    if limit is not None:
        todo = todo[:limit]

    batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]

    if dry_run:
        print(f"{len(occupations)} occupations total, {len(cache)} already cached, "
              f"{len(todo)} to score in {len(batches)} batches of up to {BATCH_SIZE}.")
        print("\n--- prompt for batch 1 ---\n")
        if batches:
            print(build_prompt(rubric, batches[0]))
        if len(batches) > 1:
            print("\n--- prompt for batch 2 ---\n")
            print(build_prompt(rubric, batches[1]))
        return

    if backend == "anthropic" and client is None:
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    spend_usd = 0.0
    scored_count = 0
    start_time = time.monotonic()

    print(f"{len(occupations)} occupations total, {len(cache)} already cached, "
          f"{len(todo)} to score in {len(batches)} batches (backend={backend}).")

    for i, batch in enumerate(batches, start=1):
        if max_minutes is not None and (time.monotonic() - start_time) / 60 >= max_minutes:
            print(f"stopping: wall-clock cap of {max_minutes} minutes reached after "
                  f"{i - 1}/{len(batches)} batches ({scored_count} occupations scored this run).")
            break

        prompt = build_prompt(rubric, batch)
        parsed_result = None
        last_error = None

        for attempt in range(MAX_RETRIES_PER_BATCH + 1):
            try:
                if backend == "claude-cli":
                    raw = call_claude_cli(prompt)
                    parsed = extract_json_array(raw)
                else:
                    raw, in_tok, out_tok = call_anthropic_api(client, prompt)
                    cost = (in_tok / 1_000_000 * PRICE_INPUT_PER_MTOK
                            + out_tok / 1_000_000 * PRICE_OUTPUT_PER_MTOK)
                    if spend_usd + cost > usd_cap:
                        print(f"stopping: batch {i} would push spend to "
                              f"${spend_usd + cost:.4f}, over the ${usd_cap:.2f} cap.")
                        save_cache(cache)
                        return
                    spend_usd += cost
                    parsed = extract_json_array(raw)
                parsed_result = validate_batch_result(parsed, batch)
                break
            except Exception as exc:  # noqa: BLE001 - deliberately broad, we retry once then skip
                last_error = exc
                print(f"batch {i}/{len(batches)} attempt {attempt + 1} failed: {exc}", file=sys.stderr)

        if parsed_result is None:
            print(f"batch {i}/{len(batches)}: giving up after {MAX_RETRIES_PER_BATCH + 1} "
                  f"attempt(s), last error: {last_error}", file=sys.stderr)
            continue

        for occ in batch:
            entry = parsed_result[occ.code]
            cache[str(occ.code)] = {
                "score": entry["score"],
                "rationale": entry["rationale"],
                "model": ANTHROPIC_MODEL if backend == "anthropic" else "claude-cli (haiku)",
                "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            scored_count += 1

        save_cache(cache)
        elapsed = time.monotonic() - start_time
        spend_note = f", spend so far ${spend_usd:.4f}" if backend == "anthropic" else ""
        print(f"batch {i}/{len(batches)} done ({len(batch)} occupations, "
              f"{elapsed:.0f}s elapsed{spend_note})")

    print(f"\nfinished: {scored_count} occupations scored this run, "
          f"{len(cache)} total cached in {display_path(SCORES_PATH)}.")
    if backend == "anthropic":
        print(f"estimated spend this run: ${spend_usd:.4f} (cap was ${usd_cap:.2f})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["anthropic", "claude-cli"], default="anthropic")
    parser.add_argument("--limit", type=int, default=None, help="only score the first N uncached occupations")
    parser.add_argument("--usd-cap", type=float, default=DEFAULT_USD_CAP, help="hard spend cap, anthropic backend only")
    parser.add_argument("--max-minutes", type=float, default=None, help="stop starting new batches after this many minutes")
    parser.add_argument("--dry-run", action="store_true", help="print the first two assembled prompts and exit, no API/CLI calls")
    args = parser.parse_args()

    score_all(args.backend, args.limit, args.usd_cap, args.max_minutes, args.dry_run)


if __name__ == "__main__":
    main()
