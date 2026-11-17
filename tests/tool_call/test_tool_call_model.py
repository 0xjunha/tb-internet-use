"""Tests for the text helpers in tool_call/model.py."""

from tb_internet_use.tool_call.model import join_text_parts


def test_join_text_parts_starts_a_new_line_only_when_needed():
    assert join_text_parts(["a\n", "b"]) == "a\nb"
    assert join_text_parts(["a", "b"]) == "a\nb"
    assert join_text_parts(["", "b"]) == "b"
    assert join_text_parts(["a", ""]) == "a"
