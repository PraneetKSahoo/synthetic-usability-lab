"""Tests for the scroll-termination signal.

Regression guard: a category advertising "32 results" renders only 20 on page one,
so a survey that waits for seen >= total never finishes. The agent scrolled into
the bottom of the page repeatedly until stall detection killed the run, never
acting on the winner it had correctly identified four steps earlier.
"""
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import UsabilityEngine  # noqa: E402

PERSONA = {"name": "Maya", "tech_literacy": "High", "habits": "n/a"}
ELEMENTS = [{"id": 1, "tag": "button", "type": "submit", "text": "Add to basket"}]


def prompt_for(**kwargs):
    llm = Mock()
    llm.generate_with_vision.return_value = '{"action": "CLICK", "target_tag": 1}'
    eng = UsabilityEngine(llm_client=llm)
    eng.simulate_visual_web_step(
        persona=PERSONA, screenshot=None, page_title="Mystery", url="http://x",
        task="find the cheapest book on the first page", visual_elements=ELEMENTS,
        history=[], step_num=6, **kwargs,
    )
    return llm.generate_with_vision.call_args[0][0]


class TestAtPageBottomNotice:
    def test_bottom_forbids_scrolling(self):
        prompt = prompt_for(at_page_bottom=True)
        assert "STOP SCROLLING" in prompt
        assert "SCROLL is FORBIDDEN" in prompt

    def test_bottom_tells_the_model_to_act_now(self):
        prompt = prompt_for(at_page_bottom=True)
        assert "ACT NOW" in prompt

    def test_bottom_warns_stated_total_may_exceed_page_contents(self):
        """The 20-of-32 trap that made the exit condition unreachable."""
        prompt = prompt_for(at_page_bottom=True)
        assert "may be higher than what it actually renders" in prompt

    def test_bottom_takes_priority_over_plain_exhaustion(self):
        prompt = prompt_for(at_page_bottom=True, survey_exhausted=True)
        assert "STOP SCROLLING" in prompt
        assert "SCROLLING IS EXHAUSTED" not in prompt

    def test_exhaustion_notice_used_when_not_at_bottom(self):
        prompt = prompt_for(at_page_bottom=False, survey_exhausted=True)
        assert "SCROLLING IS EXHAUSTED" in prompt

    def test_no_notice_when_survey_still_progressing(self):
        prompt = prompt_for(at_page_bottom=False, survey_exhausted=False)
        assert "STOP SCROLLING" not in prompt
        assert "SCROLLING IS EXHAUSTED" not in prompt


class TestSurveyRuleWording:
    def test_rule_warns_against_waiting_for_the_stated_total(self):
        prompt = prompt_for()
        assert "Do NOT wait for" in prompt
        assert "infinite loop" in prompt
