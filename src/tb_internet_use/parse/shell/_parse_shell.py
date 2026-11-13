"""Parse a shell text into its simple commands, with when each runs and where its output goes.

tree-sitter-bash 0.25.1 misreads a few shapes.
The walk reads them as bash runs them, and each place says which shape it handles.

Known limits, rare in the trajectories
- After `!` the deciding commands are unknown, e.g. for b in `! a && b`.
- In `bash -c` text, a `$(...)` written like one the outer shell ran counts as that one.
- `exec > log` changes later output only when it stands alone, not in `exec > log || x`.
- `set -e` is off inside `$(...)` as in bash, also when the shell is sh.
- A `set` in a function body is taken to hold in the body only.
- tree-sitter misreads `$"..."`, an escaped line break inside a word, `! { a; b; }`
  and backticks in heredocs.
"""

import itertools
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any, NamedTuple

import tree_sitter_bash
from tree_sitter import Language, Node, Parser, Tree

from tb_internet_use.parse.shell._words import node_text, word_has_expansion, word_value
from tb_internet_use.parse.shell.model import (
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
    VariableAssignment,
)
from tb_internet_use.parse.shell.programs import (
    nested_shell_text,
    program_words,
    shell_options_at_start,
)

_PARSER = Parser(Language(tree_sitter_bash.language()))
# Shell text run by `bash -c` is read up to this depth, e.g. bash -c in bash -c.
_MAX_NESTING_DEPTH = 3
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
    "stdin_file_path",
    "stdout",
    "stderr",
    "runs_if",
    "in_loop_body",
    "in_function_body",
    "in_case_branch",
    "runs_in_background",
    "succeeded_if_text_exits_zero",
    "structure_may_be_wrong",
)
# Fields that text run by a command takes from that command.
# Stdin is left out. That is right for the heredoc of `bash <<EOF`, which is the text itself,
# and misses a file that the text's commands read, e.g. log for grep in `bash -c 'grep x' < log`.
_FIELDS_FROM_RUNNER = tuple(
    name for name in _FIELDS_FROM_SCOPE if name not in ("stdin_text", "stdin_file_path")
)
# A word such as {a,b} or {1..3}, which bash turns into several words.
_BRACE_LIST = re.compile(r"\{[^{}\s]*,[^{}\s]*\}|\{\w+\.\.\w+\}")
# A glob character that a backslash does not escape, e.g. * in *.txt.
_GLOB_CHARACTER = re.compile(r"(?<!\\)[*?[]")
# A line break that ends a command, not one escaped by a backslash.
_UNESCAPED_LINE_BREAK = re.compile(rb"(?<!\\)\n")
# A comment, which starts with # after a space.
_COMMENT_START = re.compile(rb"(?:^|\s)#")
# How many times a text is parsed again to keep joined lines apart.
_MAX_LINE_REPAIRS = 3
# A cluster of one-letter options of `set`, e.g. -e, +e or -euo.
_SET_OPTION_CLUSTER = re.compile(r"[-+][a-zA-Z]+")

# The ids of the commands whose exit code can be a statement's.
# None when unknown, e.g. for `! a`, `[ -f x ]` or an if statement.
type _DecidingCommandIds = tuple[int, ...] | None
# Walks one statement under a scope.
type _StatementWalk = Callable[[_Scope], _DecidingCommandIds]


def parse_shell(
    text: str, *, runner: ShellCommand | None = None, first_id: int = 0
) -> ParsedShellText:
    """Split a shell text into its simple commands, recording when each runs and where its output goes.

    Pass `runner` when another command runs the text,
    e.g. `cd x && bash fetch.sh > log` for the content of fetch.sh, or `bash <<EOF` for its heredoc.
    The text's commands then take the runner's run conditions (cd must succeed),
    output destination (log) and shell options (errexit for `bash -e`).

    Pass `first_id` to keep ids unique when one call runs several texts.
    """
    parse_state = _ParseState(first_id)
    scope = _Scope.of_runner(runner, nesting_depth=0) if runner else _Scope()
    options = _ShellOptions.at_start_of(runner) if runner else _ShellOptions()
    _ShellTextWalker(parse_state, options).walk_text(text, scope)
    return ParsedShellText(tuple(parse_state.commands), tuple(parse_state.assignments))


class _ShellTextWalker:
    """Walker of one shell text, which adds its commands to the parse state.

    Its shell options hold for this text only. A text that a command runs gets a walker of its own.
    """

    def __init__(
        self,
        parse_state: _ParseState,
        options: _ShellOptions,
        *,
        records_assignments: bool = True,
        substitutions_run_by_outer_shell: frozenset[str] = frozenset(),
    ) -> None:
        self._parse_state = parse_state
        self._options = options
        # Assignments in text that a new shell runs are left out, see VariableAssignment.
        self._records_assignments = records_assignments
        # The text of each `$(...)` that an outer shell ran before this text ran,
        # e.g. `$(a)` in the text of `bash -c "echo $(a)"`.
        self._substitutions_run_by_outer_shell = substitutions_run_by_outer_shell
        self._has_brace_list = False

    def walk_text(self, text: str, scope: _Scope) -> None:
        """Add the text's commands, all marked as maybe wrong after a syntax error or a brace list."""
        first_new_index = len(self._parse_state.commands)
        tree = _parse_with_lines_kept_apart(text)
        self._walk_statements(tree.root_node.named_children, scope)
        if tree.root_node.has_error or self._has_brace_list:
            commands = self._parse_state.commands
            for index in range(first_new_index, len(commands)):
                commands[index] = replace(commands[index], structure_may_be_wrong=True)

    def _walk_statements(
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
            statement_scope = scope.running_if(*conditions_for_later_statements)
            if _is_in_background(statement):
                self._walk_in_background(statement, statement_scope)
                deciding_command_ids = None  # it always exits 0
                continue
            decides = not has_exited and (
                index == len(statements) - 1
                or self._ends_text_on_failure(statement, scope)
            )
            deciding_command_ids, exit_guard = self._walk_with_exit_guard(
                statement, statement_scope.succeeded_if_text_exits_zero_only_if(decides)
            )
            conditions_for_later_statements = self._conditions_for_later_statements(
                conditions_for_later_statements,
                statement,
                scope,
                deciding_command_ids,
                exit_guard,
            )
            has_exited = has_exited or _always_exits_or_returns(statement)
            scope = self._scope_after_exec(statement, scope, deciding_command_ids)
        return deciding_command_ids

    def _walk_in_background(self, statement: Node, scope: _Scope) -> None:
        """Walk a statement started with `&`, which never decides the exit code."""
        background = replace(scope, runs_in_background=True)
        self._walk_node(
            statement, background.succeeded_if_text_exits_zero_only_if(False)
        )

    def _walk_node(self, node: Node, scope: _Scope) -> _DecidingCommandIds:
        """Walk any node by its type and return its deciding command ids."""
        match node.type:
            case "command":
                return self._walk_command_node(node, scope)
            case "list":
                left, operator, right = _list_parts(node)
                return self._walk_bash_list(
                    _BashList(left, operator, right), scope
                ).whole
            case "pipeline":
                return self._walk_pipeline_node(node, scope)
            case "redirected_statement":
                return self._walk_redirected_statement(node, scope)
            case "compound_statement" | "do_group":
                return self._walk_statements(node.named_children, scope)
            case "subshell":
                walk = partial(self._walk_statements, node.named_children, scope)
                return self._walk_with_own_options(walk)
            case "if_statement":
                return self._walk_if(node, scope)
            case "while_statement":
                return self._walk_while(node, scope)
            case "for_statement" | "c_style_for_statement":
                return self._walk_for(node, scope)
            case "case_statement":
                return self._walk_case(node, scope)
            case "function_definition":
                return self._walk_function_definition(node, scope)
            case "negated_command":
                negated_scope = scope.succeeded_if_text_exits_zero_only_if(False)
                for child in node.named_children:
                    self._walk_node(child, negated_scope.ignoring_errexit())
                return None
            case "command_substitution" | "process_substitution":
                return self._walk_substitution(node, scope)
            case "variable_assignment":
                return self._walk_variable_assignment(node, scope)
            case "variable_assignments":  # e.g. `A=1 B=$(b)`
                return self._walk_variable_assignments(node, scope)
            case "comment":
                return None
            case _:  # e.g. `[ -f x ]`, `export X=1`, or the words in a string
                for child in node.named_children:
                    self._walk_node(
                        child, scope.succeeded_if_text_exits_zero_only_if(False)
                    )
                return None

    def _walk_command_node(
        self, node: Node, scope: _Scope, outer_redirects: Sequence[Node] = ()
    ) -> _DecidingCommandIds:
        """Walk a command under its own redirects and those of its redirected statement."""
        redirects = _redirects_in_text_order(node, outer_redirects)
        walk = partial(self._walk_command_words, node)
        return self._walk_under_redirects(redirects, scope, walk)

    def _walk_command_words(self, node: Node, scope: _Scope) -> _DecidingCommandIds:
        """Add a command from its words, then walk the commands in its `$(...)`."""
        word_nodes = _command_word_nodes(node)
        if any(map(_is_brace_list, word_nodes)):
            self._has_brace_list = True
        deciding_command_ids: _DecidingCommandIds = None
        if word_nodes:
            deciding_command_ids = (self._append_shell_command(word_nodes, scope),)
        substitution_scope = scope.inside_substitution()
        for word_node in word_nodes:
            # e.g. `$(ls)` in `echo $(ls)`
            self._walk_node(word_node, substitution_scope)
        for child in node.named_children:
            if child.type == "variable_assignment":
                # Only the value, e.g. `$(ls)` in `A=$(ls) b`, since b alone gets A.
                value = child.child_by_field_name("value")
                if value is not None:
                    self._walk_node(value, substitution_scope)
            elif child.type in ("subshell", "compound_statement"):
                # The statement that `time` times, e.g. `time (a && b)`.
                deciding_command_ids = self._walk_node(child, scope)
        return deciding_command_ids

    def _walk_under_redirects(
        self, redirects: Sequence[Node], scope: _Scope, walk_statement: _StatementWalk
    ) -> _DecidingCommandIds:
        """Walk a statement under its redirects, which apply in order.

        The commands in a redirect's `$(...)`, `<(...)` or heredoc run before the statement.
        A `>(...)` target reads the statement's output, so its commands come after it.
        """
        substitution_scope = scope.inside_substitution()
        for redirect in redirects:
            for part in _parts_run_before_redirect(redirect):
                self._walk_node(part, substitution_scope)
        redirected = _scope_after_redirects(
            redirects, scope, self._parse_state.pipe_placeholders
        )
        commands = self._parse_state.commands
        writer_start_index = len(commands)
        deciding_command_ids = walk_statement(redirected.scope)
        for placeholder, output_reader in redirected.output_readers:
            reader_index = len(commands)
            self._walk_substitution(output_reader, substitution_scope)
            self._connect_pipe(placeholder, writer_start_index, reader_index)
        return deciding_command_ids

    def _walk_substitution(
        self, node: Node, scope: _Scope, *, decides_exit: bool = False
    ) -> _DecidingCommandIds:
        """Walk the commands of a `$(...)`, backticks, `<(...)` or `>(...)`.

        The first three hand their stdout to the enclosing command.
        `>(...)` reads output instead, and its stdout goes where the enclosing command's goes.
        Each runs in a subshell, so its `set` options end with it.
        Bash also turns `set -e` off inside `$(...)`, while sh keeps it, and this follows bash.
        A `$(...)` that an outer shell already ran is not walked again.
        `decides_exit` is for the `$(...)` whose exit code an assignment takes.
        """
        if node_text(node) in self._substitutions_run_by_outer_shell:
            return None
        inner_scope = scope.without_stdin()
        if not decides_exit:
            inner_scope = inner_scope.succeeded_if_text_exits_zero_only_if(False)
        if not _reads_output(node):
            inner_scope = replace(inner_scope, stdout=CaptureDestination())
        walk = partial(self._walk_statements, node.named_children, inner_scope)
        errexit = self._options.errexit and node.type != "command_substitution"
        return self._walk_with_own_options(walk, errexit=errexit)

    def _walk_bash_list(
        self,
        bash_list: _BashList,
        scope: _Scope,
        walk_right: _StatementWalk | None = None,
    ) -> _ListDecidingCommandIds:
        """Walk a statement that bash runs as a list, or its left side and `walk_right`."""
        walk_left = self._walk_side(bash_list.left, bash_list.left_redirects)
        if walk_right is None:
            walk_right = self._walk_side(bash_list.right, bash_list.right_redirects)
        return self._walk_list(walk_left, bash_list.operator, walk_right, scope)

    def _walk_side(self, node: Node, redirects: Sequence[Node]) -> _StatementWalk:
        """Make the walk of one side of a list, under the redirects that belong to that side."""
        if redirects:
            return partial(self._walk_with_redirects, node, redirects)
        return partial(self._walk_node, node)

    def _walk_with_redirects(
        self, body: Node, redirects: Sequence[Node], scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a statement under its redirects. For a list or pipeline they are its last part's.

        tree-sitter reads `a && b > f` as `(a && b) > f` and `a | b > f` as `(a | b) > f`.
        Bash runs `a && (b > f)` and `a | (b > f)`.
        """
        if body.type == "command":
            return self._walk_command_node(body, scope, redirects)
        if body.type == "list":
            left, operator, right = _list_parts(body)
            bash_list = _BashList(left, operator, right, right_redirects=redirects)
            return self._walk_bash_list(bash_list, scope).whole
        if body.type == "pipeline":
            stages, pipes_stderr = _pipeline_stages(body)
            if stages:
                stage_walks = [
                    *(partial(self._walk_node, stage) for stage in stages[:-1]),
                    partial(self._walk_with_redirects, stages[-1], redirects),
                ]
                return self._walk_pipeline_stages(stage_walks, pipes_stderr, scope)
        return self._walk_under_redirects(
            redirects, scope, partial(self._walk_node, body)
        )

    def _walk_pipeline_node(self, node: Node, scope: _Scope) -> _DecidingCommandIds:
        """Walk a pipeline, also `! a | b` and `a && b 2>&1 | c`, which tree-sitter misreads."""
        stages, pipes_stderr = _pipeline_stages(node)
        if not stages:
            return None
        first = stages[0]
        if first.type == "negated_command":
            # tree-sitter reads `! a | b` as `(! a) | b`. Bash runs `! (a | b)`.
            negated = _named_children_without_comments(first)[:1]
            stage_walks = [partial(self._walk_node, s) for s in [*negated, *stages[1:]]]
            negated_scope = scope.succeeded_if_text_exits_zero_only_if(False)
            self._walk_pipeline_stages(
                stage_walks, pipes_stderr, negated_scope.ignoring_errexit()
            )
            return None
        misread_list = _misread_list(first)
        if misread_list is not None:
            # tree-sitter reads `a && b 2>&1 | c` as `(a && b) 2>&1 | c`.
            # Bash runs `a && (b 2>&1 | c)`.
            left, operator, right = _list_parts(misread_list)
            redirects = first.children_by_field_name("redirect")
            stage_walks = [
                partial(self._walk_with_redirects, right, redirects),
                *(partial(self._walk_node, stage) for stage in stages[1:]),
            ]
            walk_pipeline = partial(
                self._walk_pipeline_stages, stage_walks, pipes_stderr
            )
            bash_list = _BashList(left, operator, right)
            return self._walk_bash_list(bash_list, scope, walk_pipeline).whole
        stage_walks = [partial(self._walk_node, stage) for stage in stages]
        return self._walk_pipeline_stages(stage_walks, pipes_stderr, scope)

    def _walk_redirected_statement(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a statement with redirects, also a list or pipe that tree-sitter misread into it."""
        redirects = node.children_by_field_name("redirect")
        bash_list = _bash_list(node)
        piped = _pipeline_after_heredoc(redirects)
        if piped is None and bash_list is not None:
            return self._walk_bash_list(bash_list, scope).whole
        # A list that tree-sitter misread, e.g. `a && b > f`, has the redirects on its last command.
        misread_list = bash_list if bash_list and bash_list.right_redirects else None
        last = misread_list.right if misread_list else node.child_by_field_name("body")
        if last is None:
            return None
        walk_last = partial(self._walk_with_redirects, last, redirects)
        if piped is None:
            return walk_last(scope)
        # tree-sitter reads `| b` in `cat <<EOF | b` as part of the heredoc.
        # In `a && cat <<EOF | b`, bash pipes cat alone into b.
        stages, pipes_stderr = _pipeline_stages(piped)
        stage_walks = [
            walk_last,
            *(partial(self._walk_node, stage) for stage in stages),
        ]
        pipes_stderr = [_starts_with_stderr_pipe(piped), *pipes_stderr]
        walk_pipeline = partial(self._walk_pipeline_stages, stage_walks, pipes_stderr)
        if misread_list is not None:
            return self._walk_bash_list(misread_list, scope, walk_pipeline).whole
        return walk_pipeline(scope)

    def _walk_if(self, node: Node, scope: _Scope) -> _DecidingCommandIds:
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
        remaining_clauses_scope = scope.succeeded_if_text_exits_zero_only_if(False)
        for clause in clauses:
            conditions, body = _if_clause_parts(clause)
            if conditions:
                deciding_command_ids = self._walk_statements(
                    conditions, remaining_clauses_scope.ignoring_errexit()
                )
                success = _run_condition(deciding_command_ids, ExitOutcome.SUCCESS)
                self._walk_statements(body, remaining_clauses_scope.running_if(success))
                remaining_clauses_scope = remaining_clauses_scope.running_if(
                    _run_condition(deciding_command_ids, ExitOutcome.FAILURE)
                )
            else:
                self._walk_statements(body, remaining_clauses_scope)
        return None

    def _walk_while(self, node: Node, scope: _Scope) -> _DecidingCommandIds:
        """Walk a while or until loop.

        The body runs while the condition succeeds, or for `until` while it fails.
        """
        loop_scope = scope.succeeded_if_text_exits_zero_only_if(False)
        deciding_command_ids = self._walk_statements(
            node.children_by_field_name("condition"), loop_scope.ignoring_errexit()
        )
        is_until = node.children[0].type == "until"
        required = ExitOutcome.FAILURE if is_until else ExitOutcome.SUCCESS
        body = node.child_by_field_name("body")
        if body is not None:
            body_scope = replace(loop_scope, in_loop_body=True)
            self._walk_node(
                body,
                body_scope.running_if(_run_condition(deciding_command_ids, required)),
            )
        return None

    def _walk_for(self, node: Node, scope: _Scope) -> _DecidingCommandIds:
        """Walk a for loop, and record each item of `for x in a b` as a value of x, with where the loop ends.

        A list with `$A`, a glob such as `*.txt` or a brace list such as `{1,2}` is computed as the loop runs,
        and so is a missing list, which stands for the script's arguments as in `for x; do`. Then one assignment without a value is recorded.
        A C-style loop such as `for ((i=0; i<3; i++))` changes what its header assigns, so i gets no value.
        """
        loop_scope = scope.succeeded_if_text_exits_zero_only_if(False)
        variable = node.child_by_field_name("variable")
        items = node.children_by_field_name("value")
        assignments = self._parse_state.assignments
        first_item_index = len(assignments)
        if variable is not None:
            if items and not any(map(_is_computed_word, items)):
                for item in items:
                    self._record_assignment(node_text(variable), word_value(item))
            else:
                self._record_assignment(node_text(variable), None)
        item_indexes = range(first_item_index, len(assignments))
        for child in _named_children_without_comments(node, except_field="body"):
            self._walk_node(child, loop_scope)  # e.g. `$(ls)` in `for f in $(ls)`
        if variable is None:
            for index in range(item_indexes.stop, len(assignments)):
                assignments[index] = replace(assignments[index], value=None)
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_node(body, replace(loop_scope, in_loop_body=True))
        for index in item_indexes:
            assignments[index] = replace(
                assignments[index],
                next_command_id_after_for_loop=self._parse_state.next_command_id,
            )
        return None

    def _walk_case(self, node: Node, scope: _Scope) -> _DecidingCommandIds:
        """Walk a case statement, whose branches run only if their pattern matches."""
        branch_scope = scope.succeeded_if_text_exits_zero_only_if(False)
        value = node.child_by_field_name("value")
        if value is not None:
            self._walk_node(value, branch_scope)
        for item in node.named_children:
            if item.type == "case_item":
                body = _named_children_without_comments(item, except_field="value")
                self._walk_statements(body, replace(branch_scope, in_case_branch=True))
        return None

    def _walk_function_definition(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk a function body, which runs only if the function is called.

        Calls are not followed, so a `set` in the body is taken to hold in the body only.
        """
        body = node.child_by_field_name("body")
        if body is not None:
            body_scope = replace(
                scope.succeeded_if_text_exits_zero_only_if(False), in_function_body=True
            )
            self._walk_with_own_options(partial(self._walk_node, body, body_scope))
        return None

    def _walk_variable_assignment(
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
            value is None or not (value.type == "array" or word_has_expansion(value))
        )
        if name is not None:
            literal = word_value(value) if value is not None else ""
            self._record_assignment(node_text(name), literal if is_literal else None)
        if value is None:
            return None
        substitutions = _command_substitutions(value)
        last_substitution = substitutions[-1] if substitutions else None
        has_parts = value.type in ("string", "concatenation")
        deciding_command_ids: _DecidingCommandIds = None
        for part in value.named_children if has_parts else [value]:
            if part == last_substitution:
                deciding_command_ids = self._walk_substitution(
                    part, scope, decides_exit=True
                )
            else:
                self._walk_node(part, scope.succeeded_if_text_exits_zero_only_if(False))
        return deciding_command_ids

    def _walk_variable_assignments(
        self, node: Node, scope: _Scope
    ) -> _DecidingCommandIds:
        """Walk `A=1 B=$(b)`, which exits as its last assignment with a `$(...)` does."""
        deciding_command_ids: _DecidingCommandIds = None
        for assignment in node.named_children:
            assignment_deciding_command_ids = self._walk_node(assignment, scope)
            if _command_substitutions(assignment):
                deciding_command_ids = assignment_deciding_command_ids
        return deciding_command_ids

    def _walk_with_exit_guard(
        self, statement: Node, scope: _Scope
    ) -> tuple[_DecidingCommandIds, RunCondition | None]:
        """Walk a statement, and return its deciding command ids and its condition on later statements.

        Later statements run only if a succeeded after `a || exit`,
        and only if a failed after `a && exit`.
        """
        bash_list = _bash_list(statement)
        if bash_list is None or not _always_exits_or_returns(bash_list.right):
            return self._walk_node(statement, scope), None
        walked = self._walk_bash_list(bash_list, scope)
        is_or = bash_list.operator == "||"
        outcome = ExitOutcome.SUCCESS if is_or else ExitOutcome.FAILURE
        return walked.whole, _run_condition(walked.left, outcome)

    def _append_shell_command(self, word_nodes: Sequence[Node], scope: _Scope) -> int:
        """Add one command, then the commands of the text it runs, and return its id."""
        command = ShellCommand(
            id=self._parse_state.next_command_id,
            words=tuple(map(word_value, word_nodes)),
            has_expansion=any(map(word_has_expansion, word_nodes)),
            **scope.command_fields(),
        )
        self._parse_state.commands.append(command)
        if command.words[:1] == ("set",):
            self._options = self._options.after_set(command.words[1:])
        self._walk_nested_text(command, word_nodes, scope)
        return command.id

    def _walk_nested_text(
        self, command: ShellCommand, word_nodes: Sequence[Node], scope: _Scope
    ) -> None:
        """Walk the text a command runs with `bash -c` or `eval`, with a walker of its own.

        A new shell starts with its own options. `eval` runs the text in this shell.
        """
        nested_text = nested_shell_text(command)
        if nested_text is None or scope.nesting_depth >= _MAX_NESTING_DEPTH:
            return
        runs_in_this_shell = program_words(command)[:1] == ("eval",)
        nested_scope = _Scope.of_runner(command, scope.nesting_depth + 1)
        if runs_in_this_shell:
            options = self._options
            nested_scope = replace(
                nested_scope, errexit_is_ignored=scope.errexit_is_ignored
            )
        else:
            options = _ShellOptions.at_start_of(command)
        # In `bash -c "echo $(a)"` this shell runs a and passes its output to bash.
        text_words = [w for w in word_nodes if word_value(w) == nested_text]
        run_here = {
            node_text(s)
            for w in text_words or word_nodes[1:]  # eval may take several words
            for s in _command_substitutions(w)
        }
        walker = _ShellTextWalker(
            self._parse_state,
            options,
            records_assignments=self._records_assignments and runs_in_this_shell,
            substitutions_run_by_outer_shell=self._substitutions_run_by_outer_shell
            | run_here,
        )
        walker.walk_text(nested_text, nested_scope)
        if runs_in_this_shell:
            self._options = walker._options  # e.g. `eval "set -e"`

    def _walk_with_own_options(
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

    def _walk_pipeline_stages(
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
            stage_scope = scope.succeeded_if_text_exits_zero_only_if(
                is_last or self._options.pipefail
            )
            if index > 0:
                stage_scope = stage_scope.without_stdin()
            placeholder = None
            if not is_last:
                placeholder = PipeDestination(next(self._parse_state.pipe_placeholders))
                stderr = placeholder if pipes_stderr[index] else stage_scope.stderr
                stage_scope = replace(stage_scope, stdout=placeholder, stderr=stderr)
            stage_start_index = len(commands)
            stage_deciding_command_ids = walk_stage(stage_scope)
            if previous_stage is not None:
                self._connect_pipe(*previous_stage, reader_index=stage_start_index)
            previous_stage = (
                (placeholder, stage_start_index) if placeholder is not None else None
            )
            deciding_command_ids = (
                _combined_deciding_command_ids(
                    deciding_command_ids, stage_deciding_command_ids
                )
                if self._options.pipefail
                else stage_deciding_command_ids
            )
        return deciding_command_ids

    def _connect_pipe(
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

    def _walk_list(
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
        side_scope = scope.succeeded_if_text_exits_zero_only_if(is_and)
        left = walk_left(side_scope.ignoring_errexit())
        required = ExitOutcome.SUCCESS if is_and else ExitOutcome.FAILURE
        right = walk_right(side_scope.running_if(_run_condition(left, required)))
        return _ListDecidingCommandIds(
            left, _combined_deciding_command_ids(left, right)
        )

    def _record_assignment(self, name: str, value: str | None) -> None:
        """Record an assignment, unless a new shell runs this text."""
        if self._records_assignments:
            next_command_id = self._parse_state.next_command_id
            assignment = VariableAssignment(name, value, next_command_id, None)
            self._parse_state.assignments.append(assignment)

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
        if condition is None and self._ends_text_on_failure(statement, scope):
            condition = _run_condition(deciding_command_ids, ExitOutcome.SUCCESS)
        if condition is None:
            return conditions
        return _with_later_condition(conditions, condition)

    def _ends_text_on_failure(self, statement: Node, scope: _Scope) -> bool:
        """Check whether `set -e` makes the text end when this statement fails."""
        return (
            self._options.errexit
            and not scope.errexit_is_ignored
            and _is_errexit_statement(statement)
        )

    def _scope_after_exec(
        self,
        statement: Node,
        scope: _Scope,
        deciding_command_ids: _DecidingCommandIds,
    ) -> _Scope:
        """Compute the scope of later statements, whose output `exec > log` sends to log."""
        if not _is_bare_exec(statement) or not deciding_command_ids:
            return scope
        exec_command = self._parse_state.command_with_id(deciding_command_ids[-1])
        return replace(scope, stdout=exec_command.stdout, stderr=exec_command.stderr)


@dataclass(slots=True)
class _ParseState:
    """Parser state kept during one `parse_shell` call, shared by the walkers of the text and of `bash -c` text in it."""

    first_id: int  # from parse_shell, so that ids stay unique within one call
    # In id order, so an id gives its index.
    commands: list[ShellCommand] = field(default_factory=list)
    assignments: list[VariableAssignment] = field(default_factory=list)
    # Placeholder reader ids for pipes whose reader is not walked yet. Each pipe has its own.
    pipe_placeholders: Iterator[int] = field(
        default_factory=lambda: itertools.count(-1, -1)
    )

    @property
    def next_command_id(self) -> int:
        return self.first_id + len(self.commands)

    def command_with_id(self, command_id: int) -> ShellCommand:
        return self.commands[command_id - self.first_id]


@dataclass(frozen=True, slots=True)
class _ShellOptions:
    """Shell options of one text that change what an exit code says."""

    errexit: bool = False  # set -e, so a failing command or pipeline ends the text
    pipefail: bool = False  # set -o pipefail, so every stage decides a pipeline

    @classmethod
    def at_start_of(cls, runner: ShellCommand) -> _ShellOptions:
        """Read the options that `runner` starts its text with, e.g. errexit for `bash -e fetch.sh`."""
        names = shell_options_at_start(runner)
        return cls(errexit="errexit" in names, pipefail="pipefail" in names)

    def after_set(self, arguments: Sequence[str]) -> _ShellOptions:
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


def _parse_with_lines_kept_apart(text: str) -> Tree:
    """Parse a text, putting `;` at the end of lines that tree-sitter joins.

    tree-sitter joins the next line into the last stage of a pipeline of three or more stages,
    e.g. `a | b | c` then `d 2>&1 | e` gives `c d` piped into e.
    A `;` keeps the lines apart and means the same to bash.
    """
    source = text.encode("utf-8", "replace")
    tree = _PARSER.parse(source)
    for _ in range(_MAX_LINE_REPAIRS):
        positions = _joined_line_ends(tree.root_node, source)
        if not positions:
            break
        for position in sorted(positions, reverse=True):
            source = source[:position] + b";" + source[position:]
        tree = _PARSER.parse(source)
    return tree


def _joined_line_ends(root: Node, source: bytes) -> list[int]:
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
        words = _command_word_nodes(node)
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


def _always_exits_or_returns(node: Node) -> bool:
    """Check whether a statement ends the shell, e.g. `exit 1` or `{ echo failed; exit 1; }`."""
    if node.type == "command":
        name = node.child_by_field_name("name")
        return name is not None and word_value(name) in ("exit", "return")
    if node.type == "compound_statement":
        statements = _named_children_without_comments(node)
        return bool(statements) and _always_exits_or_returns(statements[-1])
    return False


def _redirects_in_text_order(
    command_node: Node, outer_redirects: Sequence[Node]
) -> list[Node]:
    """List a command's own redirects, then those of its redirected statement, as in the text.

    Own redirects come first, e.g. `> f` before `2>&1` in `> f a 2>&1`.
    """
    return [*command_node.children_by_field_name("redirect"), *outer_redirects]


def _is_computed_word(word_node: Node) -> bool:
    """Check whether the shell computes a word's value as it runs, e.g. `$A`, `*.txt` or `{a,b}`."""
    return (
        word_has_expansion(word_node)
        or _is_brace_list(word_node)
        or _is_glob(word_node)
    )


def _is_glob(word_node: Node) -> bool:
    """Check whether a word has a `*`, `?` or `[` outside quotes, which the shell turns into file names."""
    parts = word_node.children if word_node.type == "concatenation" else [word_node]
    return any(
        part.type == "word" and _GLOB_CHARACTER.search(node_text(part))
        for part in parts
    )


def _is_brace_list(word_node: Node) -> bool:
    """Check whether a word outside quotes is a brace list, e.g. `{a,b}` or `x{1..3}`."""
    if word_node.type == "brace_expression":
        return True
    if word_node.type == "word":
        return bool(_BRACE_LIST.search(node_text(word_node)))
    if word_node.type == "concatenation":
        unquoted = "".join(node_text(c) for c in word_node.children if c.type == "word")
        return any(c.type == "brace_expression" for c in word_node.children) or bool(
            _BRACE_LIST.search(unquoted)
        )
    return False


def _parts_run_before_redirect(redirect: Node) -> list[Node]:
    """Find the parts of a redirect whose `$(...)` and `<(...)` run before the statement.

    They are the target of `> f$(a)` or `< <(a)`, the word of `<<< "$(a)"`
    and the body of a heredoc whose delimiter is not quoted.
    """
    if redirect.type == "file_redirect":
        destination = redirect.child_by_field_name("destination")
        if destination is None or _reads_output(destination):
            return []
        return [destination]
    if redirect.type == "herestring_redirect":
        return list(redirect.named_children)
    if redirect.type == "heredoc_redirect":
        bodies = [c for c in redirect.named_children if c.type == "heredoc_body"]
        # e.g. `> f` in `cat <<EOF > f`
        inner = redirect.children_by_field_name("redirect")
        return [*bodies, *(p for r in inner for p in _parts_run_before_redirect(r))]
    return []


def _scope_after_redirects(
    redirects: Sequence[Node], scope: _Scope, placeholders: Iterator[int]
) -> _RedirectedScope:
    """Apply redirects to a scope in order, e.g. `> log 2>&1` sends both streams to log.

    A `>(...)` target gets a pipe placeholder, which its walk connects to its first command.
    """
    output_readers: list[tuple[PipeDestination, Node]] = []
    for redirect in redirects:
        if redirect.type == "file_redirect":
            destination_node = redirect.child_by_field_name("destination")
            if destination_node is not None and _reads_output(destination_node):
                placeholder = PipeDestination(next(placeholders))
                output_readers.append((placeholder, destination_node))
                scope = _scope_after_file_redirect(redirect, scope, placeholder)
            else:
                scope = _scope_after_file_redirect(redirect, scope)
        elif redirect.type == "heredoc_redirect":
            body = next(
                (c for c in redirect.named_children if c.type == "heredoc_body"), None
            )
            scope = replace(
                scope,
                stdin_text=node_text(body) if body is not None else "",
                stdin_file_path=None,
            )
            # e.g. `> f` in `cat <<EOF > f`
            inner = redirect.children_by_field_name("redirect")
            inner_redirected = _scope_after_redirects(inner, scope, placeholders)
            scope = inner_redirected.scope
            output_readers.extend(inner_redirected.output_readers)
        elif redirect.type == "herestring_redirect" and redirect.named_children:
            scope = replace(
                scope,
                stdin_text=word_value(redirect.named_children[-1]),
                stdin_file_path=None,
            )
    return _RedirectedScope(scope, tuple(output_readers))


def _reads_output(node: Node) -> bool:
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


def _scope_after_file_redirect(
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
        descriptor = node_text(descriptor_node)
    else:
        descriptor = "0" if is_input else "1"
    destination_node = redirect.child_by_field_name("destination")
    target = word_value(destination_node) if destination_node is not None else ""
    if is_input:
        # `<&3` copies a descriptor and names no file.
        if operator != "<" or descriptor != "0":
            return scope
        # `< <(cmd)` gives stdin the output of cmd, not a file.
        if (
            destination_node is not None
            and destination_node.type == "process_substitution"
        ):
            return scope.without_stdin()
        return replace(scope, stdin_file_path=target, stdin_text=None)
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
    stdin_file_path: str | None = None
    runs_if: tuple[RunCondition, ...] = ()
    in_loop_body: bool = False
    in_function_body: bool = False
    in_case_branch: bool = False
    runs_in_background: bool = False
    # True for the whole text, then narrowed by each statement.
    succeeded_if_text_exits_zero: bool = True
    structure_may_be_wrong: bool = False
    # `set -e` does not end the text here, e.g. left of && or in an if condition.
    errexit_is_ignored: bool = False
    # How many bash -c or eval texts this one is in, capped by _MAX_NESTING_DEPTH.
    nesting_depth: int = 0

    @classmethod
    def of_runner(cls, runner: ShellCommand, nesting_depth: int) -> _Scope:
        """Make the scope of text that `runner` runs, which exits as the text does."""
        inherited = {name: getattr(runner, name) for name in _FIELDS_FROM_RUNNER}
        return cls(nesting_depth=nesting_depth, **inherited)

    def command_fields(self) -> dict[str, Any]:
        """Return the ShellCommand fields that a command in this scope takes from it."""
        return {name: getattr(self, name) for name in _FIELDS_FROM_SCOPE}

    def running_if(self, *conditions: RunCondition) -> _Scope:
        return replace(self, runs_if=self.runs_if + conditions)

    def ignoring_errexit(self) -> _Scope:
        return replace(self, errexit_is_ignored=True)

    def inside_substitution(self) -> _Scope:
        """Make the scope of the commands in a `$(...)` of a statement in this scope."""
        return self.succeeded_if_text_exits_zero_only_if(False).without_stdin()

    def without_stdin(self) -> _Scope:
        """Drop the heredoc, herestring or file that this scope gives to stdin, for commands that do not read it."""
        return replace(self, stdin_text=None, stdin_file_path=None)

    def succeeded_if_text_exits_zero_only_if(self, condition: bool) -> _Scope:
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


def _pipeline_stages(node: Node) -> tuple[list[Node], list[bool]]:
    """Split a pipeline into its stages, with whether `|&` sends each stage's stderr to the next."""
    stages = _named_children_without_comments(node)
    if len(stages) == 1 and stages[0].type == "pipeline":  # `| a | b` after a heredoc
        return _pipeline_stages(stages[0])
    pipes_stderr = [
        stage.next_sibling is not None and stage.next_sibling.type == "|&"
        for stage in stages
    ]
    return stages, pipes_stderr


def _pipeline_after_heredoc(redirects: Sequence[Node]) -> Node | None:
    """Find the `| b` that tree-sitter puts in the heredoc of `cat <<EOF | b`."""
    for redirect in redirects:
        if redirect.type == "heredoc_redirect":
            for child in redirect.named_children:
                if child.type == "pipeline":
                    return child
    return None


def _starts_with_stderr_pipe(node: Node) -> bool:
    """Check whether a pipeline that tree-sitter put after a heredoc starts with `|&`."""
    return bool(node.children) and node.children[0].type == "|&"


def _if_clause_parts(clause: Node) -> tuple[list[Node], list[Node]]:
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


def _run_condition(
    deciding_command_ids: _DecidingCommandIds, outcome: ExitOutcome
) -> RunCondition:
    """Make a RunCondition, with no deciding ids when they are unknown."""
    return RunCondition(deciding_command_ids or (), outcome)


def _combined_deciding_command_ids(
    *parts: _DecidingCommandIds,
) -> _DecidingCommandIds:
    """Combine the deciding command ids of statements, unknown when any of them is unknown."""
    combined: list[int] = []
    for part in parts:
        if part is None:
            return None
        combined.extend(part)
    return tuple(combined)


def _with_later_condition(
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
    if statement.type not in _ERREXIT_STATEMENT_TYPES or _bash_list(statement):
        return False
    if statement.type == "pipeline":
        stages = _named_children_without_comments(statement)
        return not stages or (
            stages[0].type != "negated_command" and _misread_list(stages[0]) is None
        )
    if statement.type in ("variable_assignment", "variable_assignments"):
        return bool(_command_substitutions(statement))
    return True


def _bash_list(statement: Node) -> _BashList | None:
    """Read a statement as the list bash runs, also when tree-sitter reads it otherwise.

    tree-sitter puts `&& b` of `cat <<EOF && b` in the heredoc, and reads `a && b > f`
    as `(a && b) > f`. Bash runs `(cat <<EOF) && b` and `a && (b > f)`.
    The operator after a heredoc comes last, e.g. `||` in `a && cat <<EOF || b`.
    """
    if statement.type == "list":
        left, operator, right = _list_parts(statement)
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
    misread_list = _misread_list(statement)
    if misread_list is not None:
        left, operator, right = _list_parts(misread_list)
        return _BashList(left, operator, right, right_redirects=redirects)
    return None


def _list_parts(node: Node) -> tuple[Node, str, Node]:
    """Split a list into its left side, operator and right side.

    A list with a syntax error and no operator counts as ||, which says least.
    """
    operator = next((c.type for c in node.children if c.type in ("&&", "||")), "||")
    parts = _named_children_without_comments(node)
    return parts[0], operator, parts[-1]


def _named_children_without_comments(
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


def _misread_list(statement: Node) -> Node | None:
    """Find the list that tree-sitter took as one redirected statement, e.g. `a && b` in `a && b > f`."""
    if statement.type != "redirected_statement":
        return None
    body = statement.child_by_field_name("body")
    return body if body is not None and body.type == "list" else None


def _command_substitutions(node: Node) -> list[Node]:
    """Find the outermost `$(...)` and backtick nodes in a node, e.g. in a word."""
    if node.type == "command_substitution":
        return [node]
    return [s for child in node.children for s in _command_substitutions(child)]


def _is_bare_exec(statement: Node) -> bool:
    """Check whether a statement is `exec` with redirects only, e.g. `exec > log 2>&1`."""
    is_redirected = statement.type == "redirected_statement"
    command = statement.child_by_field_name("body") if is_redirected else statement
    if command is None or command.type != "command":
        return False
    return [word_value(w) for w in _command_word_nodes(command)] == ["exec"]


def _command_word_nodes(node: Node) -> list[Node]:
    """List the word nodes of a command node, its name and then its arguments.

    A word that tree-sitter adds after a syntax error, e.g. after the `||` of `a ||`, is left out.
    """
    name = node.child_by_field_name("name")
    name_words = name.named_children[:1] if name is not None else []
    words = [*name_words, *node.children_by_field_name("argument")]
    return [w for w in words if not w.is_missing and w.end_byte > w.start_byte]
