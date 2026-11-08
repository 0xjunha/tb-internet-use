"""Tool call converters, one per harness, keyed by the harness name ATIF records in `agent.name`."""

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.harnesses.claude_code import ClaudeCodeConverter
from tb_internet_use.toolcall.harnesses.codex import CodexConverter
from tb_internet_use.toolcall.harnesses.cursor_cli import CursorCliConverter
from tb_internet_use.toolcall.harnesses.devin import DevinConverter
from tb_internet_use.toolcall.harnesses.grok_build import GrokBuildConverter
from tb_internet_use.toolcall.harnesses.mini_swe_agent import MiniSweAgentConverter
from tb_internet_use.toolcall.harnesses.muse_code import MuseCodeConverter

CONVERTERS: dict[str, HarnessToolCallConverter] = {
    "claude-code": ClaudeCodeConverter(),
    "codex": CodexConverter(),
    "cursor-cli": CursorCliConverter(),
    "devin": DevinConverter(),
    "grok-build": GrokBuildConverter(),
    "mini-swe-agent": MiniSweAgentConverter(),
    "muse-code": MuseCodeConverter(),
}


def converter_for(harness: str) -> HarnessToolCallConverter:
    """The converter of a harness; raises ValueError for a harness without one."""
    try:
        return CONVERTERS[harness]
    except KeyError:
        raise ValueError(f"no converter for harness {harness!r}") from None
