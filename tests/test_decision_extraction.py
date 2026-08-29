"""Tests for UsabilityEngine._extract_clean_json decision normalization."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import UsabilityEngine  # noqa: E402


def engine():
    # The LLM client is only used by methods we don't exercise here.
    return UsabilityEngine(llm_client=None)


class TestExtractCleanJson:
    def test_valid_decision_passes_through(self):
        raw = '{"action": "CLICK", "target_tag": 5, "confusion_pct": 30, "internal_monologue": "Clicking."}'
        out = engine()._extract_clean_json(raw)
        assert out["action"] == "CLICK"
        assert out["target_tag"] == 5
        assert out["confusion_pct"] == 30
        assert out.get("parse_failed") is not True

    def test_confusion_pct_is_clamped(self):
        assert engine()._extract_clean_json('{"confusion_pct": 500}')["confusion_pct"] == 100
        assert engine()._extract_clean_json('{"confusion_pct": -20}')["confusion_pct"] == 0

    def test_non_numeric_confusion_does_not_discard_the_parse(self):
        """One bad field used to throw inside the try and nuke an otherwise-good parse."""
        out = engine()._extract_clean_json('{"action": "SCROLL", "confusion_pct": "high"}')
        assert out["action"] == "SCROLL"
        assert out["confusion_pct"] == 20

    def test_click_coords_default_is_injected(self):
        out = engine()._extract_clean_json('{"action": "CLICK"}')
        assert out["click_coords"] == {"x_pct": 50, "y_pct": 50}

    def test_empty_monologue_gets_placeholder(self):
        out = engine()._extract_clean_json('{"internal_monologue": ""}')
        assert out["internal_monologue"] == "Evaluating the interface..."

    def test_json_wrapped_in_markdown_fence(self):
        raw = 'Sure!\n```json\n{"action": "TYPE", "input_text": "hello"}\n```'
        out = engine()._extract_clean_json(raw)
        assert out["action"] == "TYPE"
        assert out["input_text"] == "hello"

    def test_prose_with_example_braces_picks_the_real_object(self):
        raw = 'Format is {"x": 1} but my answer is {"action": "CLICK", "target_tag": 9}'
        out = engine()._extract_clean_json(raw)
        assert out["action"] == "CLICK"
        assert out["target_tag"] == 9

    def test_unparseable_output_reports_blocked_not_complete(self):
        """A run we cannot read is a failed run — it must not look like a success."""
        out = engine()._extract_clean_json("I have no idea what to do here.")
        assert out["parse_failed"] is True
        assert out["action"] == "DROP_OFF"
        assert out["goal_status"] == "BLOCKED"
        assert out["action"] != "COMPLETE"

    def test_parse_failure_counter_increments(self):
        eng = engine()
        eng._extract_clean_json('{"action": "CLICK"}')
        eng._extract_clean_json("garbage")
        assert eng.parse_attempts == 2
        assert eng.parse_failures == 1
