"""Tests for the per-step terminal log block."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser_agent import format_step_log  # noqa: E402

STEP = {
    "step": 3,
    "persona_name": "Dev, 34",
    "avatar": "D",
    "page_title": "Mystery | Books to Scrape",
    "url": "https://books.toscrape.com/mystery_3/index.html",
    "internal_monologue": "The prices visible are 47.82 and 10.69.",
    "action": "SCROLL",
    "confusion_pct": 45,
    "sentiment": "FRUSTRATED",
    "goal_status": "IN_PROGRESS",
    "critique": "No easy way to sort by price.",
    "latency_telemetry": {
        "total_sec": 57.6, "vlm_cognition_sec": 55.3,
        "web_settle_sec": 0.1, "action_exec_sec": 2.15,
    },
    "debug_info": {
        "execution_log": "Action: SCROLL | Scrolled down 680px",
        "observations": "Cheapest so far: Tastes Like Fear - 10.69 (8 of 32).",
    },
}


class TestFormatStepLog:
    def test_includes_monologue(self):
        assert "The prices visible are 47.82 and 10.69." in format_step_log(STEP, 8)

    def test_includes_action_and_state(self):
        out = format_step_log(STEP, 8)
        assert "SCROLL" in out
        assert "confusion 45%" in out
        assert "FRUSTRATED" in out

    def test_includes_execution_log(self):
        assert "Scrolled down 680px" in format_step_log(STEP, 8)

    def test_includes_notes_carried_forward(self):
        assert "Cheapest so far: Tastes Like Fear" in format_step_log(STEP, 8)

    def test_includes_critique_and_step_budget(self):
        out = format_step_log(STEP, 8)
        assert "No easy way to sort by price." in out
        assert "Step 3/8" in out

    def test_is_ascii_safe_for_cp1252_consoles(self):
        """Box-drawing glyphs would raise UnicodeEncodeError on Windows consoles."""
        skeleton = format_step_log({**STEP, "avatar": "", "persona_name": "Dev"}, 8)
        skeleton.encode("cp1252")  # must not raise

    def test_tolerates_missing_optional_sections(self):
        out = format_step_log({"step": 1, "action": "CLICK"}, 5)
        assert "CLICK" in out
        assert "Notes" not in out  # omitted rather than rendered empty

    def test_empty_fields_are_skipped(self):
        out = format_step_log({**STEP, "critique": "", "debug_info": {}}, 8)
        assert "Finding" not in out
        assert "Executed" not in out
