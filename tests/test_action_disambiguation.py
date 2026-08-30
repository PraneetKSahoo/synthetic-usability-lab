"""Tests for disambiguating repeated action labels.

A listing page renders ~20 buttons all labelled "Add to basket". Picking the right
one was previously pure visual grounding — the model could name the correct item in
its monologue while clicking any row's button, with no way to tell from the logs.
"""
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import UsabilityEngine  # noqa: E402

PERSONA = {"name": "Maya", "tech_literacy": "High", "habits": "n/a"}


def prompt_with(elements):
    llm = Mock()
    llm.generate_with_vision.return_value = '{"action": "CLICK", "target_tag": 1}'
    eng = UsabilityEngine(llm_client=llm)
    eng.simulate_visual_web_step(
        persona=PERSONA, screenshot=None, page_title="Mystery", url="http://x",
        task="find the cheapest book and add it to your basket",
        visual_elements=elements, history=[], step_num=5,
    )
    return llm.generate_with_vision.call_args[0][0]


class TestQualifiedButtonLabels:
    def test_qualifier_reaches_the_prompt(self):
        prompt = prompt_with([
            {"id": 9, "tag": "button", "type": "submit",
             "text": "Add to basket [for: Tastes Like Fear (DI Marnie Rome #3)]"},
            {"id": 12, "tag": "button", "type": "submit",
             "text": "Add to basket [for: Hide Away (Eve Duncan #20)]"},
        ])
        assert "Add to basket [for: Tastes Like Fear (DI Marnie Rome #3)]" in prompt
        assert "Add to basket [for: Hide Away (Eve Duncan #20)]" in prompt

    def test_both_buttons_remain_distinguishable(self):
        """Two same-labelled buttons must not collapse to identical prompt lines."""
        prompt = prompt_with([
            {"id": 9, "tag": "button", "type": "submit", "text": "Add to basket [for: Book A]"},
            {"id": 12, "tag": "button", "type": "submit", "text": "Add to basket [for: Book B]"},
        ])
        lines = [
            ln.strip() for ln in prompt.splitlines()
            if ln.strip().startswith("Tag [") and "Add to basket" in ln
        ]
        assert len(lines) == 2
        assert len(set(lines)) == 2, "same-labelled buttons collapsed to identical lines"


class TestControlSelectionRules:
    def test_model_told_to_match_the_qualifier(self):
        prompt = prompt_with([{"id": 1, "tag": "button", "type": "submit", "text": "Add to basket"}])
        assert "MANY BUTTONS SHARE THE SAME LABEL" in prompt
        assert "Do NOT pick the first" in prompt

    def test_opening_an_item_is_not_adding_it(self):
        """Guards the observed false SATISFIED on a title-link click."""
        prompt = prompt_with([{"id": 1, "tag": "a", "type": "a", "text": "Tastes Like Fear"}])
        assert "do not mark the goal SATISFIED after merely opening an item" in prompt

    def test_button_and_link_kinds_still_labelled(self):
        prompt = prompt_with([
            {"id": 1, "tag": "a", "type": "a", "text": "Tastes Like Fear"},
            {"id": 2, "tag": "button", "type": "submit", "text": "Add to basket [for: Tastes Like Fear]"},
        ])
        assert "LINK (click to navigate)" in prompt
        assert "BUTTON (click to act)" in prompt
