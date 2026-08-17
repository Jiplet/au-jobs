"""
test_score_parse.py - checks score.py's JSON parsing, validation, and USD cap logic.

The cap logic is exercised with a fake Anthropic client (no network, no API key) since
the real anthropic backend could not be exercised live during this build - the workspace
API key had no credit at the time. See README "Design notes" for the claude-cli backend
that was used for the real scoring run instead.

Run: uv run pytest tests/test_score_parse.py -q
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import score  # noqa: E402


# --- extract_json_array ---------------------------------------------------------------

def test_extract_json_array_plain():
    text = '[{"code": 1111, "score": 5, "rationale": "x"}]'
    assert score.extract_json_array(text) == [{"code": 1111, "score": 5, "rationale": "x"}]


def test_extract_json_array_strips_markdown_fence():
    text = '```json\n[{"code": 1111, "score": 5, "rationale": "x"}]\n```'
    assert score.extract_json_array(text) == [{"code": 1111, "score": 5, "rationale": "x"}]


def test_extract_json_array_ignores_stray_prose_around_it():
    text = 'Sure, here you go:\n[{"code": 1111, "score": 5, "rationale": "x"}]\nHope that helps!'
    assert score.extract_json_array(text) == [{"code": 1111, "score": 5, "rationale": "x"}]


def test_extract_json_array_raises_on_garbage():
    with pytest.raises(ValueError):
        score.extract_json_array("not json at all")


# --- validate_batch_result --------------------------------------------------------------

def _batch():
    return [
        score.OccRow(code=1111, title="Chief Executives", major_group="Managers", tasks_text=""),
        score.OccRow(code=2211, title="Accountants", major_group="Professionals", tasks_text=""),
    ]


def test_validate_batch_result_happy_path():
    parsed = [
        {"code": 1111, "score": 5, "rationale": "a"},
        {"code": 2211, "score": 8, "rationale": "b"},
    ]
    result = score.validate_batch_result(parsed, _batch())
    assert result[1111]["score"] == 5
    assert result[2211]["rationale"] == "b"


def test_validate_batch_result_missing_code_raises():
    parsed = [{"code": 1111, "score": 5, "rationale": "a"}]
    with pytest.raises(ValueError, match="missing codes"):
        score.validate_batch_result(parsed, _batch())


def test_validate_batch_result_strips_em_dashes_from_rationale():
    # Models reach for an em dash a lot; house style bans it everywhere, including
    # in LLM-generated text, so validate_batch_result normalises it on the way in.
    parsed = [
        {"code": 1111, "score": 5, "rationale": "Drafting and analysis\u2014both AI-assisted."},
        {"code": 2211, "score": 8, "rationale": "no dash here"},
    ]
    result = score.validate_batch_result(parsed, _batch())
    assert "\u2014" not in result[1111]["rationale"]
    assert result[1111]["rationale"] == "Drafting and analysis - both AI-assisted."
    assert result[2211]["rationale"] == "no dash here"


def test_validate_batch_result_score_out_of_range_raises():
    parsed = [
        {"code": 1111, "score": 15, "rationale": "a"},
        {"code": 2211, "score": 8, "rationale": "b"},
    ]
    with pytest.raises(ValueError, match="out of range"):
        score.validate_batch_result(parsed, _batch())


# --- build_prompt ------------------------------------------------------------------------

def test_build_prompt_includes_rubric_and_every_occupation():
    rubric = "RUBRIC TEXT HERE"
    prompt = score.build_prompt(rubric, _batch())
    assert "RUBRIC TEXT HERE" in prompt
    assert "1111" in prompt and "Chief Executives" in prompt
    assert "2211" in prompt and "Accountants" in prompt


def test_build_prompt_flags_missing_task_text():
    rubric = "R"
    prompt = score.build_prompt(rubric, _batch())
    assert "infer briefly" in prompt


# --- USD cap logic, with a fake Anthropic client (no network) --------------------------

class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _fake_response(codes, input_tokens, output_tokens):
    payload = json.dumps([{"code": c, "score": 5, "rationale": "x"} for c in codes])
    return SimpleNamespace(
        content=[SimpleNamespace(text=payload)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_score_all_anthropic_stops_at_usd_cap(tmp_path, monkeypatch):
    # Three occupations, one per batch (BATCH_SIZE patched down to 1 so each batch's
    # cost is cheap and predictable). The cost of a batch is only known once its API
    # call returns (that's how token-metered billing works), so the cap is enforced
    # by refusing to SAVE a batch that would breach it and stopping before starting
    # the next one - not by predicting cost in advance.
    monkeypatch.setattr(score, "BATCH_SIZE", 1)
    monkeypatch.setattr(score, "CSV_PATH", tmp_path / "occupations.csv")
    monkeypatch.setattr(score, "SCORES_PATH", tmp_path / "scores.json")
    monkeypatch.setattr(score, "RUBRIC_PATH", tmp_path / "rubric.md")
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "occupations.csv").write_text(
        "anzsco_code,title,major_group_code,major_group,skill_level,employment_thousands,"
        "avg_weekly_earnings,growth_5y_pct,growth_10y_pct,shortage_rating,tasks_text\n"
        "1111,Chief Executives,1,Managers,1,10,2000,5,10,NS,\n"
        "2211,Accountants,2,Professionals,1,10,2000,5,10,NS,\n"
        "3211,Bricklayers,3,Trades,1,10,2000,5,10,NS,\n",
        encoding="utf-8",
    )

    # 1,000,000 input tokens at $1/Mtok = $1.00 per batch. Cap 1.50: batch 1 lands at
    # $1.00 (under cap, cached); batch 2 would take spend to $2.00 (over cap, refused,
    # loop stops); batch 3 must never be called at all.
    fake = FakeClient([
        _fake_response([1111], input_tokens=1_000_000, output_tokens=0),
        _fake_response([2211], input_tokens=1_000_000, output_tokens=0),
        _fake_response([3211], input_tokens=1_000_000, output_tokens=0),
    ])

    score.score_all(backend="anthropic", limit=None, usd_cap=1.50, max_minutes=None,
                     dry_run=False, client=fake)

    cache = json.loads((tmp_path / "scores.json").read_text(encoding="utf-8"))
    assert "1111" in cache
    assert "2211" not in cache  # this batch's cost breached the cap, so it was not saved
    assert "3211" not in cache  # never attempted - loop stopped after breaching the cap
    assert fake.messages.calls == 2


def test_score_all_resumes_from_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(score, "BATCH_SIZE", 18)
    monkeypatch.setattr(score, "CSV_PATH", tmp_path / "occupations.csv")
    monkeypatch.setattr(score, "SCORES_PATH", tmp_path / "scores.json")
    monkeypatch.setattr(score, "RUBRIC_PATH", tmp_path / "rubric.md")
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "occupations.csv").write_text(
        "anzsco_code,title,major_group_code,major_group,skill_level,employment_thousands,"
        "avg_weekly_earnings,growth_5y_pct,growth_10y_pct,shortage_rating,tasks_text\n"
        "1111,Chief Executives,1,Managers,1,10,2000,5,10,NS,\n"
        "2211,Accountants,2,Professionals,1,10,2000,5,10,NS,\n",
        encoding="utf-8",
    )
    (tmp_path / "scores.json").write_text(
        json.dumps({"1111": {"score": 5, "rationale": "cached", "model": "x", "scored_at": "t"}}),
        encoding="utf-8",
    )

    fake = FakeClient([_fake_response([2211], input_tokens=100, output_tokens=100)])

    score.score_all(backend="anthropic", limit=None, usd_cap=2.00, max_minutes=None,
                     dry_run=False, client=fake)

    # only the uncached occupation should have triggered a call
    assert fake.messages.calls == 1
    cache = json.loads((tmp_path / "scores.json").read_text(encoding="utf-8"))
    assert cache["1111"]["rationale"] == "cached"
    assert "2211" in cache
