"""Tests for the LLM output parsing in src/engine.py.

These cover the single most failure-prone part of the pipeline: turning free-form
model text into a usable decision dict. They import the parsing helpers directly
so no model/GPU is required.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import _find_json_objects, _coerce_int  # noqa: E402


def objects(text):
    return list(_find_json_objects(text))


class TestFindJsonObjects:
    def test_plain_object(self):
        assert objects('{"a": 1}') == ['{"a": 1}']

    def test_object_with_surrounding_prose(self):
        text = 'Here is my answer:\n{"action": "CLICK"}\nHope that helps!'
        assert objects(text) == ['{"action": "CLICK"}']

    def test_nested_object_kept_whole(self):
        text = '{"outer": {"inner": 2}}'
        assert objects(text) == ['{"outer": {"inner": 2}}']

    def test_two_separate_objects_are_not_merged(self):
        """A greedy `{.*}` would return one invalid span from first { to last }."""
        text = 'example: {"a": 1} and the real one: {"b": 2}'
        assert objects(text) == ['{"a": 1}', '{"b": 2}']

    def test_braces_inside_strings_are_ignored(self):
        text = '{"monologue": "I saw a {weird} label"}'
        assert objects(text) == ['{"monologue": "I saw a {weird} label"}']

    def test_escaped_quote_inside_string(self):
        text = r'{"monologue": "he said \"hi\" to me"}'
        assert objects(text) == [text]

    def test_unclosed_object_yields_nothing(self):
        assert objects('{"a": 1') == []

    def test_no_braces_yields_nothing(self):
        assert objects('I could not decide what to do.') == []


class TestCoerceInt:
    @pytest.mark.parametrize("value,expected", [
        (42, 42),
        ("42", 42),
        (42.7, 42),
        ("42.7", 42),
    ])
    def test_valid_values(self, value, expected):
        assert _coerce_int(value, 0) == expected

    @pytest.mark.parametrize("value", ["high", None, "", [], {}])
    def test_invalid_values_fall_back(self, value):
        assert _coerce_int(value, 20) == 20
