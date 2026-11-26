"""Tests for network_request/_extract_command_network_requests.py, with commands and calls made by hand and the real `NetworkRequestKnowledge`."""

import dataclasses
from collections import Counter
from dataclasses import dataclass, replace

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    ExpandedToolCall,
    FileText,
    FileTextWithoutKnownWriter,
    FileWriteChannel,
    OutputRoute,
    OutputVisibility,
    ProgramInvocation,
    ProgramOption,
    RanCodeText,
    RanCommand,
    RanShellText,
    RanText,
    RanTextSource,
    StdinText,
    UnknownProgramInvocation,
    UnknownRanText,
    UnknownRanTextReason,
    VariableValues,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.knowledge.network_request_knowledge import (
    PROGRAM_NETWORK_REQUESTS_CSV,
    NetworkRequestKnowledge,
)
from tb_internet_use.network_request._extract_command_network_requests import (
    extract_command_network_requests,
    urls_that_may_be_public,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
    treat_single_label_or_templated_host_name_as_possibly_public,
    treat_values_outside_their_for_loop_as_unknown_target,
)
from tb_internet_use.network_request.model import (
    ContentSaved,
    ContentShownInResult,
    FromCommand,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoNetworkRequestReason,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
    UnknownReceivedContentDestination,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    ResultDestination,
    RunCommandAction,
    ShellCommand,
    ShellCommandVariableAssignment,
    ToolCall,
    ToolCallKey,
    ToolCallResult,
)

U = "https://a.org/x"
KEY = ToolCallKey("trial", "main", 2, 0)
WRITER_KEY = ToolCallKey("trial", "main", 1, 0)
CALL_COMMAND_TEXT = CallCommandText()
TO_RESULT = OutputRoute((), ResultDestination(), OutputVisibility.WHOLE)
CONFIRMED = NetworkRequestCertainty.CONFIRMED
UNCERTAIN = NetworkRequestCertainty.UNCERTAIN
UNKNOWN_PROGRAM = NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM
FETCHES_ONLY_WHAT_IS_MISSING = (
    NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING
)
UNKNOWN_OPTION_EFFECT = NetworkRequestUncertaintyReason.UNKNOWN_OPTION_EFFECT
PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
URL = NetworkRequestTargetKind.URL
NAMED_IN_FILE = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.NAMED_IN_FILE
)
VALUE_SET_AT_RUN_TIME = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME
)
UNREAD_WORDS = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.UNREAD_WORDS
)
SINGLE_LABEL_RULE_NAME = (
    treat_single_label_or_templated_host_name_as_possibly_public.__name__
)
DOTTED_NAME_RULE_NAME = treat_dotted_host_name_as_public.__name__


def _program(
    program_name: str,
    *subcommand_words: str,
    options: tuple[tuple[str, str | None], ...] = (),
    arguments: tuple[str, ...] = (),
    gets_more_arguments_at_run_time: bool = False,
    unread_words: tuple[str, ...] = (),
    runs_next_program: bool = False,
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name,
        subcommand_words,
        tuple(ProgramOption(name, value) for name, value in options),
        arguments,
        gets_more_arguments_at_run_time,
        unread_words,
        exits_with_exit_code_of_next_program=runs_next_program,
    )


def _command(
    *program_invocations: ProgramInvocation | UnknownProgramInvocation,
    command_id: int = 0,
    variable_values: tuple[VariableValues, ...] = (),
) -> RanCommand:
    return RanCommand(
        ShellCommand(command_id, (program_invocations[0].program_name,)),
        program_invocations,
        variable_values,
        (TO_RESULT,),
        (),
    )


def _expanded_tool_call(
    *,
    ran_texts: tuple[RanText, ...] = (),
    written_files: tuple[WrittenFile, ...] = (),
    execution_status: ExecutionStatus = ExecutionStatus.FINISHED,
) -> ExpandedToolCall:
    tool_call = ToolCall(
        HarnessToolCall(KEY, HarnessTool("h", "t"), "", {}, None),
        RunCommandAction(),
        ToolCallResult(execution_status=execution_status),
    )
    return ExpandedToolCall(tool_call, ran_texts, None, (), written_files, ())


@dataclass(frozen=True, slots=True)
class _Extraction:
    """Output of one call of `extract_command_network_requests` with the counts it added and the `NetworkRequestKnowledge` it asked."""

    network_requests: tuple[NetworkRequest, ...]
    judgment_rule_use_counts: Counter[str]
    no_network_request_counts: Counter[NoNetworkRequestReason]
    knowledge: NetworkRequestKnowledge


def _extract(
    ran_command: RanCommand,
    expanded_tool_call: ExpandedToolCall | None = None,
    *,
    ran_text_source: RanTextSource = CALL_COMMAND_TEXT,
    first_index_in_tool_call: int = 0,
) -> _Extraction:
    knowledge = NetworkRequestKnowledge()
    judgment_rule_use_counts: Counter[str] = Counter()
    no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()
    network_requests = extract_command_network_requests(
        ran_command,
        ran_text_source,
        expanded_tool_call or _expanded_tool_call(),
        first_index_in_tool_call,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )
    return _Extraction(
        network_requests, judgment_rule_use_counts, no_network_request_counts, knowledge
    )


def _requests(
    *program_invocations: ProgramInvocation | UnknownProgramInvocation,
    variable_values: tuple[VariableValues, ...] = (),
) -> tuple[NetworkRequest, ...]:
    return _extract(
        _command(*program_invocations, variable_values=variable_values)
    ).network_requests


def _targets(network_requests: tuple[NetworkRequest, ...]) -> list[object]:
    return [network_request.target for network_request in network_requests]


def _certainties(
    network_requests: tuple[NetworkRequest, ...],
) -> list[tuple[NetworkRequestCertainty, NetworkRequestUncertaintyReason | None]]:
    return [
        (network_request.certainty, network_request.uncertainty_reason)
        for network_request in network_requests
    ]


# What a program is known to do, with a public URL in its words and without one.


def test_a_program_known_to_fetch_gives_a_confirmed_request_for_a_visible_public_url():
    curl = _program("curl", arguments=(U,))
    assert _requests(curl) == (
        NetworkRequest(
            KEY,
            0,
            FromCommand(0, CallCommandText(), curl),
            U,
            URL,
            ("a.org",),
            ContentShownInResult(),
            CONFIRMED,
            None,
        ),
    )


def test_a_program_known_to_fetch_gives_a_confirmed_request_without_a_visible_url():
    apt_get = _program("apt-get", "update")
    assert _requests(apt_get) == (
        NetworkRequest(
            KEY,
            0,
            FromCommand(0, CallCommandText(), apt_get),
            None,
            PACKAGE_NAME,
            (),
            ContentSaved(None),
            CONFIRMED,
            None,
        ),
    )


def test_an_unknown_program_gives_an_uncertain_request_for_a_visible_public_url():
    mytool = UnknownProgramInvocation("mytool", (U,))
    assert _requests(mytool) == (
        NetworkRequest(
            KEY,
            0,
            FromCommand(0, CallCommandText(), mytool),
            U,
            URL,
            ("a.org",),
            UnknownReceivedContentDestination(),
            UNCERTAIN,
            UNKNOWN_PROGRAM,
        ),
    )


@pytest.mark.parametrize(
    ("ran_command", "no_network_request_reason"),
    [
        pytest.param(
            _command(UnknownProgramInvocation("mytool", ("sync",))),
            NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC,
            id="mytool sync",
        ),
        pytest.param(
            _command(UnknownProgramInvocation("mytool", ("http://localhost:8000/x",))),
            NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC,
            id="an unknown program with a URL to localhost",
        ),
        pytest.param(
            _command(UnknownProgramInvocation("mytool", ("https://example.com/x",))),
            NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC,
            id="an unknown program with a URL to a reserved host",
        ),
        pytest.param(
            _command(_program("echo", arguments=("https://a.org",))),
            NoNetworkRequestReason.NON_FETCHING_PROGRAM,
            id="echo https://a.org",
        ),
        pytest.param(
            _command(_program("cat", arguments=("a.txt",))),
            NoNetworkRequestReason.NON_FETCHING_PROGRAM,
            id="cat a.txt",
        ),
        pytest.param(
            _command(_program("pip", "install", options=(("--no-index", None),))),
            NoNetworkRequestReason.OPTION_SENDS_NO_REQUEST,
            id="pip install --no-index x",
        ),
        pytest.param(
            _command(_program("curl", options=(("--version", None),))),
            NoNetworkRequestReason.OPTION_SENDS_NO_REQUEST,
            id="curl --version",
        ),
        pytest.param(
            _command(_program("curl")),
            NoNetworkRequestReason.NO_TARGET_ARGUMENTS,
            id="curl without arguments",
        ),
    ],
)
def test_commands_without_a_request_count_their_reason(
    ran_command: RanCommand, no_network_request_reason: NoNetworkRequestReason
):
    extraction = _extract(ran_command)
    assert extraction.network_requests == ()
    assert extraction.no_network_request_counts == Counter(
        {no_network_request_reason: 1}
    )


@pytest.mark.parametrize(
    ("program_invocations", "targets", "certainties"),
    [
        pytest.param(
            (
                _program("npx", runs_next_program=True),
                UnknownProgramInvocation("tsc", ("--noEmit",)),
            ),
            ["tsc"],
            [(UNCERTAIN, FETCHES_ONLY_WHAT_IS_MISSING)],
            id="npx tsc --noEmit",
        ),
        pytest.param(
            (_program("lake", "build"),),
            [NAMED_IN_FILE],
            [(UNCERTAIN, FETCHES_ONLY_WHAT_IS_MISSING)],
            id="lake build",
        ),
        pytest.param(
            (
                _program(
                    "npm",
                    "install",
                    options=(("--prefer-offline", None),),
                    arguments=("x",),
                ),
            ),
            ["x"],
            [(UNCERTAIN, FETCHES_ONLY_WHAT_IS_MISSING)],
            id="npm install --prefer-offline x",
        ),
        pytest.param(
            (_program("curl", options=(("--tlsv1.2", None),), arguments=(U,)),),
            [U],
            [(UNCERTAIN, UNKNOWN_OPTION_EFFECT)],
            id="curl --tlsv1.2 u without a row of --tlsv1.2",
        ),
        pytest.param(
            (_program("sbt", options=(("--version", None),)),),
            [NAMED_IN_FILE],
            [(UNCERTAIN, UNKNOWN_OPTION_EFFECT)],
            id="sbt --version, before an unknown option effect over fetching only what is missing",
        ),
        pytest.param(
            (_program("pip", "install", arguments=("A", "B", "C")),),
            ["A", "B", "C"],
            [(CONFIRMED, None)] * 3,
            id="pip install A B C",
        ),
        pytest.param(
            (_program("pip", "install", options=(("-r", "reqs.txt"),)),),
            [NAMED_IN_FILE],
            [(CONFIRMED, None)],
            id="pip install -r reqs.txt",
        ),
        pytest.param(
            (
                _program(
                    "pip",
                    "install",
                    options=(("-r", "a.txt"),),
                    arguments=("./x.whl", "./y.whl", "z"),
                ),
            ),
            [
                "z",
                NAMED_IN_FILE,
                UnknownNetworkRequestTarget(
                    UnknownNetworkRequestTargetReason.LOCAL_PATH
                ),
            ],
            [(CONFIRMED, None)] * 3,
            id="pip install -r a.txt ./x.whl ./y.whl z",
        ),
        pytest.param(
            (_program("curl", gets_more_arguments_at_run_time=True),),
            [VALUE_SET_AT_RUN_TIME],
            [(CONFIRMED, None)],
            id="cat urls.txt | xargs curl",
        ),
        pytest.param(
            (_program("curl", arguments=(U, U)),),
            [U, U],
            [(CONFIRMED, None)] * 2,
            id="curl u u",
        ),
        pytest.param(
            (
                _program("sudo", runs_next_program=True),
                _program("curl", arguments=(U,)),
            ),
            [U],
            [(CONFIRMED, None)],
            id="sudo curl u",
        ),
        pytest.param(
            (
                _program("timeout", arguments=("5",), runs_next_program=True),
                _program("curl", arguments=(U,)),
            ),
            [U],
            [(CONFIRMED, None)],
            id="timeout 5 curl u",
        ),
        pytest.param(
            (
                _program("xargs", runs_next_program=True),
                UnknownProgramInvocation("mytool", (U,)),
            ),
            [U],
            [(UNCERTAIN, UNKNOWN_PROGRAM)],
            id="xargs mytool u",
        ),
    ],
)
def test_targets_and_certainty_of_command_requests(
    program_invocations: tuple[ProgramInvocation | UnknownProgramInvocation, ...],
    targets: list[object],
    certainties: list[
        tuple[NetworkRequestCertainty, NetworkRequestUncertaintyReason | None]
    ],
):
    network_requests = _requests(*program_invocations)
    assert _targets(network_requests) == targets
    assert _certainties(network_requests) == certainties
    assert [r.index_in_tool_call for r in network_requests] == list(range(len(targets)))


@pytest.mark.parametrize(
    "options",
    [
        pytest.param((), id="curl u"),
        # The words may be wrong, which comes before an option without a row.
        pytest.param((("--tlsv1.2", None),), id="curl --tlsv1.2 u"),
    ],
)
def test_a_command_whose_structure_may_be_wrong_gives_uncertain_requests(
    options: tuple[tuple[str, str | None], ...],
):
    curl = _program("curl", options=options, arguments=(U,))
    command = _command(curl)
    misread_command = dataclasses.replace(
        command,
        shell_command=dataclasses.replace(
            command.shell_command, structure_may_be_wrong=True
        ),
    )

    (network_request,) = _extract(misread_command).network_requests

    assert (network_request.certainty, network_request.uncertainty_reason) == (
        NetworkRequestCertainty.UNCERTAIN,
        NetworkRequestUncertaintyReason.STRUCTURE_MAY_BE_WRONG,
    )


def test_the_request_of_a_program_run_by_another_belongs_to_the_inner_program():
    sudo = _program("sudo", runs_next_program=True)
    curl = _program("curl", arguments=(U,))
    extraction = _extract(_command(sudo, curl))
    (network_request,) = extraction.network_requests
    assert network_request.source == FromCommand(0, CallCommandText(), curl)
    assert extraction.no_network_request_counts == Counter(
        {NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE: 1}
    )


def test_npx_and_the_program_it_runs_each_give_a_request():
    npx = _program("npx", options=(("-y", None),), runs_next_program=True)
    playwright = _program("playwright", "install", arguments=("chromium",))
    # `-y` of npx has no row of the request catalog, so the request of npx is uncertain for that reason first.
    network_requests = _requests(npx, playwright)
    assert [
        (
            network_request.source,
            network_request.index_in_tool_call,
            network_request.target,
            network_request.certainty,
        )
        for network_request in network_requests
    ] == [
        (FromCommand(0, CallCommandText(), npx), 0, "playwright", UNCERTAIN),
        # The browser name chromium is no target of playwright install.
        (FromCommand(0, CallCommandText(), playwright), 1, None, CONFIRMED),
    ]


def test_requests_are_numbered_from_the_first_index_in_the_call():
    extraction = _extract(
        _command(_program("pip", "install", arguments=("A", "B"))),
        first_index_in_tool_call=4,
    )
    assert [r.index_in_tool_call for r in extraction.network_requests] == [4, 5]


def test_a_command_in_a_file_that_an_earlier_call_wrote_is_the_source_of_its_request():
    fetch_sh = FileText(0, "fetch.sh", WRITER_KEY)
    curl = _program("curl", arguments=(U,))
    extraction = _extract(_command(curl, command_id=1), ran_text_source=fetch_sh)
    (network_request,) = extraction.network_requests
    assert network_request.source == FromCommand(1, fetch_sh, curl)


# A program without a row of the request catalog, depending on what it runs.


@pytest.mark.parametrize(
    ("runner", "ran_text_source"),
    [
        pytest.param(
            _program("bash", arguments=("fetch.sh", U)),
            FileText(5, "fetch.sh", WRITER_KEY),
            id="bash fetch.sh u",
        ),
        pytest.param(
            UnknownProgramInvocation("fetch.sh", (U,)),
            FileText(5, "./fetch.sh", WRITER_KEY),
            id="./fetch.sh u",
        ),
        pytest.param(
            _program("bash", arguments=(U,)),
            StdinText(5),
            id="curl u | bash, with a URL in the words of bash",
        ),
    ],
)
def test_a_runner_of_a_text_that_the_trial_holds_gives_no_request(
    runner: ProgramInvocation | UnknownProgramInvocation,
    ran_text_source: FileText | StdinText,
):
    ran_shell_text = RanShellText(ran_text_source, ())
    extraction = _extract(
        _command(runner, command_id=5),
        _expanded_tool_call(ran_texts=(ran_shell_text,)),
    )
    assert extraction.network_requests == ()
    assert extraction.no_network_request_counts == Counter(
        {NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE: 1}
    )


def test_a_runner_of_code_that_the_trial_holds_gives_no_request():
    python = _program("python", options=(("-c", "import requests"),), arguments=(U,))
    ran_code_text = RanCodeText(ArgumentText(0), CodeLanguage.PYTHON, "import x")
    extraction = _extract(
        _command(python), _expanded_tool_call(ran_texts=(ran_code_text,))
    )
    assert extraction.network_requests == ()


def test_uv_run_python_get_py_gives_the_request_of_uv_run_only():
    uv_run = _program("uv", "run", runs_next_program=True)
    python = _program("python", arguments=("get.py",))
    ran_code_text = RanCodeText(
        FileText(0, "get.py", WRITER_KEY), CodeLanguage.PYTHON, "requests.get(u)"
    )
    network_requests = _extract(
        _command(uv_run, python), _expanded_tool_call(ran_texts=(ran_code_text,))
    ).network_requests
    assert [(r.source, r.target) for r in network_requests] == [
        (FromCommand(0, CallCommandText(), uv_run), NAMED_IN_FILE)
    ]


def test_a_runner_of_a_text_that_the_trial_does_not_hold_is_read_like_an_unknown_program():
    bash = _program("bash", arguments=("setup.sh", U))
    unknown_ran_text = UnknownRanText(
        FileTextWithoutKnownWriter(0, "setup.sh"),
        UnknownRanTextReason.NOT_WRITTEN_IN_TRIAL,
    )
    (network_request,) = _extract(
        _command(bash), _expanded_tool_call(ran_texts=(unknown_ran_text,))
    ).network_requests
    assert (
        network_request.source,
        network_request.target,
        network_request.certainty,
        network_request.uncertainty_reason,
    ) == (FromCommand(0, CallCommandText(), bash), U, UNCERTAIN, UNKNOWN_PROGRAM)


def test_a_text_that_another_command_runs_does_not_stop_the_request():
    bash = _program("bash", arguments=("setup.sh", U))
    ran_shell_text = RanShellText(FileText(7, "other.sh", WRITER_KEY), ())
    network_requests = _extract(
        _command(bash), _expanded_tool_call(ran_texts=(ran_shell_text,))
    ).network_requests
    assert _targets(network_requests) == [U]


def test_the_requests_of_an_unknown_program_carry_its_command_and_their_index():
    mytool = UnknownProgramInvocation("mytool", (U, "https://b.org/y"))
    extraction = _extract(_command(mytool, command_id=5), first_index_in_tool_call=3)
    assert [
        (network_request.source, network_request.index_in_tool_call)
        for network_request in extraction.network_requests
    ] == [
        (FromCommand(5, CallCommandText(), mytool), 3),
        (FromCommand(5, CallCommandText(), mytool), 4),
    ]


@pytest.mark.parametrize(
    "program_invocation",
    [
        _program("pip", "install", arguments=("requests",)),
        UnknownProgramInvocation("mytool", (U,)),
    ],
)
def test_the_requests_of_a_command_carry_the_assignments_before_its_name(
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
):
    # The made-up command is `PIP_INDEX_URL=https://a.org/simple A=$(b) pip install requests`.
    variable_assignments = (
        ShellCommandVariableAssignment("PIP_INDEX_URL", "https://a.org/simple"),
        ShellCommandVariableAssignment("A", None),
    )
    ran_command = replace(
        _command(program_invocation),
        shell_command=ShellCommand(
            0, ("pip",), variable_assignments=variable_assignments
        ),
    )
    (network_request,) = _extract(ran_command).network_requests
    assert network_request.source == FromCommand(
        0, CallCommandText(), program_invocation, variable_assignments
    )


def test_a_url_whose_host_cannot_be_read_gives_an_uncertain_request_without_a_host():
    mytool = UnknownProgramInvocation("mytool", ("http://[::1/x",))
    extraction = _extract(_command(mytool))
    assert extraction.network_requests == (
        NetworkRequest(
            KEY,
            0,
            FromCommand(0, CallCommandText(), mytool),
            "http://[::1/x",
            URL,
            (),
            UnknownReceivedContentDestination(),
            UNCERTAIN,
            UNKNOWN_PROGRAM,
        ),
    )
    assert extraction.judgment_rule_use_counts == Counter()


def test_a_program_without_a_row_finds_urls_in_its_option_values_and_unread_words():
    git_push = _program(
        "git",
        "push",
        options=(("--repo", "https://a.org/r"),),
        arguments=("origin",),
        unread_words=("--foo", "https://b.org/r"),
    )
    assert _targets(_requests(git_push)) == ["https://a.org/r", "https://b.org/r"]


def test_the_knowledge_class_is_asked_once_for_each_program_of_a_command():
    # `python -m venv` as `expand_tool_calls` reads it, a python that runs the module venv, neither with a row of the request catalog.
    python = _program("python", runs_next_program=True)
    venv = _program("venv")
    extraction = _extract(_command(python, venv))
    assert extraction.network_requests == ()
    assert extraction.knowledge.uses.unknown_input_counts == Counter(
        {
            (PROGRAM_NETWORK_REQUESTS_CSV, ("python", "", "", "")): 1,
            (PROGRAM_NETWORK_REQUESTS_CSV, ("venv", "", "", "")): 1,
        }
    )
    assert extraction.no_network_request_counts == Counter(
        {
            NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE: 1,
            NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC: 1,
        }
    )


# URLs in the words of an unknown program and their hosts.


@pytest.mark.parametrize(
    ("words", "variable_values", "targets_and_host_names", "rule_use_counts"),
    [
        pytest.param(
            ("http://db:5432",),
            (),
            [("http://db:5432", ("db",))],
            {SINGLE_LABEL_RULE_NAME: 1},
            id="mytool http://db:5432",
        ),
        pytest.param(
            ("https://$HOST/x",),
            (),
            [("https://$HOST/x", ("$HOST",))],
            {SINGLE_LABEL_RULE_NAME: 1},
            id="mytool https://$HOST/x",
        ),
        pytest.param(
            ("https://files.acme.org/x",),
            (),
            [("https://files.acme.org/x", ("files.acme.org",))],
            {DOTTED_NAME_RULE_NAME: 1},
            id="mytool https://files.acme.org/x",
        ),
        # A name with an empty label is kept without a rule, so its request counts toward the upper bound, as the user decided on 2026-11-21.
        pytest.param(
            ("https://a..org/x",),
            (),
            [("https://a..org/x", ("a..org",))],
            {},
            id="mytool https://a..org/x",
        ),
        pytest.param(
            ("https://$U/x",),
            (VariableValues("U", ("a.org",), False, False),),
            [("https://a.org/x", ("a.org",))],
            {DOTTED_NAME_RULE_NAME: 1},
            id="a variable of one value is filled in",
        ),
        pytest.param(
            ("https://$U/x",),
            (VariableValues("U", ("a.org",), False, True),),
            [("https://$U/x", ("$U",))],
            {SINGLE_LABEL_RULE_NAME: 1},
            id="a variable that may also get a value when it runs is not filled in",
        ),
        pytest.param(
            ("https://$U/x",),
            (VariableValues("U", ("a.org", "b.org"), False, False),),
            [("https://$U/x", ("$U",))],
            {SINGLE_LABEL_RULE_NAME: 1},
            id="a variable of several values is not filled in",
        ),
        pytest.param(
            ("https://github.com/${REPO}/a.tgz", "https://${HOST}/x"),
            (),
            [
                ("https://github.com/${REPO}/a.tgz", ("github.com",)),
                ("https://${HOST}/x", ("${HOST}",)),
            ],
            {DOTTED_NAME_RULE_NAME: 1, SINGLE_LABEL_RULE_NAME: 1},
            id="braced variables stay whole in the target and the host",
        ),
        pytest.param(
            (U, U),
            (),
            [(U, ("a.org",))],
            {DOTTED_NAME_RULE_NAME: 1},
            id="mytool u u gives one request",
        ),
        pytest.param(
            ("--url=" + U, "http://127.0.0.1/y"),
            (),
            [(U, ("a.org",))],
            {DOTTED_NAME_RULE_NAME: 1},
            id="a URL inside a word, beside a local one",
        ),
    ],
)
def test_urls_in_the_words_of_an_unknown_program(
    words: tuple[str, ...],
    variable_values: tuple[VariableValues, ...],
    targets_and_host_names: list[tuple[str, tuple[str, ...]]],
    rule_use_counts: dict[str, int],
):
    extraction = _extract(
        _command(
            UnknownProgramInvocation("mytool", words), variable_values=variable_values
        )
    )
    assert [
        (network_request.target, network_request.host_names)
        for network_request in extraction.network_requests
    ] == targets_and_host_names
    assert extraction.judgment_rule_use_counts == Counter(rule_use_counts)


# A known program with words that `expand_tool_calls` could not read.


def test_unread_words_give_one_request_whose_target_and_destination_are_unknown():
    curl = _program(
        "curl", unread_words=("--foo", "x", "https://a.org", "-o", "a"), arguments=()
    )
    written_file = WrittenFile(
        "a", (WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),), ()
    )
    assert _extract(
        _command(curl), _expanded_tool_call(written_files=(written_file,))
    ).network_requests == (
        NetworkRequest(
            KEY,
            0,
            FromCommand(0, CallCommandText(), curl),
            UNREAD_WORDS,
            URL,
            ("a.org",),
            UnknownReceivedContentDestination(),
            UNCERTAIN,
            NetworkRequestUncertaintyReason.UNREAD_WORDS,
        ),
    )


def test_unread_words_name_the_hosts_of_arguments_and_unread_words_without_templates():
    curl = _program(
        "curl",
        arguments=("https://a.org/x",),
        unread_words=("--foo", "https://$H/y", "https://$U/z", "https://a.org/w"),
    )
    (network_request,) = _requests(
        curl, variable_values=(VariableValues("U", ("b.org",), False, False),)
    )
    assert network_request.host_names == ("a.org", "b.org")


# Values that a command passes to the pieces that read its targets and its content destination.


def test_variable_values_of_the_command_give_its_targets():
    pip = _program("pip", "install", arguments=("pkg$A",))
    extraction = _extract(
        _command(pip, variable_values=(VariableValues("A", ("1", "2"), False, False),))
    )
    assert _targets(extraction.network_requests) == [VALUE_SET_AT_RUN_TIME]
    assert extraction.judgment_rule_use_counts == Counter(
        {treat_values_outside_their_for_loop_as_unknown_target.__name__: 1}
    )


def test_each_option_gets_the_effect_of_its_own_row():
    # `-e` names a target in its value and `-r` a file of targets, so swapped effects would make reqs.txt a target.
    pip = _program("pip", "install", options=(("-e", "x"), ("-r", "reqs.txt")))
    assert _targets(_requests(pip)) == ["x", NAMED_IN_FILE]


def test_written_files_of_the_call_give_the_content_destination_also_when_it_did_not_run():
    curl = _program("curl", options=(("-o", "a.tgz"),), arguments=(U,))
    written_file = WrittenFile(
        "a.tgz", (WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),), ()
    )
    expanded_tool_call = _expanded_tool_call(
        written_files=(written_file,), execution_status=ExecutionStatus.NOT_RUN
    )
    (network_request,) = _extract(_command(curl), expanded_tool_call).network_requests
    assert network_request.received_content_destination == ContentSaved("a.tgz")


def test_the_number_of_requests_of_the_program_reaches_its_content_destination():
    # curl writes the file of `-o` for the first URL only, but with one file of `-o` and two requests `extract_received_content_destination` names no path for either request and gives both `ContentSaved(None)`.
    curl = _program("curl", options=(("-o", "a.tgz"),), arguments=(U, U + "2"))
    written_file = WrittenFile(
        "a.tgz", (WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),), ()
    )
    network_requests = _extract(
        _command(curl), _expanded_tool_call(written_files=(written_file,))
    ).network_requests
    assert [r.received_content_destination for r in network_requests] == [
        ContentSaved(None),
        ContentSaved(None),
    ]


# Which URLs may be public.


def test_urls_that_may_be_public_keep_public_and_possibly_public_hosts_only():
    judgment_rule_use_counts: Counter[str] = Counter()
    assert urls_that_may_be_public(
        (
            "https://8.8.8.8/x",
            "http://10.0.0.5/x",
            "https://api.example.org/x",
            "http://[::1/x",
            "https://files.acme.org/x",
            "http://db:5432",
        ),
        judgment_rule_use_counts,
    ) == ("https://8.8.8.8/x", "https://files.acme.org/x", "http://db:5432")
    assert judgment_rule_use_counts == Counter(
        {DOTTED_NAME_RULE_NAME: 1, SINGLE_LABEL_RULE_NAME: 1}
    )
