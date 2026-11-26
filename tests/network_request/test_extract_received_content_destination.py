"""Tests for network_request/_extract_received_content_destination.py, with commands made by hand and content routes and option effects from the real catalog."""

import pytest

from tb_internet_use.expanded_tool_call.model import (
    FileWriteChannel,
    OutputRoute,
    OutputRouteEnd,
    OutputVisibility,
    ProgramInvocation,
    ProgramOption,
    RanCommand,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.knowledge.network_request_knowledge import (
    NetworkRequestKnowledge,
)
from tb_internet_use.network_request._extract_received_content_destination import (
    extract_received_content_destination,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentPipedToCommand,
    ContentSaved,
    ContentShownInResult,
    FetchingProgramLabel,
    NoContentRequested,
    ProgramContentRoute,
    ReceivedContentDestination,
    UnknownProgramContentRoute,
    UnknownReceivedContentDestination,
)
from tb_internet_use.tool_call.model import (
    CaptureDestination,
    DiscardDestination,
    FileDestination,
    ResultDestination,
    ShellCommand,
)

U = "https://a.org/x"
TO_RESULT = OutputRoute((), ResultDestination(), OutputVisibility.WHOLE)


def _invocation(
    program_name: str,
    subcommand_words: tuple[str, ...] = (),
    *,
    options: tuple[tuple[str, str | None], ...] = (),
    arguments: tuple[str, ...] = (U,),
    gets_more_arguments_at_run_time: bool = False,
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name,
        subcommand_words,
        tuple(ProgramOption(name, value) for name, value in options),
        arguments,
        gets_more_arguments_at_run_time,
        (),
        exits_with_exit_code_of_next_program=False,
    )


def _route_to(end: OutputRouteEnd) -> OutputRoute:
    return OutputRoute((), end, OutputVisibility.WHOLE)


def _own_output_file(path: str, command_id: int = 0) -> WrittenFile:
    return WrittenFile(
        path, (WrittenFileWriter(command_id, FileWriteChannel.OWN_OUTPUT_FILE),), ()
    )


def _destination(
    program_invocation: ProgramInvocation,
    *,
    stdout_routes: tuple[OutputRoute, ...] = (TO_RESULT,),
    written_files: tuple[WrittenFile, ...] = (),
    network_request_count: int = 1,
) -> ReceivedContentDestination:
    """Extract the destination of the program of command 0 with the content route and the option effects that the real catalog gives it."""
    knowledge = NetworkRequestKnowledge()
    fetching_program_label = knowledge.program_network_request_label(program_invocation)
    assert isinstance(fetching_program_label, FetchingProgramLabel)
    ran_command = RanCommand(
        ShellCommand(0, (program_invocation.program_name,)),
        (program_invocation,),
        (),
        stdout_routes,
        (),
    )
    return extract_received_content_destination(
        fetching_program_label.content_route,
        [
            knowledge.program_option_effect(program_invocation, program_option)
            for program_option in program_invocation.options
        ],
        program_invocation,
        ran_command,
        written_files,
        network_request_count,
    )


@pytest.mark.parametrize(
    ("destination_arguments", "received_content_destination"),
    [
        pytest.param(
            {"program_invocation": _invocation("curl")},
            ContentShownInResult(),
            id="curl u",
        ),
        pytest.param(
            {"program_invocation": _invocation("apt-get", ("update",), arguments=())},
            ContentSaved(None),
            id="apt-get update",
        ),
        pytest.param(
            {"program_invocation": _invocation("pip", ("install",), arguments=("x",))},
            ContentSaved(None),
            id="pip install x, also in a call that did not run",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl", options=(("-o", "a.tgz"),)),
                "written_files": (_own_output_file("a.tgz"),),
            },
            ContentSaved("a.tgz"),
            id="curl -o a.tgz u, also in a call that did not run",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "stdout_routes": (_route_to(FileDestination("a.tgz", appends=False)),),
                "written_files": (
                    WrittenFile(
                        "a.tgz",
                        (WrittenFileWriter(0, FileWriteChannel.STDOUT),),
                        (),
                    ),
                ),
            },
            ContentSaved("a.tgz"),
            id="curl u > a.tgz",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "written_files": (
                    WrittenFile(
                        "err.log",
                        (WrittenFileWriter(0, FileWriteChannel.STDERR),),
                        (),
                    ),
                ),
            },
            ContentShownInResult(),
            id="curl u 2> err.log",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "stdout_routes": (_route_to(DiscardDestination()),),
            },
            ContentDiscarded(),
            id="curl u > /dev/null",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "curl", options=(("-o", "/dev/null"),)
                ),
                "written_files": (_own_output_file("/dev/null"),),
            },
            ContentDiscarded(),
            id="curl -o /dev/null u",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "curl", options=(("-O", None), ("-O", None)), arguments=(U, U + "2")
                ),
                "written_files": (_own_output_file("x"), _own_output_file("x2")),
                "network_request_count": 2,
            },
            ContentSaved(None),
            id="curl -O u1 -O u2",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "curl", options=(("-o", "a.tgz"),), arguments=(U, U + "2")
                ),
                "written_files": (_own_output_file("a.tgz"),),
                "network_request_count": 2,
            },
            ContentSaved(None),
            id="one file of its own for two requests",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "curl", options=(("-o", "a.tgz"), ("-o", "b.tgz"))
                ),
                "written_files": (_own_output_file("a.tgz"), _own_output_file("b.tgz")),
            },
            ContentSaved(None),
            id="two files of its own for one request",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "curl",
                    options=(("-o", "/dev/null"), ("-o", "/dev/null")),
                    arguments=(U, U + "2"),
                ),
                "written_files": (_own_output_file("/dev/null"),),
                "network_request_count": 2,
            },
            ContentSaved(None),
            id="curl -o /dev/null u1 -o /dev/null u2 saves to an unknown file",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl", options=(("-D", "h.txt"),)),
                "written_files": (_own_output_file("h.txt"),),
            },
            ContentShownInResult(),
            id="curl -D h.txt u, whose headers file does not hold the content",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl", options=(("-D", "h.txt"),)),
                "stdout_routes": (_route_to(FileDestination("b.txt", appends=False)),),
                "written_files": (
                    _own_output_file("h.txt"),
                    WrittenFile(
                        "b.txt", (WrittenFileWriter(0, FileWriteChannel.STDOUT),), ()
                    ),
                ),
            },
            ContentSaved("b.txt"),
            id="curl -D h.txt u > b.txt",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "curl", options=(("-o", "b.txt"), ("-D", "h.txt"))
                ),
                "written_files": (_own_output_file("b.txt"), _own_output_file("h.txt")),
            },
            ContentSaved("b.txt"),
            id="curl -o b.txt -D h.txt u",
        ),
        pytest.param(
            {"program_invocation": _invocation("curl"), "stdout_routes": ()},
            UnknownReceivedContentDestination(),
            id="a command without a stdout route",
        ),
        pytest.param(
            {"program_invocation": _invocation("curl", options=(("--foo", None),))},
            UnknownReceivedContentDestination(),
            id="curl --foo u, whose option has no row and may send the content elsewhere",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "written_files": (_own_output_file("a.tgz", command_id=1),),
            },
            ContentShownInResult(),
            id="a file of its own that another command writes",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "stdout_routes": (
                    OutputRoute((1,), ResultDestination(), OutputVisibility.NONE),
                ),
            },
            ContentPipedToCommand(1, OutputVisibility.NONE),
            id="curl u | tar xz",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "stdout_routes": (
                    OutputRoute((1,), ResultDestination(), OutputVisibility.PARTIAL),
                ),
            },
            ContentPipedToCommand(1, OutputVisibility.PARTIAL),
            id="curl u | jq .",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "stdout_routes": (
                    OutputRoute(
                        (1, 2),
                        FileDestination("x.gz", appends=False),
                        OutputVisibility.NONE,
                    ),
                ),
            },
            ContentPipedToCommand(1, OutputVisibility.NONE),
            id="curl u | gzip > x.gz, or with a second reader",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "stdout_routes": (
                    OutputRoute((1,), ResultDestination(), OutputVisibility.WHOLE),
                    OutputRoute(
                        (1,),
                        FileDestination("log", appends=False),
                        OutputVisibility.WHOLE,
                    ),
                ),
            },
            UnknownReceivedContentDestination(),
            id="curl u | tee log",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl"),
                "stdout_routes": (_route_to(CaptureDestination()),),
            },
            UnknownReceivedContentDestination(),
            id="x=$(curl u)",
        ),
        pytest.param(
            {"program_invocation": _invocation("curl", options=(("-I", None),))},
            NoContentRequested(),
            id="curl -I u",
        ),
        pytest.param(
            {"program_invocation": _invocation("ping", arguments=("pypi.org",))},
            NoContentRequested(),
            id="ping pypi.org",
        ),
        # A lookup of a name prints the address and asks the host itself for nothing.
        pytest.param(
            {
                "program_invocation": _invocation(
                    "getent", ("hosts",), arguments=("pypi.org",)
                )
            },
            NoContentRequested(),
            id="getent hosts pypi.org",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "ping", arguments=(), gets_more_arguments_at_run_time=True
                )
            },
            NoContentRequested(),
            id="xargs ping asks for no content",
        ),
        pytest.param(
            {
                "program_invocation": _invocation("curl", options=(("-o", "-"),)),
                "written_files": (_own_output_file("-"),),
            },
            ContentShownInResult(),
            id="curl -o - u",
        ),
        pytest.param(
            {"program_invocation": _invocation("wget", options=(("-O", "-"),))},
            ContentShownInResult(),
            id="wget -O - u, whose row says own_file",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "rsync", (), arguments=("a.org:/x", "x")
                )
            },
            UnknownReceivedContentDestination(),
            id="rsync a.org:/x x, whose row leaves the route blank",
        ),
        pytest.param(
            {
                "program_invocation": _invocation(
                    "curl",
                    options=(("-O", None),),
                    arguments=(),
                    gets_more_arguments_at_run_time=True,
                ),
            },
            UnknownReceivedContentDestination(),
            id="cat urls.txt | xargs curl -O",
        ),
    ],
)
def test_received_content_destination(
    destination_arguments, received_content_destination: ReceivedContentDestination
):
    assert _destination(**destination_arguments) == received_content_destination


def test_a_file_of_its_own_is_the_destination_also_when_the_row_leaves_the_route_blank():
    ran_command = RanCommand(ShellCommand(0, ("mytool",)), (), (), (TO_RESULT,), ())
    program_invocation = _invocation("mytool")

    assert extract_received_content_destination(
        UnknownProgramContentRoute(),
        [],
        program_invocation,
        ran_command,
        [_own_output_file("a.tgz")],
        1,
    ) == ContentSaved("a.tgz")
    assert extract_received_content_destination(
        ProgramContentRoute.OWN_FILE,
        [],
        program_invocation,
        ran_command,
        [_own_output_file("a.tgz")],
        1,
    ) == ContentSaved("a.tgz")
