"""Tests for network_request/_extract_network_request_targets.py, with program invocations made by hand and labels and option effects from the real catalog."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ProgramInvocation,
    ProgramOption,
    VariableValues,
)
from tb_internet_use.knowledge.network_request_knowledge import (
    NetworkRequestKnowledge,
)
from tb_internet_use.network_request import _extract_network_request_targets
from tb_internet_use.network_request._extract_network_request_targets import (
    extract_network_request_targets,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_values_outside_their_for_loop_as_one_request_each,
)
from tb_internet_use.network_request.model import (
    FetchingProgramLabel,
    NetworkRequestTargetKind,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
)

PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
REPOSITORY_URL = NetworkRequestTargetKind.REPOSITORY_URL
URL = NetworkRequestTargetKind.URL
HOST = NetworkRequestTargetKind.HOST
NAMED_IN_FILE = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.NAMED_IN_FILE
)
LOCAL_PATH = UnknownNetworkRequestTarget(UnknownNetworkRequestTargetReason.LOCAL_PATH)
VALUE_SET_AT_RUN_TIME = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME
)
UNKNOWN_OPTION_EFFECT = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.UNKNOWN_OPTION_EFFECT
)
VALUES_OUTSIDE_LOOP_RULE_NAME = (
    treat_values_outside_their_for_loop_as_one_request_each.__name__
)
LOOP = VariableValues("p", ("A", "B", "C"), True, False)
BRANCHES = VariableValues("A", ("1", "2"), False, False)
SINGLE_HOST = VariableValues("U", ("a.org",), False, False)
ONE_ITEM_LOOP = VariableValues("o", ("e",), True, False)
OTHER_LOOP = VariableValues("q", ("c", "d"), True, False)
VALUE_ALSO_SET_AT_RUN_TIME = VariableValues("V", ("a",), False, True)
HOST_ALSO_SET_AT_RUN_TIME = VariableValues("H", ("a.org",), False, True)
_VARIABLE_VALUES = (
    LOOP,
    BRANCHES,
    SINGLE_HOST,
    ONE_ITEM_LOOP,
    OTHER_LOOP,
    VALUE_ALSO_SET_AT_RUN_TIME,
    HOST_ALSO_SET_AT_RUN_TIME,
)


def _invocation(
    program_name: str,
    subcommand_words: tuple[str, ...] = (),
    *,
    options: tuple[tuple[str, str | None], ...] = (),
    arguments: tuple[str, ...] = (),
    gets_more_arguments_at_run_time: bool = False,
    unread_words: tuple[str, ...] = (),
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name,
        subcommand_words,
        tuple(ProgramOption(name, value) for name, value in options),
        arguments,
        gets_more_arguments_at_run_time,
        unread_words,
        exits_with_exit_code_of_next_program=False,
    )


def _targets(
    program_invocation: ProgramInvocation,
    *,
    next_program_name: str | None = None,
    variable_values: tuple[VariableValues, ...] = (),
    judgment_rule_use_counts: Counter[str] | None = None,
):
    """Extract the targets with the label and the option effects that the real catalog gives the invocation."""
    knowledge = NetworkRequestKnowledge()
    fetching_program_label = knowledge.program_network_request_label(program_invocation)
    assert isinstance(fetching_program_label, FetchingProgramLabel)
    program_option_effects = [
        knowledge.program_option_effect(program_invocation, program_option)
        for program_option in program_invocation.options
    ]
    return extract_network_request_targets(
        program_invocation,
        fetching_program_label,
        program_option_effects,
        next_program_name,
        variable_values,
        judgment_rule_use_counts=Counter()
        if judgment_rule_use_counts is None
        else judgment_rule_use_counts,
    )


# One row per command whose program's words show its targets, or show that it has none.
_CASES_OF_COMMANDS = [
    pytest.param(
        _invocation("curl", arguments=("https://a.org/x",)),
        [("https://a.org/x", URL, ("a.org",))],
        id="curl https://a.org/x",
    ),
    pytest.param(
        _invocation("curl", arguments=("http://localhost:8000/health",)),
        [("http://localhost:8000/health", URL, ("localhost",))],
        id="curl to a local host",
    ),
    pytest.param(
        _invocation("curl", arguments=("pypi.org/simple",)),
        [("pypi.org/simple", URL, ("pypi.org",))],
        id="curl pypi.org/simple",
    ),
    pytest.param(
        _invocation("curl", arguments=("https://a.org/x", "https://a.org/x")),
        [("https://a.org/x", URL, ("a.org",))] * 2,
        id="curl u u",
    ),
    pytest.param(
        _invocation("apt-get", ("update",)),
        [(None, PACKAGE_NAME, ())],
        id="apt-get update",
    ),
    pytest.param(
        _invocation("pip", ("install",), arguments=("A", "B", "C")),
        [("A", PACKAGE_NAME, ()), ("B", PACKAGE_NAME, ()), ("C", PACKAGE_NAME, ())],
        id="pip install A B C",
    ),
    pytest.param(
        _invocation(
            "pip", ("install",), arguments=("requests", "git+https://github.com/a/b")
        ),
        [
            ("requests", PACKAGE_NAME, ()),
            ("git+https://github.com/a/b", REPOSITORY_URL, ("github.com",)),
        ],
        id="pip install requests git+https://github.com/a/b",
    ),
    pytest.param(
        _invocation("pip", ("install",), options=(("-r", "reqs.txt"),)),
        [(NAMED_IN_FILE, PACKAGE_NAME, ())],
        id="pip install -r reqs.txt",
    ),
    pytest.param(
        _invocation("pip", ("install",), options=(("-r", "a.txt"), ("-r", "b.txt"))),
        [(NAMED_IN_FILE, PACKAGE_NAME, ())],
        id="pip install -r a.txt -r b.txt",
    ),
    pytest.param(
        _invocation("pip", ("install",), options=(("-e", "."),)),
        [(LOCAL_PATH, PACKAGE_NAME, ())],
        id="pip install -e .",
    ),
    pytest.param(
        _invocation("pip", ("install",), arguments=("./dist/x.whl",)),
        [(LOCAL_PATH, PACKAGE_NAME, ())],
        id="pip install ./dist/x.whl",
    ),
    pytest.param(
        _invocation(
            "pip", ("install",), options=(("-e", "git+https://github.com/a/b"),)
        ),
        [("git+https://github.com/a/b", REPOSITORY_URL, ("github.com",))],
        id="pip install -e git+https://github.com/a/b",
    ),
    pytest.param(
        _invocation(
            "pip",
            ("install",),
            options=(("-e", "git+https://github.com/a/b"),),
            arguments=("requests",),
        ),
        [
            ("requests", PACKAGE_NAME, ()),
            ("git+https://github.com/a/b", REPOSITORY_URL, ("github.com",)),
        ],
        id="the value of -e comes after the arguments",
    ),
    pytest.param(
        _invocation(
            "pip",
            ("install",),
            options=(("-r", "a.txt"),),
            arguments=("./x.whl", "./y.whl", "z"),
        ),
        [
            ("z", PACKAGE_NAME, ()),
            (NAMED_IN_FILE, PACKAGE_NAME, ()),
            (LOCAL_PATH, PACKAGE_NAME, ()),
        ],
        id="pip install -r a.txt ./x.whl ./y.whl z",
    ),
    pytest.param(
        _invocation(
            "pip",
            ("install",),
            options=(("-i", "https://pypi.org/simple"),),
            arguments=("x",),
        ),
        [("x", PACKAGE_NAME, ("pypi.org",))],
        id="pip install -i https://pypi.org/simple x",
    ),
    pytest.param(
        _invocation(
            "pip",
            ("install",),
            options=(("-r", "reqs.txt"), ("-i", "https://pypi.org/simple")),
        ),
        [(NAMED_IN_FILE, PACKAGE_NAME, ("pypi.org",))],
        id="the index host is a host of a request whose targets a file names",
    ),
    pytest.param(
        _invocation(
            "pip",
            ("install",),
            options=(("-i", "https://pypi.org/simple"),),
            arguments=("git+https://github.com/a/b",),
        ),
        [("git+https://github.com/a/b", REPOSITORY_URL, ("github.com", "pypi.org"))],
        id="the host of the target comes before the index host",
    ),
    pytest.param(
        _invocation(
            "pip",
            ("install",),
            options=(("-i", "https://github.com/simple"),),
            arguments=("git+https://github.com/a/b",),
        ),
        [("git+https://github.com/a/b", REPOSITORY_URL, ("github.com",))],
        id="a host of both the target and the index is listed once",
    ),
    pytest.param(
        _invocation("pip", ("install",), options=(("-i", "https://pypi.org/simple"),)),
        [(None, PACKAGE_NAME, ("pypi.org",))],
        id="pip install -i https://pypi.org/simple, a request without a target",
    ),
    pytest.param(
        _invocation("pip", ("install",), options=(("-e", None),)),
        [(None, PACKAGE_NAME, ())],
        id="pip install -e without a value names no target",
    ),
    pytest.param(
        _invocation("pip", ("install",), options=(("-i", None),), arguments=("x",)),
        [("x", PACKAGE_NAME, ())],
        id="pip install -i without a value names no host",
    ),
    pytest.param(
        _invocation("curl", options=(("-K", "cfg"),)),
        [(UNKNOWN_OPTION_EFFECT, URL, ())],
        id="curl -K cfg, whose option has no row and may name the target",
    ),
    pytest.param(
        _invocation("git", ("clone",), arguments=("git@github.com:a/b.git", "d")),
        [("git@github.com:a/b.git", REPOSITORY_URL, ("github.com",))],
        id="git clone git@github.com:a/b.git d",
    ),
    pytest.param(
        _invocation("git", ("fetch",), arguments=("origin", "main:main")),
        [("origin", REPOSITORY_URL, ())],
        id="git fetch origin main:main",
    ),
    pytest.param(
        _invocation("ping", options=(("-c", "1"),), arguments=("pypi.org",)),
        [("pypi.org", HOST, ("pypi.org",))],
        id="ping -c 1 pypi.org, whose option has no row",
    ),
    pytest.param(
        _invocation("getent", ("hosts",), arguments=("a.org", "b.org")),
        [("a.org", HOST, ("a.org",)), ("b.org", HOST, ("b.org",))],
        id="getent hosts a.org b.org",
    ),
    pytest.param(
        _invocation("curl", options=(("-L", None),), arguments=("https://a.org",)),
        [("https://a.org", URL, ("a.org",))],
        id="curl -L u, whose option has no row",
    ),
    pytest.param(
        _invocation("curl", options=(("-o", "a.tgz"),), arguments=("https://a.org/x",)),
        [("https://a.org/x", URL, ("a.org",))],
        id="curl -o a.tgz u, whose option value is no target",
    ),
    pytest.param(
        _invocation("lake", ("build",)),
        [(NAMED_IN_FILE, PACKAGE_NAME, ())],
        id="lake build",
    ),
    pytest.param(
        _invocation("sbt", arguments=("compile",)),
        [(NAMED_IN_FILE, PACKAGE_NAME, ())],
        id="sbt compile, whose row names no target arguments",
    ),
    pytest.param(_invocation("curl"), [], id="curl without arguments"),
    pytest.param(
        _invocation(
            "curl",
            options=(("-s", None), ("-O", None)),
            gets_more_arguments_at_run_time=True,
        ),
        [(VALUE_SET_AT_RUN_TIME, URL, ())],
        id="cat urls.txt | xargs curl -sO",
    ),
    pytest.param(
        _invocation(
            "apt-get",
            ("install",),
            options=(("-y", None),),
            gets_more_arguments_at_run_time=True,
        ),
        [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
        id="cat pkgs.txt | xargs apt-get install -y",
    ),
    pytest.param(
        _invocation(
            "pip", ("install",), arguments=("x",), gets_more_arguments_at_run_time=True
        ),
        [("x", PACKAGE_NAME, ()), (VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
        id="xargs pip install x adds an unknown target after x",
    ),
]


@pytest.mark.parametrize(("program_invocation", "targets"), _CASES_OF_COMMANDS)
def test_targets_of_commands(program_invocation: ProgramInvocation, targets):
    judgment_rule_use_counts: Counter[str] = Counter()

    assert (
        list(
            _targets(
                program_invocation, judgment_rule_use_counts=judgment_rule_use_counts
            )
        )
        == targets
    )
    assert judgment_rule_use_counts == Counter()


def test_the_next_program_is_the_target_of_npx():
    npx = _invocation("npx")

    assert _targets(npx, next_program_name="tsc") == (("tsc", PACKAGE_NAME, ()),)
    assert _targets(npx, next_program_name=None) == ()


@pytest.mark.parametrize(
    ("program_invocation", "targets", "values_outside_loop_rule_use_count"),
    [
        pytest.param(
            _invocation("pip", ("install",), arguments=("$p",)),
            [("A", PACKAGE_NAME, ()), ("B", PACKAGE_NAME, ()), ("C", PACKAGE_NAME, ())],
            0,
            id="for p in A B C; do pip install $p; done",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("${p}",)),
            [("A", PACKAGE_NAME, ()), ("B", PACKAGE_NAME, ()), ("C", PACKAGE_NAME, ())],
            0,
            id="a variable in braces",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("$PKG",)),
            [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
            0,
            id="pip install $PKG, or a loop over $(cat list.txt)",
        ),
        pytest.param(
            _invocation("curl", arguments=("https://a.org/$F",)),
            [(VALUE_SET_AT_RUN_TIME, URL, ("a.org",))],
            0,
            id="curl https://a.org/$F",
        ),
        pytest.param(
            _invocation(
                "pip",
                ("install",),
                options=(("-i", "https://pypi.org/simple"),),
                arguments=("$PKG",),
            ),
            [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ("pypi.org",))],
            0,
            id="the index host is a host of an unknown target",
        ),
        pytest.param(
            _invocation("curl", arguments=("https://a.org/$p/$p.tgz",)),
            [
                ("https://a.org/A/A.tgz", URL, ("a.org",)),
                ("https://a.org/B/B.tgz", URL, ("a.org",)),
                ("https://a.org/C/C.tgz", URL, ("a.org",)),
            ],
            0,
            id="a loop variable written twice in a word",
        ),
        pytest.param(
            _invocation("curl", arguments=("https://$p/$F",)),
            [(VALUE_SET_AT_RUN_TIME, URL, ())],
            0,
            id="a host of several values names no host",
        ),
        pytest.param(
            _invocation("curl", arguments=("https://$U/x",)),
            [("https://a.org/x", URL, ("a.org",))],
            0,
            id="a variable of one value is filled in",
        ),
        pytest.param(
            _invocation("curl", arguments=("https://$U/$F",)),
            [(VALUE_SET_AT_RUN_TIME, URL, ("a.org",))],
            0,
            id="the host of an unknown target is filled in",
        ),
        pytest.param(
            _invocation("curl", arguments=("https://$NOHOST/x",)),
            [(VALUE_SET_AT_RUN_TIME, URL, ())],
            0,
            id="a host without a value names no host",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("pkg$A",)),
            [("pkg1", PACKAGE_NAME, ()), ("pkg2", PACKAGE_NAME, ())],
            1,
            id="pip install pkg$A after A=1 or A=2",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("$o-$p",)),
            [
                ("e-A", PACKAGE_NAME, ()),
                ("e-B", PACKAGE_NAME, ()),
                ("e-C", PACKAGE_NAME, ()),
            ],
            0,
            id="a one-item loop is filled in beside a loop of several",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("$p-$q",)),
            [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
            0,
            id="two variables of several values",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("$p-$A",)),
            [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
            0,
            id="a loop and a variable of branches, without asking the rule",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("$p$(date)",)),
            [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
            0,
            id="a loop beside a command substitution",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("pkg$A`x`",)),
            [(VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
            0,
            id="a backtick beside a variable of branches, without asking the rule",
        ),
        pytest.param(
            _invocation("curl", arguments=("${U:-b.org}",)),
            [(VALUE_SET_AT_RUN_TIME, URL, ())],
            0,
            id="a default value expansion",
        ),
        pytest.param(
            _invocation("pip", ("install",), arguments=("$V",)),
            [("a", PACKAGE_NAME, ()), (VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ())],
            0,
            id="U=a; U=$(cat u.txt); pip install $U",
        ),
        pytest.param(
            _invocation("curl", arguments=("https://$H/x",)),
            [
                ("https://a.org/x", URL, ("a.org",)),
                (VALUE_SET_AT_RUN_TIME, URL, ()),
            ],
            0,
            id="a host also set at run time is no host of the unknown target",
        ),
        pytest.param(
            _invocation(
                "pip",
                ("install",),
                options=(("-i", "https://$U/simple"),),
                arguments=("x",),
            ),
            [("x", PACKAGE_NAME, ("a.org",))],
            0,
            id="the index host is filled in",
        ),
        pytest.param(
            _invocation(
                "pip",
                ("install",),
                options=(("-i", "https://$H/simple"),),
                arguments=("x",),
            ),
            [("x", PACKAGE_NAME, ())],
            0,
            id="an index host also set at run time names no host",
        ),
    ],
)
def test_targets_of_words_with_variables(
    program_invocation: ProgramInvocation,
    targets,
    values_outside_loop_rule_use_count: int,
):
    judgment_rule_use_counts: Counter[str] = Counter()

    assert (
        list(
            _targets(
                program_invocation,
                variable_values=_VARIABLE_VALUES,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
        )
        == targets
    )
    assert judgment_rule_use_counts == Counter(
        {VALUES_OUTSIDE_LOOP_RULE_NAME: values_outside_loop_rule_use_count}
        if values_outside_loop_rule_use_count
        else {}
    )


def test_values_outside_their_for_loop_give_one_unknown_target_when_the_rule_gives_none(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _extract_network_request_targets,
        VALUES_OUTSIDE_LOOP_RULE_NAME,
        lambda variable_values, *, use_counts: (),
    )
    pip_install = _invocation("pip", ("install",), arguments=("pkg$A",))

    assert _targets(pip_install, variable_values=(BRANCHES,)) == (
        (VALUE_SET_AT_RUN_TIME, PACKAGE_NAME, ()),
    )


@pytest.mark.parametrize(
    "program_invocation",
    [
        pytest.param(
            _invocation("curl", unread_words=("--foo", "x", "https://a.org")),
            id="curl --foo x u",
        ),
        pytest.param(
            _invocation(
                "pip", ("install",), options=(("--no-index", None),), arguments=("x",)
            ),
            id="pip install --no-index x",
        ),
    ],
)
def test_an_invocation_that_the_caller_settles_is_refused(
    program_invocation: ProgramInvocation,
):
    with pytest.raises(ValueError):
        _targets(program_invocation)
