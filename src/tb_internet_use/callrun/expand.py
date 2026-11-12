"""Expand each call of a trial into its run, i.e. everything it actually ran and the calls that show its output, for finding candidate requests and linking output to them.

A call can run more than its own text shows, e.g. the content of fetch.sh that an earlier call wrote, so the whole trial is read.
"""

from collections.abc import Mapping, Sequence

from tb_internet_use.callrun.file_reads import TrialFileReads
from tb_internet_use.callrun.model import CallRun, RanCommand, RanShellText
from tb_internet_use.callrun.output_routes import output_routes
from tb_internet_use.callrun.poll_links import command_text_status, link_polls
from tb_internet_use.callrun.ran_texts import ParsedRanTexts, parse_ran_texts_of_calls
from tb_internet_use.callrun.variable_values import command_variable_values
from tb_internet_use.shell.model import ParsedShellText, ShellCommand
from tb_internet_use.toolcall.model import ToolCall


def expand_calls(calls: Sequence[ToolCall]) -> tuple[CallRun, ...]:
    """Expand each call of one trial into its run, i.e. everything it actually ran and the later calls that show its output, one result per call in call order.

    What a call ran includes what its own text does not show, e.g. the content of a file it runs or the values of its variables.
    """
    poll_links = link_polls(calls)
    parsed_texts_of_calls = parse_ran_texts_of_calls(calls, poll_links)
    shell_texts_of_calls = [
        _ran_shell_texts(parsed) for parsed in parsed_texts_of_calls
    ]
    file_reads = TrialFileReads(calls, shell_texts_of_calls)
    call_of_key = {call.raw.key: call for call in calls}
    call_runs: list[CallRun] = []
    for index, (call, parsed, shell_texts) in enumerate(
        zip(calls, parsed_texts_of_calls, shell_texts_of_calls, strict=True)
    ):
        polls = poll_links.polls_of_call.get(call.raw.key, ())
        call_runs.append(
            CallRun(
                call=call,
                shell_texts=shell_texts,
                code_texts=parsed.code_texts,
                command_text_status=command_text_status(
                    call, [call_of_key[key] for key in polls]
                ),
                polls=polls,
                harness_output_file_readers=file_reads.harness_output_file_readers(
                    index
                ),
                redirected_output_reads=file_reads.redirected_output_reads(index),
            )
        )
    return tuple(call_runs)


def _ran_shell_texts(parsed: ParsedRanTexts) -> tuple[RanShellText, ...]:
    """Add variable values and output routes to the commands of a call's parsed shell texts."""
    command_of_id = {
        command.id: command
        for _, parsed_text in parsed.shell_texts
        if parsed_text is not None
        for command in parsed_text.commands
    }
    return tuple(
        RanShellText(
            source,
            None
            if parsed_text is None
            else tuple(
                _ran_command(c, parsed_text, command_of_id)
                for c in parsed_text.commands
            ),
        )
        for source, parsed_text in parsed.shell_texts
    )


def _ran_command(
    command: ShellCommand,
    parsed_text: ParsedShellText,
    command_of_id: Mapping[int, ShellCommand],
) -> RanCommand:
    """Make the run of one command, with the values of its variables and the routes of its output."""
    return RanCommand(
        command=command,
        variable_values=command_variable_values(command, parsed_text),
        stdout_routes=output_routes(command.stdout, command_of_id),
        stderr_routes=output_routes(command.stderr, command_of_id),
    )
