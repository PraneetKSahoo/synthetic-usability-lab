"""Tests for code-enforced survey bookkeeping.

Direct regression guards for observed failures: the model overwrote a recorded
best of 10.69 with a worse 11.84, re-estimated the page's result total on every
step (20 -> 32 -> 24 -> 36 -> 16), and never satisfied its own "seen everything?"
check, so it scrolled until stall detection killed the run.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.survey import SurveyTracker, parse_numeric_value  # noqa: E402


class TestParseNumericValue:
    @pytest.mark.parametrize("raw,expected", [
        (10.69, 10.69), (11, 11.0), ("10.69", 10.69),
        ("£10.69", 10.69), ("$1,234.56", 1234.56), ("10.69 GBP", 10.69),
    ])
    def test_valid(self, raw, expected):
        assert parse_numeric_value(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "free", [], {}, True])
    def test_invalid(self, raw):
        assert parse_numeric_value(raw) is None


class TestBestCandidate:
    def test_minimize_keeps_the_lowest_across_steps(self):
        """The exact regression seen in testing: 10.69 must survive a later 11.84."""
        t = SurveyTracker()
        t.set_objective("MINIMIZE")
        t.add_candidates([{"name": "Tastes Like Fear", "value": 10.69}])
        t.add_candidates([{"name": "Hide Away", "value": 11.84}])
        assert t.best == ("Tastes Like Fear", 10.69)

    def test_minimize_accepts_a_strictly_better_value(self):
        t = SurveyTracker()
        t.set_objective("MINIMIZE")
        t.add_candidates([{"name": "In a Dark, Dark Wood", "value": 19.63}])
        t.add_candidates([{"name": "Tastes Like Fear", "value": 10.69}])
        assert t.best == ("Tastes Like Fear", 10.69)

    def test_maximize_keeps_the_highest(self):
        t = SurveyTracker()
        t.set_objective("MAXIMIZE")
        t.add_candidates([{"name": "A", "value": 5}, {"name": "B", "value": 9}])
        t.add_candidates([{"name": "C", "value": 7}])
        assert t.best == ("B", 9.0)

    def test_no_objective_means_no_winner(self):
        t = SurveyTracker()
        t.add_candidates([{"name": "A", "value": 5}])
        assert t.best is None

    def test_objective_does_not_flip_mid_task(self):
        t = SurveyTracker()
        t.set_objective("MINIMIZE")
        t.set_objective("MAXIMIZE")
        assert t.objective == "MINIMIZE"

    def test_malformed_candidates_are_skipped_not_fatal(self):
        t = SurveyTracker()
        t.set_objective("MINIMIZE")
        t.add_candidates([
            {"name": "Good", "value": 12.0},
            {"name": "", "value": 1.0},
            {"name": "No value"},
            "not a dict",
        ])
        assert t.best == ("Good", 12.0)
        assert t.seen_count == 1

    def test_non_list_candidates_are_ignored(self):
        t = SurveyTracker()
        assert t.add_candidates("nonsense") == 0
        assert t.add_candidates(None) == 0


class TestTotalLocking:
    def test_first_total_wins_and_later_guesses_are_ignored(self):
        t = SurveyTracker()
        for reported in (32, 24, 36, 16):
            t.set_total(reported)
        assert t.total == 32

    def test_null_total_is_not_locked_in(self):
        t = SurveyTracker()
        t.set_total(None)
        t.set_total(32)
        assert t.total == 32

    def test_completion_uses_locked_total(self):
        t = SurveyTracker()
        t.set_objective("MINIMIZE")
        t.set_total(3)
        t.add_candidates([{"name": "A", "value": 1}, {"name": "B", "value": 2}])
        assert not t.is_complete
        t.add_candidates([{"name": "C", "value": 3}])
        assert t.is_complete


class TestDeduplicationAndExhaustion:
    def test_repeated_items_are_not_double_counted(self):
        t = SurveyTracker()
        t.add_candidates([{"name": "A", "value": 1}])
        t.add_candidates([{"name": "a", "value": 1}])
        assert t.seen_count == 1

    def test_exhausted_when_a_scroll_reveals_nothing_new(self):
        t = SurveyTracker()
        t.add_candidates([{"name": "A", "value": 1}])
        assert not t.is_exhausted
        t.add_candidates([{"name": "A", "value": 1}])
        assert t.is_exhausted

    def test_exhaustion_resets_when_new_items_appear(self):
        t = SurveyTracker()
        t.add_candidates([{"name": "A", "value": 1}])
        t.add_candidates([{"name": "A", "value": 1}])
        t.add_candidates([{"name": "B", "value": 2}])
        assert not t.is_exhausted


class TestRender:
    def test_render_names_the_current_winner(self):
        t = SurveyTracker()
        t.set_objective("MINIMIZE")
        t.set_total(32)
        t.add_candidates([{"name": "Tastes Like Fear", "value": 10.69}])
        out = t.render()
        assert "Tastes Like Fear" in out
        assert "10.69" in out
        assert "1 of 32" in out
        assert "lowest" in out

    def test_render_is_empty_before_anything_is_known(self):
        assert SurveyTracker().render() == ""
