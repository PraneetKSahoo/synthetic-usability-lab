"""Tests for the cross-step observation scratchpad.

Regression guard for a real failure: during a "find the cheapest" task the agent
surveyed a long list, saw GBP 10.69, scrolled, and then picked GBP 11.84 because
nothing carried the earlier finding forward.
"""
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import UsabilityEngine  # noqa: E402

ELEMENTS = [{"id": 1, "tag": "a", "type": "a", "text": "A Book"}]
PERSONA = {"name": "Test", "tech_literacy": "High", "habits": "n/a"}


def run_step(llm_response, observations=""):
    llm = Mock()
    llm.generate_with_vision.return_value = llm_response
    eng = UsabilityEngine(llm_client=llm)
    decision = eng.simulate_visual_web_step(
        persona=PERSONA, screenshot=None, page_title="T", url="http://x",
        task="find the cheapest book", visual_elements=ELEMENTS,
        history=[], step_num=2, observations=observations,
    )
    return llm.generate_with_vision.call_args[0][0], decision


class TestObservationsInPrompt:
    def test_prior_notes_are_injected(self):
        prompt, _ = run_step('{"action": "SCROLL"}', observations="Best so far: Tastes Like Fear GBP 10.69")
        assert "Best so far: Tastes Like Fear GBP 10.69" in prompt
        assert "YOUR NOTES CARRIED FORWARD" in prompt

    def test_empty_notes_show_placeholder(self):
        prompt, _ = run_step('{"action": "SCROLL"}', observations="")
        assert "nothing recorded yet" in prompt

    def test_observations_field_is_requested_in_schema(self):
        prompt, _ = run_step('{"action": "SCROLL"}')
        assert '"observations"' in prompt

    def test_badge_renumbering_warning_present(self):
        """The same book was tag [28] on one step and [4] on the next."""
        prompt, _ = run_step('{"action": "SCROLL"}')
        assert "RE-ASSIGNED EVERY STEP" in prompt

    def test_system_maintained_survey_state_is_injected(self):
        """Superlative bookkeeping is code-owned now — see tests/test_survey_tracker.py."""
        llm = Mock()
        llm.generate_with_vision.return_value = '{"action": "SCROLL"}'
        eng = UsabilityEngine(llm_client=llm)
        eng.simulate_visual_web_step(
            persona=PERSONA, screenshot=None, page_title="T", url="http://x",
            task="find the cheapest book", visual_elements=ELEMENTS, history=[],
            step_num=2, survey_state='BEST FOUND SO FAR: "Tastes Like Fear" at 10.69',
        )
        prompt = llm.generate_with_vision.call_args[0][0]
        assert 'BEST FOUND SO FAR: "Tastes Like Fear" at 10.69' in prompt

    def test_exhausted_scroll_notice_breaks_the_loop(self):
        """Without this the model scrolls forever waiting to 'finish surveying'."""
        llm = Mock()
        llm.generate_with_vision.return_value = '{"action": "CLICK"}'
        eng = UsabilityEngine(llm_client=llm)
        eng.simulate_visual_web_step(
            persona=PERSONA, screenshot=None, page_title="T", url="http://x",
            task="find the cheapest book", visual_elements=ELEMENTS, history=[],
            step_num=5, survey_exhausted=True,
        )
        prompt = llm.generate_with_vision.call_args[0][0]
        assert "SCROLLING IS EXHAUSTED" in prompt
        assert "Do NOT choose SCROLL again" in prompt

    def test_pagination_rule_present(self):
        prompt, _ = run_step('{"action": "SCROLL"}')
        assert "SECOND PAGE" in prompt


class TestObservationsRoundTrip:
    def test_observations_survive_parsing(self):
        _, decision = run_step(
            '{"action": "SCROLL", "observations": "Cheapest so far: Thirst GBP 17.27 (12/32 surveyed)"}'
        )
        assert decision["observations"] == "Cheapest so far: Thirst GBP 17.27 (12/32 surveyed)"

    def test_missing_observations_is_absent_not_fatal(self):
        _, decision = run_step('{"action": "CLICK", "target_tag": 1}')
        assert decision["action"] == "CLICK"
        assert "observations" not in decision or not decision["observations"]
