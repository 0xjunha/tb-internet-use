"""Expand the tool calls of one trial into everything each call ran, where its output shows up and which later calls use the files it wrote."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call._expand_command_text_status import (
    expand_command_text_status,
)
from tb_internet_use.expanded_tool_call._expand_file_uses_without_known_writer import (
    expand_file_uses_without_known_writer,
)
from tb_internet_use.expanded_tool_call._expand_output_places import (
    expand_output_places,
)
from tb_internet_use.expanded_tool_call._expand_poll_links import (
    PollLinks,
    expand_poll_links,
)
from tb_internet_use.expanded_tool_call._expand_ran_texts import expand_ran_texts
from tb_internet_use.expanded_tool_call._expand_written_files import (
    expand_written_files,
)
from tb_internet_use.expanded_tool_call.model import (
    CommandTextStatus,
    ExpandedToolCall,
)
from tb_internet_use.tool_call.model import ToolCall, ToolCallKey

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `expand_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
        ExpandedToolCallKnowledge,
    )


def expand_tool_calls(
    tool_calls: Sequence[ToolCall],
    *,
    knowledge: ExpandedToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[ExpandedToolCall, ...]:
    """Expand every tool call of one trial into an `ExpandedToolCall`, in the order of `tool_calls`, asking `knowledge` what each program does.

    The pieces run in this order, since each reads what the earlier ones gave.
    The polls are linked to the calls that started what they poll, so that typed text goes to the program that reads it.
    Then the texts each call ran are followed in call order, with the files written so far, e.g. the content of fetch.sh for `bash fetch.sh`.
    Then each call gets the end state of its command text, the results that show its output, the files it wrote with their later uses and its uses of files that no call wrote.
    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule.
    """
    poll_links = expand_poll_links(
        tool_calls, judgment_rule_use_counts=judgment_rule_use_counts
    )
    ran_texts_of_tool_calls = expand_ran_texts(
        tool_calls,
        poll_links,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    command_text_statuses = _expand_command_text_statuses(
        tool_calls, poll_links, judgment_rule_use_counts=judgment_rule_use_counts
    )
    output_places_of_tool_calls = expand_output_places(
        tool_calls,
        ran_texts_of_tool_calls,
        poll_links,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    written_files_of_tool_calls = expand_written_files(ran_texts_of_tool_calls)
    file_uses_without_known_writer_of_tool_calls = (
        expand_file_uses_without_known_writer(ran_texts_of_tool_calls)
    )
    return tuple(
        ExpandedToolCall(
            tool_call=tool_call,
            ran_texts=ran_texts_of_tool_call.ran_texts,
            command_text_status=command_text_status,
            output_places=output_places,
            written_files=written_files,
            file_uses_without_known_writer=file_uses_without_known_writer,
        )
        for (
            tool_call,
            ran_texts_of_tool_call,
            command_text_status,
            output_places,
            written_files,
            file_uses_without_known_writer,
        ) in zip(
            tool_calls,
            ran_texts_of_tool_calls,
            command_text_statuses,
            output_places_of_tool_calls,
            written_files_of_tool_calls,
            file_uses_without_known_writer_of_tool_calls,
            strict=True,
        )
    )


def _expand_command_text_statuses(
    tool_calls: Sequence[ToolCall],
    poll_links: PollLinks,
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[CommandTextStatus | None, ...]:
    """Expand the end state of the command text of each call, giving `expand_command_text_status` the later calls that `poll_links` links to it as polls."""
    tool_call_by_key: dict[ToolCallKey, ToolCall] = {
        tool_call.harness_tool_call.key: tool_call for tool_call in tool_calls
    }
    return tuple(
        expand_command_text_status(
            tool_call,
            [
                tool_call_by_key[poll_tool_call_key]
                for poll_tool_call_key in poll_links.poll_tool_call_keys_of_starter.get(
                    tool_call.harness_tool_call.key, ()
                )
            ],
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        for tool_call in tool_calls
    )
