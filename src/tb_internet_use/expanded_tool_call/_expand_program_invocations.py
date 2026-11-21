"""Read the words of one command into the programs they run, the outermost first, with the role of each word, asking the program catalogs through `ExpandedToolCallKnowledge`.

A command can run several programs, e.g. sudo, then bash in `sudo bash -c 'curl u'`, or find, then chmod in `find . -exec chmod +x {} ;`.
Which word is an option, an option value, a file or the next program differs from program to program, so every such answer comes from a catalog row, and a word that no row covers is kept as unread or unknown.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_word_with_expansion_as_one_argument,
)
from tb_internet_use.expanded_tool_call.model import (
    ProgramArgumentWord,
    ProgramBehavior,
    ProgramInvocation,
    ProgramOption,
    ProgramOptionBehavior,
    ProgramOptionWord,
    ProgramWordRole,
    SameAsArgumentRole,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownOptionsEndAtFirstArgument,
    UnknownProgramBehavior,
    UnknownProgramInvocation,
    UnknownProgramOptionWord,
    UnknownProgramWordRole,
)
from tb_internet_use.tool_call.model import ShellCommand

if TYPE_CHECKING:
    # `ExpandedToolCallKnowledge` is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
        ExpandedToolCallKnowledge,
    )

# A `NAME=value` word as shell grammar writes an assignment, e.g. `A=1` in `env A=1 curl u`.
_ASSIGNMENT_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# The word that ends the options of a program, after which every word is an argument.
_END_OF_OPTIONS_WORD = "--"
# Words that start like an option and hold none, i.e. the `-` that stands for stdin or stdout in `cat - log` and the lone `+` of `expr 1 + 2`.
_WORDS_WITHOUT_OPTIONS = frozenset({"-", "+"})
# The value `-` means stdout or stdin for many programs, e.g. `curl -o - u` writes to stdout, but no column of `program_option_behaviors.csv` says so for an option.
# So when the row of the option gives its value a role that names a file, the role of that value is unknown, whether the value is the next word as in `-o -` or sits in the word of the option as in `-o-` and `--output=-`.
_STDIN_OR_STDOUT_VALUE = "-"
# The roles that name a file.
_FILE_ROLES = frozenset(
    {
        ProgramWordRole.RUN_FILE,
        ProgramWordRole.READ_FILE,
        ProgramWordRole.USED_FILE,
        ProgramWordRole.SIZE_OR_TYPE_FILE,
        ProgramWordRole.WRITTEN_FILE,
        ProgramWordRole.APPENDED_FILE,
        ProgramWordRole.WRITTEN_FILE_SOURCE,
        ProgramWordRole.CHANGED_FILE,
        ProgramWordRole.COPY_SOURCE,
        ProgramWordRole.COPY_DESTINATION,
        ProgramWordRole.DELETED_FILE,
        ProgramWordRole.METADATA_CHANGED_FILE,
    }
)


def expand_program_invocations(
    shell_command: ShellCommand,
    *,
    knowledge: ExpandedToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[
    tuple[ProgramInvocation | UnknownProgramInvocation, ...],
    tuple[ProgramWordRole | UnknownProgramWordRole | None, ...],
    tuple[ProgramBehavior | UnknownProgramBehavior, ...],
    tuple[int, ...],
]:
    """Read the words of a command into the programs they run, the outermost first, and give the role of each word, the row of each program and the index of the word of each program.

    The roles have one entry per word of `shell_command.words`. A program word, a subcommand word, a word that holds an option name and the `--` that ends the options have None.
    The rows have one entry per program, in the order of the programs, and `UnknownProgramBehavior` for an `UnknownProgramInvocation`.
    They are given so that later code reads a fact of a program, e.g. how much of piped input tail passes on, without asking `ExpandedToolCallKnowledge` again, which would count the row twice.
    The program word indexes are 0-based in `shell_command.words`, one per program in the order of the programs, e.g. `(0, 3)` for find and ./run.sh in `find . -exec ./run.sh ;`, so that later code finds the word of a program that words of an outer program follow.
    Every use of `treat_word_with_expansion_as_one_argument` adds one to `judgment_rule_use_counts`.
    """
    command_state = _CommandState(shell_command, knowledge, judgment_rule_use_counts)
    command_state.add_program_invocations(
        0, len(shell_command.words), gets_more_arguments_at_run_time=False
    )
    return (
        tuple(command_state.program_invocations),
        tuple(command_state.roles),
        tuple(command_state.program_behaviors),
        tuple(command_state.program_word_indexes),
    )


class _CommandState:
    """State kept during one `expand_program_invocations` call, shared by the states of the programs of its command.

    A next program is read only once all words of the program that runs it are placed, since an option after the first argument can change which word starts it, e.g. `-exec` of find.
    """

    def __init__(
        self,
        shell_command: ShellCommand,
        knowledge: ExpandedToolCallKnowledge,
        judgment_rule_use_counts: Counter[str],
    ) -> None:
        self.words = shell_command.words
        self.expansion_word_indexes = frozenset(shell_command.expansion_word_indexes)
        self.knowledge = knowledge
        self.judgment_rule_use_counts = judgment_rule_use_counts
        # The programs read so far, in the order of their program words.
        self.program_invocations: list[
            ProgramInvocation | UnknownProgramInvocation
        ] = []
        # The row of each program in `program_invocations`, at the same index.
        self.program_behaviors: list[ProgramBehavior | UnknownProgramBehavior] = []
        # The 0-based index of the word of each program in `program_invocations`, at the same index.
        self.program_word_indexes: list[int] = []
        # Each entry is set by the state of the program that the word belongs to.
        self.roles: list[ProgramWordRole | UnknownProgramWordRole | None] = [
            None
        ] * len(shell_command.words)

    def add_program_invocations(
        self,
        program_word_index: int,
        end_word_index: int,
        *,
        gets_more_arguments_at_run_time: bool,
    ) -> None:
        """Read the program whose word is at the 0-based `program_word_index` and the next programs it runs, from the words up to `end_word_index`, exclusive, and add them to `program_invocations`."""
        if program_word_index >= end_word_index:
            return
        program_word = self.words[program_word_index]
        if program_word_index in self.expansion_word_indexes:
            # The program is known only when the command runs, so no catalog row can answer for it.
            self.add_unknown_program_invocation(
                program_word_index, end_word_index, program_word
            )
            return
        # A word that ends with `/`, e.g. `dir/`, has nothing left without its folder, so it stays as written.
        program_name = program_word.rsplit("/", 1)[-1] or program_word
        program_behavior = self.knowledge.program_behavior(
            program_name, self.words[program_word_index + 1 : end_word_index]
        )
        if isinstance(program_behavior, UnknownProgramBehavior):
            self.add_unknown_program_invocation(
                program_word_index, end_word_index, program_name
            )
            return
        program_words_state = _ProgramWordsState(
            self, program_behavior, program_word_index, end_word_index
        )
        program_words_state.place_words()
        program_words_state.settle_places()
        program_words_state.set_roles()
        self.program_invocations.append(
            program_words_state.program_invocation_for(
                gets_more_arguments_at_run_time=gets_more_arguments_at_run_time
            )
        )
        self.program_behaviors.append(program_behavior)
        self.program_word_indexes.append(program_word_index)
        for next_program_range in program_words_state.next_program_ranges_for(
            gets_more_arguments_at_run_time=gets_more_arguments_at_run_time
        ):
            self.add_program_invocations(
                next_program_range.program_word_index,
                next_program_range.end_word_index,
                gets_more_arguments_at_run_time=next_program_range.gets_more_arguments_at_run_time,
            )

    def add_unknown_program_invocation(
        self, program_word_index: int, end_word_index: int, program_name: str
    ) -> None:
        """Add an `UnknownProgramInvocation` for the words from the 0-based `program_word_index` up to `end_word_index`, whose roles are then unknown."""
        self.program_invocations.append(
            UnknownProgramInvocation(
                program_name, self.words[program_word_index + 1 : end_word_index]
            )
        )
        self.program_behaviors.append(UnknownProgramBehavior())
        self.program_word_indexes.append(program_word_index)
        self.roles[program_word_index] = None
        for word_index in range(program_word_index + 1, end_word_index):
            self.roles[word_index] = UnknownProgramWordRole()


@dataclass(frozen=True, slots=True)
class _NextProgramRange:
    """Words of a next program that the state of the program before it found, read by `_CommandState.add_program_invocations` once that program is added."""

    # The 0-based index of the program word in `ShellCommand.words`.
    program_word_index: int
    # The 0-based index after its last word, i.e. of its end word or the end of the command.
    end_word_index: int
    gets_more_arguments_at_run_time: bool


@dataclass(frozen=True, slots=True)
class _PlacedProgramOption:
    """Option that `_ProgramWordsState` placed, with the row that covers it and the indexes of its words."""

    # As `ProgramOption.name` holds it, e.g. `-o` for `-oout`.
    name: str
    # The value in the word of the name or in the next word, None when it has none.
    value: str | None
    program_option_behavior: ProgramOptionBehavior
    # The 0-based index of the word that holds the option name.
    word_index: int
    # The 0-based index of the word that is the value, None when the value sits in the word of the name, e.g. `-oout`, or there is none.
    value_word_index: int | None

    def has_next_program_end_words(self) -> bool:
        """Tell whether the option starts a next program that ends at one of its end words, e.g. `-exec` of find."""
        return bool(self.program_option_behavior.next_program_end_words)


class _ProgramWordsState:
    """State of the words of one program of a command, from its program word to the end of its range, kept by `_CommandState.add_program_invocations` until the program is added.

    The roles of the arguments come from the program row and the rows of the options of the command together, so they are settled only after all of its words are placed.
    """

    def __init__(
        self,
        command_state: _CommandState,
        program_behavior: ProgramBehavior,
        program_word_index: int,
        end_word_index: int,
    ) -> None:
        self.command_state = command_state
        self.program_behavior = program_behavior
        # The 0-based index of the program word.
        self.program_word_index = program_word_index
        # The 0-based index after the last word of the range.
        self.end_word_index = end_word_index
        # Whether the subcommand words of the row are still to come, e.g. after `-y` of `apt-get -y install curl`, since options of the program may stand before them.
        self.is_before_subcommand = bool(program_behavior.subcommand_words)
        self.placed_program_options: list[_PlacedProgramOption] = []
        # The 0-based indexes of the words that are arguments and take a role from their place among them, in word order.
        self.placed_argument_indexes: list[int] = []
        # The 0-based indexes of the arguments whose role is `OTHER` whatever their place, i.e. skipped assignments and end words of a next program.
        self.other_argument_indexes: list[int] = []
        # The 0-based index of the first unread word, None when every word was placed.
        self.first_unread_word_index: int | None = None
        # The 0-based index of the argument whose role is `PROGRAM`, None when none has it.
        self.next_program_word_index: int | None = None
        # The words of next programs that options start, e.g. `-exec` of find.
        self.next_program_ranges_of_options: list[_NextProgramRange] = []

    def place_words(self) -> None:
        """Place the words after the program word left to right as options, values, subcommand words and arguments, up to an unread word, the argument that starts the next program or the end.

        Before the subcommand only options of the program without a subcommand are read, as `ExpandedToolCallKnowledge.program_behavior` skipped them to find the subcommand.
        """
        command_state = self.command_state
        words = command_state.words
        word_index = self.program_word_index + 1
        after_end_of_options = False
        while word_index < self.end_word_index:
            word = words[word_index]
            if self.is_before_subcommand and not (
                word_index not in command_state.expansion_word_indexes
                and word.startswith("-")
                and word not in (*_WORDS_WITHOUT_OPTIONS, _END_OF_OPTIONS_WORD)
            ):
                subcommand_words = self.program_behavior.subcommand_words
                subcommand_end_index = word_index + len(subcommand_words)
                if tuple(words[word_index:subcommand_end_index]) != subcommand_words:
                    # `ExpandedToolCallKnowledge` found the subcommand after the options it skipped, so another word here is not read.
                    self.first_unread_word_index = word_index
                    return
                self.is_before_subcommand = False
                word_index = subcommand_end_index
                continue
            if self.is_skipped_assignment_word(word):
                self.other_argument_indexes.append(word_index)
                word_index += 1
                continue
            program_option_word = None
            if (
                not after_end_of_options
                and word_index not in command_state.expansion_word_indexes
                and self.may_be_option_word(word)
            ):
                if word.startswith("-") and self.is_option_place_unknown():
                    # The word may be an option or an argument, e.g. `-v` of `printf %s -v`, so it is read as neither, as a word without an option row is not.
                    self.first_unread_word_index = word_index
                    return
                if (
                    word == _END_OF_OPTIONS_WORD
                    and self.program_behavior.takes_non_option_dash_words_as_arguments
                    is not True
                ):
                    after_end_of_options = True
                    word_index += 1
                    continue
                program_option_word = command_state.knowledge.program_option_word(
                    self.program_behavior,
                    word,
                    is_before_subcommand=self.is_before_subcommand,
                )
                if (
                    isinstance(program_option_word, ProgramOptionWord)
                    and self.is_option_place_unknown()
                ):
                    # A word that starts with `+` is an option only for a program with such an option, e.g. `+o` of `plusprog a +o`, and here even that is not known.
                    self.first_unread_word_index = word_index
                    return
            if program_option_word is None or isinstance(
                program_option_word, ProgramArgumentWord
            ):
                if self.is_next_program_word(word_index):
                    self.next_program_word_index = word_index
                    return
                self.placed_argument_indexes.append(word_index)
                word_index += 1
                continue
            if isinstance(program_option_word, UnknownProgramOptionWord):
                self.first_unread_word_index = word_index
                return
            last_option = program_option_word.options[-1]
            takes_next_word = (
                last_option.program_option_behavior.takes_value
                and last_option.attached_value is None
            )
            if takes_next_word and word_index + 1 >= self.end_word_index:
                # The last option takes a value, but the command ends before it, e.g. `curl -o`, so the word is unread.
                self.first_unread_word_index = word_index
                return
            value_word_index = word_index + 1 if takes_next_word else None
            next_program_range_count = len(self.next_program_ranges_of_options)
            self.add_options_of_word(word_index, program_option_word, value_word_index)
            word_index = (
                word_index if value_word_index is None else value_word_index
            ) + 1
            if len(self.next_program_ranges_of_options) > next_program_range_count:
                # The words of the next program that the option starts are not this program's, and its end word is an argument of this program, e.g. `;` of `-exec chmod +x {} ;`.
                end_word_index = self.next_program_ranges_of_options[-1].end_word_index
                if end_word_index < self.end_word_index:
                    self.other_argument_indexes.append(end_word_index)
                word_index = end_word_index + 1

    def is_skipped_assignment_word(self, word: str) -> bool:
        """Tell whether a word is a `NAME=value` that the program skips before the next program, e.g. `A=1` in `env A=1 curl u`."""
        return (
            self.program_behavior.skips_assignment_words
            and not self.placed_argument_indexes
            and _ASSIGNMENT_WORD.match(word) is not None
        )

    def may_be_option_word(self, word: str) -> bool:
        """Tell whether a word stands where an option can and starts with `-` or `+`, apart from a lone `-` or `+`."""
        if (
            self.program_behavior.options_end_at_first_argument is True
            and self.has_argument()
        ):
            return False
        return word.startswith(("-", "+")) and word not in _WORDS_WITHOUT_OPTIONS

    def is_option_place_unknown(self) -> bool:
        """Tell whether the program has an argument and its row leaves `options_end_at_first_argument` blank, so that whether a later word can be an option is not known.

        It asks `ExpandedToolCallKnowledge` only after an argument, and is called only for a word that the program then leaves unread when the answer is yes, so `ExpandedToolCallKnowledge` counts one unknown input per such word.
        """
        return self.has_argument() and isinstance(
            self.command_state.knowledge.options_end_at_first_argument(
                self.program_behavior
            ),
            UnknownOptionsEndAtFirstArgument,
        )

    def has_argument(self) -> bool:
        """Tell whether an argument of the program has been placed, a skipped assignment or an end word of a next program included."""
        return bool(self.placed_argument_indexes or self.other_argument_indexes)

    def is_next_program_word(self, word_index: int) -> bool:
        """Tell whether the argument at a 0-based word index starts the next program, i.e. whether its place has the role `PROGRAM` by the program row and the rows of the options placed so far.

        The word of the next program is the last argument of this program, since the words after it are the next program's.
        """
        position = len(self.placed_argument_indexes)
        role = _argument_role_for(
            self.program_behavior,
            position,
            position + 1,
            _role_changing_option_behaviors_of(self.placed_program_options),
        )
        return role == ProgramWordRole.PROGRAM

    def add_options_of_word(
        self,
        word_index: int,
        program_option_word: ProgramOptionWord,
        value_word_index: int | None,
    ) -> None:
        """Add the options that the word at a 0-based index holds, the last taking the word at `value_word_index` as its value when that is not None."""
        words = self.command_state.words
        last_position = len(program_option_word.options) - 1
        for position, option in enumerate(program_option_word.options):
            own_value_word_index = (
                value_word_index if position == last_position else None
            )
            self.add_program_option(
                _PlacedProgramOption(
                    option.name,
                    option.attached_value
                    if own_value_word_index is None
                    else words[own_value_word_index],
                    option.program_option_behavior,
                    word_index,
                    own_value_word_index,
                )
            )

    def add_program_option(self, placed_program_option: _PlacedProgramOption) -> None:
        """Add a placed option, and for an option that starts a next program up to an end word, e.g. `-exec` of find, the range of that program."""
        self.placed_program_options.append(placed_program_option)
        end_words = placed_program_option.program_option_behavior.next_program_end_words
        if not end_words:
            return
        words = self.command_state.words
        last_option_word_index = (
            placed_program_option.word_index
            if placed_program_option.value_word_index is None
            else placed_program_option.value_word_index
        )
        next_program_word_index = last_option_word_index + 1
        end_word_index = next(
            (
                word_index
                for word_index in range(next_program_word_index, self.end_word_index)
                if words[word_index] in end_words
            ),
            self.end_word_index,
        )
        self.next_program_ranges_of_options.append(
            _NextProgramRange(
                next_program_word_index,
                end_word_index,
                placed_program_option.program_option_behavior.gives_arguments_at_run_time,
            )
        )

    def settle_places(self) -> None:
        """Settle what the placed words are once all are placed, i.e. the letters of option clusters, an argument that later options make a next program, and the words that `treat_word_with_expansion_as_one_argument` reads."""
        self.place_option_clusters()
        self.make_words_unread_from_late_next_program_word()
        self.place_expansion_words_by_judgment_rule()

    def place_option_clusters(self) -> None:
        """Place each argument whose role is `OPTION_CLUSTER` as one-letter options, e.g. `xzf` in `tar xzf a.tgz`, whose values take the arguments after it in turn.

        A letter without a row, a letter whose value is missing, and a cluster word that holds an expansion make the cluster word and every word after it unread.
        """
        command_state = self.command_state
        words = command_state.words
        argument_count = self.argument_count
        option_behaviors = _role_changing_option_behaviors_of(
            self.placed_program_options
        )
        taken_word_indexes: set[int] = set()
        for position, word_index in enumerate(self.placed_argument_indexes):
            if word_index in taken_word_indexes:
                continue
            role = _argument_role_for(
                self.program_behavior, position, argument_count, option_behaviors
            )
            if role != ProgramWordRole.OPTION_CLUSTER:
                continue
            if word_index in command_state.expansion_word_indexes:
                # The letters are known only when the command runs.
                self.make_words_unread_from(word_index)
                return
            program_option_word = command_state.knowledge.program_option_word(
                self.program_behavior, words[word_index], is_option_cluster=True
            )
            if not isinstance(program_option_word, ProgramOptionWord):
                self.make_words_unread_from(word_index)
                return
            free_value_word_indexes = iter(
                later_word_index
                for later_word_index in self.placed_argument_indexes[position + 1 :]
                if later_word_index not in taken_word_indexes
            )
            cluster_options: list[_PlacedProgramOption] = []
            for option in program_option_word.options:
                value_word_index = None
                if option.program_option_behavior.takes_value:
                    value_word_index = next(free_value_word_indexes, None)
                    if value_word_index is None:
                        # The letter takes a value, but no argument is left for it, e.g. `tar xf`.
                        self.make_words_unread_from(word_index)
                        return
                cluster_options.append(
                    _PlacedProgramOption(
                        option.name,
                        None if value_word_index is None else words[value_word_index],
                        option.program_option_behavior,
                        word_index,
                        value_word_index,
                    )
                )
            for cluster_option in cluster_options:
                self.add_program_option(cluster_option)
                taken_word_indexes.add(word_index)
                if cluster_option.value_word_index is not None:
                    taken_word_indexes.add(cluster_option.value_word_index)

    def make_words_unread_from_late_next_program_word(self) -> None:
        """Make an argument unread with the words after it when the options placed after it give it the role `PROGRAM`, e.g. made-up `late a -m` where the row of `-m` makes the arguments programs.

        Such a word cannot start the next program, since those options would then be the next program's, and it cannot be an argument either, so what it is stays unknown.
        """
        while True:
            option_word_indexes = _option_word_indexes_of(self.placed_program_options)
            argument_count = self.argument_count
            option_behaviors = _role_changing_option_behaviors_of(
                self.placed_program_options
            )
            late_next_program_word_index = next(
                (
                    word_index
                    for position, word_index in enumerate(self.placed_argument_indexes)
                    if word_index not in option_word_indexes
                    and _argument_role_for(
                        self.program_behavior,
                        position,
                        argument_count,
                        option_behaviors,
                    )
                    == ProgramWordRole.PROGRAM
                ),
                None,
            )
            if late_next_program_word_index is None:
                return
            self.make_words_unread_from(late_next_program_word_index)

    def place_expansion_words_by_judgment_rule(self) -> None:
        """Ask `treat_word_with_expansion_as_one_argument` about each word with an expansion that ends as an argument or as the value of an option, e.g. `$OPTS` of `curl $OPTS u` and `$F` of `curl -o $F u`, and make it unread with the words after it when the rule says no.

        For a value, the word of its option becomes unread too, since the option is then missing its value.
        """
        command_state = self.command_state
        option_word_indexes = _option_word_indexes_of(self.placed_program_options)
        option_word_index_of_value_word_index = {
            placed_program_option.value_word_index: placed_program_option.word_index
            for placed_program_option in self.placed_program_options
            if placed_program_option.value_word_index is not None
        }
        for word_index in sorted(command_state.expansion_word_indexes):
            if word_index in option_word_index_of_value_word_index:
                first_unread_word_index = option_word_index_of_value_word_index[
                    word_index
                ]
            elif (
                word_index in self.placed_argument_indexes
                and word_index not in option_word_indexes
            ):
                first_unread_word_index = word_index
            else:
                continue
            if not treat_word_with_expansion_as_one_argument(
                command_state.words[word_index],
                use_counts=command_state.judgment_rule_use_counts,
            ):
                self.make_words_unread_from(first_unread_word_index)
                return

    def make_words_unread_from(self, word_index: int) -> None:
        """Make the word at a 0-based index and every word after it unread, dropping what was placed from them."""
        self.first_unread_word_index = word_index
        self.next_program_word_index = None
        self.placed_program_options = [
            placed_program_option
            for placed_program_option in self.placed_program_options
            if placed_program_option.word_index < word_index
        ]
        self.placed_argument_indexes = [
            argument_index
            for argument_index in self.placed_argument_indexes
            if argument_index < word_index
        ]
        self.other_argument_indexes = [
            argument_index
            for argument_index in self.other_argument_indexes
            if argument_index < word_index
        ]
        self.next_program_ranges_of_options = [
            next_program_range
            for next_program_range in self.next_program_ranges_of_options
            if next_program_range.program_word_index < word_index
        ]

    def set_roles(self) -> None:
        """Set the role of every word of the range that this program owns, i.e. all but the words of its next programs."""
        roles = self.command_state.roles
        # The program word, the subcommand words, the words of option names and the `--` that ends the options keep None, and the loops below set the other words.
        for word_index in range(self.program_word_index, self.index_after_own_words):
            roles[word_index] = None
        option_word_indexes = _option_word_indexes_of(self.placed_program_options)
        argument_count = self.argument_count
        option_behaviors = _role_changing_option_behaviors_of(
            self.placed_program_options
        )
        for position, word_index in enumerate(self.placed_argument_indexes):
            if word_index not in option_word_indexes:
                roles[word_index] = _argument_role_for(
                    self.program_behavior, position, argument_count, option_behaviors
                )
        for word_index in self.other_argument_indexes:
            roles[word_index] = ProgramWordRole.OTHER
        for placed_program_option in self.placed_program_options:
            value_role = self.value_role_of(placed_program_option)
            if placed_program_option.value_word_index is not None:
                roles[placed_program_option.value_word_index] = value_role
            elif placed_program_option.value == _STDIN_OR_STDOUT_VALUE and isinstance(
                value_role, UnknownProgramWordRole
            ):
                # The value `-` sits in the word of the option, e.g. `-o-`, so the word holds a value of unknown role.
                roles[placed_program_option.word_index] = value_role
        if self.first_unread_word_index is not None:
            for word_index in range(self.first_unread_word_index, self.end_word_index):
                roles[word_index] = UnknownProgramWordRole()

    def value_role_of(
        self, placed_program_option: _PlacedProgramOption
    ) -> ProgramWordRole | UnknownProgramWordRole | None:
        """Give the role of the value of an option, from its row unless another option of the command names it in `changed_option_name`, unknown for a `-` that the row reads as a file, and None for an option that takes no value."""
        changed_roles = [
            other.program_option_behavior.changed_option_value_role
            for other in self.placed_program_options
            if other.program_option_behavior.changed_option_name
            == placed_program_option.name
        ]
        value_role = _answer_of_program_row_and_option_rows(
            placed_program_option.program_option_behavior.value_role,
            changed_roles,
            unknown=UnknownProgramWordRole(),
        )
        if (
            placed_program_option.value == _STDIN_OR_STDOUT_VALUE
            and value_role in _FILE_ROLES
        ):
            return UnknownProgramWordRole()
        return value_role

    def program_invocation_for(
        self, *, gets_more_arguments_at_run_time: bool
    ) -> ProgramInvocation:
        """Give the `ProgramInvocation` of the placed words."""
        words = self.command_state.words
        option_word_indexes = _option_word_indexes_of(self.placed_program_options)
        arguments = tuple(
            words[word_index]
            for word_index in sorted(
                [*self.placed_argument_indexes, *self.other_argument_indexes]
            )
            if word_index not in option_word_indexes
        )
        unread_words = (
            ()
            if self.first_unread_word_index is None
            else words[self.first_unread_word_index : self.end_word_index]
        )
        return ProgramInvocation(
            program_name=self.program_behavior.program_name,
            subcommand_words=self.program_behavior.subcommand_words,
            options=tuple(
                ProgramOption(placed_program_option.name, placed_program_option.value)
                for placed_program_option in self.placed_program_options
            ),
            arguments=arguments,
            gets_more_arguments_at_run_time=gets_more_arguments_at_run_time,
            unread_words=unread_words,
            exits_with_exit_code_of_next_program=self.exits_with_exit_code_of_next_program_of_words(),
        )

    def exits_with_exit_code_of_next_program_of_words(
        self,
    ) -> bool | UnknownExitsWithExitCodeOfNextProgram:
        """Give whether the program ends with the exit code of the next program, from its row unless options of the command change it, and unknown when two options change it differently.

        A yes becomes False when all of its words are placed and none starts a next program, e.g. `sudo` alone, since then it runs none. A blank cell stays unknown, since a word of unknown role may still run one.
        """
        answer = _answer_of_program_row_and_option_rows(
            self.program_behavior.exits_with_exit_code_of_next_program,
            [
                placed_program_option.program_option_behavior.exits_with_exit_code_of_next_program_with_option
                for placed_program_option in self.placed_program_options
            ],
            unknown=UnknownExitsWithExitCodeOfNextProgram(),
        )
        runs_next_program = self.next_program_word_index is not None or any(
            next_program_range.program_word_index < next_program_range.end_word_index
            for next_program_range in self.next_program_ranges_of_options
        )
        if (
            answer is True
            and not runs_next_program
            and self.first_unread_word_index is None
        ):
            return False
        return answer

    def next_program_ranges_for(
        self, *, gets_more_arguments_at_run_time: bool
    ) -> list[_NextProgramRange]:
        """Give the ranges of the next programs of the placed words in word order, those that options start and the one that starts at the argument whose role is `PROGRAM`."""
        next_program_ranges = list(self.next_program_ranges_of_options)
        if self.next_program_word_index is not None:
            next_program_ranges.append(
                _NextProgramRange(
                    self.next_program_word_index,
                    self.end_word_index,
                    gets_more_arguments_at_run_time
                    or self.program_behavior.gives_arguments_at_run_time
                    or any(
                        option_behavior.gives_arguments_at_run_time
                        for option_behavior in _role_changing_option_behaviors_of(
                            self.placed_program_options
                        )
                    ),
                )
            )
        return sorted(
            next_program_ranges,
            key=lambda next_program_range: next_program_range.program_word_index,
        )

    @property
    def argument_count(self) -> int:
        """Give the number of places among the arguments, the word of the next program included as the last."""
        return len(self.placed_argument_indexes) + (
            0 if self.next_program_word_index is None else 1
        )

    @property
    def index_after_own_words(self) -> int:
        """Give the 0-based index after the last word that this program owns, before unread words and the next program."""
        for stop_word_index in (
            self.first_unread_word_index,
            self.next_program_word_index,
        ):
            if stop_word_index is not None:
                return stop_word_index
        return self.end_word_index


def _option_word_indexes_of(
    placed_program_options: Sequence[_PlacedProgramOption],
) -> set[int]:
    """Collect the 0-based indexes of the words that hold option names or values, a cluster word and the arguments its letters take included."""
    option_word_indexes = {
        placed_program_option.word_index
        for placed_program_option in placed_program_options
    }
    option_word_indexes.update(
        placed_program_option.value_word_index
        for placed_program_option in placed_program_options
        if placed_program_option.value_word_index is not None
    )
    return option_word_indexes


def _role_changing_option_behaviors_of(
    placed_program_options: Sequence[_PlacedProgramOption],
) -> list[ProgramOptionBehavior]:
    """List the rows of the placed options that change the roles of the arguments, i.e. all but those whose next program ends at an end word, e.g. `-exec` of find, since that program starts right after them."""
    return [
        placed_program_option.program_option_behavior
        for placed_program_option in placed_program_options
        if not placed_program_option.has_next_program_end_words()
    ]


def _argument_role_for(
    program_behavior: ProgramBehavior,
    position: int,
    argument_count: int,
    option_behaviors: Sequence[ProgramOptionBehavior],
) -> ProgramWordRole | UnknownProgramWordRole:
    """Give the role of the argument at a 0-based place among a number of arguments, by the program row and the option rows together."""
    argument_role = _answer_of_program_row_and_option_rows(
        program_behavior.argument_role,
        [behavior.argument_role_with_option for behavior in option_behaviors],
        unknown=UnknownProgramWordRole(),
    )
    if argument_count == 1 or position == 0:
        place_role = _answer_of_program_row_and_option_rows(
            program_behavior.first_argument_role,
            [behavior.first_argument_role_with_option for behavior in option_behaviors],
            unknown=UnknownProgramWordRole(),
        )
    elif position == argument_count - 1:
        place_role = _answer_of_program_row_and_option_rows(
            program_behavior.last_argument_role,
            [behavior.last_argument_role_with_option for behavior in option_behaviors],
            unknown=UnknownProgramWordRole(),
        )
    else:
        return argument_role
    if isinstance(place_role, SameAsArgumentRole):
        return argument_role
    return place_role


def _answer_of_program_row_and_option_rows[Answer, Unknown](
    program_answer: Answer,
    option_answers: Sequence[Answer | None],
    *,
    unknown: Unknown,
) -> Answer | Unknown:
    """Give the answer of the program row unless the options of the command change it, i.e. the one answer that all changing options give, or `unknown` when two of them differ.

    An option answer of None keeps the answer of the program row.
    """
    changed_answers = [answer for answer in option_answers if answer is not None]
    if not changed_answers:
        return program_answer
    first_answer = changed_answers[0]
    if all(answer == first_answer for answer in changed_answers):
        return first_answer
    return unknown
