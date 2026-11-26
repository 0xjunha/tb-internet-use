"""Tests for expanded_tool_call/_expand_output_places.py, on made-up calls of one trial whose texts and poll links come from the real `expand_ran_texts` and `expand_poll_links`, with a made-up program catalog whose rows the cases name."""

from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call import _expand_output_places, _expand_ran_texts
from tb_internet_use.expanded_tool_call._expand_output_places import (
    expand_output_places,
)
from tb_internet_use.expanded_tool_call._expand_poll_links import expand_poll_links
from tb_internet_use.expanded_tool_call._expand_ran_texts import expand_ran_texts
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_poll_result_as_showing_every_command_of_starter,
    treat_read_of_output_path_of_several_calls_as_showing_none,
    treat_script_step_output_as_shown_in_call_result,
    treat_typed_text_as_of_unknown_language,
)
from tb_internet_use.expanded_tool_call.model import OutputPlace
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    SearchFilesAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

SCRIPT_STEP_RULE_NAME = treat_script_step_output_as_shown_in_call_result.__name__
EVERY_COMMAND_RULE_NAME = treat_poll_result_as_showing_every_command_of_starter.__name__
SEVERAL_CALLS_RULE_NAME = (
    treat_read_of_output_path_of_several_calls_as_showing_none.__name__
)
TYPED_TEXT_LANGUAGE_RULE_NAME = treat_typed_text_as_of_unknown_language.__name__
HANDLE = ExecutionHandle(ExecutionHandleKind.COMMAND, "h1")
OTHER_HANDLE = ExecutionHandle(ExecutionHandleKind.COMMAND, "h2")
OUTPUT_PATH = "/tmp/tasks/b1.output"

# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool has no row.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {"program_name": "cat", "argument_role": "read_file", "stdin_role": "read_file"},
    {
        "program_name": "tail",
        "argument_role": "read_file",
        "visibility_of_piped_input": "partial",
    },
    {"program_name": "wc", "argument_role": "size_or_type_file"},
    {"program_name": "rm", "argument_role": "deleted_file"},
    {"program_name": "curl"},
    {"program_name": "echo"},
]
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {"program_name": "tail", "option_name": "-1"},
    {"program_name": "wc", "option_name": "-c"},
]
CODE_RUNNER_ROWS: list[dict[str, str]] = [
    {"runner_kind": "program_name", "runner": "bash"},
]


def _key(step_id: int) -> ToolCallKey:
    return ToolCallKey("trial", "main", step_id, 0)


K1, K2, K3, K4, K5, K6 = (_key(step_id) for step_id in range(1, 7))


def _result(
    execution_status: ExecutionStatus = ExecutionStatus.FINISHED,
    *,
    tool_output_text: str | None = "",
    handles: tuple[ExecutionHandle, ...] = (),
    output_path: str | None = None,
) -> ToolCallResult:
    return ToolCallResult(
        tool_output_text=tool_output_text,
        execution_status=execution_status,
        handles=handles,
        output_path=output_path,
    )


FINISHED = _result()
RUNNING = _result(ExecutionStatus.RUNNING, handles=(HANDLE,))


def _command(text: str, *, first_command_id: int = 0) -> RunCommandAction:
    """Make a command action as the converted call holds it, whose command ids start at `first_command_id`, as they do for a later step of a tool script."""
    return RunCommandAction(
        text,
        parse_shell_text(
            text, judgment_rule_use_counts=Counter(), first_command_id=first_command_id
        ),
    )


def _call(
    step_id: int,
    action: ToolCallAction | str,
    result: ToolCallResult | None = FINISHED,
    *,
    is_subagent: bool = False,
) -> ToolCall:
    """Make a call at a step of the main trajectory, taking a string as the command of a `RunCommandAction`."""
    return ToolCall(
        HarnessToolCall(
            _key(step_id),
            HarnessTool("harness", "tool"),
            "",
            {},
            None,
            is_subagent=is_subagent,
        ),
        _command(action) if isinstance(action, str) else action,
        result,
    )


def _poll(step_id: int, typed_text: str | None = None, **result_fields) -> ToolCall:
    return _call(step_id, PollAction((HANDLE,), typed_text), _result(**result_fields))


@pytest.fixture(scope="module")
def knowledge(catalogs_dir: Path) -> ExpandedToolCallKnowledge:
    return ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def _expand(
    knowledge: ExpandedToolCallKnowledge,
    *tool_calls: ToolCall,
    judgment_rule_use_counts: Counter[str] | None = None,
) -> tuple[tuple[OutputPlace, ...], ...]:
    """Expand the output places of calls from the poll links and texts that the earlier pieces give for them."""
    poll_links = expand_poll_links(tool_calls, judgment_rule_use_counts=Counter())
    return expand_output_places(
        tool_calls,
        expand_ran_texts(
            tool_calls,
            poll_links,
            knowledge=knowledge,
            judgment_rule_use_counts=Counter(),
        ),
        poll_links,
        judgment_rule_use_counts=Counter()
        if judgment_rule_use_counts is None
        else judgment_rule_use_counts,
    )


def _answer(monkeypatch: pytest.MonkeyPatch, rule_name: str, answer: bool) -> None:
    """Make a rule of `_expand_output_places` give an answer, e.g. the other one."""
    monkeypatch.setattr(_expand_output_places, rule_name, lambda *_, use_counts: answer)


def _read_typed_text_by_last_command_of_starter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make typed text run as the last command of the starting call reads it, the other answer of the rule that `expand_ran_texts` asks, so that typed commands have output to place."""
    monkeypatch.setattr(
        _expand_ran_texts,
        TYPED_TEXT_LANGUAGE_RULE_NAME,
        lambda *, use_counts: False,
    )


# (case id, the text of one call, the ids of its commands whose output its own result shows, None for no place)
OWN_RESULT_CASES = [
    ("command alone", "curl u", (0,)),
    ("pipe reader shows a part", "curl u | tail -1", (0, 1)),
    ("unknown program reads the pipe", "curl u | mytool", (0, 1)),
    ("stdout alone ends in the result", "curl u 2>/dev/null", (0,)),
    ("stderr alone ends in the result", "curl u > log", (0,)),
    ("all output to a file", "curl u > log 2>&1", None),
    ("all output thrown away", "curl u > /dev/null 2>&1", None),
    ("output captured by $(...)", "x=$(curl u 2>/dev/null)", None),
    ("only the later command", "curl u > /dev/null 2>&1; echo done", (1,)),
]


# (case id, the result of a `curl u` call)
NO_PLACE_RESULTS = [
    ("not run", _result(ExecutionStatus.NOT_RUN)),
    ("no result", None),
    ("no text of what it returned", _result(tool_output_text=None)),
]


# (case id, a command of the call after the call whose result the harness saved in `OUTPUT_PATH`, whether its call is a place of that result)
HARNESS_OUTPUT_FILE_READ_CASES = [
    ("plain read", f"cat {OUTPUT_PATH}", True),
    ("read through a pipe reader", f"cat {OUTPUT_PATH} | tail -1", True),
    ("read thrown away", f"cat {OUTPUT_PATH} > /dev/null; echo done", False),
    ("read after an overwrite", f"echo x > {OUTPUT_PATH}; cat {OUTPUT_PATH}", False),
    ("read after an append", f"echo x >> {OUTPUT_PATH}; cat {OUTPUT_PATH}", True),
    ("read after a removal", f"rm {OUTPUT_PATH}; cat {OUTPUT_PATH}", False),
]


@pytest.mark.parametrize(
    ("text", "command_ids"),
    [case[1:] for case in OWN_RESULT_CASES],
    ids=[case[0] for case in OWN_RESULT_CASES],
)
def test_own_result_shows_the_commands_whose_output_ends_there(
    knowledge: ExpandedToolCallKnowledge, text: str, command_ids: tuple[int, ...] | None
):
    (output_places,) = _expand(knowledge, _call(1, text))

    assert output_places == (
        () if command_ids is None else (OutputPlace(K1, command_ids),)
    )


def test_commands_of_a_file_print_where_their_runner_prints(
    knowledge: ExpandedToolCallKnowledge,
):
    write = _call(1, WriteFileAction("f.sh", "curl a"))

    shown = _expand(knowledge, write, _call(2, "bash f.sh"))
    redirected = _expand(knowledge, write, _call(2, "bash f.sh > log 2>&1"))

    assert shown[1] == (OutputPlace(K2, (0, 1)),)
    assert redirected[1] == ()


def test_a_later_read_of_a_redirected_file_is_no_place_of_the_writer(
    knowledge: ExpandedToolCallKnowledge,
):
    output_places = _expand(
        knowledge, _call(1, "curl u > log 2>&1"), _call(2, "cat log")
    )

    assert output_places == ((), (OutputPlace(K2, (0,)),))


@pytest.mark.parametrize(
    "result",
    [case[1] for case in NO_PLACE_RESULTS],
    ids=[case[0] for case in NO_PLACE_RESULTS],
)
def test_a_result_that_the_trajectory_does_not_hold_shows_nothing(
    knowledge: ExpandedToolCallKnowledge, result: ToolCallResult | None
):
    assert _expand(knowledge, _call(1, "curl u", result)) == ((),)


def test_later_polls_of_a_started_handle_show_its_output(
    knowledge: ExpandedToolCallKnowledge,
):
    output_places = _expand(
        knowledge,
        _call(1, "curl u", RUNNING),
        _poll(2),
        _poll(3, execution_status=ExecutionStatus.NOT_RUN),
        _call(4, PollAction((HANDLE,)), None),
        _poll(5, tool_output_text=None),
        _poll(6),
    )

    assert output_places[0] == (
        OutputPlace(K1, (0,)),
        OutputPlace(K2, (0,)),
        OutputPlace(K6, (0,)),
    )
    assert output_places[1:] == ((), (), (), (), ())


def test_a_poll_shows_every_command_of_the_starter_by_a_rule(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    calls = (_call(1, "curl a; curl b > /dev/null 2>&1; curl c", RUNNING), _poll(2))
    use_counts: Counter[str] = Counter()

    output_places = _expand(knowledge, *calls, judgment_rule_use_counts=use_counts)
    _answer(monkeypatch, EVERY_COMMAND_RULE_NAME, False)
    output_places_on_false = _expand(knowledge, *calls)

    assert output_places[0] == (OutputPlace(K1, (0, 2)), OutputPlace(K2, (0, 2)))
    assert use_counts == Counter({EVERY_COMMAND_RULE_NAME: 1})
    assert output_places_on_false[0] == (OutputPlace(K1, (0, 2)),)


def test_a_poll_of_one_command_asks_no_rule(knowledge: ExpandedToolCallKnowledge):
    use_counts: Counter[str] = Counter()

    _expand(
        knowledge,
        _call(1, "curl a > /dev/null 2>&1; curl b", RUNNING),
        _poll(2),
        judgment_rule_use_counts=use_counts,
    )

    assert use_counts == Counter()


def test_typed_text_shows_in_its_own_poll_and_the_later_polls_of_the_same_starter(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _read_typed_text_by_last_command_of_starter(monkeypatch)
    output_places = _expand(
        knowledge,
        _call(1, "bash", RUNNING),
        _poll(2),
        _poll(3, "curl u\n"),
        _poll(4, "\n"),
        _poll(5),
    )

    assert output_places[0] == tuple(
        OutputPlace(tool_call_key, (0,)) for tool_call_key in (K1, K2, K3, K4, K5)
    )
    assert output_places[2] == tuple(
        OutputPlace(tool_call_key, (0,)) for tool_call_key in (K3, K4, K5)
    )
    assert output_places[1] == output_places[3] == output_places[4] == ()


def test_typed_text_shows_only_in_later_polls_of_a_handle_the_typing_poll_names(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _read_typed_text_by_last_command_of_starter(monkeypatch)
    output_places = _expand(
        knowledge,
        _call(
            1, "bash", _result(ExecutionStatus.RUNNING, handles=(HANDLE, OTHER_HANDLE))
        ),
        _poll(2, "curl u\n"),
        _call(3, PollAction((OTHER_HANDLE,))),
        _call(4, RunToolScriptAction("...", (PollAction((OTHER_HANDLE, HANDLE)),))),
    )

    assert output_places[1] == (OutputPlace(K2, (0,)), OutputPlace(K4, (0,)))


def test_several_typed_commands_ask_the_rule_once_per_later_poll(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _read_typed_text_by_last_command_of_starter(monkeypatch)
    calls = (_call(1, "bash", RUNNING), _poll(2, "curl a; curl b\n"), _poll(3))
    use_counts: Counter[str] = Counter()

    output_places = _expand(knowledge, *calls, judgment_rule_use_counts=use_counts)
    _answer(monkeypatch, EVERY_COMMAND_RULE_NAME, False)
    output_places_on_false = _expand(knowledge, *calls)

    assert output_places[1] == (OutputPlace(K2, (0, 1)), OutputPlace(K3, (0, 1)))
    assert use_counts == Counter({EVERY_COMMAND_RULE_NAME: 1})
    assert output_places_on_false[1] == (OutputPlace(K2, (0, 1)),)


def test_script_steps_show_in_the_script_result_by_a_rule(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    script = RunToolScriptAction(
        "...",
        (
            _command("curl a"),
            RunCommandAction(),
            _command("curl b", first_command_id=1),
        ),
    )
    calls = (
        _call(1, script, _result(ExecutionStatus.RUNNING, handles=(HANDLE,))),
        _poll(2),
    )
    use_counts: Counter[str] = Counter()

    output_places = _expand(knowledge, *calls, judgment_rule_use_counts=use_counts)
    _answer(monkeypatch, SCRIPT_STEP_RULE_NAME, False)
    output_places_on_false = _expand(knowledge, *calls)

    assert output_places[0] == (OutputPlace(K1, (0, 1)), OutputPlace(K2, (0, 1)))
    assert use_counts == Counter({SCRIPT_STEP_RULE_NAME: 2, EVERY_COMMAND_RULE_NAME: 1})
    assert output_places_on_false[0] == (OutputPlace(K2, (0, 1)),)


def test_text_typed_by_a_script_step_asks_the_script_rule(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _read_typed_text_by_last_command_of_starter(monkeypatch)
    script = RunToolScriptAction("...", (PollAction((HANDLE,), "curl u\n"),))
    calls = (_call(1, "bash", RUNNING), _call(2, script), _poll(3))
    use_counts: Counter[str] = Counter()

    output_places = _expand(knowledge, *calls, judgment_rule_use_counts=use_counts)
    _answer(monkeypatch, SCRIPT_STEP_RULE_NAME, False)
    output_places_on_false = _expand(knowledge, *calls)

    assert output_places[1] == (OutputPlace(K2, (0,)), OutputPlace(K3, (0,)))
    assert use_counts == Counter({SCRIPT_STEP_RULE_NAME: 1})
    assert output_places_on_false[1] == (OutputPlace(K3, (0,)),)


def test_commands_of_a_file_that_a_script_step_runs_ask_the_script_rule_once(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    calls = (
        _call(1, WriteFileAction("f.sh", "curl a")),
        _call(2, RunToolScriptAction("...", (_command("bash f.sh"),))),
    )
    use_counts: Counter[str] = Counter()

    output_places = _expand(knowledge, *calls, judgment_rule_use_counts=use_counts)
    _answer(monkeypatch, SCRIPT_STEP_RULE_NAME, False)
    output_places_on_false = _expand(knowledge, *calls)

    assert output_places[1] == (OutputPlace(K2, (0, 1)),)
    assert use_counts == Counter({SCRIPT_STEP_RULE_NAME: 1})
    assert output_places_on_false[1] == ()


def test_commands_of_a_file_belong_to_the_script_step_that_runs_it(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    script = RunToolScriptAction(
        "...", (_command("bash f.sh"), _command("curl b", first_command_id=1))
    )
    monkeypatch.setattr(
        _expand_output_places,
        SCRIPT_STEP_RULE_NAME,
        lambda step_index, *, use_counts: step_index == 1,
    )

    output_places = _expand(
        knowledge, _call(1, WriteFileAction("f.sh", "curl a")), _call(2, script)
    )

    assert output_places[1] == (OutputPlace(K2, (1,)),)


def test_text_typed_into_another_handle_is_no_output_of_what_the_typing_call_started(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    _read_typed_text_by_last_command_of_starter(monkeypatch)
    started_handle = ExecutionHandle(ExecutionHandleKind.COMMAND, "h2")
    script = RunToolScriptAction(
        "...",
        (PollAction((HANDLE,), "curl a\n"), _command("curl b")),
    )
    output_places = _expand(
        knowledge,
        _call(1, "bash", RUNNING),
        _call(2, script, _result(ExecutionStatus.RUNNING, handles=(started_handle,))),
        _call(3, PollAction((started_handle,)), FINISHED),
    )

    # The command of the script step has the id 0 and the typed command the id 1.
    assert output_places[1] == (OutputPlace(K2, (0, 1)), OutputPlace(K3, (0,)))


def test_text_typed_by_a_poll_that_did_not_run_shows_nowhere(
    knowledge: ExpandedToolCallKnowledge,
):
    output_places = _expand(
        knowledge,
        _call(1, "bash", RUNNING),
        _poll(2, "curl u\n", execution_status=ExecutionStatus.NOT_RUN),
        _poll(3),
    )

    assert output_places[1] == ()


def test_reads_of_the_harness_output_file_show_the_whole_result(
    knowledge: ExpandedToolCallKnowledge,
):
    output_places = _expand(
        knowledge,
        _call(1, "curl u", _result(output_path=OUTPUT_PATH)),
        _call(2, ReadFileAction(OUTPUT_PATH)),
        _call(3, SearchFilesAction(("/tmp/tasks", OUTPUT_PATH))),
        _call(4, "cat tasks/b1.output"),
        _call(5, "cat /tmp/tasks/b2.output; wc -c /tmp/tasks/b1.output"),
        _call(6, ReadFileAction(OUTPUT_PATH), _result(tool_output_text=None)),
    )

    assert output_places[0] == tuple(
        OutputPlace(tool_call_key, (0,)) for tool_call_key in (K1, K2, K3, K4)
    )


@pytest.mark.parametrize(
    ("text", "is_place"),
    [case[1:] for case in HARNESS_OUTPUT_FILE_READ_CASES],
    ids=[case[0] for case in HARNESS_OUTPUT_FILE_READ_CASES],
)
def test_a_read_of_the_harness_output_file_is_a_place_while_it_shows_that_result(
    knowledge: ExpandedToolCallKnowledge, text: str, is_place: bool
):
    output_places = _expand(
        knowledge, _call(1, "curl u", _result(output_path=OUTPUT_PATH)), _call(2, text)
    )

    assert output_places[0] == (
        (OutputPlace(K1, (0,)), OutputPlace(K2, (0,)))
        if is_place
        else (OutputPlace(K1, (0,)),)
    )


def test_a_read_of_the_output_file_of_several_calls_shows_none_by_a_rule(
    knowledge: ExpandedToolCallKnowledge, monkeypatch: pytest.MonkeyPatch
):
    calls = (
        _call(1, "curl a", _result(output_path=OUTPUT_PATH)),
        _call(2, "curl b", _result(output_path=OUTPUT_PATH)),
        _call(3, ReadFileAction(OUTPUT_PATH)),
    )
    use_counts: Counter[str] = Counter()

    output_places = _expand(knowledge, *calls, judgment_rule_use_counts=use_counts)
    _answer(monkeypatch, SEVERAL_CALLS_RULE_NAME, False)
    output_places_on_false = _expand(knowledge, *calls)

    assert output_places[:2] == ((OutputPlace(K1, (0,)),), (OutputPlace(K2, (0,)),))
    assert use_counts == Counter({SEVERAL_CALLS_RULE_NAME: 1})
    assert output_places_on_false[:2] == (
        (OutputPlace(K1, (0,)), OutputPlace(K3, (0,))),
        (OutputPlace(K2, (0,)), OutputPlace(K3, (0,))),
    )


def test_a_read_of_the_output_file_that_a_starter_and_its_poll_name_shows_the_starter_without_the_rule(
    knowledge: ExpandedToolCallKnowledge,
):
    use_counts: Counter[str] = Counter()

    output_places = _expand(
        knowledge,
        _call(
            1,
            "curl u",
            _result(
                ExecutionStatus.RUNNING, handles=(HANDLE,), output_path=OUTPUT_PATH
            ),
        ),
        _poll(2, output_path=OUTPUT_PATH),
        _call(3, f"cat {OUTPUT_PATH}"),
        judgment_rule_use_counts=use_counts,
    )

    assert output_places[0] == (
        OutputPlace(K1, (0,)),
        OutputPlace(K2, (0,)),
        OutputPlace(K3, (0,)),
    )
    assert use_counts[SEVERAL_CALLS_RULE_NAME] == 0


def test_a_read_of_the_harness_output_file_of_a_poll_shows_the_starter(
    knowledge: ExpandedToolCallKnowledge,
):
    output_places = _expand(
        knowledge,
        _call(1, "curl u", RUNNING),
        _poll(2, output_path=OUTPUT_PATH),
        _call(3, f"cat {OUTPUT_PATH}"),
    )

    assert output_places[0] == tuple(
        OutputPlace(tool_call_key, (0,)) for tool_call_key in (K1, K2, K3)
    )
    assert output_places[1] == ()


def test_a_read_of_the_harness_output_file_in_another_trajectory_is_no_place(
    knowledge: ExpandedToolCallKnowledge,
):
    output_places = _expand(
        knowledge,
        _call(1, "curl u", _result(output_path=OUTPUT_PATH)),
        _call(2, ReadFileAction(OUTPUT_PATH), is_subagent=True),
    )

    assert output_places[0] == (OutputPlace(K1, (0,)),)


def test_a_call_that_polls_and_reads_the_output_file_is_one_place(
    knowledge: ExpandedToolCallKnowledge,
):
    script = RunToolScriptAction(
        "...", (PollAction((HANDLE,)), ReadFileAction(OUTPUT_PATH))
    )
    output_places = _expand(
        knowledge,
        _call(
            1,
            "curl u",
            _result(
                ExecutionStatus.RUNNING, handles=(HANDLE,), output_path=OUTPUT_PATH
            ),
        ),
        _call(2, script),
    )

    assert output_places[0] == (OutputPlace(K1, (0,)), OutputPlace(K2, (0,)))


def test_places_of_polls_and_of_reads_of_the_output_file_come_in_call_order(
    knowledge: ExpandedToolCallKnowledge,
):
    output_places = _expand(
        knowledge,
        _call(
            1,
            "curl u",
            _result(
                ExecutionStatus.RUNNING, handles=(HANDLE,), output_path=OUTPUT_PATH
            ),
        ),
        _call(2, ReadFileAction(OUTPUT_PATH)),
        _poll(3),
    )

    assert output_places[0] == tuple(
        OutputPlace(tool_call_key, (0,)) for tool_call_key in (K1, K2, K3)
    )
