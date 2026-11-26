"""Tests for _decide_output_line_owners.py, with made-up calls, places and requests of one trial and lines read by the real `NetworkRequestResultKnowledge`."""

from collections import Counter
from dataclasses import dataclass

from tb_internet_use.expanded_tool_call import _expand_ran_texts, expand_tool_calls
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_last_command_of_starter_as_reader_of_typed_text,
)
from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    ExpandedToolCall,
    FileText,
    FileTextWithoutKnownWriter,
    PollInputText,
    ProgramInvocation,
    ProgramOption,
    RanCodeText,
    RanCommand,
    RanShellText,
    RanText,
    StdinText,
    UnknownProgramInvocation,
    UnknownRanText,
    UnknownRanTextReason,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request.model import (
    ContentShownInResult,
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
)
from tb_internet_use.network_request_result._decide_output_line_owners import (
    decide_output_line_owners,
    has_unknown_run_beside,
    stopped_command_ids_from_missing_program_line,
)
from tb_internet_use.network_request_result._decide_output_place_sources import (
    decide_output_place_sources,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    OutputLineMeaning,
    OutputLineOwners,
    OutputLineWithMeaning,
    OutputPlaceSourceCommands,
    OutputPlaceSources,
    UnusedOutputLineReason,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    ExitOutcome,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    RunCommandAction,
    RunCondition,
    RunToolScriptAction,
    ShellCommand,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WebFetchAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

R = UnusedOutputLineReason
K = OutputLineKind
COMMAND = RunCommandAction("x")
URL = NetworkRequestTargetKind.URL
PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
HOST = NetworkRequestTargetKind.HOST


def key_of(step_id: int) -> ToolCallKey:
    return ToolCallKey("trial", "main", step_id, 0)


K1, K2, K3 = key_of(1), key_of(2), key_of(3)


def program(
    program_name: str,
    *subcommand_words: str,
    options: tuple[ProgramOption, ...] = (),
    unread_words: tuple[str, ...] = (),
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name=program_name,
        subcommand_words=subcommand_words,
        options=options,
        arguments=(),
        gets_more_arguments_at_run_time=False,
        unread_words=unread_words,
        exits_with_exit_code_of_next_program=False,
    )


def unknown_program(program_name: str) -> UnknownProgramInvocation:
    return UnknownProgramInvocation(program_name, ())


def command(
    command_id: int,
    words: str,
    *program_invocations: ProgramInvocation | UnknownProgramInvocation,
    runs_if: tuple[RunCondition, ...] = (),
    structure_may_be_wrong: bool = False,
) -> RanCommand:
    return RanCommand(
        shell_command=ShellCommand(
            command_id,
            tuple(words.split()),
            runs_if=runs_if,
            structure_may_be_wrong=structure_may_be_wrong,
        ),
        program_invocations=program_invocations,
        variable_values=(),
        stdout_routes=(),
        stderr_routes=(),
    )


def after_success_of(*deciding_command_ids: int) -> tuple[RunCondition, ...]:
    return (RunCondition(deciding_command_ids, ExitOutcome.SUCCESS),)


def after_failure_of(*deciding_command_ids: int) -> tuple[RunCondition, ...]:
    return (RunCondition(deciding_command_ids, ExitOutcome.FAILURE),)


def call(
    tool_call_key: ToolCallKey,
    *ran_commands: RanCommand,
    unknown_ran_texts: tuple[UnknownRanText, ...] = (),
    action: ToolCallAction = COMMAND,
) -> ExpandedToolCall:
    ran_texts: tuple[RanText, ...] = (
        (RanShellText(CallCommandText(), ran_commands),) if ran_commands else ()
    )
    return ExpandedToolCall(
        tool_call=ToolCall(
            HarnessToolCall(tool_call_key, HarnessTool("h", "t"), "", {}, None),
            action,
            None,
        ),
        ran_texts=ran_texts + unknown_ran_texts,
        command_text_status=None,
        output_places=(),
        written_files=(),
        file_uses_without_known_writer=(),
    )


def tool_call_of(
    tool_call_key: ToolCallKey, action: ToolCallAction, result: ToolCallResult
) -> ToolCall:
    """Make a call for the real `expand_tool_calls`."""
    return ToolCall(
        HarnessToolCall(tool_call_key, HarnessTool("h", "t"), "", {}, None),
        action,
        result,
    )


def shell_text_action(command_text: str) -> RunCommandAction:
    return RunCommandAction(
        command_text,
        parse_shell_text(command_text, judgment_rule_use_counts=Counter()),
    )


def place(
    showing_tool_call_key: ToolCallKey,
    *source_commands: tuple[ToolCallKey, tuple[int, ...]],
    may_show_file_content: bool = False,
    may_show_page_text: bool = False,
    is_web_tool_result: bool = False,
) -> OutputPlaceSources:
    return OutputPlaceSources(
        showing_tool_call_key=showing_tool_call_key,
        source_commands=tuple(
            OutputPlaceSourceCommands(tool_call_key, command_ids)
            for tool_call_key, command_ids in source_commands
        ),
        may_show_file_content=may_show_file_content,
        may_show_page_text=may_show_page_text,
        is_web_tool_result=is_web_tool_result,
    )


def lines(
    showing_tool_call_key: ToolCallKey, text: str, *, is_web_tool_result: bool = False
) -> list[OutputLineWithMeaning]:
    """Read each line of a made-up result with a `NetworkRequestResultKnowledge` of its own, so that the one under test counts nothing for it."""
    knowledge = NetworkRequestResultKnowledge()
    output_lines_with_meaning: list[OutputLineWithMeaning] = []
    for line_index, line in enumerate(text.split("\n")):
        output_line_meaning = knowledge.output_line_meaning(
            line, is_web_tool_result=is_web_tool_result
        )
        assert isinstance(output_line_meaning, OutputLineMeaning), line
        output_lines_with_meaning.append(
            OutputLineWithMeaning(
                showing_tool_call_key, line_index, None, output_line_meaning
            )
        )
    return output_lines_with_meaning


def request(
    tool_call_key: ToolCallKey,
    source: NetworkRequestSource,
    target: str | None = None,
    *,
    target_kind: NetworkRequestTargetKind = URL,
    host_names: tuple[str, ...] = (),
    index_in_tool_call: int = 0,
) -> NetworkRequest:
    """Make a request, uncertain when its program has no row as `NetworkRequest` requires, and confirmed otherwise."""
    is_of_unknown_program = isinstance(source, FromCommand) and isinstance(
        source.program_invocation, UnknownProgramInvocation
    )
    return NetworkRequest(
        tool_call_key=tool_call_key,
        index_in_tool_call=index_in_tool_call,
        source=source,
        target=target,
        target_kind=target_kind,
        host_names=host_names,
        received_content_destination=ContentShownInResult(),
        certainty=NetworkRequestCertainty.UNCERTAIN
        if is_of_unknown_program
        else NetworkRequestCertainty.CONFIRMED,
        uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM
        if is_of_unknown_program
        else None,
    )


def from_command(ran_command: RanCommand, program_index: int = -1) -> FromCommand:
    return FromCommand(
        ran_command.shell_command.id,
        CallCommandText(),
        ran_command.program_invocations[program_index],
    )


def from_code(runner_command_id: int, path: str) -> FromCode:
    """Make the source of a request in a Python file that a command runs, written by call 1."""
    return FromCode(
        runner_command_id,
        FileText(runner_command_id, path, K1),
        CodeLanguage.PYTHON,
        "requests.get",
    )


@dataclass(frozen=True)
class Decided:
    output_line_owners: tuple[OutputLineOwners, ...]
    unused_output_line_counts: Counter[tuple[UnusedOutputLineReason, OutputLineKind]]
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ]


def decide(
    places: list[OutputPlaceSources],
    output_lines_with_meaning: list[OutputLineWithMeaning],
    expanded_tool_calls: list[ExpandedToolCall],
    network_requests: list[NetworkRequest],
) -> Decided:
    unused_output_line_counts: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind]
    ] = Counter()
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ] = Counter()
    output_line_owners = decide_output_line_owners(
        places,
        output_lines_with_meaning,
        expanded_tool_calls,
        network_requests,
        knowledge=NetworkRequestResultKnowledge(),
        unused_output_line_counts=unused_output_line_counts,
        program_counts_of_unowned_output_lines=program_counts_of_unowned_output_lines,
    )
    return Decided(
        output_line_owners,
        unused_output_line_counts,
        program_counts_of_unowned_output_lines,
    )


def owner_targets_of(decided: Decided) -> list[tuple[str | None, ...]]:
    return [
        tuple(
            network_request.target if isinstance(network_request.target, str) else None
            for network_request in output_line_owners.owner_network_requests
        )
        for output_line_owners in decided.output_line_owners
    ]


def test_a_line_that_one_request_can_print_is_owned_by_it_alone():
    # `pip install A` and `Successfully installed A-1.0`.
    pip = command(0, "pip install A", program("pip", "install"))
    decided = decide(
        [place(K1, (K1, (0,)))],
        lines(K1, "Successfully installed A-1.0"),
        [call(K1, pip)],
        [request(K1, from_command(pip), "A", target_kind=PACKAGE_NAME)],
    )

    assert owner_targets_of(decided) == [("A",)]
    assert decided.output_line_owners[0].names_another_target is False
    assert decided.unused_output_line_counts == Counter()


def test_a_line_of_pip_install_with_two_packages_is_owned_by_each_request_that_it_names():
    # `pip install A B`, then a line that names both and a line that names A alone.
    pip = command(0, "pip install A B", program("pip", "install"))
    decided = decide(
        [place(K1, (K1, (0,)))],
        lines(K1, "Successfully installed A-1 B-2\nSuccessfully installed A-1"),
        [call(K1, pip)],
        [
            request(K1, from_command(pip), "A", target_kind=PACKAGE_NAME),
            request(
                K1,
                from_command(pip),
                "B",
                target_kind=PACKAGE_NAME,
                index_in_tool_call=1,
            ),
        ],
    )

    assert owner_targets_of(decided) == [("A", "B"), ("A",)]


def test_a_line_of_two_curl_commands_is_shared_unless_it_names_the_host_of_one():
    # `curl -sS https://a.org/x; curl -sS https://b.org/y`.
    curl_a = command(0, "curl -sS https://a.org/x", program("curl"))
    curl_b = command(1, "curl -sS https://b.org/y", program("curl"))
    decided = decide(
        [place(K1, (K1, (0, 1)))],
        lines(
            K1,
            "Temporary failure in name resolution\n"
            "curl: (6) Could not resolve host: B.org\n"
            "curl: (6) Could not resolve host: c.org",
        ),
        [call(K1, curl_a, curl_b)],
        [
            request(K1, from_command(curl_a), "https://a.org/x", host_names=("a.org",)),
            request(
                K1,
                from_command(curl_b),
                "https://b.org/y",
                host_names=("b.org",),
                index_in_tool_call=1,
            ),
        ],
    )

    assert owner_targets_of(decided) == [
        ("https://a.org/x", "https://b.org/y"),
        ("https://b.org/y",),
        ("https://a.org/x", "https://b.org/y"),
    ]
    assert [
        output_line_owners.names_another_target
        for output_line_owners in decided.output_line_owners
    ] == [False, False, True]


def test_a_line_that_names_another_package_under_a_visible_command_is_its_evidence_and_no_new_request():
    # `pip install A` and `Downloading B-1.0.whl`, and `apt-get install x` and `apt-get install y` with a `Get:` line that names host and package x.
    pip = command(0, "pip install A", program("pip", "install"))
    apt_get_x = command(0, "apt-get install x", program("apt-get", "install"))
    apt_get_y = command(1, "apt-get install y", program("apt-get", "install"))
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0, 1)))],
        lines(K1, "Downloading B-1.0.whl")
        + lines(
            K2,
            "Get:1 http://archive.ubuntu.com/ubuntu jammy/main amd64 x amd64 1.0 [10 kB]",
        ),
        [call(K1, pip), call(K2, apt_get_x, apt_get_y)],
        [
            request(K1, from_command(pip), "A", target_kind=PACKAGE_NAME),
            request(K2, from_command(apt_get_x), "x", target_kind=PACKAGE_NAME),
            request(
                K2,
                from_command(apt_get_y),
                "y",
                target_kind=PACKAGE_NAME,
                index_in_tool_call=1,
            ),
        ],
    )

    assert owner_targets_of(decided) == [("A",), ("x",)]
    assert [
        output_line_owners.names_another_target
        for output_line_owners in decided.output_line_owners
    ] == [True, False]
    assert decided.unused_output_line_counts == Counter()


def test_a_line_that_contradicts_some_requests_is_shared_by_all_unless_a_kept_one_has_its_package_or_host():
    # `pip install -r reqs.txt; pip install A` with a line that names x and a line whose package text `==2.0` cannot be read.
    # `curl -sSL https://a.org/x -o x; pip install y` with `curl: (6) Could not resolve host: cdn.b.net`, which any program can print.
    pip_r = command(0, "pip install -r reqs.txt", program("pip", "install"))
    pip_a = command(1, "pip install A", program("pip", "install"))
    curl = command(0, "curl -sSL https://a.org/x -o x", program("curl"))
    pip_y = command(1, "pip install y", program("pip", "install"))
    decided = decide(
        [place(K1, (K1, (0, 1))), place(K2, (K2, (0, 1)))],
        lines(K1, "Successfully installed x-1.0\nSuccessfully installed ==2.0")
        + lines(K2, "curl: (6) Could not resolve host: cdn.b.net"),
        [call(K1, pip_r, pip_a), call(K2, curl, pip_y)],
        [
            request(K1, from_command(pip_r), None, target_kind=PACKAGE_NAME),
            request(
                K1,
                from_command(pip_a),
                "A",
                target_kind=PACKAGE_NAME,
                index_in_tool_call=1,
            ),
            request(K2, from_command(curl), "https://a.org/x", host_names=("a.org",)),
            request(K2, from_command(pip_y), "y", target_kind=PACKAGE_NAME),
        ],
    )

    assert owner_targets_of(decided) == [
        (None, "A"),
        (None, "A"),
        ("https://a.org/x", "y"),
    ]
    assert [
        output_line_owners.names_another_target
        for output_line_owners in decided.output_line_owners
    ] == [True, False, True]


def test_a_line_is_compared_on_package_names_only_with_a_request_for_a_package():
    # `mytool pypi.org`, a program without a row, under `Downloading B-1.0.whl`, which any program can print, whose target is a host and not a package.
    # `apt-get install http://archive.ubuntu.com/x.deb http://mirror.example.org/x.deb` under a `Get:` line that names both a package and a host.
    mytool = command(0, "mytool pypi.org", program("mytool"))
    apt_get = command(
        0,
        "apt-get install http://archive.ubuntu.com/x.deb http://mirror.example.org/x.deb",
        program("apt-get", "install"),
    )
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0,)))],
        lines(K1, "Downloading B-1.0.whl")
        + lines(
            K2,
            "Get:1 http://archive.ubuntu.com/ubuntu jammy/main amd64 x amd64 1.0 [10 kB]",
        ),
        [call(K1, mytool), call(K2, apt_get)],
        [
            request(
                K1,
                from_command(mytool),
                "pypi.org",
                target_kind=NetworkRequestTargetKind.HOST,
                host_names=("pypi.org",),
            ),
            request(
                K2,
                from_command(apt_get),
                "http://archive.ubuntu.com/x.deb",
                host_names=("archive.ubuntu.com",),
            ),
            request(
                K2,
                from_command(apt_get),
                "http://mirror.example.org/x.deb",
                host_names=("mirror.example.org",),
                index_in_tool_call=1,
            ),
        ],
    )

    assert owner_targets_of(decided) == [
        ("pypi.org",),
        ("http://archive.ubuntu.com/x.deb",),
    ]
    assert [
        output_line_owners.names_another_target
        for output_line_owners in decided.output_line_owners
    ] == [False, False]


def test_a_line_that_only_other_programs_print_has_no_owner_unless_the_run_prints_it_or_its_lines_are_not_known():
    # `Requirement already satisfied: x`, which only pip prints, under `curl u`, `mytool u`, `curl --foo x u` and `npm ERR! code E404` under `npx tsc`.
    curl = command(0, "curl https://a.org/x", program("curl"))
    mytool = command(0, "mytool https://a.org/x", unknown_program("mytool"))
    curl_unread = command(
        0, "curl --foo x https://a.org/x", program("curl", unread_words=("--foo",))
    )
    npx = command(0, "npx tsc", program("npx"), unknown_program("tsc"))
    decided = decide(
        [
            place(K1, (K1, (0,))),
            place(K2, (K2, (0,))),
            place(K3, (K3, (0,))),
            place(key_of(4), (key_of(4), (0,))),
        ],
        lines(K1, "Requirement already satisfied: x")
        + lines(K2, "Requirement already satisfied: x")
        + lines(K3, "Requirement already satisfied: x")
        + lines(key_of(4), "npm ERR! code E404"),
        [call(K1, curl), call(K2, mytool), call(K3, curl_unread), call(key_of(4), npx)],
        [
            request(K1, from_command(curl), "https://a.org/x"),
            request(K2, from_command(mytool), "https://a.org/x"),
            request(K3, from_command(curl_unread), "https://a.org/x"),
            request(key_of(4), from_command(npx, 0), "tsc", target_kind=PACKAGE_NAME),
        ],
    )

    assert owner_targets_of(decided) == [
        (),
        ("https://a.org/x",),
        ("https://a.org/x",),
        ("tsc",),
    ]
    assert decided.unused_output_line_counts == Counter(
        {(R.NO_UNKNOWN_RUN, K.ALREADY_PRESENT): 1}
    )
    assert decided.program_counts_of_unowned_output_lines == Counter(
        {(R.NO_UNKNOWN_RUN, K.ALREADY_PRESENT, "curl"): 1}
    )


def test_a_line_that_any_program_prints_has_no_owner_whose_run_the_knowledge_class_says_prints_no_line():
    # `getent hosts a.org; curl -i https://b.org/y` and `HTTP/1.1 405 Method Not Allowed`. getent(1) shows only entries of the hosts database, so curl alone owns the status line.
    getent = command(0, "getent hosts a.org", program("getent", "hosts"))
    curl = command(
        1,
        "curl -i https://b.org/y",
        program("curl", options=(ProgramOption("-i", None),)),
    )
    decided = decide(
        [place(K1, (K1, (0, 1)))],
        lines(K1, "HTTP/1.1 405 Method Not Allowed"),
        [call(K1, getent, curl)],
        [
            request(K1, from_command(getent), "a.org", target_kind=HOST),
            request(K1, from_command(curl), "https://b.org/y", index_in_tool_call=1),
        ],
    )

    assert owner_targets_of(decided) == [("https://b.org/y",)]


def test_a_bare_number_is_owned_only_by_a_run_that_prints_a_status_code():
    # `curl -w '%{http_code}' u` prints `200`. `curl u` and `./setup.sh` beside it do not, so their `404` is counted as not printed by the run.
    curl_w = command(
        0,
        "curl -w %{http_code} https://a.org/x",
        program("curl", options=(ProgramOption("-w", "%{http_code}"),)),
    )
    curl = command(0, "curl https://a.org/x", program("curl"))
    setup = command(1, "./setup.sh", unknown_program("setup.sh"))
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0, 1)))],
        lines(K1, "200") + lines(K2, "404"),
        [call(K1, curl_w), call(K2, curl, setup)],
        [
            request(K1, from_command(curl_w), "https://a.org/x"),
            request(K2, from_command(curl), "https://a.org/x"),
        ],
    )

    assert owner_targets_of(decided) == [("https://a.org/x",), ()]
    assert decided.unused_output_line_counts == Counter(
        {(R.STATUS_CODE_NOT_PRINTED_BY_RUN, K.BARE_STATUS_CODE): 1}
    )
    assert decided.program_counts_of_unowned_output_lines == Counter()


def test_a_line_of_a_missing_program_is_owned_by_the_request_whose_command_names_that_program():
    # `pip3 install requests` and `bash: pip3: command not found`, `/opt/bin/mytool https://a.org/x` and its missing file, `pip install A && curl -s u` and `bash: pip: command not found`.
    pip3 = command(0, "pip3 install requests", program("pip", "install"))
    mytool = command(0, "/opt/bin/mytool https://a.org/x", unknown_program("mytool"))
    pip = command(0, "pip install A", program("pip", "install"))
    curl = command(
        1, "curl -s https://a.org/x", program("curl"), runs_if=after_success_of(0)
    )
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0,))), place(K3, (K3, (0, 1)))],
        lines(K1, "bash: pip3: command not found")
        + lines(K2, "bash: /opt/bin/mytool: No such file or directory")
        + lines(K3, "bash: pip: command not found"),
        [call(K1, pip3), call(K2, mytool), call(K3, pip, curl)],
        [
            request(K1, from_command(pip3), "requests", target_kind=PACKAGE_NAME),
            request(K2, from_command(mytool), "https://a.org/x"),
            request(K3, from_command(pip), "A", target_kind=PACKAGE_NAME),
            request(K3, from_command(curl), "https://a.org/x", index_in_tool_call=1),
        ],
    )

    assert owner_targets_of(decided) == [("requests",), ("https://a.org/x",), ("A",)]
    assert decided.unused_output_line_counts == Counter()


def test_a_missing_program_named_only_by_a_later_word_is_a_program_word_only_under_its_own_name():
    # `python -m pip install x` and `No module named pip`, where pip is a program of the command. `sudo pip3 install x` with `sudo: pip3: command not found`, whose program is read as pip.
    python_pip = command(
        0, "python -m pip install x", program("python"), program("pip", "install")
    )
    sudo_pip3 = command(
        0, "sudo pip3 install x", program("sudo"), program("pip", "install")
    )
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0,)))],
        lines(K1, "No module named pip") + lines(K2, "sudo: pip3: command not found"),
        [call(K1, python_pip), call(K2, sudo_pip3)],
        [
            request(K1, from_command(python_pip), "x", target_kind=PACKAGE_NAME),
            request(K2, from_command(sudo_pip3), "x", target_kind=PACKAGE_NAME),
        ],
    )

    assert owner_targets_of(decided) == [("x",), ()]
    assert decided.unused_output_line_counts == Counter(
        {(R.NO_UNKNOWN_RUN, K.PROGRAM_MISSING): 1}
    )


def test_a_missing_program_that_stops_a_later_command_with_a_request_is_not_counted():
    # `mytool x && curl https://a.org/x` and `bash: mytool: command not found`, also when the place may show a file, e.g. after `cat notes.md`.
    mytool = command(0, "mytool x", unknown_program("mytool"))
    curl = command(
        1, "curl https://a.org/x", program("curl"), runs_if=after_success_of(0)
    )
    cat = command(0, "cat notes.md", program("cat"))
    rg = command(1, "rg x", program("rg"))
    pip = command(
        2, "pip install y", program("pip", "install"), runs_if=after_success_of(1)
    )
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0, 1)), may_show_file_content=True)],
        lines(K1, "bash: mytool: command not found")
        + lines(K2, "rg: command not found"),
        [call(K1, mytool, curl), call(K2, cat, rg, pip)],
        [
            request(K1, from_command(curl), "https://a.org/x"),
            request(K2, from_command(pip), "y", target_kind=PACKAGE_NAME),
        ],
    )

    assert owner_targets_of(decided) == [(), ()]
    assert decided.unused_output_line_counts == Counter()


def test_a_missing_program_of_a_command_without_a_request_is_counted_apart_from_one_that_no_command_names():
    # `rg foo` with `rg: command not found`, and `./setup.sh` with `pip: command not found`, which no command of the place names.
    rg = command(0, "rg foo", program("rg"))
    setup = command(0, "./setup.sh", unknown_program("setup.sh"))
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0,)))],
        lines(K1, "rg: command not found") + lines(K2, "pip: command not found"),
        [call(K1, rg), call(K2, setup)],
        [],
    )

    assert decided.unused_output_line_counts == Counter(
        {
            (R.MISSING_PROGRAM_OF_COMMAND_WITHOUT_REQUEST, K.PROGRAM_MISSING): 1,
            (R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.PROGRAM_MISSING): 1,
        }
    )
    assert decided.program_counts_of_unowned_output_lines == Counter(
        {(R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.PROGRAM_MISSING, "setup.sh"): 1}
    )


def test_a_line_where_a_run_of_unknown_content_reaches_makes_no_request_and_is_counted_by_that_program():
    # `./setup.sh` prints two `Downloading` lines. `ls; bash setup.sh` prints one, where no call wrote setup.sh.
    setup = command(0, "./setup.sh", unknown_program("setup.sh"))
    ls = command(0, "ls", program("ls"))
    bash = command(1, "bash setup.sh", program("bash"))
    unknown_setup_text = UnknownRanText(
        FileTextWithoutKnownWriter(1, "setup.sh"),
        UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL,
    )
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0, 1)))],
        lines(K1, "Downloading torch-2.3.0.whl\nDownloading numpy-1.26.whl")
        + lines(K2, "Downloading x-1.0.whl"),
        [call(K1, setup), call(K2, ls, bash, unknown_ran_texts=(unknown_setup_text,))],
        [],
    )

    assert owner_targets_of(decided) == [(), (), ()]
    assert decided.unused_output_line_counts == Counter(
        {(R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.DOWNLOAD_STARTED): 3}
    )
    assert decided.program_counts_of_unowned_output_lines == Counter(
        {
            (R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.DOWNLOAD_STARTED, "setup.sh"): 2,
            (R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.DOWNLOAD_STARTED, "bash"): 1,
        }
    )


def test_a_line_that_several_calls_printed_into_is_counted_once_and_once_under_each_program():
    # Call 1 `./a.sh >> log`, call 2 `./b.sh >> log`, call 3 `cat log` with `Downloading x`.
    decided = decide(
        [place(K3, (K1, (0,)), (K2, (0,)))],
        lines(K3, "Downloading x"),
        [
            call(K1, command(0, "./a.sh", unknown_program("a.sh"))),
            call(K2, command(0, "./b.sh", unknown_program("b.sh"))),
            call(K3, command(0, "cat log", program("cat"))),
        ],
        [],
    )

    assert decided.unused_output_line_counts == Counter(
        {(R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.DOWNLOAD_STARTED): 1}
    )
    assert decided.program_counts_of_unowned_output_lines == Counter(
        {
            (R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.DOWNLOAD_STARTED, "a.sh"): 1,
            (R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.DOWNLOAD_STARTED, "b.sh"): 1,
        }
    )


def test_a_line_in_a_place_that_the_request_of_its_call_does_not_reach_has_no_owner():
    # `pip install A > /dev/null 2>&1; ./setup.sh`, whose result shows only what setup.sh printed.
    pip = command(0, "pip install A", program("pip", "install"))
    setup = command(1, "./setup.sh", unknown_program("setup.sh"))
    decided = decide(
        [place(K1, (K1, (1,)))],
        lines(K1, "Downloading torch-2.3.0.whl"),
        [call(K1, pip, setup)],
        [request(K1, from_command(pip), "torch", target_kind=PACKAGE_NAME)],
    )

    assert owner_targets_of(decided) == [()]
    assert decided.unused_output_line_counts == Counter(
        {(R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.DOWNLOAD_STARTED): 1}
    )


def test_a_line_where_only_read_runs_reach_is_counted_by_each_program_name_once():
    # Call 1 `ls -la; ls`, call 2 `conda install x` and call 3 whose place has no source commands, as that of a tool script without command steps, each showing `HTTP/1.1 200 OK`.
    ls_la = command(0, "ls -la", program("ls"))
    ls = command(1, "ls", program("ls"))
    conda = command(0, "conda install x", program("conda", "install"))
    decided = decide(
        [place(K1, (K1, (0, 1))), place(K2, (K2, (0,))), place(K3)],
        lines(K1, "HTTP/1.1 200 OK")
        + lines(K2, "HTTP/1.1 200 OK")
        + lines(K3, "HTTP/1.1 200 OK"),
        [call(K1, ls_la, ls), call(K2, conda), call(K3)],
        [],
    )

    assert decided.unused_output_line_counts == Counter(
        {(R.NO_UNKNOWN_RUN, K.HTTP_STATUS): 3}
    )
    assert decided.program_counts_of_unowned_output_lines == Counter(
        {
            (R.NO_UNKNOWN_RUN, K.HTTP_STATUS, "ls"): 1,
            (R.NO_UNKNOWN_RUN, K.HTTP_STATUS, "conda"): 1,
            (R.NO_UNKNOWN_RUN, K.HTTP_STATUS, ""): 1,
        }
    )


def test_a_line_without_an_owner_is_counted_under_the_last_program_of_each_command():
    # `sudo python get.py` and `sudo ./setup.sh`, each showing `HTTP/1.1 200 OK`.
    sudo_python = command(0, "sudo python get.py", program("sudo"), program("python"))
    sudo_setup = command(
        0, "sudo ./setup.sh", program("sudo"), unknown_program("setup.sh")
    )
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0,)))],
        lines(K1, "HTTP/1.1 200 OK") + lines(K2, "HTTP/1.1 200 OK"),
        [call(K1, sudo_python), call(K2, sudo_setup)],
        [],
    )

    assert decided.program_counts_of_unowned_output_lines == Counter(
        {
            (R.NO_UNKNOWN_RUN, K.HTTP_STATUS, "python"): 1,
            (R.UNOWNED_LINE_IN_UNKNOWN_RUN, K.HTTP_STATUS, "setup.sh"): 1,
        }
    )


def test_a_line_without_an_owner_is_counted_first_as_no_place_then_as_file_content_then_as_page_text():
    # A result that is no output place, `cat README.md`, `cat notes.md; ./setup.sh` and `./setup.sh` in a place marked as showing page text, as a tool script with a web step beside its commands is.
    cat = command(0, "cat README.md", program("cat"))
    cat_and_setup = (
        command(0, "cat notes.md", program("cat")),
        command(1, "./setup.sh", unknown_program("setup.sh")),
    )
    setup = command(0, "./setup.sh", unknown_program("setup.sh"))
    decided = decide(
        [
            place(K1, (K1, (0,)), may_show_file_content=True),
            place(
                K2, (K2, (0, 1)), may_show_file_content=True, may_show_page_text=True
            ),
            place(K3, (K3, (0,)), may_show_page_text=True),
        ],
        lines(K1, "Downloading torch-2.3.0")
        + lines(K2, "Downloading x")
        + lines(K3, "Connection refused")
        + lines(key_of(4), "error: externally-managed-environment"),
        [call(K1, cat), call(K2, *cat_and_setup), call(K3, setup), call(key_of(4))],
        [],
    )

    assert owner_targets_of(decided) == [(), (), (), ()]
    assert decided.unused_output_line_counts == Counter(
        {
            (R.FILE_CONTENT, K.DOWNLOAD_STARTED): 2,
            (R.PAGE_TEXT, K.CONNECTION_FAILED): 1,
            (R.NOT_AN_OUTPUT_PLACE, K.REFUSED_LOCALLY): 1,
        }
    )
    assert decided.program_counts_of_unowned_output_lines == Counter()


def test_a_request_still_owns_its_line_in_a_place_that_may_show_file_content():
    # `cat notes.md; curl -sS https://a.org/x` and `curl: (7) Connection refused`.
    cat = command(0, "cat notes.md", program("cat"))
    curl = command(1, "curl -sS https://a.org/x", program("curl"))
    decided = decide(
        [place(K1, (K1, (0, 1)), may_show_file_content=True)],
        lines(K1, "curl: (7) Connection refused"),
        [call(K1, cat, curl)],
        [request(K1, from_command(curl), "https://a.org/x")],
    )

    assert owner_targets_of(decided) == [("https://a.org/x",)]


def test_code_typed_through_a_poll_owns_lines_of_the_typing_call_and_of_later_places_of_the_starter(
    monkeypatch,
):
    # Call 1 starts `python3`, call 2 types `requests.get(u)` into it, call 3 polls it and call 4 runs `ls`. Each result shows `Connection refused`.
    # The typed text is code only on the other answer of the rule on the reader of typed text, which takes `python3` as its reader.
    monkeypatch.setattr(
        _expand_ran_texts,
        treat_last_command_of_starter_as_reader_of_typed_text.__name__,
        lambda *, use_counts: True,
    )
    handle = ExecutionHandle(ExecutionHandleKind.COMMAND, "s")
    running = ToolCallResult(
        tool_output_text="Connection refused",
        execution_status=ExecutionStatus.RUNNING,
        handles=(handle,),
    )
    expanded_tool_calls = list(
        expand_tool_calls(
            (
                tool_call_of(K1, shell_text_action("python3"), running),
                tool_call_of(
                    K2,
                    PollAction(
                        (handle,),
                        input="import requests; requests.get('https://b.org/y')",
                    ),
                    running,
                ),
                tool_call_of(K3, PollAction((handle,)), running),
                tool_call_of(
                    key_of(4),
                    shell_text_action("ls"),
                    ToolCallResult(
                        tool_output_text="Connection refused",
                        execution_status=ExecutionStatus.FINISHED,
                        exit_code=0,
                    ),
                ),
            ),
            knowledge=ExpandedToolCallKnowledge(),
            judgment_rule_use_counts=Counter(),
        )
    )
    (typed_code,) = expanded_tool_calls[1].ran_texts
    assert isinstance(typed_code, RanCodeText)
    decided = decide(
        list(decide_output_place_sources(expanded_tool_calls)),
        lines(K1, "Connection refused")
        + lines(K2, "Connection refused")
        + lines(K3, "Connection refused")
        + lines(key_of(4), "Connection refused"),
        expanded_tool_calls,
        [
            request(
                K2,
                FromCode(None, typed_code.source, CodeLanguage.PYTHON, "requests.get"),
                "https://b.org/y",
            )
        ],
    )

    assert owner_targets_of(decided) == [
        (),
        ("https://b.org/y",),
        ("https://b.org/y",),
        (),
    ]


def test_a_request_in_code_reaches_a_place_through_the_command_that_ran_the_code_and_prints_what_its_last_program_prints():
    # `python get.py; python put.py > /dev/null`, each with a request in its code, and `Connection refused`. `sudo uv run get.py`, whose last program `uv run` prints lines of uv and none of npm, while sudo has no row.
    get = command(0, "python get.py", program("python"))
    put = command(1, "python put.py", program("python"))
    uv_run = command(0, "sudo uv run get.py", program("sudo"), program("uv", "run"))
    decided = decide(
        [place(K1, (K1, (0,))), place(K2, (K2, (0,)))],
        lines(K1, "Connection refused")
        + lines(K2, "Audited 1 package\nnpm ERR! code E404"),
        [call(K1, get, put), call(K2, uv_run)],
        [
            request(K1, from_code(0, "get.py"), "https://a.org/x"),
            request(
                K1, from_code(1, "put.py"), "https://b.org/y", index_in_tool_call=1
            ),
            request(K2, from_code(0, "get.py"), "https://c.org/z"),
        ],
    )

    assert owner_targets_of(decided) == [
        ("https://a.org/x",),
        ("https://c.org/z",),
        (),
    ]


def test_a_web_tool_request_owns_the_lines_of_its_own_result_only():
    # A web fetch call, `ls` with a request of a web step as a tool script would have it, and a tool script made only of web steps.
    web_fetch_tool = HarnessTool("h", "web_fetch")
    web_fetch = WebFetchAction(("https://a.org/x",))
    ls = command(0, "ls", program("ls"))
    decided = decide(
        [
            place(K1, is_web_tool_result=True),
            place(K2, (K2, (0,))),
            place(K3, is_web_tool_result=True),
        ],
        lines(K1, "Please verify you are not a robot", is_web_tool_result=True)
        + lines(K2, "Connection refused")
        + lines(K3, "Please verify you are not a robot", is_web_tool_result=True),
        [
            call(K1, action=web_fetch),
            call(K2, ls),
            call(K3, action=RunToolScriptAction(steps=(web_fetch,))),
        ],
        [
            request(K1, FromWebTool(None, web_fetch_tool), "https://a.org/x"),
            request(K2, FromWebTool(0, web_fetch_tool), "https://b.org/y"),
            request(K3, FromWebTool(0, web_fetch_tool), "https://c.org/z"),
        ],
    )

    assert owner_targets_of(decided) == [("https://a.org/x",), (), ()]
    assert decided.unused_output_line_counts == Counter(
        {
            (R.NO_UNKNOWN_RUN, K.CONNECTION_FAILED): 1,
            (R.NO_UNKNOWN_RUN, K.SERVER_ANSWERED): 1,
        }
    )


def test_the_knowledge_class_is_asked_only_about_runs_whose_rows_answer_whether_they_print_a_line():
    # `pip install A` under a line that only pip prints, `curl u` under a line that any program prints, which still needs the question whether curl prints no line at all, and `curl --foo x u`, whose unread words no row can answer for.
    pip = command(0, "pip install A", program("pip", "install"))
    curl = command(0, "curl https://a.org/x", program("curl"))
    curl_unread = command(
        0, "curl --foo x https://a.org/x", program("curl", unread_words=("--foo",))
    )
    knowledge = NetworkRequestResultKnowledge()
    decide_output_line_owners(
        [place(K1, (K1, (0,))), place(K2, (K2, (0,))), place(K3, (K3, (0,)))],
        lines(K1, "Successfully installed A-1.0")
        + lines(K2, "Connection refused")
        + lines(K3, "Successfully installed A-1.0"),
        [call(K1, pip), call(K2, curl), call(K3, curl_unread)],
        [
            request(K1, from_command(pip), "A", target_kind=PACKAGE_NAME),
            request(K2, from_command(curl), "https://a.org/x"),
            request(K3, from_command(curl_unread), "https://a.org/x"),
        ],
        knowledge=knowledge,
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )

    assert sum(knowledge.uses.row_use_counts.values()) == 2
    assert not knowledge.uses.unknown_input_counts


def test_stopped_command_ids_follow_the_run_conditions_that_require_success_of_a_missing_program():
    # `/opt/bin/rg x && b && c; rg y || e`, with `rg` missing, `rg z && g` whose `rg z` may have a wrong structure, and `h` after `/opt/bin/rg x` whose own structure may be wrong.
    ran_commands = (
        command(0, "/opt/bin/rg x", program("rg")),
        command(1, "b", program("b"), runs_if=after_success_of(0)),
        command(2, "c", program("c"), runs_if=after_success_of(0, 1)),
        command(3, "rg y", program("rg")),
        command(
            4,
            "e",
            program("e"),
            runs_if=(RunCondition((3,), ExitOutcome.FAILURE),),
        ),
        command(5, "rg z", program("rg"), structure_may_be_wrong=True),
        command(6, "g", program("g"), runs_if=after_success_of(5)),
        command(
            7,
            "h",
            program("h"),
            runs_if=after_success_of(0),
            structure_may_be_wrong=True,
        ),
    )

    assert stopped_command_ids_from_missing_program_line("rg", ran_commands) == (1, 2)
    assert stopped_command_ids_from_missing_program_line("b", ran_commands) == (2,)
    assert stopped_command_ids_from_missing_program_line("x", ran_commands) == ()


# (text, commands as (id, text, run conditions), missing program, ids of the stopped commands)
STOPPED_AFTER_OR_LIST_CASES = [
    # grep runs after rg failed, and pip then runs if grep succeeds.
    (
        "rg x || grep x f && pip install y",
        [
            (0, "rg", ()),
            (1, "grep", after_failure_of(0)),
            (2, "pip", after_success_of(0, 1)),
        ],
        "rg",
        (),
    ),
    # grep failed, so it ran, rg failed before it and the list failed.
    (
        "rg x || grep x f && pip install y",
        [
            (0, "rg", ()),
            (1, "grep", after_failure_of(0)),
            (2, "pip", after_success_of(0, 1)),
        ],
        "grep",
        (2,),
    ),
    # b never runs after rg failed, and d runs after c, which runs after the left list failed.
    (
        "rg x && b || c && d",
        [
            (0, "rg", ()),
            (1, "b", after_success_of(0)),
            (2, "c", after_failure_of(0, 1)),
            (3, "d", after_success_of(0, 1, 2)),
        ],
        "rg",
        (1,),
    ),
]


def test_missing_program_left_of_or_stops_no_command_after_the_list():
    for (
        text,
        commands,
        missing_program_word,
        stopped_command_ids,
    ) in STOPPED_AFTER_OR_LIST_CASES:
        ran_commands = tuple(
            command(command_id, program_name, program(program_name), runs_if=runs_if)
            for command_id, program_name, runs_if in commands
        )
        assert (
            stopped_command_ids_from_missing_program_line(
                missing_program_word, ran_commands
            )
            == stopped_command_ids
        ), text


def test_unknown_run_beside_a_request_is_another_source_command_or_another_program_of_its_own_command():
    curl = command(0, "curl -s https://a.org/x", program("curl"))
    test_sh = command(1, "./test.sh", unknown_program("test.sh"))
    ls = command(1, "ls", program("ls"))
    npx = command(0, "npx tsc", program("npx"), unknown_program("tsc"))
    mytool = command(0, "mytool https://a.org/x", unknown_program("mytool"))
    bash_fetch = command(0, "bash fetch.sh https://a.org/x", program("bash"))
    bash = command(1, "bash", program("bash"))
    setup = command(0, "./setup.sh", unknown_program("setup.sh"))
    python3 = command(1, "python3", program("python"))
    typed_code = FromCode(
        None, PollInputText(None, K1), CodeLanguage.PYTHON, "requests.get"
    )

    cases = [
        # `curl -s u; ./test.sh`.
        (
            [call(K1, curl, test_sh)],
            place(K1, (K1, (0, 1))),
            K1,
            from_command(curl),
            True,
        ),
        # `curl -s u; ls`.
        ([call(K1, curl, ls)], place(K1, (K1, (0, 1))), K1, from_command(curl), False),
        # `curl -s u; ./test.sh > /dev/null`.
        (
            [call(K1, curl, test_sh)],
            place(K1, (K1, (0,))),
            K1,
            from_command(curl),
            False,
        ),
        # `npx tsc`, whose request is that of npx.
        ([call(K1, npx)], place(K1, (K1, (0,))), K1, from_command(npx, 0), True),
        # `mytool u`, whose own program is the request's.
        ([call(K1, mytool)], place(K1, (K1, (0,))), K1, from_command(mytool), False),
        # `bash fetch.sh u`, where no call wrote fetch.sh.
        (
            [
                call(
                    K1,
                    bash_fetch,
                    unknown_ran_texts=(
                        UnknownRanText(
                            FileTextWithoutKnownWriter(0, "fetch.sh"),
                            UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL,
                        ),
                    ),
                )
            ],
            place(K1, (K1, (0,))),
            K1,
            from_command(bash_fetch),
            True,
        ),
        # `curl -s u; cat x | bash`, whose piped text is not known.
        (
            [
                call(
                    K1,
                    curl,
                    bash,
                    unknown_ran_texts=(
                        UnknownRanText(
                            StdinText(1), UnknownRanTextReason.READ_FROM_PIPE
                        ),
                    ),
                )
            ],
            place(K1, (K1, (0, 1))),
            K1,
            from_command(curl),
            True,
        ),
        # `curl -s u; bash -c "$CMD"`.
        (
            [
                call(
                    K1,
                    curl,
                    bash,
                    unknown_ran_texts=(
                        UnknownRanText(
                            ArgumentText(1), UnknownRanTextReason.BUILT_AT_RUN_TIME
                        ),
                    ),
                )
            ],
            place(K1, (K1, (0, 1))),
            K1,
            from_command(curl),
            True,
        ),
        # `curl -s u; bash f.sh` after `sed -i` changed f.sh.
        (
            [
                call(
                    K1,
                    curl,
                    bash,
                    unknown_ran_texts=(
                        UnknownRanText(
                            FileText(1, "f.sh", K1),
                            UnknownRanTextReason.CHANGED_BY_UNREAD_COMMAND,
                        ),
                    ),
                )
            ],
            place(K1, (K1, (0, 1))),
            K1,
            from_command(curl),
            True,
        ),
        # Call 1 `./setup.sh >> log` and call 2 `curl -s u >> log; cat log`, whose commands have the same id 0.
        (
            [call(K1, setup), call(K2, curl)],
            place(K2, (K1, (0,)), (K2, (0,))),
            K2,
            from_command(curl),
            True,
        ),
        # Call 1 starts `python3` and call 2 types code into it.
        (
            [call(K1, ls, python3), call(K2)],
            place(K2, (K1, (1,))),
            K2,
            typed_code,
            False,
        ),
        # Call 1 starts `./setup.sh; python3` and call 2 types code into python3.
        (
            [call(K1, setup, python3), call(K2)],
            place(K2, (K1, (0, 1))),
            K2,
            typed_code,
            True,
        ),
    ]
    for (
        expanded_tool_calls,
        output_place_sources,
        tool_call_key,
        source,
        expected,
    ) in cases:
        assert (
            has_unknown_run_beside(
                request(tool_call_key, source, "https://a.org/x"),
                output_place_sources,
                {
                    expanded_tool_call.tool_call.harness_tool_call.key: expanded_tool_call
                    for expanded_tool_call in expanded_tool_calls
                },
            )
            is expected
        ), [expanded_tool_call.ran_texts for expanded_tool_call in expanded_tool_calls]
