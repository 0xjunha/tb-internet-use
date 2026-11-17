"""Pick the tool call converter of a harness, keyed by the harness name that ATIF records in `agent.name`."""

from tb_internet_use.tool_call.harnesses.claude_code import ClaudeCodeConverter
from tb_internet_use.tool_call.harnesses.codex import CodexConverter
from tb_internet_use.tool_call.harnesses.cursor_cli import CursorCliConverter
from tb_internet_use.tool_call.harnesses.devin import DevinConverter
from tb_internet_use.tool_call.harnesses.grok_build import GrokBuildConverter
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.harnesses.muse_code import MuseCodeConverter

CONVERTERS: dict[str, HarnessToolCallConverter] = {
    "claude-code": ClaudeCodeConverter(),
    "codex": CodexConverter(),
    "cursor-cli": CursorCliConverter(),
    "devin": DevinConverter(),
    "grok-build": GrokBuildConverter(),
    # Every part of mini-swe-agent conversion is shared, so it needs no converter of its own.
    "mini-swe-agent": HarnessToolCallConverter(),
    "muse-code": MuseCodeConverter(),
}


def converter_for(harness: str) -> HarnessToolCallConverter:
    """Find the converter of a harness, raising ValueError for a harness without one."""
    try:
        return CONVERTERS[harness]
    except KeyError:
        raise ValueError(f"no converter for harness {harness!r}") from None
