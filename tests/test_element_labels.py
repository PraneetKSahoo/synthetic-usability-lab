"""Tests for how badges are described to the model in the prompt.

The item-vs-its-button distinction is load-bearing: the model previously flip-flopped
between an item's title badge and its 'Add to basket' badge mid-decision.
"""
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import UsabilityEngine  # noqa: E402


def build_prompt(elements):
    """Runs simulate_visual_web_step with a stub LLM and returns the prompt sent."""
    llm = Mock()
    llm.generate_with_vision.return_value = '{"action": "CLICK", "target_tag": 1}'
    eng = UsabilityEngine(llm_client=llm)
    eng.simulate_visual_web_step(
        persona={"name": "Test", "tech_literacy": "High", "habits": "n/a"},
        screenshot=None,
        page_title="T",
        url="http://example.com",
        task="do a thing",
        visual_elements=elements,
        history=[],
        step_num=1,
    )
    return llm.generate_with_vision.call_args[0][0]


class TestElementDescriptions:
    def test_text_input_is_marked_as_typeable(self):
        prompt = build_prompt([{"id": 1, "tag": "input", "type": "text", "text": "Search:"}])
        assert 'Tag [1] -> TEXT INPUT (type into this): "Search:"' in prompt

    def test_button_and_link_are_distinguished(self):
        prompt = build_prompt([
            {"id": 16, "tag": "a", "type": "a", "text": "A Murder in Time"},
            {"id": 26, "tag": "button", "type": "submit", "text": "Add to basket"},
        ])
        assert 'Tag [16] -> LINK (click to navigate): "A Murder in Time"' in prompt
        assert 'Tag [26] -> BUTTON (click to act): "Add to basket"' in prompt

    def test_select_is_marked_as_dropdown(self):
        prompt = build_prompt([{"id": 3, "tag": "select", "type": "select", "text": "Sort by"}])
        assert "Tag [3] -> DROPDOWN" in prompt

    def test_empty_elements_falls_back_to_canvas_note(self):
        prompt = build_prompt([])
        assert "Canvas interface / Figma prototype" in prompt


class TestPromptRules:
    def test_confusion_rubric_is_present(self):
        prompt = build_prompt([{"id": 1, "tag": "a", "type": "a", "text": "x"}])
        assert "CONFUSION SCORING RUBRIC" in prompt
        assert "do NOT default to 0" in prompt

    def test_survey_rule_is_present(self):
        prompt = build_prompt([{"id": 1, "tag": "a", "type": "a", "text": "x"}])
        assert "SURVEY RULE" in prompt
        assert "SCROLL" in prompt

    def test_item_vs_control_rule_is_present(self):
        prompt = build_prompt([{"id": 1, "tag": "a", "type": "a", "text": "x"}])
        assert "REFERENCING ITEMS VS THEIR CONTROLS" in prompt
