"""Tests for callrun/output_routes.py."""

import pytest

from tb_internet_use.callrun.model import OutputRouteEnd
from tb_internet_use.callrun.output_routes import output_routes
from tb_internet_use.shell import parse_shell
from tb_internet_use.shell.model import (
    CaptureDestination,
    DiscardDestination,
    FileDestination,
    ResultDestination,
)

RESULT = ResultDestination()


def _routes_of_curl(text: str, stream: str) -> list[tuple[list[str], OutputRouteEnd]]:
    """The routes of curl's stdout or stderr, with each pipe reader named by its first word."""
    parsed = parse_shell(text)
    commands_by_id = {c.id: c for c in parsed.commands}
    (curl,) = [c for c in parsed.commands if c.words[0] == "curl"]
    routes = output_routes(getattr(curl, stream), commands_by_id)
    return [
        ([commands_by_id[i].words[0] for i in route.pipe_reader_ids], route.end)
        for route in routes
    ]


@pytest.mark.parametrize(
    ("text", "stream", "routes"),
    [
        ("curl u", "stdout", [([], RESULT)]),
        ("curl u > log", "stdout", [([], FileDestination("log", appends=False))]),
        ("curl u >> log", "stdout", [([], FileDestination("log", appends=True))]),
        ("curl u | tail -1", "stdout", [(["tail"], RESULT)]),
        ("curl u | jq . | head", "stdout", [(["jq", "head"], RESULT)]),
        (
            "curl u | tee log | tail -1",
            "stdout",
            [
                (["tee", "tail"], RESULT),
                (["tee"], FileDestination("log", appends=False)),
            ],
        ),
        (
            "curl u | tee -a log",
            "stdout",
            [(["tee"], RESULT), (["tee"], FileDestination("log", appends=True))],
        ),
        ("curl u | tee /dev/null", "stdout", [(["tee"], RESULT)]),
        (
            "curl u > >(tee log)",
            "stdout",
            [(["tee"], RESULT), (["tee"], FileDestination("log", appends=False))],
        ),
        ("curl u | { grep a; grep b; }", "stdout", [(["grep"], RESULT)]),
        ("X=$(curl u)", "stdout", [([], CaptureDestination())]),
        ("curl u > /dev/null", "stdout", [([], DiscardDestination())]),
        ("curl u 2>&1 | tail", "stderr", [(["tail"], RESULT)]),
        ("curl u | tail", "stderr", [([], RESULT)]),
    ],
)
def test_output_routes(
    text: str, stream: str, routes: list[tuple[list[str], OutputRouteEnd]]
):
    assert _routes_of_curl(text, stream) == routes
