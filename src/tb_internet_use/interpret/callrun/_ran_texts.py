"""Find and parse the shell texts and code that a call ran, including the files and heredocs that its commands run.

A command can run text that its own words do not show, e.g. the content of fetch.sh in `bash fetch.sh` or the heredoc in `python - <<EOF`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from tb_internet_use.interpret.callrun._paths import can_name_same_file
from tb_internet_use.interpret.callrun._poll_links import PollLinks, typed_text
from tb_internet_use.interpret.callrun._written_files import WrittenFiles
from tb_internet_use.interpret.callrun.code_program_tables import (
    CODE_PROGRAMS,
    LANGUAGE_OF_FILE_EXTENSION,
    SHELL_FILE_EXTENSIONS,
)
from tb_internet_use.interpret.callrun.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    FileText,
    PollInputText,
    RanCodeText,
    ScriptStepText,
    ShellTextSource,
    StdinText,
)
from tb_internet_use.parse.program.arguments import parse_arguments
from tb_internet_use.parse.program.catalog_rows import last_program_words
from tb_internet_use.parse.shell import parse_shell
from tb_internet_use.parse.shell.model import ParsedShellText, ShellCommand
from tb_internet_use.parse.shell.programs import (
    program_word_as_written,
    program_words,
    runs_stdin_as_shell_text,
    shell_file_path,
)
from tb_internet_use.parse.toolcall.model import (
    PollAction,
    RunCommandAction,
    ToolCall,
    ToolCallKey,
    action_steps_with_index,
    may_have_run,
)

# The extension that ends a file name, e.g. .sh.
_FILE_EXTENSION_AT_END = re.compile(r"\.\w+$")


@dataclass(frozen=True, slots=True)
class ParsedRanTexts:
    """Parse result of the texts one call ran, before variable values and output routes are added."""

    # Each shell text with its parse, None when the trial does not hold the text.
    shell_texts: tuple[tuple[ShellTextSource, ParsedShellText | None], ...]
    code_texts: tuple[RanCodeText, ...]


def parse_ran_texts_of_calls(
    calls: Sequence[ToolCall], poll_links: PollLinks
) -> list[ParsedRanTexts]:
    """Parse the texts that each call of a trial ran, one result per call in call order.

    The calls are read in order, so a file is known with the content that the calls before the run wrote.
    """
    written_files = WrittenFiles()
    return [_parse_ran_texts(call, written_files, poll_links) for call in calls]


def _parse_ran_texts(
    call: ToolCall,
    written_files: WrittenFiles,
    poll_links: PollLinks,
) -> ParsedRanTexts:
    """Parse the texts a call ran, then the files and heredocs their commands run, and record what they write.

    The steps of a tool script are read in order, so a file that one step writes is known to a later step that runs it.
    A call that the tool did not run writes nothing.
    """
    records_writes = may_have_run(call)
    collector = _RanTextCollector(
        call.raw.key, written_files, records_writes=records_writes
    )
    for step_index, step in action_steps_with_index(call.action):
        if isinstance(step, RunCommandAction):
            source = (
                CallCommandText() if step_index is None else ScriptStepText(step_index)
            )
            collector.add_text(source, step.command_str)
        elif isinstance(step, PollAction) and (text := typed_text(step)) is not None:
            started_by = poll_links.starting_call_of_poll_step.get(
                (call.raw.key, step_index)
            )
            source = PollInputText(step_index, started_by)
            collector.add_text(source, text)
        elif records_writes:
            written_files.record_tool_step(step, call.raw.key)
    return ParsedRanTexts(tuple(collector.shell_texts), tuple(collector.code_texts))


class _RanTextCollector:
    """Collector of the texts of one call, which gives their commands ids that are unique within the call."""

    def __init__(
        self,
        call_key: ToolCallKey,
        written_files: WrittenFiles,
        *,
        records_writes: bool,
    ) -> None:
        self._call_key = call_key
        self._written_files = written_files
        # False for a call that the tool did not run, whose commands wrote nothing.
        self._records_writes = records_writes
        self._next_command_id = 0
        self.shell_texts: list[tuple[ShellTextSource, ParsedShellText | None]] = []
        self.code_texts: list[RanCodeText] = []

    def add_text(self, source: ShellTextSource, text: str | None) -> None:
        """Parse one of the call's own texts and the texts its commands run."""
        self._add_shell_text(source, text, runner=None, running_file_paths=())

    def _add_shell_text(
        self,
        source: ShellTextSource,
        text: str | None,
        *,
        runner: ShellCommand | None,
        running_file_paths: tuple[str, ...],
    ) -> None:
        """Parse a shell text with ids after those given so far, then walk its commands."""
        if text is None:
            self.shell_texts.append((source, None))
            return
        parsed = parse_shell(text, runner=runner, first_id=self._next_command_id)
        self._next_command_id += len(parsed.commands)
        self.shell_texts.append((source, parsed))
        for command in parsed.commands:
            if self._records_writes:
                self._written_files.record_command(command, self._call_key)
            self._add_texts_run_by(command, running_file_paths)

    def _add_texts_run_by(
        self, command: ShellCommand, running_file_paths: tuple[str, ...]
    ) -> None:
        """Add the shell file, heredoc or code that a command runs, if any.

        A file that is already running is not read again, e.g. a script that runs itself.
        """
        path = _shell_file_run_by(command)
        if path is not None:
            if any(can_name_same_file(path, running) for running in running_file_paths):
                return
            write = self._written_files.latest_write(path)
            source = FileText(command.id, path, write.written_by if write else None)
            content = write.content if write else None
            self._add_shell_text(
                source,
                content,
                runner=command,
                running_file_paths=(*running_file_paths, path),
            )
        elif runs_stdin_as_shell_text(command):
            self._add_shell_text(
                StdinText(command.id),
                command.stdin_text,
                runner=command,
                running_file_paths=running_file_paths,
            )
        elif (code_text := self._code_text_run_by(command)) is not None:
            self.code_texts.append(code_text)

    def _code_text_run_by(self, command: ShellCommand) -> RanCodeText | None:
        """Find the Python or JavaScript code that a command runs, from an argument, its stdin or a file.

        The code program can come after programs that run the next program, e.g. tsx in `npx tsx get.ts`.
        """
        words = last_program_words(program_words(command))
        code_program = CODE_PROGRAMS.get(words[0]) if words else None
        if code_program is None:
            return self._directly_run_code_file(command)
        parsed = parse_arguments(words[0], words[1:])
        inline_codes = parsed.option_values(*code_program.inline_code_options)
        if inline_codes:
            return RanCodeText(
                ArgumentText(command.id), code_program.language, inline_codes[0]
            )
        plain_arguments = parsed.plain_arguments
        if code_program.file_subcommand is not None and plain_arguments[:1] == (
            code_program.file_subcommand,
        ):
            plain_arguments = plain_arguments[1:]
        path = plain_arguments[0] if plain_arguments else None
        if (
            code_program.needs_code_file_extension
            and path is not None
            and _file_extension(path) not in LANGUAGE_OF_FILE_EXTENSION
        ):
            return None
        if path is None or path == "-":
            if command.stdin_text is None:
                return None
            return RanCodeText(
                StdinText(command.id), code_program.language, command.stdin_text
            )
        return self._code_file_text(command.id, path, code_program.language)

    def _directly_run_code_file(self, command: ShellCommand) -> RanCodeText | None:
        """Find a code file that a command runs by its path, e.g. ./get.py, with the language its extension gives."""
        word = program_word_as_written(command)
        extension = _file_extension(word) if word and "/" in word else None
        language = LANGUAGE_OF_FILE_EXTENSION.get(extension) if extension else None
        if word is None or language is None:
            return None
        return self._code_file_text(command.id, word, language)

    def _code_file_text(
        self, runner_command_id: int, path: str, language: CodeLanguage
    ) -> RanCodeText:
        """Make the code text of a file, with the content the trial last wrote to it, or None when it shows none."""
        write = self._written_files.latest_write(path)
        source = FileText(runner_command_id, path, write.written_by if write else None)
        return RanCodeText(source, language, write.content if write else None)


def _shell_file_run_by(command: ShellCommand) -> str | None:
    """Find the shell file a command runs, e.g. fetch.sh for `bash fetch.sh` or ./fetch.sh run by its path."""
    path = shell_file_path(command)
    if path is not None:
        return path
    word = program_word_as_written(command)
    if word and "/" in word and _file_extension(word) in SHELL_FILE_EXTENSIONS:
        return word
    return None


def _file_extension(path: str) -> str | None:
    """Take the extension of a path's last component, e.g. .sh for ./fetch.sh."""
    match = _FILE_EXTENSION_AT_END.search(path.rsplit("/", 1)[-1])
    return match.group(0) if match else None
