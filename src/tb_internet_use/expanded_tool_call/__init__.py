"""Expand the tool calls of one trial into everything each call ran and the later calls that show its output."""

from tb_internet_use.expanded_tool_call._expand_tool_calls import expand_tool_calls

__all__ = ["expand_tool_calls"]
