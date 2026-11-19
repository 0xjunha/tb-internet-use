"""Collect the result formats that each harness declares for its tools, keyed by the harness name ATIF records in `agent.name`."""

from collections.abc import Mapping

from tb_internet_use.knowledge.declarations.tool_call.harness_result_formats import (
    antigravity_cli,
    claude_code,
    codex,
    cursor_cli,
    devin,
    grok_build,
    mini_swe_agent,
    muse_code,
)
from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessToolResultDeclaration,
)

RESULT_FORMATS_BY_HARNESS: Mapping[str, Mapping[str, HarnessToolResultDeclaration]] = {
    "antigravity-cli": antigravity_cli.RESULT_FORMATS_BY_TOOL,
    "claude-code": claude_code.RESULT_FORMATS_BY_TOOL,
    "codex": codex.RESULT_FORMATS_BY_TOOL,
    "cursor-cli": cursor_cli.RESULT_FORMATS_BY_TOOL,
    "devin": devin.RESULT_FORMATS_BY_TOOL,
    "grok-build": grok_build.RESULT_FORMATS_BY_TOOL,
    "mini-swe-agent": mini_swe_agent.RESULT_FORMATS_BY_TOOL,
    "muse-code": muse_code.RESULT_FORMATS_BY_TOOL,
}
