"""Decide what the trajectory and the program catalogs do not settle about what a tool call ran, one named rule per situation, e.g. how to read a command word that holds `$OPTS`.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, `curl $OPTS u` shows only the word `$OPTS`, which may stand for several options or none when the command runs, and only a rule says how `expand_tool_calls` reads it.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into an `ExpandedToolCall`.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter


def treat_values_outside_their_for_loop_as_one_of_them(
    variable_name: str, *, use_counts: Counter[str]
) -> bool:
    """Read the several values that assignments give a variable of a command outside the for loop over them as values of which the command runs with one, e.g. A after `A=1` in one if branch and `A=2` in the other, then `echo $A`.

    The text does not say which assignment ran last, since an assignment can sit in an if branch, a case branch, a function body or a loop that ended before the command, e.g. `for U in a b; do :; done; curl $U`.
    For a command in a loop body or a function body, an assignment later in the text may also run before it, e.g. `U=y` in `U=x; for i in 1 2; do curl $U; U=y; done`.
    `expand_variable_values` asks it for a variable that has more than one possible value, counting a value that the text computes as it runs as one, and whose values are not only the items of the innermost for loop whose body holds the command.
    It returns whether the command runs with one of the values. On `True` every value stays in `VariableValues.values` and `takes_each_value_in_turn` is False. On `False` the command takes each value in turn.
    A use is such a variable of a command.

    Provisional. It keeps the choice of the earlier code, which listed all the values and took each in turn only for the items of the innermost for loop around the command.
    """
    use_counts[treat_values_outside_their_for_loop_as_one_of_them.__name__] += 1
    return True


def treat_word_with_expansion_as_one_argument(
    word: str, *, use_counts: Counter[str]
) -> bool:
    """Read a command word that holds an expansion as one word where it is written, i.e. one argument or one option value, e.g. `$OPTS` in `curl $OPTS u`, `$PKGS` in `pip install $PKGS` or `$F` in `curl -o $F u`.

    The words of a command are as written in the trajectory, so such a word can stand for several options, several arguments or none when the command runs.
    `expand_program_invocations` asks it for each word of `ShellCommand.expansion_word_indexes` that ends as an argument or as the value of an option, once all words of its program are placed.
    It does not ask it for the program word, which is an `UnknownProgramInvocation`, for a skipped `NAME=value` word, or for a word whose place makes it a cluster of one-letter options, which is unread.
    On `True` the word is one argument or one value, and on `False` it and the words after it are unread words, from the word of the option for a value.
    A use is such a word.

    Provisional. It keeps the choice of the earlier code, which read such a word as one argument.
    """
    use_counts[treat_word_with_expansion_as_one_argument.__name__] += 1
    return True


def treat_poll_as_reading_latest_earlier_start_of_handle(
    *, use_counts: Counter[str]
) -> bool:
    """Link a poll to the latest of the earlier calls of its trajectory that started a handle of the id it names, when several did, e.g. call 9 that polls handle `3` after calls 2 and 7 both started a handle `3`.

    A harness can give a handle id again once the work it named has ended, and the trajectory does not say which of the starts a poll means.
    `expand_poll_links` asks it for each handle of a poll that more than one earlier call of the poll's trajectory started.
    On `True` the poll is linked to the latest of them, and on `False` to none, so that handle of the poll has no starter.
    A use is such a handle of a poll.

    Provisional. It keeps the choice of the earlier code, which linked a poll to the latest earlier call that started the id.
    """
    use_counts[treat_poll_as_reading_latest_earlier_start_of_handle.__name__] += 1
    return True


def treat_calls_of_other_trajectory_as_not_linked(*, use_counts: Counter[str]) -> bool:
    """Leave a link that only a call of another trajectory of the trial would give unmade, e.g. a poll in a subagent of the handle `3` that a call of the main trajectory started.

    The trajectory of a call is its `ToolCallKey.trajectory_id` with its `HarnessToolCall.is_subagent`.
    The trajectories do not say how the calls of the main trajectory and of each subagent interleave, or whether they share handles, e.g. Muse puts the calls of a subagent after all calls of the main trajectory.
    `expand_poll_links` asks it for each handle of a poll that no earlier call of the poll's trajectory started and a call of another trajectory did start, wherever that call sits in the trial.
    On `True` that handle of the poll has no starter, and on `False` it is linked as if the trial had one trajectory, to the latest call before the poll that started the id.
    A use is such a handle of a poll.

    Provisional. It claims least, since the earlier code linked across the whole trial.
    """
    use_counts[treat_calls_of_other_trajectory_as_not_linked.__name__] += 1
    return True


def treat_script_poll_step_naming_no_handle_as_polling_none(
    *, use_counts: Counter[str]
) -> bool:
    """Read a poll step of a tool script that names no handle as reading no handle, even when the script's result names one, e.g. a Codex `exec` script whose step `wait()` has no session id and whose result names session `3`.

    The trajectory has one result for the whole script, so it does not say whether the handle in it is the one the step read, one that another step started, or one the script only printed.
    `expand_poll_links` asks it for each such step of a script whose result names at least one handle.
    On `True` the step reads no handle and has no starter, and on `False` it reads every handle that the script's result names, as a poll that is the call's action does.
    So on `False`, when an earlier call started the same id, the step and the later polls of that id link to that earlier call, which is wrong when the script started the id again, as 2 scripts in the 100 sample trials did.
    A use is such a step.

    Provisional. It keeps the choice of the earlier code, which read no handle for such a step.
    """
    use_counts[treat_script_poll_step_naming_no_handle_as_polling_none.__name__] += 1
    return True
