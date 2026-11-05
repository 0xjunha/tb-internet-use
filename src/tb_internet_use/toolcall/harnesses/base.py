"""Interface for tool call converters that each harness implements."""

from abc import ABC, abstractmethod
from typing import Any

from tb_internet_use.toolcall.model import Action, RawToolCall, ToolCallOutput


class HarnessConverter(ABC):
    """The parts of tool call conversion logic that differ by harness."""

    @abstractmethod
    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        """Parse a logged tool call result into common types."""

    def refine_action(
        self, raw: RawToolCall, action: Action, output: ToolCallOutput | None
    ) -> Action:
        """Fill fields of an Action that the tool call catalog cannot express. (no-op by default)"""
        return action

    def deferred_action(
        self, raw: RawToolCall, output: ToolCallOutput | None
    ) -> Action:
        """Decide the Action of a tool labeled Deferred.

        Only harnesses with Deferred tools override this.
        """
        raise NotImplementedError(f"no Deferred handling for {raw.tool}")
