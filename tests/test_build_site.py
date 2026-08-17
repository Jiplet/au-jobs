"""
test_build_site.py - checks build_site.py merges occupations.csv + scores.json correctly,
and that missing values stay null rather than becoming 0 or "".

Run: uv run pytest tests/test_build_site.py -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_site  # noqa: E402


def test_build_merges_csv_and_scores_and_preserves_nulls(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "CSV_PATH", tmp_path / "occupations.csv")
    monkeypatch.setattr(build_site, "SCORES_PATH", tmp_path / "scores.json")

    (tmp_path / "occupations.csv").write_text(
        "anzsco_code,title,major_group_code,major_group,skill_level,employment_thousands,"
        "avg_weekly_earnings,growth_5y_pct,growth_10y_pct,shortage_rating,tasks_text\n"
        "1111,Chief Executives,1,Managers,1,63.4,2962.8,6.85,14.09,NS,\n"
        "2211,Accountants,2,Professionals,1,,,,,,\n",  # every optional field missing
        encoding="utf-8",
    )
    (tmp_path / "scores.json").write_text(
        json.dumps({"1111": {"score": 5, "rationale": "a reason", "model": "x", "scored_at": "t"}}),
        encoding="utf-8",
    )

    payload = build_site.build()
    by_code = {o["code"]: o for o in payload["occupations"]}

    assert payload["meta"]["occupation_count"] == 2
    assert payload["meta"]["ai_exposure_scored_count"] == 1

    scored = by_code[1111]
    assert scored["employment_thousands"] == 63.4
    assert scored["avg_weekly_earnings"] == 2962.8
    assert scored["ai_exposure_score"] == 5
    assert scored["ai_exposure_rationale"] == "a reason"

    unscored = by_code[2211]
    assert unscored["employment_thousands"] is None
    assert unscored["avg_weekly_earnings"] is None
    assert unscored["shortage_rating"] is None
    assert unscored["ai_exposure_score"] is None
    assert unscored["ai_exposure_rationale"] is None


def test_build_handles_no_scores_file_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "CSV_PATH", tmp_path / "occupations.csv")
    monkeypatch.setattr(build_site, "SCORES_PATH", tmp_path / "does-not-exist.json")

    (tmp_path / "occupations.csv").write_text(
        "anzsco_code,title,major_group_code,major_group,skill_level,employment_thousands,"
        "avg_weekly_earnings,growth_5y_pct,growth_10y_pct,shortage_rating,tasks_text\n"
        "1111,Chief Executives,1,Managers,1,63.4,2962.8,6.85,14.09,NS,\n",
        encoding="utf-8",
    )

    payload = build_site.build()
    assert payload["meta"]["ai_exposure_scored_count"] == 0
    assert payload["occupations"][0]["ai_exposure_score"] is None
