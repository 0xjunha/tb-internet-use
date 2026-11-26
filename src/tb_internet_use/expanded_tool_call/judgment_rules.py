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
    It returns `False`, so the rule is asked once per command, for the first such word.
    A use is such a word.

    Decided. The user decided on 2026-11-24 that such a word starts the unread words, since its value may hold options, e.g. `--no-index --find-links /wheels` in `$OPTS` of `pip install $OPTS requests`, so reading it as one argument puts in the lower bound a target and a default host that the trajectory does not show. The earlier code read it as one argument.
    """
    use_counts[treat_word_with_expansion_as_one_argument.__name__] += 1
    return False


def treat_poll_as_reading_latest_earlier_start_of_handle(
    *, use_counts: Counter[str]
) -> bool:
    """Link a poll to the latest of the earlier calls of its trajectory that started a handle of the id it names, when several did, e.g. call 9 that polls handle `3` after calls 2 and 7 both started a handle `3`.

    A harness can give a handle id again once the work it named has ended, and the trajectory does not say which of the starts a poll means.
    `expand_poll_links` asks it for each handle of a poll that more than one earlier call of the poll's trajectory started.
    On `True` the poll is linked to the latest of them, and on `False` to none, so that handle of the poll has no starter.
    It returns `False`.
    A use is such a handle of a poll.

    Decided. The user decided on 2026-11-24 to link such a poll to none of the starts, since the trajectory does not say which start it reads, and a link to the wrong one gives a request the output of another call as evidence that it received, e.g. `Successfully installed x-1.0` that an earlier `pip install --index-url http://localhost:8080/simple x` printed. The earlier code linked a poll to the latest earlier call that started the id.
    """
    use_counts[treat_poll_as_reading_latest_earlier_start_of_handle.__name__] += 1
    return False


def treat_calls_of_other_trajectory_as_not_linked(*, use_counts: Counter[str]) -> bool:
    """Leave a link that only a call of another trajectory of the trial would give unmade, e.g. a poll in a subagent of the handle `3` that a call of the main trajectory started.

    The trajectory of a call is its `ToolCallKey.trajectory_id` with its `HarnessToolCall.is_subagent`.
    The trajectories do not say how the calls of the main trajectory and of each subagent interleave, or whether they share handles, e.g. Muse puts the calls of a subagent after all calls of the main trajectory.
    `expand_poll_links` asks it for each handle of a poll that no earlier call of the poll's trajectory started and a call of another trajectory did start, wherever that call sits in the trial.
    `expand_ran_texts` asks it, once all calls are read, for each run or use of a path that no write of its own trajectory fits and a write of another trajectory does, wherever that write sits in the trial.
    On `True` that handle of the poll has no starter and that run or use has no writer.
    On `False` the handle is linked as if the trial had one trajectory, to the latest call before the poll that started the id, and `expand_ran_texts` reads all calls of the trial again as one trajectory.
    A use is such a handle of a poll, or such a run or use of a path.

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


def treat_first_poll_that_saw_end_as_command_text_status(
    *, use_counts: Counter[str]
) -> bool:
    """Take the end state of a call's command text from the later polls that saw it end, when the call's own result is running or unknown, e.g. a call whose result says running and whose handle three later polls read.

    A handle can be polled again after its command ended, and a later poll can report another state, e.g. one poll reports a timeout and a later one exit code 0, so the trajectory does not say which report is the end state.
    Only a poll that is the call's action and reads one handle counts, since a poll of several handles or a poll step of a tool script has one result for more than that command.
    `expand_command_text_status` asks it for each call that has such a poll whose result is finished, timed out or killed.
    On `True` the status is that of the first such poll, and the exit code that of the first such poll with the same status that states one, e.g. 7 from an Antigravity CLI `SYSTEM_MESSAGE` `Command exited with code 7` after a `manage_task` result `Status: DONE` that states none. When two such polls state different exit codes, the exit code is unknown.
    On `False` the status and exit code stay those of the call's own result, e.g. running without an exit code.
    A use is such a call.

    Provisional. It keeps the choice of the earlier code, which took the first poll of one handle that saw the command end, and takes the exit code from a later poll only where the first states none, since a poll such as `Status: DONE` says that the command ended but not how.
    """
    use_counts[treat_first_poll_that_saw_end_as_command_text_status.__name__] += 1
    return True


def treat_path_that_ends_another_as_same_file(
    path: str, other_path: str, *, use_counts: Counter[str]
) -> bool:
    """Read two different path texts as one file when their parts are the same or the relative one ends the other by whole folders, e.g. `scripts/fetch.sh` and `/app/scripts/fetch.sh`.

    The working folder of a call is not in the trajectory, so a relative path can name any file whose path ends with it.
    A leading `$NAME`, `~` or `..` part stands for a folder that the text does not show, so such parts are dropped and the rest is read as relative, e.g. `out` for `$LOG/out`.
    `expand_ran_texts` asks it for two paths of different text whose parts, without `.` and `x/..`, match in this way. Two absolute paths do only when their parts are the same, e.g. `/a/./f` and `/a/f`, and two relative paths of as many parts that differ never do, e.g. `a/f` and `b/f`. A base name alone does end a longer relative path, e.g. `f` and `a/f`.
    On `True` the two paths name one file, so a read of one is a read of what was written to the other. On `False` they name different files.
    A use is such a pair of paths.

    Provisional. It keeps the choice of the earlier code, which matched paths in this way.
    """
    use_counts[treat_path_that_ends_another_as_same_file.__name__] += 1
    return True


def treat_path_that_fits_several_written_files_as_unknown_text(
    path: str, *, use_counts: Counter[str]
) -> bool:
    """Read the text of a file that a command runs as unknown when its path fits several files that calls wrote, e.g. `bash fetch.sh` after writes to `/a/fetch.sh` and `/b/fetch.sh`.

    The working folder of the call is not in the trajectory, so the text does not say which of the files ran.
    `expand_ran_texts` asks it for a path that a command runs or that an edit tool edits when it fits more than one written file.
    On `True` the text of a run is an `UnknownRanText` with the reason `FITS_SEVERAL_WRITTEN_FILES`, and the content after an edit is unknown. On `False` the latest of the written files would be followed.
    A use is such a run or edit of a file.

    Provisional. It keeps the choice of the earlier code, which gave such a file unknown content.
    """
    use_counts[treat_path_that_fits_several_written_files_as_unknown_text.__name__] += 1
    return True


def treat_edit_of_text_not_found_once_as_unknown_content(
    path: str, *, use_counts: Counter[str]
) -> bool:
    """Read the content of a file after an edit tool as unknown when the text it replaces is not in the known content exactly once, e.g. `old` that occurs twice or not at all.

    The trajectory does not say which occurrence the tool replaced, or whether it failed and left the file as it was.
    `expand_ran_texts` asks it for an edit of a file whose content is known.
    On `True` the content after the edit is unknown, so a later run of the file is an `UnknownRanText` with the reason `CHANGED_BY_UNREAD_COMMAND`. On `False` the first occurrence would be replaced.
    A use is such an edit.

    Provisional. It keeps the choice of the earlier code, which applied an edit only when its text occurred exactly once.
    """
    use_counts[treat_edit_of_text_not_found_once_as_unknown_content.__name__] += 1
    return True


def treat_input_of_key_presses_only_as_no_text(
    typed_text: str, *, use_counts: Counter[str]
) -> bool:
    """Read the input of a poll that holds only spaces, line breaks, Ctrl-C or Ctrl-D as key presses and not as text that ran, e.g. `\\n` typed to wake a running command.

    Such input may still end or confirm what runs, but it holds no command or code.
    `expand_ran_texts` asks it for each such `PollAction.input`.
    On `True` the poll ran no text. On `False` the input would be read as text, like any other input.
    A use is such an input.

    Provisional. It keeps the choice of the earlier code, which skipped such input.
    """
    use_counts[treat_input_of_key_presses_only_as_no_text.__name__] += 1
    return True


def treat_use_after_later_overwrite_as_use_of_later_write(
    path: str, *, use_counts: Counter[str]
) -> bool:
    """Read a use of a file that a later call overwrote as a use of the later write only, e.g. `cat log` in call 4 after `a > log` in call 1 and `b > log` in call 3.

    A write with `>>` keeps what the file held, so it is no overwrite, and writes within one call are taken together.
    `expand_ran_texts` asks it for a use of a file that an earlier call wrote before another call overwrote it.
    On `True` the use belongs to the later write only. On `False` it would belong to the earlier writes too.
    A use is such a use of a file.

    Provisional. It keeps the choice of the earlier code, which counted reads of a file only until it was overwritten.
    """
    use_counts[treat_use_after_later_overwrite_as_use_of_later_write.__name__] += 1
    return True


def treat_tool_call_not_marked_not_run_as_maybe_run(
    *, use_counts: Counter[str]
) -> bool:
    """Read a tool call without a result, or whose result has the status `UNKNOWN`, as one that may have run, e.g. `curl u > log` cut off at the end of a trajectory.

    The trajectory does not say whether the tool ran such a call.
    `expand_ran_texts` asks it for each such call, but not for a message that the harness wrote, which no tool ran.
    On `True` the call's writes change the files that later calls run and read, and its uses are recorded. On `False` it would be read as a call that did not run.
    A use is such a call.

    Provisional. It keeps the choice of the earlier code, which read every call as run unless its result said `NOT_RUN`.
    """
    use_counts[treat_tool_call_not_marked_not_run_as_maybe_run.__name__] += 1
    return True


def treat_last_command_of_starter_as_reader_of_typed_text(
    *, use_counts: Counter[str]
) -> bool:
    """Read the text that a poll types as taken by the innermost program of the last command of the call that started the polled handle, e.g. gdb for `run` typed after `cd /app && gdb ./a.out`.

    The trajectory does not say which command of the starting call reads the input, e.g. when a Codex `exec` script starts two commands.
    The last command is that of the last text the starting call holds itself, i.e. its command string or its script step with the highest index.
    `expand_ran_texts` asks it for each typed text whose poll has exactly one starting call.
    On `True` that program decides whether and how the text runs. On `False` the text is an `UnknownRanText` with the reason `LANGUAGE_NOT_KNOWN`, whatever reads it.
    It returns `False`.
    A use is such a typed text.

    Decided. The user decided on 2026-11-24 that every such text is of a language not known, since a program that an earlier poll started may read it instead, e.g. cat after `cat > notes.txt` typed into a running bash, and the code does not follow such a change of reader. The earlier code read every typed text as shell text.
    """
    use_counts[treat_last_command_of_starter_as_reader_of_typed_text.__name__] += 1
    return False


def treat_command_under_run_condition_as_run(*, use_counts: Counter[str]) -> bool:
    """Record the file writes, removals and uses of a command that runs only under a condition as if it ran, e.g. `curl u > log` in `test -f x && curl u > log` or `cat log` in a function that is never called.

    Whether the condition held is not in the text, and later steps judge each command by its own evidence.
    `expand_ran_texts` asks it for each file write, removal or use of a command with `runs_if`, `in_function_body` or `in_case_branch`.
    On `True` the write, removal or use is recorded. On `False` it would be left out.
    A use is such a write, removal or use of a file.

    Provisional. It keeps the choice of the earlier code, which recorded them.
    """
    use_counts[treat_command_under_run_condition_as_run.__name__] += 1
    return True


def treat_use_of_path_that_fits_several_written_files_as_use_of_each(
    path: str, *, use_counts: Counter[str]
) -> bool:
    """Record a use of a path that fits several files that calls wrote as a use of each, marked as fitting several, e.g. `cat fetch.log` after writes to `/a/fetch.log` and `/b/fetch.log`.

    The working folder of the call is not in the trajectory, so the text does not say which file was used.
    `expand_ran_texts` asks it for such a use.
    On `True` the use goes on each written file with `fits_several_written_files` set. On `False` it goes on none of them, so it is a use of a file without a known writer.
    It returns `False`.
    A use is such a use of a file.

    Decided. The user decided on 2026-11-24 that such a use goes on none of the files, since the mark `fits_several_written_files` is not read where the lines of a shown file get their owners, so a use on each lets a request that wrote one of the files own alone a line that another file held. The earlier code recorded such a read on each file without a mark.
    """
    use_counts[
        treat_use_of_path_that_fits_several_written_files_as_use_of_each.__name__
    ] += 1
    return False


def treat_file_not_named_by_command_words_as_untouched(
    word: str, *, use_counts: Counter[str]
) -> bool:
    """Read a command as touching only the files that its words name as they are, e.g. none of the files under `scripts` for `rm -rf scripts` or `sed -i s/a/b/ *.sh`.

    A glob, a folder or the arguments that a program gets at run time, e.g. sed in `ls | xargs sed -i s/a/b/`, name files that the text does not show.
    `expand_ran_texts` asks it for each word with a file role and each redirect path that holds `*`, `?`, `[` or `{` outside a parameter such as `${D}`, for each word with the role `DELETED_FILE` or path of a delete tool that names a folder of a written file, and for each program with a file role that gets arguments at run time.
    On `True` the content and the uses of those files stay as they are, and a copy from a glob records no write of its destination either, e.g. g.sh of `cp *.sh g.sh` stays a file that no call wrote.
    On `False` a glob or a folder is read as a path as written, so those files stay as they are on either answer, and a touch of that path is recorded instead, e.g. a written file named `*.sh` for `sed -i s/a/b/ *.sh`, or the copy g.sh with unknown content for `cp *.sh g.sh`.
    A use is such a word or program.

    Provisional. It keeps the choice of the earlier code, which matched only the paths as written.
    """
    use_counts[treat_file_not_named_by_command_words_as_untouched.__name__] += 1
    return True


def treat_copy_with_two_arguments_as_same_content(*, use_counts: Counter[str]) -> bool:
    """Read the copy that a command with exactly two arguments makes as having the content of its source, e.g. g.sh after `cp f.sh g.sh` or `mv f.sh g.sh`, and leave the source as it was.

    The command may fail, and a `mv` removes its source, which the text does not show.
    `expand_ran_texts` asks it for each such copy.
    On `True` the copy has the content of the source, unknown when that is unknown. On `False` the copy has unknown content.
    It returns `False`. The source stays as it was on either answer.
    A use is such a copy.

    Decided. The user decided on 2026-11-24 that the copy has unknown content, since the code does not read whether the copy failed, e.g. `cp fetch.sh /usr/local/bin/run.sh` under `Permission denied`, so a later run would follow content that may never have been copied. The earlier code copied the known content and left the source.
    """
    use_counts[treat_copy_with_two_arguments_as_same_content.__name__] += 1
    return False


def treat_outer_assignment_as_not_visible_in_new_shell(
    *, use_counts: Counter[str]
) -> bool:
    """Read text that a new shell runs as seeing only its own assignments, e.g. no value for U in `curl $U` of `U=a.org; bash -c 'curl $U'` or of `export U=a.org; bash f.sh`.

    An assignment reaches a new shell only when it is exported, and the reading of `export` is not settled.
    `expand_ran_texts` asks it for each text that a program with a row runs in a new shell, e.g. `bash -c` or `bash f.sh`, when the text that runs it assigns a variable before the running command.
    A file run by its path, e.g. `./f.sh`, is a new shell too, but the code does not ask this rule there and gives its text none of those assignments.
    On `True` the text sees none of those assignments. On `False` it would see them as text run in the calling shell does, e.g. the text of `eval`, though without the shell options of the command that runs it, e.g. `-o pipefail` of `bash -o pipefail f.sh`.
    A use is such a text.

    Provisional. The earlier code gave the outer values, so this rule claims less.
    """
    use_counts[treat_outer_assignment_as_not_visible_in_new_shell.__name__] += 1
    return True


def treat_deleted_file_as_never_written(path: str, *, use_counts: Counter[str]) -> bool:
    """Read a file that a command or a delete tool removed as one that no call wrote, e.g. f.sh in `bash f.sh` after `rm f.sh`.

    The removal may fail, and a later step of the task may put the file back, which the text does not show.
    `expand_ran_texts` asks it for each run, use or edit of a path that fits a written file that was removed since.
    On `True` the run is an `UnknownRanText` with the reason `NOT_WRITTEN_IN_TRIAL`, the use goes on no written file and the content after an edit is unknown. On `False` the written file would still be used.
    A use is such a run, use or edit.

    Provisional. The earlier code did not read removals and kept the written content.
    """
    use_counts[treat_deleted_file_as_never_written.__name__] += 1
    return True


def treat_extension_of_file_without_interpreter_line_as_its_language(
    path: str, *, use_counts: Counter[str]
) -> bool:
    """Read a file that a command runs by its path and whose first line is no `#!` line as text in the language of its extension, e.g. Python for `./get.py`.

    Without a `#!` line the kernel does not run the file by its extension, and the shell may run it as shell text.
    `expand_ran_texts` asks it for each such file with known content.
    On `True` the language is that of its extension in `code_runners.csv`, and the text is an `UnknownRanText` with the reason `LANGUAGE_NOT_KNOWN` when the extension has no row. On `False` the language is unknown.
    It returns `False`. It is asked before the extension is looked at, so a file without an extension counts too, e.g. `./run`.
    A use is such a file.

    Decided. The user decided on 2026-11-24 that the language of such a file is unknown, since the kernel does not run a file by its extension, e.g. `./get.py` without a `#!` line runs as shell text and fails at `import requests`. The earlier code read such a file by its extension.
    """
    use_counts[
        treat_extension_of_file_without_interpreter_line_as_its_language.__name__
    ] += 1
    return False


def treat_script_step_output_as_shown_in_call_result(
    step_index: int, *, use_counts: Counter[str]
) -> bool:
    """Read the output of the commands of a tool script step as shown in the result of the script's call, e.g. a Codex `exec` script whose step calls `exec_command` and whose code may not print what the command returned.

    The trajectory has one result for the whole script, and what the script prints is up to its code, so it does not say whether the output of a step reached that result.
    `expand_output_places` asks it for each step of a tool script, i.e. a `RunCommandAction` step or a poll step that types text, with a command whose output ends in the result, when the result of the call has tool output text and is not `NOT_RUN`. `step_index` is 0-based.
    On `True` the call's result is a place of those commands. On `False` it is not, and neither is a later read of the file where the harness saved that result, so a step that shows a file, e.g. `cat build.log`, shows it nowhere.
    It returns `False`. The later polls of a handle that the script started stay places on either answer.
    A use is such a step.

    Decided. The user decided on 2026-11-24 that the result is no place of the step's commands, since the script's code decides what its result prints, so a line there may come from anything but the step, e.g. a log that the code reads itself. The earlier code took the result of a call as the result of all of its commands, script steps included.
    """
    use_counts[treat_script_step_output_as_shown_in_call_result.__name__] += 1
    return False


def treat_poll_result_as_showing_every_command_of_starter(
    *, use_counts: Counter[str]
) -> bool:
    """Read the result of a poll as showing the output of every command that runs in what it polls and whose output ends in a result, e.g. both a and b of `a; b &` after the call that started the handle, or both commands that an earlier poll typed.

    The trajectory does not say which of several commands of the starting call the handle names, or which of them are still printing when the poll reads.
    `expand_output_places` asks it for each pair of such a group of more than one command and a later poll whose result can show output, i.e. one with tool output text that is not `NOT_RUN`. A group is the commands of the starting call, with every later poll of a handle it started, or the commands that one poll typed into it, with every later poll of a handle that the typing poll names.
    On `True` the poll's result is a place of all of them. On `False` it is a place of none of them.
    It returns `False`. A group of one command is a place of the poll without the rule.
    A use is such a pair.

    Decided. The user decided on 2026-11-24 that such a result shows none of them, since a poll of one handle shows only the output of what that handle names, e.g. one of the two sessions that a Codex `exec` script started. The earlier code linked the later polls of a handle to the call that started it as a whole, and those after typed input to that input.
    """
    use_counts[treat_poll_result_as_showing_every_command_of_starter.__name__] += 1
    return False


def treat_read_of_output_path_of_several_calls_as_showing_each(
    *, use_counts: Counter[str]
) -> bool:
    """Read a read of a file where the harness saved the results of several earlier calls as showing the result of each of them, e.g. a Cursor terminal file that the results of three calls name.

    The trajectory does not say whether the file still holds the output of the earlier calls or only that of the latest.
    `expand_output_places` asks it for each read that shows the content of such a file, in a call whose result can show output, i.e. for a `FileTouch` with more than one `harness_output_file_tool_call_keys`.
    On `True` the reading call is a place of each of those calls. On `False` it is a place of the latest of them only.
    A use is such a read.

    Provisional. It keeps the choice of the code before this rule, which linked the read to every call whose result named the path.
    """
    use_counts[treat_read_of_output_path_of_several_calls_as_showing_each.__name__] += 1
    return True
