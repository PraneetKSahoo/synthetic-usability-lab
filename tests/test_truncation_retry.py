"""Tests for the retry-on-truncation path.

Regression guard: a monologue that listed every price on screen exhausted the
token budget mid-number, leaving unclosed JSON. That single truncated response
aborted an entire 8-step run as BLOCKED.
"""
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import UsabilityEngine  # noqa: E402

TRUNCATED = (
    '```json\n{\n  "internal_monologue": "The prices are: 35.28, 11.84, 59.48, 27.26, 13'
)
VALID = '{"action": "SCROLL", "internal_monologue": "Scrolling.", "confusion_pct": 40}'

PERSONA = {"name": "Dev", "tech_literacy": "High", "habits": "n/a"}
ELEMENTS = [{"id": 1, "tag": "a", "type": "a", "text": "Mystery"}]


def run(responses):
    llm = Mock()
    llm.generate_with_vision.side_effect = responses
    eng = UsabilityEngine(llm_client=llm)
    decision = eng.simulate_visual_web_step(
        persona=PERSONA, screenshot=None, page_title="T", url="http://x",
        task="find the cheapest book", visual_elements=ELEMENTS,
        history=[], step_num=3, observations="Best so far: Tastes Like Fear 10.69",
    )
    return llm, decision


class TestTruncationRetry:
    def test_truncated_response_triggers_one_retry(self):
        llm, _ = run([TRUNCATED, VALID])
        assert llm.generate_with_vision.call_count == 2

    def test_retry_recovers_the_step(self):
        _, decision = run([TRUNCATED, VALID])
        assert decision["action"] == "SCROLL"
        assert decision.get("parse_failed") is not True

    def test_retry_prompt_asks_for_brevity(self):
        llm, _ = run([TRUNCATED, VALID])
        retry_prompt = llm.generate_with_vision.call_args_list[1][0][0]
        assert "CUT OFF" in retry_prompt
        assert "ONE sentence" in retry_prompt

    def test_retry_raises_the_token_budget(self):
        llm, _ = run([TRUNCATED, VALID])
        first = llm.generate_with_vision.call_args_list[0][1]["max_new_tokens"]
        second = llm.generate_with_vision.call_args_list[1][1]["max_new_tokens"]
        assert second > first

    def test_valid_first_response_does_not_retry(self):
        llm, _ = run([VALID])
        assert llm.generate_with_vision.call_count == 1

    def test_two_failures_falls_back_to_blocked(self):
        _, decision = run([TRUNCATED, TRUNCATED])
        assert decision["parse_failed"] is True
        assert decision["goal_status"] == "BLOCKED"


class TestSurveyRules:
    def test_model_is_told_it_need_not_remember(self):
        """Bookkeeping moved into code; the model only reports what it sees."""
        llm, _ = run([VALID])
        prompt = llm.generate_with_vision.call_args[0][0]
        assert "You do NOT have to remember anything across steps" in prompt
        assert "REPORT WHAT YOU CAN SEE RIGHT NOW" in prompt

    def test_structured_survey_fields_are_requested(self):
        llm, _ = run([VALID])
        prompt = llm.generate_with_vision.call_args[0][0]
        assert '"candidates"' in prompt
        assert '"objective"' in prompt
        assert '"survey_total"' in prompt

    def test_monologue_length_cap_present(self):
        llm, _ = run([VALID])
        prompt = llm.generate_with_vision.call_args[0][0]
        assert "MAXIMUM 2 sentences" in prompt
