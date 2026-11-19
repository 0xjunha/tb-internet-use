"""Split a shell text into its simple commands, with when each runs and where its output goes, by bash grammar alone.

The text is read as bash reads it, also when another shell such as sh runs it, since the trajectories do not say which shell a harness runs.
Besides the grammar, the reading knows the few words of the shell itself that change how later parts of the same text run, i.e. `set -e` and `set -o pipefail`, `exec` with redirects only, `exit`, `return` and the redirect targets `/dev/null`, `/dev/stdout` and `/dev/stderr`.
It also knows the reserved word `time` with its `-p`, which starts a pipeline and is no word of its first command, e.g. `time -p curl u` runs curl u.
It knows no program, so text that a command runs, e.g. `curl u` in `bash -c 'curl u'` or in `eval 'curl u'`, stays one word of that command.
A caller that reads such a text passes the command that runs it as `runner`.

tree-sitter-bash 0.25.1 misreads a few shapes.
The walk reads them as bash runs them, and each place says which shape it handles.

Known limits, rare in the trajectories
- After `!` the deciding commands are unknown, e.g. for b in `! a && b`.
- A `$(...)` written like one in `command_substitution_texts_run_by_outer_shell` counts as that one.
- `exec > log` changes later output only when it stands alone, not in `exec > log || x`.
- `set -e` is off inside `$(...)` as in bash, also when the shell is sh.
- A `set` in a function body is taken to hold in the body only.
- tree-sitter misreads `$"..."`, an escaped line break inside a word, `! { a; b; }` and backticks in heredocs.
- tree-sitter misreads what `time` times when it starts with a reserved word, `((` or an assignment, or when a redirect leaves words beside a timed subshell, e.g. `time { a; }`, `time ! a`, `time A=1 b` or `time (a) > f b`.
  The words keep `time` there, and the commands of the text are marked as maybe wrong.
- `time` alone and `time -p` alone stay a command, although bash runs nothing for them.
- A `-` written right before a heredoc operator, as in `python -<<EOF`, is part of the operator to tree-sitter and is lost.
- Words after a redirect that closes a descriptor, e.g. a in `cmd 2>&- a`, and a `-` between a heredoc start and a later redirect, e.g. in `cmd <<EOF - 2>&1 a`, are lost. Neither occurs in the trajectories.
- In a redirect that tree-sitter misread, what follows its first target is lost, and that can be whole commands, not only words.
  For example `python - <<EOF 2>&1 | tail -5` gives python alone with its stdout to the result, without `tail -5` and the pipe to it.
  The text has a syntax error then, so its commands are marked.
  Words after the redirect target of a statement that is no simple command, e.g. b in `{ a; } > f b`, are lost too, and the commands are marked.
"""

import itertools
import re
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from functools import partial
from typing import Any, NamedTuple

import tree_sitter_bash
from tree_sitter import Language, Node, Parser, Tree

from tb_internet_use.tool_call.judgment_rules import (
    treat_lines_joined_after_three_repairs_as_left_joined,
)
from tb_internet_use.tool_call.model import (
    CaptureDestination,
    DiscardDestination,
    ExitOutcome,
    FileDestination,
    OutputDestination,
    ParsedShellText,
    PipeDestination,
    ResultDestination,
    RunCondition,
    ShellCommand,
    UnreadableShellText,
    VariableAssignment,
)

_PARSER = Parser(Language(tree_sitter_bash.language()))
# Node types whose value is known only when the text runs.
_EXPANSION_NODE_TYPES = frozenset(
    {
        "simple_expansion",  # `$A`
        "expansion",  # `${A:-x}`
        "command_substitution",  # `$(ls)` or `` `ls` ``
        "process_substitution",  # `<(ls)` or `>(ls)`
        "arithmetic_expansion",  # `$((1 + 2))`
    }
)
# Outside quotes, a backslash keeps the next character as is.
# Before a line break, it joins the two lines.
_UNQUOTED_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
# Inside double quotes, a backslash escapes only these characters.
_DOUBLE_QUOTED_ESCAPE = re.compile(r'\\([$`"\\\n])')
# Statements that end the text when they fail under `set -e`.
# A list such as `a && b` does not, and an assignment does only with a `$(...)`.
_ERREXIT_STATEMENT_TYPES = frozenset(
    {
        "command",
        "pipeline",
        "redirected_statement",
        "subshell",
        "compound_statement",
        "test_command",
        "variable_assignment",
        "variable_assignments",
    }
)
# ShellCommand fields that a command takes from the scope it is in.
_FIELDS_FROM_SCOPE = (
    "stdin_text",
    "is_heredoc_delimiter_quoted",
    "stdin_file_path",
    "stdout",
    "stderr",
    "runs_if",
    "in_loop_body",
    "in_function_body",
    "in_case_branch",
    "succeeded_if_text_exits_zero",
    "structure_may_be_wrong",
)
# Fields that text run by a command takes from that command.
# Stdin is left out. That is right for the heredoc of `bash <<EOF`, which is the text itself,
# and misses a file that the text's commands read, e.g. log for grep in `bash -c 'grep x' < log`.
_FIELDS_FROM_RUNNER = tuple(
    name
    for name in _FIELDS_FROM_SCOPE
    if name not in ("stdin_text", "is_heredoc_delimiter_quoted", "stdin_file_path")
)
# A quote or backslash in a heredoc delimiter, e.g. in `<<'EOF'`, `<<"EOF"` or `<<\EOF`, which keeps the shell from expanding the body.
_HEREDOC_DELIMITER_QUOTING = re.compile(r"['\"\\]")
# A word such as {a,b} or {1..3}, which bash turns into several words.
_BRACE_LIST = re.compile(r"\{[^{}\s]*,[^{}\s]*\}|\{\w+\.\.\w+\}")
# A glob character that a backslash does not escape, e.g. * in *.txt.
_GLOB_CHARACTER = re.compile(r"(?<!\\)[*?[]")
# A line break that ends a command, not one escaped by a backslash.
_UNESCAPED_LINE_BREAK = re.compile(rb"(?<!\\)\n")
# A comment, which starts with # after a space.
_COMMENT_START = re.compile(rb"(?:^|\s)#")
# How many times a text is parsed again to keep joined lines apart before `treat_lines_joined_after_three_repairs_as_left_joined` decides whether to go on.
_MAX_LINE_REPAIRS = 3
# A cluster of one-letter options of `set`, e.g. -e, +e or -euo.
_SET_OPTION_CLUSTER = re.compile(r"[-+][a-zA-Z]+")
# Text between two parts of a command that is a `-` word alone, e.g. ` - ` in `python - <<EOF`.
_LOST_DASH = re.compile(rb"\s+-\s+")
# The start of a word that bash reads as an assignment before a command, e.g. `A=` of `A=1` or `a[0]=` of `a[0]=1` in `time A=1 b`, which tree-sitter reads as a word after `time`.
_ASSIGNMENT_WORD_START = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
# Reserved words that bash reads after `time` as the start of the statement it times, i.e. a compound command, a negation (`!`), a function definition or a coprocess.
# tree-sitter reads them as plain words, e.g. `{` in `time { a; }`.
_RESERVED_WORDS_MISREAD_AFTER_TIME = frozenset(
    [
        "!",
        "{",
        "[[",
        "case",
        "coproc",
        "for",
        "function",
        "if",
        "select",
        "until",
        "while",
    ]
)

# The ids of the commands whose exit code can be a statement's.
# None when unknown, e.g. for `! a`, `[ -f x ]` or an if statement.
type _DecidingCommandIds = tuple[int, ...] | None
# Walks one statement under a scope.
type _StatementWalk = Callable[[_Scope], _DecidingCommandIds]
# The node types that tree-sitter puts in a command for the statement that `time` times, e.g. `(a && b)` in `time (a && b)`.
_TIMED_STATEMENT_TYPES = frozenset(["subshell", "compound_statement"])
# A word node of a command, or a `-` word that tree-sitter left out of the tree.
type _CommandWord = Node | _LostDash


def parse_shell_text(
    shell_text: str,
    *,
    judgment_rule_use_counts: Counter[str],
    first_command_id: int = 0,
    runner: ShellCommand | None = None,
    set_arguments_at_start: tuple[str, ...] = (),
    command_substitution_texts_run_by_outer_shell: frozenset[str] = frozenset(),
) -> ParsedShellText | UnreadableShellText:
    """Split a shell text into its simple commands, recording when each runs and where its output goes.

    Pass `runner` when another command runs the text, e.g. `cd x && bash fetch.sh > log` for the content of fetch.sh, or `bash <<EOF` for its heredoc.
    The text's commands then take the runner's run conditions (cd must succeed) and output destination (log), but not its stdin.
    Pass `set_arguments_at_start` for the shell options the text starts with, as `set` takes them, e.g. `("-e",)` for `bash -e fetch.sh` or `("-o", "pipefail")`.
    Reading stops at the first word that is neither a cluster of one-letter options nor the name after `-o` or `+o`.
    Pass `command_substitution_texts_run_by_outer_shell` for each `$(...)` or backticks that the shell running `runner` already ran, e.g. `$(a)` for the text of `bash -c "echo $(a)"`, so that its commands are not added again.
    Pass `first_command_id` to keep ids unique when one call runs several texts.

    A text with a syntax error that gives no command at all is an `UnreadableShellText`, e.g. `)))`.
    `judgment_rule_use_counts` counts the judgment rules the reading uses.
    """
    parse_state = _ParseState(first_command_id)
    scope = _Scope.scope_from_runner(runner) if runner else _Scope()
    options = _ShellOptions().options_after_set_from(set_arguments_at_start)
    tree_with_lines_kept_apart = _build_tree_with_lines_kept_apart(
        shell_text, judgment_rule_use_counts=judgment_rule_use_counts
    )
    walker = _ShellTextWalker(
        parse_state,
        options,
        tree_with_lines_kept_apart,
        command_substitution_texts_run_by_outer_shell=command_substitution_texts_run_by_outer_shell,
    )
    has_syntax_error = walker.walk_text_and_report_syntax_error(scope)
    if has_syntax_error and not parse_state.commands:
        return UnreadableShellText()
    return ParsedShellText(
        tuple(parse_state.commands), tuple(parse_state.variable_assignments)
    )


def command_substitution_texts_of(shell_text: str) -> frozenset[str]:
    """Find the text of each outermost `$(...)` and backticks in a shell text, as written, e.g. `$(curl u)` and `` `ls` `` in ``echo $(curl u) `ls` ``.

    A caller that reads text run by a command gets from here what to pass as `command_substitution_texts_run_by_outer_shell`, when the outer shell expanded the word that holds the text.
    The outer shell takes single quotes inside a double-quoted word as plain characters, so it also ran a `$(...)` between them, e.g. `$(curl u)` in `bash -c "bash -c 'echo $(curl u)'"`.
    So the content of each single-quoted string outside the found ones is searched in the same way.
    """
    root = _PARSER.parse(shell_text.encode("utf-8", "replace")).root_node
    texts = {
        _command_substitution_text_of(node) for node in _command_substitutions_of(root)
    }
    for string_node in _single_quoted_strings_of(root):
        texts |= command_substitution_texts_of(_node_text_of(string_node)[1:-1])
    return frozenset(texts)


class _ShellTextWalker:
    """Walker of one shell text, which adds its commands to the parse state.

    Its shell options hold for this text only.
    """

    def __init__(
        self,
        parse_state: _ParseState,
        options: _ShellOptions,
        tree_with_lines_kept_apart: _TreeWithLinesKeptApart,
        *,
        command_substitution_texts_run_by_outer_shell: frozenset[str] = frozenset(),
    ) -> None:
        self._parse_state = parse_state
        self._options = options
        self._tree_with_lines_kept_apart = tree_with_lines_kept_apart
        # The text of each `$(...)` that an outer shell ran before this text ran, e.g. `$(a)` in the text of `bash -c "echo $(a)"`.
        self._command_substitution_texts_run_by_outer_shell = (
            command_substitution_texts_run_by_outer_shell
        )
        self._has_brace_list = False
        # tree-sitter misread a statement in a way that the walk sees but cannot repair, e.g. `time { a; }` or `{ a; } > f b`.
        self._has_misread_statement = False

    def walk_text_and_report_syntax_error(self, scope: _Scope) -> bool:
        """Add the text's commands and return whether the text has a syntax error.

        All its commands are marked as maybe wrong after a syntax error, a brace list, lines that stayed joined after the line repairs or a statement that tree-sitter misread and the walk cannot repair.
        """
        first_new_index = len(self._parse_state.commands)
        root = self._tree_with_lines_kept_apart.tree.root_node
        self._walk_statements_for_deciding_command_ids(root.named_children, scope)
        if (
            root.has_error
            or self._has_brace_list
            or self._has_misread_statement
            or self._tree_with_lines_kept_apart.has_lines_left_joined
        ):
            commands = self._parse_state.commands
            for index in range(first_new_index, len(commands)):
                commands[index] = replace(commands[index], structure_may_be_wrong=True)
        return root.has_error

    def _walk_statements_for_deciding_command_ids(
        self, statements: Sequence[Node], scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk statements in order and return the deciding command ids of the last one.

        The last statement decides the exit code.
        With `set -e`, so does every statement that ends the text on failure,
        and later statements run only if it succeeded.
        After `exit`, later statements never run, so none of them decides.
        `exec > log` sends the output of later statements to log.
        """
        # A field such as `condition` also holds the `;` after it.
        statements = [s for s in statements if s.is_named and s.type != "comment"]
        deciding_command_ids: _DecidingCommandIds = None
        conditions_for_later_statements: tuple[RunCondition, ...] = ()
        has_exited = False
        for index, statement in enumerate(statements):
            statement_scope = scope.scope_with_added_run_conditions(
                *conditions_for_later_statements
            )
            if _is_in_background(statement):
                self._walk_statement_in_background(statement, statement_scope)
                deciding_command_ids = None  # it always exits 0
                continue
            decides = not has_exited and (
                index == len(statements) - 1
                or self._may_end_text_on_failure(statement, scope)
            )
            deciding_command_ids, exit_guard = (
                self._walk_statement_for_deciding_command_ids_and_exit_guard(
                    statement,
                    statement_scope.scope_for_succeeded_if_text_exits_zero_only_if(
                        decides
                    ),
                )
            )
            conditions_for_later_statements = self._conditions_for_later_statements(
                conditions_for_later_statements,
                statement,
                scope,
                deciding_command_ids,
                exit_guard,
            )
            has_exited = has_exited or _is_ended_by_exit_or_return(statement)
            scope = self._scope_for_later_statements(
                statement, scope, deciding_command_ids
            )
        return deciding_command_ids

    def _walk_statement_in_background(self, statement: Node, scope: _Scope) -> None:
        """Walk a statement started with `&`, which never decides the exit code."""
        self._walk_node_for_deciding_command_ids(
            statement, scope.scope_for_succeeded_if_text_exits_zero_only_if(False)
        )

    def _walk_node_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk any node by its type and return its deciding command ids."""
        match node.type:
            case "command":
                return self._walk_command_node_for_deciding_command_ids(node, scope)
            case "list":
                left, operator, right = _list_parts_of(node)
                return self._walk_bash_list_for_list_deciding_command_ids(
                    _BashList(left, operator, right), scope
                ).whole
            case "pipeline":
                return self._walk_pipeline_node_for_deciding_command_ids(node, scope)
            case "redirected_statement":
                return self._walk_redirected_statement_for_deciding_command_ids(
                    node, scope
                )
            case "compound_statement" | "do_group":
                return self._walk_statements_for_deciding_command_ids(
                    node.named_children, scope
                )
            case "subshell":
                walk = partial(
                    self._walk_statements_for_deciding_command_ids,
                    node.named_children,
                    scope,
                )
                return self._walk_with_own_options_for_deciding_command_ids(walk)
            case "if_statement":
                return self._walk_if_statement_for_deciding_command_ids(node, scope)
            case "while_statement":
                return self._walk_while_loop_for_deciding_command_ids(node, scope)
            case "for_statement" | "c_style_for_statement":
                return self._walk_for_loop_for_deciding_command_ids(node, scope)
            case "case_statement":
                return self._walk_case_statement_for_deciding_command_ids(node, scope)
            case "function_definition":
                return self._walk_function_definition_for_deciding_command_ids(
                    node, scope
                )
            case "negated_command":
                negated_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(
                    False
                )
                for child in node.named_children:
                    self._walk_node_for_deciding_command_ids(
                        child, negated_scope.scope_with_ignored_errexit()
                    )
                return None
            case "command_substitution" | "process_substitution":
                return self._walk_substitution_for_deciding_command_ids(node, scope)
            case "variable_assignment":
                return self._walk_variable_assignment_for_deciding_command_ids(
                    node, scope
                )
            case "variable_assignments":  # e.g. `A=1 B=$(b)`
                return self._walk_variable_assignments_for_deciding_command_ids(
                    node, scope
                )
            case "comment":
                return None
            case _:  # e.g. `[ -f x ]`, `export X=1`, or the words in a string
                for child in node.named_children:
                    self._walk_node_for_deciding_command_ids(
                        child,
                        scope.scope_for_succeeded_if_text_exits_zero_only_if(False),
                    )
                return None

    def _walk_command_node_for_deciding_command_ids(
        self, node: Node, scope: _Scope, outer_redirects: Sequence[Node] = ()
    ) -> _DecidingCommandIds:
        """Walk a command under its own redirects and those of its redirected statement."""
        redirects = _redirects_in_text_order_of(node, outer_redirects)
        walk = partial(
            self._walk_command_words_for_deciding_command_ids, node, redirects=redirects
        )
        return self._walk_under_redirects_for_deciding_command_ids(
            redirects, scope, walk
        )

    def _walk_command_words_for_deciding_command_ids(
        self, node: Node, scope: _Scope, *, redirects: Sequence[Node]
    ) -> _DecidingCommandIds:
        """Add a command from its words, then walk the commands in its `$(...)`.

        `redirects` are the command's own and those of its redirected statement, which can hold words of the command, e.g. a in `cmd > f a`.
        """
        word_nodes = _command_word_nodes_with_redirect_word_nodes_of(node, redirects)
        if any(map(_is_brace_list, word_nodes)):
            self._has_brace_list = True
        command_words = _command_words_with_restored_dashes_from(
            word_nodes,
            redirects,
            self._tree_with_lines_kept_apart.text_after_line_repairs,
        )
        timed_command_words = _timed_command_words_of(node, command_words)
        if timed_command_words is not None:
            if _is_timed_statement_misread(node, timed_command_words):
                self._has_misread_statement = True
            else:
                command_words = timed_command_words
        deciding_command_ids: _DecidingCommandIds = None
        if command_words:
            deciding_command_ids = (
                self._append_shell_command_returning_id(command_words, scope),
            )
        substitution_scope = scope.scope_for_substitution()
        for word_node in word_nodes:
            # e.g. `$(ls)` in `echo $(ls)`
            self._walk_node_for_deciding_command_ids(word_node, substitution_scope)
        for child in node.named_children:
            if child.type == "variable_assignment":
                # Only the value, e.g. `$(ls)` in `A=$(ls) b`, since b alone gets A.
                value = child.child_by_field_name("value")
                if value is not None:
                    self._walk_node_for_deciding_command_ids(value, substitution_scope)
            elif child.type in _TIMED_STATEMENT_TYPES:
                # The statement that `time` times, e.g. `time (a && b)`.
                deciding_command_ids = self._walk_node_for_deciding_command_ids(
                    child, scope
                )
        return deciding_command_ids

    def _walk_under_redirects_for_deciding_command_ids(
        self, redirects: Sequence[Node], scope: _Scope, walk_statement: _StatementWalk
    ) -> _DecidingCommandIds:
        """Walk a statement under its redirects, which apply in order.

        The commands in a redirect's `$(...)`, `<(...)` or heredoc run before the statement.
        A `>(...)` target reads the statement's output, so its commands come after it.
        """
        substitution_scope = scope.scope_for_substitution()
        for redirect in redirects:
            for part in _parts_run_before_statement_of(redirect):
                self._walk_node_for_deciding_command_ids(part, substitution_scope)
        redirected_scope = _redirected_scope_of(
            redirects, scope, self._parse_state.pipe_placeholders
        )
        commands = self._parse_state.commands
        writer_start_index = len(commands)
        deciding_command_ids = walk_statement(redirected_scope.scope)
        for placeholder, output_reader in redirected_scope.output_readers:
            reader_index = len(commands)
            self._walk_substitution_for_deciding_command_ids(
                output_reader, substitution_scope
            )
            self._replace_pipe_placeholder(
                placeholder, writer_start_index, reader_index
            )
        return deciding_command_ids

    def _walk_substitution_for_deciding_command_ids(
        self, node: Node, scope: _Scope, *, decides_exit: bool = False
    ) -> _DecidingCommandIds:
        """Walk the commands of a `$(...)`, backticks, `<(...)` or `>(...)`.

        The first three hand their stdout to the enclosing command.
        `>(...)` reads output instead. As a word its own stdout goes where the enclosing command's goes, e.g. to f for b in `tee >(b) > f`.
        As a redirect target its own stdout goes where the statement's stdout went before the redirects of the statement, e.g. to the result of the call for b in `a > >(b)`.
        Each runs in a subshell, so its `set` options end with it.
        Bash also turns `set -e` off inside `$(...)`, while sh keeps it, and this follows bash.
        A `$(...)` that an outer shell already ran is not walked again.
        `decides_exit` is for the `$(...)` whose exit code an assignment takes.
        """
        if (
            _command_substitution_text_of(node)
            in self._command_substitution_texts_run_by_outer_shell
        ):
            return None
        inner_scope = scope.scope_without_stdin()
        if not decides_exit:
            inner_scope = inner_scope.scope_for_succeeded_if_text_exits_zero_only_if(
                False
            )
        if not _is_output_reader(node):
            inner_scope = replace(inner_scope, stdout=CaptureDestination())
        walk = partial(
            self._walk_statements_for_deciding_command_ids,
            node.named_children,
            inner_scope,
        )
        errexit = self._options.errexit and node.type != "command_substitution"
        return self._walk_with_own_options_for_deciding_command_ids(
            walk, errexit=errexit
        )

    def _walk_bash_list_for_list_deciding_command_ids(
        self,
        bash_list: _BashList,
        scope: _Scope,
        walk_right: _StatementWalk | None = None,
    ) -> _ListDecidingCommandIds:
        """Walk a statement that bash runs as a list, or its left side and `walk_right`."""
        walk_left = self._statement_walk_of_list_side(
            bash_list.left, bash_list.left_redirects
        )
        if walk_right is None:
            walk_right = self._statement_walk_of_list_side(
                bash_list.right, bash_list.right_redirects
            )
        return self._walk_list_for_list_deciding_command_ids(
            walk_left, bash_list.operator, walk_right, scope
        )

    def _statement_walk_of_list_side(
        self, node: Node, redirects: Sequence[Node]
    ) -> _StatementWalk:
        """Make the walk of one side of a list, under the redirects that belong to that side."""
        if redirects:
            return partial(
                self._walk_with_redirects_for_deciding_command_ids, node, redirects
            )
        return partial(self._walk_node_for_deciding_command_ids, node)

    def _walk_with_redirects_for_deciding_command_ids(
        self, body: Node, redirects: Sequence[Node], scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a statement under its redirects. For a list or pipeline they are its last part's.

        tree-sitter reads `a && b > f` as `(a && b) > f` and `a | b > f` as `(a | b) > f`.
        Bash runs `a && (b > f)` and `a | (b > f)`.
        """
        if body.type == "command":
            return self._walk_command_node_for_deciding_command_ids(
                body, scope, redirects
            )
        if body.type == "list":
            left, operator, right = _list_parts_of(body)
            bash_list = _BashList(left, operator, right, right_redirects=redirects)
            return self._walk_bash_list_for_list_deciding_command_ids(
                bash_list, scope
            ).whole
        if body.type == "pipeline":
            stages, pipes_stderr = _pipeline_stages_of(body)
            if stages:
                stage_walks = [
                    *(
                        partial(self._walk_node_for_deciding_command_ids, stage)
                        for stage in stages[:-1]
                    ),
                    partial(
                        self._walk_with_redirects_for_deciding_command_ids,
                        stages[-1],
                        redirects,
                    ),
                ]
                return self._walk_pipeline_stages_for_deciding_command_ids(
                    stage_walks, pipes_stderr, scope
                )
        if _redirect_word_nodes_of(redirects):
            # tree-sitter-bash 0.25.1 puts a word after the redirect target into the redirect, e.g. b in `{ a; } > f b` or in `[ -f x ] > f b`.
            # Bash reads it as a word of the statement, which is no simple command here, so the word is lost.
            self._has_misread_statement = True
        return self._walk_under_redirects_for_deciding_command_ids(
            redirects, scope, partial(self._walk_node_for_deciding_command_ids, body)
        )

    def _walk_pipeline_node_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a pipeline, also `! a | b` and `a && b 2>&1 | c`, which tree-sitter misreads."""
        stages, pipes_stderr = _pipeline_stages_of(node)
        if not stages:
            return None
        first = stages[0]
        if first.type == "negated_command":
            # tree-sitter reads `! a | b` as `(! a) | b`. Bash runs `! (a | b)`.
            negated = _named_children_without_comments_of(first)[:1]
            stage_walks = [
                partial(self._walk_node_for_deciding_command_ids, s)
                for s in [*negated, *stages[1:]]
            ]
            negated_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(False)
            self._walk_pipeline_stages_for_deciding_command_ids(
                stage_walks, pipes_stderr, negated_scope.scope_with_ignored_errexit()
            )
            return None
        misread_list = _misread_list_of(first)
        if misread_list is not None:
            # tree-sitter reads `a && b 2>&1 | c` as `(a && b) 2>&1 | c`.
            # Bash runs `a && (b 2>&1 | c)`.
            left, operator, right = _list_parts_of(misread_list)
            redirects = first.children_by_field_name("redirect")
            stage_walks = [
                partial(
                    self._walk_with_redirects_for_deciding_command_ids, right, redirects
                ),
                *(
                    partial(self._walk_node_for_deciding_command_ids, stage)
                    for stage in stages[1:]
                ),
            ]
            walk_pipeline = partial(
                self._walk_pipeline_stages_for_deciding_command_ids,
                stage_walks,
                pipes_stderr,
            )
            bash_list = _BashList(left, operator, right)
            return self._walk_bash_list_for_list_deciding_command_ids(
                bash_list, scope, walk_pipeline
            ).whole
        stage_walks = [
            partial(self._walk_node_for_deciding_command_ids, stage) for stage in stages
        ]
        return self._walk_pipeline_stages_for_deciding_command_ids(
            stage_walks, pipes_stderr, scope
        )

    def _walk_redirected_statement_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a statement with redirects, also a list or pipe that tree-sitter misread into it."""
        redirects = node.children_by_field_name("redirect")
        bash_list = _bash_list_of(node)
        piped = _pipeline_after_heredoc_of(redirects)
        if piped is None and bash_list is not None:
            return self._walk_bash_list_for_list_deciding_command_ids(
                bash_list, scope
            ).whole
        # A list that tree-sitter misread, e.g. `a && b > f`, has the redirects on its last command.
        misread_list = bash_list if bash_list and bash_list.right_redirects else None
        last = misread_list.right if misread_list else node.child_by_field_name("body")
        if last is None:
            return None
        walk_last = partial(
            self._walk_with_redirects_for_deciding_command_ids, last, redirects
        )
        if piped is None:
            return walk_last(scope)
        # tree-sitter reads `| b` in `cat <<EOF | b` as part of the heredoc.
        # In `a && cat <<EOF | b`, bash pipes cat alone into b.
        stages, pipes_stderr = _pipeline_stages_of(piped)
        stage_walks = [
            walk_last,
            *(
                partial(self._walk_node_for_deciding_command_ids, stage)
                for stage in stages
            ),
        ]
        pipes_stderr = [_has_stderr_pipe_at_start(piped), *pipes_stderr]
        walk_pipeline = partial(
            self._walk_pipeline_stages_for_deciding_command_ids,
            stage_walks,
            pipes_stderr,
        )
        if misread_list is not None:
            return self._walk_bash_list_for_list_deciding_command_ids(
                misread_list, scope, walk_pipeline
            ).whole
        return walk_pipeline(scope)

    def _walk_if_statement_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk an if statement.

        Each branch runs only if every earlier condition failed and its own succeeded.
        """
        clauses = [
            node,
            *(
                c
                for c in node.named_children
                if c.type in ("elif_clause", "else_clause")
            ),
        ]
        remaining_clauses_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(
            False
        )
        for clause in clauses:
            conditions, body = _if_clause_parts_of(clause)
            if conditions:
                deciding_command_ids = self._walk_statements_for_deciding_command_ids(
                    conditions, remaining_clauses_scope.scope_with_ignored_errexit()
                )
                success = _run_condition_from(deciding_command_ids, ExitOutcome.SUCCESS)
                self._walk_statements_for_deciding_command_ids(
                    body,
                    remaining_clauses_scope.scope_with_added_run_conditions(success),
                )
                remaining_clauses_scope = (
                    remaining_clauses_scope.scope_with_added_run_conditions(
                        _run_condition_from(deciding_command_ids, ExitOutcome.FAILURE)
                    )
                )
            else:
                self._walk_statements_for_deciding_command_ids(
                    body, remaining_clauses_scope
                )
        return None

    def _walk_while_loop_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a while or until loop.

        The body runs while the condition succeeds, or for `until` while it fails.
        """
        loop_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(False)
        deciding_command_ids = self._walk_statements_for_deciding_command_ids(
            node.children_by_field_name("condition"),
            loop_scope.scope_with_ignored_errexit(),
        )
        is_until = node.children[0].type == "until"
        required = ExitOutcome.FAILURE if is_until else ExitOutcome.SUCCESS
        body = node.child_by_field_name("body")
        if body is not None:
            body_scope = replace(loop_scope, in_loop_body=True)
            self._walk_node_for_deciding_command_ids(
                body,
                body_scope.scope_with_added_run_conditions(
                    _run_condition_from(deciding_command_ids, required)
                ),
            )
        return None

    def _walk_for_loop_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a for loop, and record each item of `for x in a b` as a value of x, with where the loop ends.

        A list with `$A`, a glob such as `*.txt` or a brace list such as `{1,2}` is computed as the loop runs,
        and so is a missing list, which stands for the script's arguments as in `for x; do`. Then one assignment without a value is recorded.
        A C-style loop such as `for ((i=0; i<3; i++))` changes what its header assigns, so i gets no value.
        """
        loop_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(False)
        variable = node.child_by_field_name("variable")
        items = node.children_by_field_name("value")
        assignments = self._parse_state.variable_assignments
        first_item_index = len(assignments)
        if variable is not None:
            if items and not any(map(_is_computed_word, items)):
                for item in items:
                    self._record_variable_assignment(
                        _node_text_of(variable), _word_value_of(item)
                    )
            else:
                self._record_variable_assignment(_node_text_of(variable), None)
        item_indexes = range(first_item_index, len(assignments))
        for child in _named_children_without_comments_of(node, except_field="body"):
            # e.g. `$(ls)` in `for f in $(ls)`
            self._walk_node_for_deciding_command_ids(child, loop_scope)
        if variable is None:
            for index in range(item_indexes.stop, len(assignments)):
                assignments[index] = replace(assignments[index], value=None)
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_node_for_deciding_command_ids(
                body, replace(loop_scope, in_loop_body=True)
            )
        for index in item_indexes:
            assignments[index] = replace(
                assignments[index],
                next_command_id_after_for_loop=self._parse_state.next_command_id,
            )
        return None

    def _walk_case_statement_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a case statement, whose branches run only if their pattern matches."""
        branch_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(False)
        value = node.child_by_field_name("value")
        if value is not None:
            self._walk_node_for_deciding_command_ids(value, branch_scope)
        for item in node.named_children:
            if item.type == "case_item":
                body = _named_children_without_comments_of(item, except_field="value")
                self._walk_statements_for_deciding_command_ids(
                    body, replace(branch_scope, in_case_branch=True)
                )
        return None

    def _walk_function_definition_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a function body, which runs only if the function is called.

        Calls are not followed, so a `set` in the body is taken to hold in the body only.
        """
        body = node.child_by_field_name("body")
        if body is not None:
            body_scope = replace(
                scope.scope_for_succeeded_if_text_exits_zero_only_if(False),
                in_function_body=True,
            )
            self._walk_with_own_options_for_deciding_command_ids(
                partial(self._walk_node_for_deciding_command_ids, body, body_scope)
            )
        return None

    def _walk_variable_assignment_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Record an assignment, with its value when the value is literal, and walk its `$(...)`.

        The assignment exits as its last `$(...)` does.
        """
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        appends = any(child.type == "+=" for child in node.children)
        # Bash does not split an assigned word, so {a,b} stays literal here.
        is_literal = not appends and (
            value is None or not (value.type == "array" or _has_expansion(value))
        )
        if name is not None:
            literal = _word_value_of(value) if value is not None else ""
            self._record_variable_assignment(
                _node_text_of(name), literal if is_literal else None
            )
        if value is None:
            return None
        substitutions = _command_substitutions_of(value)
        last_substitution = substitutions[-1] if substitutions else None
        has_parts = value.type in ("string", "concatenation")
        deciding_command_ids: _DecidingCommandIds = None
        for part in value.named_children if has_parts else [value]:
            if part == last_substitution:
                deciding_command_ids = self._walk_substitution_for_deciding_command_ids(
                    part, scope, decides_exit=True
                )
            else:
                self._walk_node_for_deciding_command_ids(
                    part, scope.scope_for_succeeded_if_text_exits_zero_only_if(False)
                )
        return deciding_command_ids

    def _walk_variable_assignments_for_deciding_command_ids(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk `A=1 B=$(b)`, which exits as its last assignment with a `$(...)` does."""
        deciding_command_ids: _DecidingCommandIds = None
        for assignment in node.named_children:
            assignment_deciding_command_ids = self._walk_node_for_deciding_command_ids(
                assignment, scope
            )
            if _command_substitutions_of(assignment):
                deciding_command_ids = assignment_deciding_command_ids
        return deciding_command_ids

    def _walk_statement_for_deciding_command_ids_and_exit_guard(
        self, statement: Node, scope: _Scope
    ) -> tuple[_DecidingCommandIds, RunCondition | None]:
        """Walk a statement, and return its deciding command ids and its condition on later statements.

        Later statements run only if a succeeded after `a || exit`,
        and only if a failed after `a && exit`.
        """
        bash_list = _bash_list_of(statement)
        if bash_list is None or not _is_ended_by_exit_or_return(bash_list.right):
            return self._walk_node_for_deciding_command_ids(statement, scope), None
        list_deciding_command_ids = self._walk_bash_list_for_list_deciding_command_ids(
            bash_list, scope
        )
        is_or = bash_list.operator == "||"
        outcome = ExitOutcome.SUCCESS if is_or else ExitOutcome.FAILURE
        return list_deciding_command_ids.whole, _run_condition_from(
            list_deciding_command_ids.left, outcome
        )

    def _append_shell_command_returning_id(
        self, command_words: Sequence[_CommandWord], scope: _Scope
    ) -> int:
        """Add one command and return its id."""
        command = ShellCommand(
            id=self._parse_state.next_command_id,
            words=tuple(map(_command_word_value_of, command_words)),
            expansion_word_indexes=tuple(
                index
                for index, command_word in enumerate(command_words)
                if not isinstance(command_word, _LostDash)
                and _has_expansion(command_word)
            ),
            **scope.command_fields_from_scope(),
        )
        self._parse_state.commands.append(command)
        if command.words[:1] == ("set",):
            self._options = self._options.options_after_set_from(command.words[1:])
        return command.id

    def _walk_with_own_options_for_deciding_command_ids(
        self, walk: Callable[[], _DecidingCommandIds], *, errexit: bool | None = None
    ) -> _DecidingCommandIds:
        """Walk a part such as a subshell, whose `set` options do not hold after it.

        `errexit` turns `set -e` on or off for the part.
        """
        options = self._options
        if errexit is not None:
            self._options = replace(options, errexit=errexit)
        try:
            return walk()
        finally:
            self._options = options

    def _walk_pipeline_stages_for_deciding_command_ids(
        self,
        stage_walks: Sequence[_StatementWalk],
        pipes_stderr: Sequence[bool],
        scope: _Scope,
    ) -> _DecidingCommandIds:
        """Walk pipeline stages, each but the last sending stdout to the next, and with `|&` stderr.

        The last stage decides the exit code. With `set -o pipefail`, every stage does.
        A stage after the first reads the pipe, so it takes no stdin from the scope, e.g. grep in `{ echo x | grep x; } < log`.
        """
        commands = self._parse_state.commands
        deciding_command_ids: _DecidingCommandIds = ()
        previous_stage: tuple[PipeDestination, int] | None = None
        for index, walk_stage in enumerate(stage_walks):
            is_last = index == len(stage_walks) - 1
            stage_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(
                is_last or self._options.pipefail
            )
            if index > 0:
                stage_scope = stage_scope.scope_without_stdin()
            placeholder = None
            if not is_last:
                placeholder = PipeDestination(next(self._parse_state.pipe_placeholders))
                stderr = placeholder if pipes_stderr[index] else stage_scope.stderr
                stage_scope = replace(stage_scope, stdout=placeholder, stderr=stderr)
            stage_start_index = len(commands)
            stage_deciding_command_ids = walk_stage(stage_scope)
            if previous_stage is not None:
                self._replace_pipe_placeholder(
                    *previous_stage, reader_index=stage_start_index
                )
            previous_stage = (
                (placeholder, stage_start_index) if placeholder is not None else None
            )
            deciding_command_ids = (
                _combined_deciding_command_ids_of(
                    deciding_command_ids, stage_deciding_command_ids
                )
                if self._options.pipefail
                else stage_deciding_command_ids
            )
        return deciding_command_ids

    def _replace_pipe_placeholder(
        self, placeholder: PipeDestination, writer_start_index: int, reader_index: int
    ) -> None:
        """Replace `placeholder` from `writer_start_index` on with the command at `reader_index`.

        When the reader has no simple command, e.g. `a | (( x ))`, the output is discarded.
        """
        commands = self._parse_state.commands
        reader: OutputDestination = (
            PipeDestination(commands[reader_index].id)
            if reader_index < len(commands)
            else DiscardDestination()
        )
        for index in range(writer_start_index, reader_index):
            command = commands[index]
            if placeholder in (command.stdout, command.stderr):
                commands[index] = replace(
                    command,
                    stdout=reader if command.stdout == placeholder else command.stdout,
                    stderr=reader if command.stderr == placeholder else command.stderr,
                )

    def _walk_list_for_list_deciding_command_ids(
        self,
        walk_left: _StatementWalk,
        operator: str,
        walk_right: _StatementWalk,
        scope: _Scope,
    ) -> _ListDecidingCommandIds:
        """Walk `a && b` or `a || b`.

        The right side runs only if the left side succeeded for && or failed for ||.
        Only && lets the text's exit code 0 say that both sides succeeded.
        `set -e` does not end the text when the left side fails.
        """
        is_and = operator == "&&"
        side_scope = scope.scope_for_succeeded_if_text_exits_zero_only_if(is_and)
        left = walk_left(side_scope.scope_with_ignored_errexit())
        required = ExitOutcome.SUCCESS if is_and else ExitOutcome.FAILURE
        right = walk_right(
            side_scope.scope_with_added_run_conditions(
                _run_condition_from(left, required)
            )
        )
        return _ListDecidingCommandIds(
            left, _combined_deciding_command_ids_of(left, right)
        )

    def _record_variable_assignment(self, name: str, value: str | None) -> None:
        """Record an assignment of this text."""
        next_command_id = self._parse_state.next_command_id
        assignment = VariableAssignment(name, value, next_command_id, None)
        self._parse_state.variable_assignments.append(assignment)

    def _conditions_for_later_statements(
        self,
        conditions: tuple[RunCondition, ...],
        statement: Node,
        scope: _Scope,
        deciding_command_ids: _DecidingCommandIds,
        exit_guard: RunCondition | None,
    ) -> tuple[RunCondition, ...]:
        """Compute the run conditions of the statements after `statement`.

        `exit_guard` comes from `a || exit`.
        With `set -e`, a statement that ends the text on failure must have succeeded.
        """
        condition = exit_guard
        if condition is None and self._may_end_text_on_failure(statement, scope):
            condition = _run_condition_from(deciding_command_ids, ExitOutcome.SUCCESS)
        if condition is None:
            return conditions
        return _conditions_with_later_condition_from(conditions, condition)

    def _may_end_text_on_failure(self, statement: Node, scope: _Scope) -> bool:
        """Check whether `set -e` makes the text end when this statement fails."""
        return (
            self._options.errexit
            and not scope.errexit_is_ignored
            and _is_errexit_statement(statement)
        )

    def _scope_for_later_statements(
        self,
        statement: Node,
        scope: _Scope,
        deciding_command_ids: _DecidingCommandIds,
    ) -> _Scope:
        """Compute the scope of later statements, whose output `exec > log` sends to log."""
        if not _is_bare_exec(statement) or not deciding_command_ids:
            return scope
        exec_command = self._parse_state.command_from_id(deciding_command_ids[-1])
        return replace(scope, stdout=exec_command.stdout, stderr=exec_command.stderr)


@dataclass(slots=True)
class _ParseState:
    """Parser state kept during one `parse_shell_text` call, read and changed by its walker."""

    # The id of the first command, from parse_shell_text, so that ids stay unique within one call.
    first_command_id: int
    # In id order, so the index of a command is its id minus first_command_id.
    commands: list[ShellCommand] = field(default_factory=list)
    variable_assignments: list[VariableAssignment] = field(default_factory=list)
    # Placeholder reader ids for pipes whose reader is not walked yet. Each pipe has its own.
    pipe_placeholders: Iterator[int] = field(
        default_factory=lambda: itertools.count(-1, -1)
    )

    @property
    def next_command_id(self) -> int:
        return self.first_command_id + len(self.commands)

    def command_from_id(self, command_id: int) -> ShellCommand:
        return self.commands[command_id - self.first_command_id]


@dataclass(frozen=True, slots=True)
class _ShellOptions:
    """Shell options of one text that change what an exit code says."""

    errexit: bool = False  # set -e, so a failing command or pipeline ends the text
    pipefail: bool = False  # set -o pipefail, so every stage decides a pipeline

    def options_after_set_from(self, arguments: Sequence[str]) -> _ShellOptions:
        """Apply `set` with these arguments, e.g. `-e`, `+e`, `-euo pipefail`.

        Options end at the first word that is not one, e.g. `--` in `set -- -e`.
        """
        options = self
        index = 0
        while index < len(arguments) and _SET_OPTION_CLUSTER.fullmatch(
            arguments[index]
        ):
            word = arguments[index]
            is_on = word.startswith("-")
            if "e" in word[1:]:
                options = replace(options, errexit=is_on)
            if "o" in word[1:] and index + 1 < len(arguments):
                index += 1
                if arguments[index] == "errexit":
                    options = replace(options, errexit=is_on)
                elif arguments[index] == "pipefail":
                    options = replace(options, pipefail=is_on)
            index += 1
        return options


def _build_tree_with_lines_kept_apart(
    text: str, *, judgment_rule_use_counts: Counter[str]
) -> _TreeWithLinesKeptApart:
    """Parse a text, putting `;` at the end of lines that tree-sitter joins.

    tree-sitter joins the next line into the last stage of a pipeline of three or more stages,
    e.g. `a | b | c` then `d 2>&1 | e` gives `c d` piped into e.
    A `;` keeps the lines apart and means the same to bash.
    The new parse can join other lines, so the text is repaired up to `_MAX_LINE_REPAIRS` times.
    When lines are still joined then, `treat_lines_joined_after_three_repairs_as_left_joined` decides whether to leave them so.
    If it does not, repairs go on until no line is joined or a repair no longer lowers the number of joined lines.
    """
    source = text.encode("utf-8", "replace")
    tree = _PARSER.parse(source)
    positions = _joined_line_ends_of(tree.root_node, source)
    repair_count = 0
    count_before_last_repair = len(positions)
    while positions:
        if repair_count == _MAX_LINE_REPAIRS:
            if treat_lines_joined_after_three_repairs_as_left_joined(
                repair_count, use_counts=judgment_rule_use_counts
            ):
                break
        elif (
            repair_count > _MAX_LINE_REPAIRS
            and len(positions) >= count_before_last_repair
        ):
            break
        for position in sorted(positions, reverse=True):
            source = source[:position] + b";" + source[position:]
        tree = _PARSER.parse(source)
        repair_count += 1
        count_before_last_repair = len(positions)
        positions = _joined_line_ends_of(tree.root_node, source)
    return _TreeWithLinesKeptApart(tree, source, has_lines_left_joined=bool(positions))


class _TreeWithLinesKeptApart(NamedTuple):
    """Tree of one shell text after the line repairs, read by `_ShellTextWalker`."""

    tree: Tree
    # The text with the `;` of the repairs, which the byte offsets of the tree point into.
    text_after_line_repairs: bytes
    # Lines are still joined after the last repair, so the commands of the tree may be wrong.
    has_lines_left_joined: bool


def _joined_line_ends_of(root: Node, source: bytes) -> list[int]:
    """Find where a command's words cross a line end, which no command in bash does.

    Each position is the line end, or the start of a comment before it.
    """
    positions: list[int] = []
    nodes = [root]
    while nodes:
        node = nodes.pop()
        nodes.extend(node.children)
        if node.type != "command":
            continue
        words = _command_word_nodes_of(node)
        for previous_word_node, word_node in itertools.pairwise(words):
            gap = source[previous_word_node.end_byte : word_node.start_byte]
            line_end = _UNESCAPED_LINE_BREAK.search(gap)
            if line_end is not None:
                comment = _COMMENT_START.search(gap, 0, line_end.start())
                end = comment.start() if comment is not None else line_end.start()
                positions.append(previous_word_node.end_byte + end)
    return positions


def _is_in_background(statement: Node) -> bool:
    return statement.next_sibling is not None and statement.next_sibling.type == "&"


def _is_ended_by_exit_or_return(node: Node) -> bool:
    """Check whether a statement ends the shell, e.g. `exit 1` or `{ echo failed; exit 1; }`."""
    if node.type == "command":
        name = node.child_by_field_name("name")
        return name is not None and _word_value_of(name) in ("exit", "return")
    if node.type == "compound_statement":
        statements = _named_children_without_comments_of(node)
        return bool(statements) and _is_ended_by_exit_or_return(statements[-1])
    return False


def _redirects_in_text_order_of(
    command_node: Node, outer_redirects: Sequence[Node]
) -> list[Node]:
    """List a command's own redirects, then those of its redirected statement, as in the text.

    Own redirects come first, e.g. `> f` before `2>&1` in `> f a 2>&1`.
    """
    return [*command_node.children_by_field_name("redirect"), *outer_redirects]


def _is_computed_word(word_node: Node) -> bool:
    """Check whether the shell computes a word's value as it runs, e.g. `$A`, `*.txt` or `{a,b}`."""
    return _has_expansion(word_node) or _is_brace_list(word_node) or _is_glob(word_node)


def _is_glob(word_node: Node) -> bool:
    """Check whether a word has a `*`, `?` or `[` outside quotes, which the shell turns into file names."""
    parts = word_node.children if word_node.type == "concatenation" else [word_node]
    return any(
        part.type == "word" and _GLOB_CHARACTER.search(_node_text_of(part))
        for part in parts
    )


def _is_brace_list(word_node: Node) -> bool:
    """Check whether a word outside quotes is a brace list, e.g. `{a,b}` or `x{1..3}`."""
    if word_node.type == "brace_expression":
        return True
    if word_node.type == "word":
        return bool(_BRACE_LIST.search(_node_text_of(word_node)))
    if word_node.type == "concatenation":
        unquoted = "".join(
            _node_text_of(c) for c in word_node.children if c.type == "word"
        )
        return any(c.type == "brace_expression" for c in word_node.children) or bool(
            _BRACE_LIST.search(unquoted)
        )
    return False


def _parts_run_before_statement_of(redirect: Node) -> list[Node]:
    """Find the parts of a redirect whose `$(...)` and `<(...)` run before the statement.

    They are the target of `> f$(a)` or `< <(a)`, the word of `<<< "$(a)"`
    and the body of a heredoc whose delimiter is not quoted.
    """
    if redirect.type == "file_redirect":
        destination = redirect.child_by_field_name("destination")
        if destination is None or _is_output_reader(destination):
            return []
        return [destination]
    if redirect.type == "herestring_redirect":
        return list(redirect.named_children)
    if redirect.type == "heredoc_redirect":
        bodies = [c for c in redirect.named_children if c.type == "heredoc_body"]
        # e.g. `> f` in `cat <<EOF > f`
        inner = redirect.children_by_field_name("redirect")
        return [*bodies, *(p for r in inner for p in _parts_run_before_statement_of(r))]
    return []


def _redirected_scope_of(
    redirects: Sequence[Node], scope: _Scope, placeholders: Iterator[int]
) -> _RedirectedScope:
    """Apply redirects to a scope in order, e.g. `> log 2>&1` sends both streams to log.

    A `>(...)` target gets a pipe placeholder, which its walk connects to its first command.
    """
    output_readers: list[tuple[PipeDestination, Node]] = []
    for redirect in redirects:
        if redirect.type == "file_redirect":
            destination_node = redirect.child_by_field_name("destination")
            if destination_node is not None and _is_output_reader(destination_node):
                placeholder = PipeDestination(next(placeholders))
                output_readers.append((placeholder, destination_node))
                scope = _scope_from_file_redirect(redirect, scope, placeholder)
            else:
                scope = _scope_from_file_redirect(redirect, scope)
        elif redirect.type == "heredoc_redirect":
            body = next(
                (c for c in redirect.named_children if c.type == "heredoc_body"), None
            )
            scope = replace(
                scope,
                stdin_text=_node_text_of(body) if body is not None else "",
                is_heredoc_delimiter_quoted=_is_heredoc_delimiter_quoted(redirect),
                stdin_file_path=None,
            )
            # e.g. `> f` in `cat <<EOF > f`
            inner = redirect.children_by_field_name("redirect")
            inner_redirected_scope = _redirected_scope_of(inner, scope, placeholders)
            scope = inner_redirected_scope.scope
            output_readers.extend(inner_redirected_scope.output_readers)
        elif redirect.type == "herestring_redirect" and redirect.named_children:
            scope = replace(
                scope,
                stdin_text=_word_value_of(redirect.named_children[-1]),
                is_heredoc_delimiter_quoted=None,
                stdin_file_path=None,
            )
    return _RedirectedScope(scope, tuple(output_readers))


def _is_heredoc_delimiter_quoted(redirect: Node) -> bool:
    """Check whether the delimiter of a heredoc has a quote or a backslash, as `'EOF'` of `<<'EOF'` or `\\EOF` of `<<-\\EOF` has, so that bash takes the body as written."""
    start = next((c for c in redirect.children if c.type == "heredoc_start"), None)
    return start is not None and bool(
        _HEREDOC_DELIMITER_QUOTING.search(_node_text_of(start))
    )


def _is_output_reader(node: Node) -> bool:
    """Check whether a node is `>(...)`, a process that reads what is written to it."""
    return (
        node.type == "process_substitution"
        and bool(node.children)
        and node.children[0].type == ">("
    )


class _RedirectedScope(NamedTuple):
    """Scope after redirects, with the `>(...)` targets still to walk."""

    scope: _Scope
    # Placeholders in the scope's stdout or stderr, each with the `>(...)` that reads it.
    output_readers: tuple[tuple[PipeDestination, Node], ...]


def _scope_from_file_redirect(
    redirect: Node, scope: _Scope, output_reader: PipeDestination | None = None
) -> _Scope:
    """Apply one redirect such as `> f`, `2>&1`, `&> f`, `2> /dev/null` or `< f` to a scope.

    `output_reader` is the destination of a `>(...)` target.
    A later redirect of stdin replaces an earlier one, as in bash, e.g. f for `cat <<EOF < f`.
    """
    operator = next((c.type for c in redirect.children if not c.is_named), "")
    is_input = operator.startswith("<")
    descriptor_node = redirect.child_by_field_name("descriptor")
    if descriptor_node is not None:
        descriptor = _node_text_of(descriptor_node)
    else:
        descriptor = "0" if is_input else "1"
    destination_node = redirect.child_by_field_name("destination")
    target = _word_value_of(destination_node) if destination_node is not None else ""
    if is_input:
        # `<&3` copies a descriptor and names no file.
        if operator != "<" or descriptor != "0":
            return scope
        # `< <(cmd)` gives stdin the output of cmd, not a file.
        if (
            destination_node is not None
            and destination_node.type == "process_substitution"
        ):
            return scope.scope_without_stdin()
        return replace(
            scope,
            stdin_file_path=target,
            stdin_text=None,
            is_heredoc_delimiter_quoted=None,
        )
    destination: OutputDestination
    if output_reader is not None:
        destination = output_reader
    elif operator == ">&-":  # closed
        destination = DiscardDestination()
    elif operator == ">&" and target in ("1", "2"):  # a copy, e.g. 2>&1
        destination = scope.stdout if target == "1" else scope.stderr
    elif operator == ">&" and target.isdigit():  # another descriptor, e.g. 1>&3
        return scope
    else:
        appends = operator in (">>", "&>>")
        destination = _destination_of_path(target, scope, appends=appends)
    if operator in ("&>", "&>>") or (operator == ">&" and not target.isdigit()):
        return replace(scope, stdout=destination, stderr=destination)
    if descriptor == "1":
        return replace(scope, stdout=destination)
    if descriptor == "2":
        return replace(scope, stderr=destination)
    return scope


def _destination_of_path(
    path: str, scope: _Scope, *, appends: bool
) -> OutputDestination:
    """Map a redirect target to a destination, e.g. `/dev/null` to discard."""
    if path == "/dev/null":
        return DiscardDestination()
    if path == "/dev/stdout":
        return scope.stdout
    if path == "/dev/stderr":
        return scope.stderr
    return FileDestination(path, appends)


@dataclass(frozen=True, slots=True)
class _Scope:
    """Scope that a statement passes down to the commands in it."""

    # The fields up to structure_may_be_wrong are ShellCommand's, see there.
    stdout: OutputDestination = field(default_factory=ResultDestination)
    stderr: OutputDestination = field(default_factory=ResultDestination)
    stdin_text: str | None = None
    is_heredoc_delimiter_quoted: bool | None = None
    stdin_file_path: str | None = None
    runs_if: tuple[RunCondition, ...] = ()
    in_loop_body: bool = False
    in_function_body: bool = False
    in_case_branch: bool = False
    # True for the whole text, then narrowed by each statement.
    succeeded_if_text_exits_zero: bool = True
    structure_may_be_wrong: bool = False
    # `set -e` does not end the text here, e.g. left of && or in an if condition.
    errexit_is_ignored: bool = False

    @classmethod
    def scope_from_runner(cls, runner: ShellCommand) -> _Scope:
        """Make the scope of text that `runner` runs, which exits as the text does."""
        inherited = {name: getattr(runner, name) for name in _FIELDS_FROM_RUNNER}
        return cls(**inherited)

    def command_fields_from_scope(self) -> dict[str, Any]:
        """Return the ShellCommand fields that a command in this scope takes from it."""
        return {name: getattr(self, name) for name in _FIELDS_FROM_SCOPE}

    def scope_with_added_run_conditions(self, *conditions: RunCondition) -> _Scope:
        return replace(self, runs_if=self.runs_if + conditions)

    def scope_with_ignored_errexit(self) -> _Scope:
        return replace(self, errexit_is_ignored=True)

    def scope_for_substitution(self) -> _Scope:
        """Make the scope of the commands in a `$(...)` of a statement in this scope."""
        return self.scope_for_succeeded_if_text_exits_zero_only_if(
            False
        ).scope_without_stdin()

    def scope_without_stdin(self) -> _Scope:
        """Drop the heredoc, herestring or file that this scope gives to stdin, for commands that do not read it."""
        return replace(
            self,
            stdin_text=None,
            is_heredoc_delimiter_quoted=None,
            stdin_file_path=None,
        )

    def scope_for_succeeded_if_text_exits_zero_only_if(self, condition: bool) -> _Scope:
        """Narrow `succeeded_if_text_exits_zero` to also need `condition`."""
        return replace(
            self,
            succeeded_if_text_exits_zero=self.succeeded_if_text_exits_zero
            and condition,
        )


class _ListDecidingCommandIds(NamedTuple):
    """Deciding command ids of a list's left side and of the whole list, e.g. `a && b`."""

    left: _DecidingCommandIds
    whole: _DecidingCommandIds


def _pipeline_stages_of(node: Node) -> tuple[list[Node], list[bool]]:
    """Split a pipeline into its stages, with whether `|&` sends each stage's stderr to the next."""
    stages = _named_children_without_comments_of(node)
    if len(stages) == 1 and stages[0].type == "pipeline":  # `| a | b` after a heredoc
        return _pipeline_stages_of(stages[0])
    pipes_stderr = [
        stage.next_sibling is not None and stage.next_sibling.type == "|&"
        for stage in stages
    ]
    return stages, pipes_stderr


def _pipeline_after_heredoc_of(redirects: Sequence[Node]) -> Node | None:
    """Find the `| b` that tree-sitter puts in the heredoc of `cat <<EOF | b`."""
    for redirect in redirects:
        if redirect.type == "heredoc_redirect":
            for child in redirect.named_children:
                if child.type == "pipeline":
                    return child
    return None


def _has_stderr_pipe_at_start(node: Node) -> bool:
    """Check whether a pipeline that tree-sitter put after a heredoc starts with `|&`."""
    return bool(node.children) and node.children[0].type == "|&"


def _if_clause_parts_of(clause: Node) -> tuple[list[Node], list[Node]]:
    """Split an if, elif or else clause at `then` into its condition and body.

    tree-sitter marks the condition of an if but not of an elif, so the position decides.
    An else clause has no condition.
    """
    then_index = next(
        (i for i, c in enumerate(clause.children) if c.type == "then"), -1
    )
    conditions: list[Node] = []
    body: list[Node] = []
    for index, child in enumerate(clause.children):
        if child.is_named and child.type not in (
            "comment",
            "elif_clause",
            "else_clause",
        ):
            (conditions if index < then_index else body).append(child)
    return conditions, body


def _run_condition_from(
    deciding_command_ids: _DecidingCommandIds, outcome: ExitOutcome
) -> RunCondition:
    """Make a RunCondition, with no deciding ids when they are unknown."""
    return RunCondition(deciding_command_ids or (), outcome)


def _combined_deciding_command_ids_of(
    *parts: _DecidingCommandIds,
) -> _DecidingCommandIds:
    """Combine the deciding command ids of statements, unknown when any of them is unknown."""
    combined: list[int] = []
    for part in parts:
        if part is None:
            return None
        combined.extend(part)
    return tuple(combined)


def _conditions_with_later_condition_from(
    conditions: tuple[RunCondition, ...], condition: RunCondition
) -> tuple[RunCondition, ...]:
    """Add `condition` to the conditions for later statements.

    A known condition implies the earlier ones, since its deciding commands ran under them.
    An unknown one does not, so the earlier ones stay.
    """
    if condition.deciding_command_ids:
        return (condition,)
    return conditions if condition in conditions else (*conditions, condition)


def _is_errexit_statement(statement: Node) -> bool:
    """Check whether `set -e` ends the text when the statement fails.

    A list does not, also when tree-sitter reads it as one statement, nor `! a | b`.
    An assignment does only with a `$(...)`, whose exit code is its own.
    """
    if statement.type not in _ERREXIT_STATEMENT_TYPES or _bash_list_of(statement):
        return False
    if statement.type == "pipeline":
        stages = _named_children_without_comments_of(statement)
        return not stages or (
            stages[0].type != "negated_command" and _misread_list_of(stages[0]) is None
        )
    if statement.type in ("variable_assignment", "variable_assignments"):
        return bool(_command_substitutions_of(statement))
    return True


def _bash_list_of(statement: Node) -> _BashList | None:
    """Read a statement as the list bash runs, also when tree-sitter reads it otherwise.

    tree-sitter puts `&& b` of `cat <<EOF && b` in the heredoc, and reads `a && b > f` as `(a && b) > f`.
    Bash runs `(cat <<EOF) && b` and `a && (b > f)`.
    The operator after a heredoc comes last, e.g. `||` in `a && cat <<EOF || b`.
    """
    if statement.type == "list":
        left, operator, right = _list_parts_of(statement)
        return _BashList(left, operator, right)
    if statement.type != "redirected_statement":
        return None
    redirects = statement.children_by_field_name("redirect")
    body = statement.child_by_field_name("body")
    for redirect in redirects:
        operator = redirect.child_by_field_name("operator")
        right = redirect.child_by_field_name("right")
        is_heredoc = redirect.type == "heredoc_redirect"
        if (
            is_heredoc
            and body is not None
            and operator is not None
            and right is not None
        ):
            return _BashList(body, operator.type, right, left_redirects=redirects)
    misread_list = _misread_list_of(statement)
    if misread_list is not None:
        left, operator, right = _list_parts_of(misread_list)
        return _BashList(left, operator, right, right_redirects=redirects)
    return None


def _list_parts_of(node: Node) -> tuple[Node, str, Node]:
    """Split a list into its left side, operator and right side.

    A list with a syntax error and no operator counts as ||, which says least.
    """
    operator = next((c.type for c in node.children if c.type in ("&&", "||")), "||")
    parts = _named_children_without_comments_of(node)
    return parts[0], operator, parts[-1]


def _named_children_without_comments_of(
    node: Node, except_field: str | None = None
) -> list[Node]:
    """List the named children of a node, without comments or those in `except_field`."""
    return [
        child
        for index, child in enumerate(node.children)
        if child.is_named
        and child.type != "comment"
        and (except_field is None or node.field_name_for_child(index) != except_field)
    ]


class _BashList(NamedTuple):
    """List as bash runs it, `a && b` or `a || b`, with the redirects of each side."""

    left: Node
    operator: str
    right: Node
    left_redirects: Sequence[Node] = ()  # e.g. `<<EOF` of `cat <<EOF && b`
    right_redirects: Sequence[Node] = ()  # e.g. `> f` of `a && b > f`


def _misread_list_of(statement: Node) -> Node | None:
    """Find the list that tree-sitter took as one redirected statement, e.g. `a && b` in `a && b > f`."""
    if statement.type != "redirected_statement":
        return None
    body = statement.child_by_field_name("body")
    return body if body is not None and body.type == "list" else None


def _command_substitutions_of(node: Node) -> list[Node]:
    """Find the outermost `$(...)` and backtick nodes in a node, e.g. in a word."""
    if node.type == "command_substitution":
        return [node]
    return [s for child in node.children for s in _command_substitutions_of(child)]


def _command_substitution_text_of(node: Node) -> str:
    """Give the text of a `$(...)`, backtick, `<(...)` or `>(...)` node as written, without the whitespace that tree-sitter puts in front of it.

    Inside double quotes tree-sitter puts the whitespace before a substitution that follows another one into the node of the later one, e.g. `` `ls` `` in ``echo "$(a) `ls`"``.
    Both `command_substitution_texts_of` and the walker take the text from here, so that a text found by one is the same text the other compares.
    """
    return _node_text_of(node).lstrip()


def _single_quoted_strings_of(node: Node) -> list[Node]:
    """Find the single-quoted strings in a node outside its `$(...)` and backtick nodes, e.g. `'echo $(a)'` in `bash -c 'echo $(a)'`."""
    if node.type == "command_substitution":
        return []
    if node.type == "raw_string":
        return [node]
    return [s for child in node.children for s in _single_quoted_strings_of(child)]


def _is_bare_exec(statement: Node) -> bool:
    """Check whether a statement is `exec` with redirects only, e.g. `exec > log 2>&1`."""
    is_redirected = statement.type == "redirected_statement"
    command = statement.child_by_field_name("body") if is_redirected else statement
    if command is None or command.type != "command":
        return False
    statement_redirects = (
        statement.children_by_field_name("redirect") if is_redirected else []
    )
    redirects = _redirects_in_text_order_of(command, statement_redirects)
    word_nodes = _command_word_nodes_with_redirect_word_nodes_of(command, redirects)
    return [_word_value_of(w) for w in word_nodes] == ["exec"]


def _command_word_nodes_with_redirect_word_nodes_of(
    command_node: Node, redirects: Sequence[Node]
) -> list[Node]:
    """List the word nodes of a command with those that tree-sitter put into its redirects, in text order, e.g. cmd and a for `cmd > f a`."""
    return sorted(
        [*_command_word_nodes_of(command_node), *_redirect_word_nodes_of(redirects)],
        key=lambda word_node: word_node.start_byte,
    )


def _redirect_word_nodes_of(redirects: Sequence[Node]) -> list[Node]:
    """Find the word nodes that tree-sitter put into redirects after their target, which bash reads as words of the command.

    tree-sitter-bash 0.25.1 reads a word after a redirect target as another target, e.g. a and b in `cmd 2>&1 a b`, and a word after a heredoc start as part of the heredoc, e.g. a in `cat <<EOF a`.
    A redirect with a syntax error in it gives none, e.g. `2>&1 | tail -5` that tree-sitter reads as the target of `python - <<EOF 2>&1 | tail -5`, since its words come from a wrong reading.
    The text has a syntax error then, so its commands are marked.
    """
    words: list[Node] = []
    for redirect in redirects:
        if any(child.type == "ERROR" for child in redirect.children):
            continue
        if redirect.type == "file_redirect":
            words.extend(redirect.children_by_field_name("destination")[1:])
        elif redirect.type == "heredoc_redirect":
            words.extend(redirect.children_by_field_name("argument"))
            # e.g. a in `cat <<EOF > f a`
            words.extend(
                _redirect_word_nodes_of(redirect.children_by_field_name("redirect"))
            )
    return words


def _command_words_with_restored_dashes_from(
    word_nodes: Sequence[Node],
    redirects: Sequence[Node],
    text_after_line_repairs: bytes,
) -> list[_CommandWord]:
    """Restore among a command's word nodes each `-` word that tree-sitter left out of the tree, in text order.

    tree-sitter-bash 0.25.1 puts a `-` word in no node when a heredoc or a redirect with a descriptor number follows it, e.g. `python - <<EOF` or `cat - 2>&1`.
    Bash reads the `-` as a word of the command in both.
    """
    # Byte offsets in the text of the redirects that follow a lost `-`.
    lost_dash_offsets: list[int] = []
    # Byte offset of the end of the last word or redirect seen.
    previous_end_offset: int | None = None
    for node in sorted([*word_nodes, *redirects], key=lambda n: n.start_byte):
        if node in redirects and previous_end_offset is not None:
            gap = text_after_line_repairs[previous_end_offset : node.start_byte]
            if _LOST_DASH.fullmatch(gap.replace(b"\\\n", b"")):
                lost_dash_offsets.append(node.start_byte)
        previous_end_offset = max(previous_end_offset or 0, node.end_byte)
    command_words: list[_CommandWord] = list(word_nodes)
    for offset in lost_dash_offsets:
        index = sum(1 for w in word_nodes if w.start_byte < offset)
        index += sum(1 for o in lost_dash_offsets if o < offset)
        command_words.insert(index, _LostDash.DASH)
    return command_words


class _LostDash(Enum):
    """`-` word that tree-sitter puts in no node, kept among the word nodes of its command, e.g. in `python - <<EOF`."""

    DASH = "-"


def _timed_command_words_of(
    command_node: Node, command_words: Sequence[_CommandWord]
) -> list[_CommandWord] | None:
    """Give the words of the command that the reserved word `time` times, without `time` and its `-p`, e.g. curl u for `time -p curl u`.

    tree-sitter-bash 0.25.1 reads `time` as a command name, e.g. `time -p curl u` as a command with four words.
    For `time (a && b)` no word is left, since the subshell is walked on its own.
    Returns None when `time` is no reserved word here or times nothing.
    Bash takes `time` as the reserved word only at the start of a pipeline, so it is a program in `a | time b`, `X=1 time b` and `'time' b`.
    `time` alone and `time -p` alone time nothing, and their words stay as they are.
    """
    name = command_node.child_by_field_name("name")
    if (
        name is None
        or command_node.children[0] != name
        or _is_pipe_reader(command_node)
    ):
        return None
    if not command_words or _written_command_word_of(command_words[0]) != "time":
        return None
    index = 1
    if (
        index < len(command_words)
        and _written_command_word_of(command_words[index]) == "-p"
    ):
        index += 1
    timed_command_words = list(command_words[index:])
    if not timed_command_words and not _timed_statements_of(command_node):
        return None
    return timed_command_words


def _is_timed_statement_misread(
    command_node: Node, timed_command_words: Sequence[_CommandWord]
) -> bool:
    """Check whether tree-sitter misread what `time` times, so the timed words are wrong.

    tree-sitter-bash 0.25.1 reads a compound command after `time` as plain words, e.g. `time { a; }` or `time if a; then b; fi`, an assignment as a word, e.g. A=1 in `time A=1 b`, and `time (( 1 ))` as two subshells.
    It also leaves words beside a timed subshell, e.g. b from the redirect in `time (a) > f b`, which bash rejects.
    """
    timed_statements = _timed_statements_of(command_node)
    if timed_command_words:
        if timed_statements:
            return True
        first_timed_word = _written_command_word_of(timed_command_words[0])
        return (
            first_timed_word in _RESERVED_WORDS_MISREAD_AFTER_TIME
            or _ASSIGNMENT_WORD_START.match(first_timed_word) is not None
        )
    return _node_text_of(timed_statements[0]).startswith("((")


def _timed_statements_of(command_node: Node) -> list[Node]:
    """Find the subshells and brace groups that tree-sitter puts in a command, e.g. `(a && b)` in `time (a && b)`."""
    return [
        child
        for child in command_node.named_children
        if child.type in _TIMED_STATEMENT_TYPES
    ]


def _is_pipe_reader(command_node: Node) -> bool:
    """Check whether a command is a pipeline stage after the first, e.g. b in `a | b` or in `a | b > f`."""
    node = command_node
    while True:
        previous = node.prev_sibling
        while previous is not None and previous.type == "comment":
            previous = previous.prev_sibling
        if previous is not None:
            return previous.type in ("|", "|&")
        parent = node.parent
        if parent is None or parent.type != "redirected_statement":
            return False
        node = parent


def _written_command_word_of(command_word: _CommandWord) -> str:
    """Give a command word as written, quotes included, e.g. `'time'` for a quoted time."""
    if isinstance(command_word, _LostDash):
        return command_word.value
    return _node_text_of(command_word)


def _command_word_value_of(command_word: _CommandWord) -> str:
    """Give a command word as the shell passes it, without quotes, e.g. `time` for `'time'`."""
    if isinstance(command_word, _LostDash):
        return command_word.value
    return _word_value_of(command_word)


def _command_word_nodes_of(node: Node) -> list[Node]:
    """List the word nodes of a command node, its name and then its arguments.

    A word that tree-sitter adds after a syntax error, e.g. after the `||` of `a ||`, is left out.
    """
    name = node.child_by_field_name("name")
    name_words = name.named_children[:1] if name is not None else []
    words = [*name_words, *node.children_by_field_name("argument")]
    return [w for w in words if not w.is_missing and w.end_byte > w.start_byte]


def _word_value_of(word_node: Node) -> str:
    """Strip a word's quotes and escapes as the shell does, e.g. `a b` for `'a b'` or `a\\ b`.

    An expansion is kept as written, e.g. `$A/x` for `"$A/x"`.
    So are tilde, glob and brace words such as `~/x`, `*.py` and `{a,b}`, and escapes in `$'...'`.
    """
    text = _node_text_of(word_node)
    if word_node.type in _EXPANSION_NODE_TYPES:
        return text
    if word_node.type == "raw_string":  # `'a'`
        return text[1:-1]
    if word_node.type == "ansi_c_string":  # `$'a'`
        return text[2:-1]
    if word_node.type == "string":  # `"a"`
        return _double_quoted_value_of(word_node)
    if word_node.type == "concatenation":  # `a"b"'c'`
        return "".join(_word_value_of(part) for part in word_node.children)
    return _UNQUOTED_ESCAPE.sub(_character_after_backslash_of, text)


def _double_quoted_value_of(string_node: Node) -> str:
    """Strip the quotes of a double-quoted word and undo its escapes outside its expansions."""
    source = string_node.text or b""
    start = string_node.start_byte
    parts: list[str] = []
    position = start + 1  # after the opening quote
    for child in string_node.named_children:
        if child.type in _EXPANSION_NODE_TYPES:
            parts.append(
                _unescaped_double_quoted_text_of(
                    source[position - start : child.start_byte - start]
                )
            )
            parts.append(_node_text_of(child))
            position = child.end_byte
    parts.append(
        _unescaped_double_quoted_text_of(source[position - start : len(source) - 1])
    )
    return "".join(parts)


def _node_text_of(node: Node) -> str:
    """Decode a tree-sitter node's text as written."""
    return node.text.decode("utf-8", "replace") if node.text else ""


def _unescaped_double_quoted_text_of(text: bytes) -> str:
    decoded = text.decode("utf-8", "replace")
    return _DOUBLE_QUOTED_ESCAPE.sub(_character_after_backslash_of, decoded)


def _character_after_backslash_of(match: re.Match[str]) -> str:
    """Replace `\\x` with x, and drop an escaped line break."""
    character = match.group(1)
    return "" if character == "\n" else character


def _has_expansion(word_node: Node) -> bool:
    """Check whether a word holds `$A`, `${A}`, `$(...)`, backticks, `<(...)`, `>(...)` or `$((...))`."""
    return word_node.type in _EXPANSION_NODE_TYPES or any(
        _has_expansion(child) for child in word_node.children
    )
