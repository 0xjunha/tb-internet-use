"""Decide what the trajectory and the output catalogs do not settle about how far a network request got, one named rule per situation, e.g. whether `curl` that ended with exit 0 and printed nothing reached a server.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, `uv pip install x` that prints only ` + x==1.0` may have taken x from a cache, and only a rule says whether that line shows that the content arrived.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a `NetworkRequestResult`.

Where the choice that claims least would contradict what the trajectory shows, e.g. a page text that a web fetch returned, a rule gives the level that the trajectory shows and marks it as resting on the rule.
`decide_network_request_results` then gives such a result the certainty ASSUMED, so it counts toward no lower bound of the trials that received something.
A rule that the user decided on the evidence of the trajectories may give a level that does not rest on it, as each such docstring says.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter
from collections.abc import Collection

from tb_internet_use.network_request_result.model import (
    NetworkRequestResultStopReason,
    OutputLineKind,
    ProgramExitCodeMeaning,
)

# The stop reasons of one level from the one taken first to the one taken last.
_STOP_REASONS_IN_FIXED_ORDER: tuple[NetworkRequestResultStopReason | None, ...] = (
    None,
    NetworkRequestResultStopReason.FAILED,
    NetworkRequestResultStopReason.NOT_NEEDED,
    NetworkRequestResultStopReason.NOT_VISIBLE,
)


def treat_exit_code_meaning_as_assumed_level(
    program_exit_code_meaning: ProgramExitCodeMeaning, *, use_counts: Counter[str]
) -> bool:
    """Take the level that the exit code catalog gives an exit code 0 as an assumed level of the request, e.g. `curl -s https://a.org/x -o x` that ended with exit 0 and printed no other line.

    The catalog says what such an exit code means for the program, e.g. that curl ends with 0 only after a server answered, but the trajectory shows no answer, and the catalog row was not checked against this run.
    `_exit_code_evidence_of` asks it for a request of a command whose text ended with exit 0 when `NetworkRequestResultKnowledge` gives the program SERVER_ANSWERED or REQUEST_SUCCEEDED.
    It raises `ValueError` for NOTHING, which shows no more than that the command ran.
    On `True` SERVER_ANSWERED gives REACHED with NOT_VISIBLE, and REQUEST_SUCCEEDED gives RECEIVED with no stop reason, or REACHED with none for a request that asks for no content, both resting on this rule.
    On `False` the exit code shows only that the command ran, EXECUTED with NOT_VISIBLE.
    A use is such a request.

    Provisional. No earlier code chose. The level that the catalog gives is taken as assumed, since leaving it at EXECUTED would contradict what the catalog says the exit code shows.
    """
    if program_exit_code_meaning == ProgramExitCodeMeaning.NOTHING:
        raise ValueError("an exit code that means nothing shows only that it ran")
    use_counts[treat_exit_code_meaning_as_assumed_level.__name__] += 1
    return True


def treat_pip_or_apt_installed_line_of_named_package_as_received(
    *, use_counts: Counter[str]
) -> bool:
    """Read a line of pip or apt that says a package was installed as showing that the content arrived when the request names the package, e.g. `Successfully installed x-1.0` as the only line of `pip install x`, or `Setting up curl (7.88)` under `apt-get install -y curl`.

    pip prints the same line when it installs x from its cache, so the line alone does not say whether the content came over the network.
    In the trajectories pip and apt downloaded what such a command installed. On all 21,450 Terminal-Bench 4.1 trajectories, 564 of 564 calls whose whole shell text is one `pip install` of named packages without `-q` and whose result shows `Successfully installed` also show a `Downloading` line of a package file, in 327 trials of 29 tasks, and none shows only `Using cached`.
    The same count for `apt-get install` found a `Get:` line of a package beside `Setting up` in 132 calls, and none without it in a result that the harness did not cut, while 27 results were cut.
    A local install prints the line without a download, e.g. `pip install -e /app` in 4 calls, so the rule holds only for a request whose target is a named package.
    `_level_and_stop_reason_from_output_line` asks it for each line of the kind INSTALLED that only pip or only apt prints and that a request owns, when the request's target is a named package, unless `treat_line_naming_another_target_as_no_evidence_of_answer` has taken the line.
    On `True` the line shows RECEIVED with no stop reason, or REACHED for a request that asks for no content, and the level does not rest on this rule. On `False` it shows only that the program ran, EXECUTED with NOT_VISIBLE.
    A use is such a line of a request.

    Decided. The user decided on 2026-11-22 from the counts above, so that such a trial counts in the lower bound of the trials that received something.
    """
    use_counts[
        treat_pip_or_apt_installed_line_of_named_package_as_received.__name__
    ] += 1
    return True


def treat_installed_line_as_no_evidence_of_download(
    *, use_counts: Counter[str]
) -> bool:
    """Read a line that says a package was installed as no evidence that it was downloaded, e.g. ` + x==1.0` as the only line of `uv pip install x`, or `Successfully installed app-0.1` under `pip install -e /app`.

    The program may have installed the package from its cache or from a local folder, so the line does not say whether the content came over the network.
    `_level_and_stop_reason_from_output_line` asks it for each line of the kind INSTALLED that a request owns, unless `treat_line_naming_another_target_as_no_evidence_of_answer` has taken the line or `treat_pip_or_apt_installed_line_of_named_package_as_received` is asked instead, i.e. for a line of another program such as uv or npm, and for a line of pip or apt under a request whose target is no named package, e.g. a local path or a file of requirements.
    A line beside a download line of a package file that the request owns never asks it, since the two show that the content arrived.
    On `True` the line shows only that the program ran, EXECUTED with NOT_VISIBLE. On `False` it shows that the content arrived, RECEIVED with no stop reason.
    A use is such a line of a request.

    Provisional. No earlier code chose, and no evidence of a download claims least. The installed lines of programs other than pip and apt were not counted in the trajectories.
    """
    use_counts[treat_installed_line_as_no_evidence_of_download.__name__] += 1
    return True


def treat_version_notice_line_as_no_evidence_of_answer(
    *, use_counts: Counter[str]
) -> bool:
    """Read a notice of a new version of the program as no evidence that a server answered the request, e.g. `[notice] A new release of pip is available` under `pip install x`.

    pip may learn of the new version from the package index or from its own check of another server, so the line does not say that the server of the request answered.
    `_level_and_stop_reason_from_output_line` asks it for each line of the kind VERSION_NOTICE that a request owns.
    On `True` the line shows only that the program ran, EXECUTED with NOT_VISIBLE. On `False` it shows that a server answered, REACHED with NOT_VISIBLE.
    A use is such a line of a request.

    Provisional. No earlier code chose, and no evidence of an answer claims least.
    """
    use_counts[treat_version_notice_line_as_no_evidence_of_answer.__name__] += 1
    return True


def treat_shown_result_text_as_assumed_content(*, use_counts: Counter[str]) -> bool:
    """Take a text in the result that shows what a request received as the content it asked for, e.g. the page text in the result of `curl https://a.org/x` or of a web fetch.

    The text may be the content asked for or an error page that a server sent instead, and the trajectory does not say which.
    `_received_content_evidence_of` asks it for a request whose received content goes to the result when that result has a text, no line of the request shows FAILED and the HTTP status of a web fetch is not from 400 to 599.
    A request of a command is asked only when it comes from the command words and is the only request whose output reaches that result, and a request of a web tool only when its call holds web tool actions only and its result has no line of the web tool result patterns, e.g. `not a robot`.
    On `True` the text gives a `ShownContentEvidence` with RECEIVED and no stop reason, resting on this rule. On `False` it gives no evidence, so the request keeps the level that its other evidence shows.
    A use is such a request.

    Provisional. No earlier code chose. The content is taken as assumed, since no evidence of content would contradict the text that the trajectory shows.
    """
    use_counts[treat_shown_result_text_as_assumed_content.__name__] += 1
    return True


def treat_size_or_type_of_saved_file_as_no_evidence_of_content(
    *, use_counts: Counter[str]
) -> bool:
    """Read a later use that shows only the size or kind of the file where a request saved its content as no evidence of that content, e.g. `ls -l a.tgz` after `curl -o a.tgz https://a.org/a.tgz`.

    A size or a kind fits an error page as well as the file asked for, so it does not say whether the content arrived.
    `_file_use_evidence_with_level_of` asks it for each `FileUse` of the use SHOWS_SIZE_OR_TYPE of a file where the request saved its content.
    On `True` the use gives no `FileUseEvidence`. On `False` it gives a `FileUseEvidence` with RECEIVED and no stop reason.
    A use is such a file use.

    Provisional. No earlier code chose, and no evidence of content claims least.
    """
    use_counts[treat_size_or_type_of_saved_file_as_no_evidence_of_content.__name__] += 1
    return True


def treat_higher_evidence_beside_failure_as_assumed_level(
    *, use_counts: Counter[str]
) -> bool:
    """Take the higher level when a request has evidence of a failure and evidence of a higher level, e.g. `Connection reset by peer` and then `Successfully downloaded x` in the output of `pip install x`.

    A program can try again after a failure, so the later line may show the same request going further, or another try that the trajectory does not tell apart.
    `_highest_level_and_stop_reason_of` asks it for a request that has evidence of FAILED at one level and evidence of a higher level.
    On `True` the result takes the higher level and its stop reason, resting on this rule. On `False` it takes the level of the failure with FAILED.
    A use is such a request.

    Provisional. No earlier code chose. The higher level is taken as assumed, since the failure alone would contradict the later line that the trajectory shows.
    """
    use_counts[treat_higher_evidence_beside_failure_as_assumed_level.__name__] += 1
    return True


def treat_web_tool_call_without_result_text_as_no_evidence_of_answer(
    *, use_counts: Counter[str]
) -> bool:
    """Read a finished call of web tool actions whose result has no text as no evidence that the provider answered, e.g. a Codex `web_search_call` whose result is `null` and whose status is finished.

    The provider ran the search on its own servers, and the trajectory keeps neither what it fetched nor what it returned.
    `_received_content_evidence_of` asks it for each request of a call that holds web tool actions only, is finished and has neither a result text nor an HTTP status.
    On `True` the call shows only that the tool ran, EXECUTED with NOT_VISIBLE. On `False` it shows that the provider answered, REACHED with NOT_VISIBLE.
    A use is such a request.

    Provisional. No earlier code chose, and no evidence of an answer claims least.
    """
    use_counts[
        treat_web_tool_call_without_result_text_as_no_evidence_of_answer.__name__
    ] += 1
    return True


def treat_line_naming_another_target_as_no_evidence_of_answer(
    *, use_counts: Counter[str]
) -> bool:
    """Read a line that names a package or host other than every one its owners name as no evidence that the server of the request answered, e.g. `Downloading B-1.0.whl` under `pip install A`.

    B may be a dependency that the request for A fetched or the output of another request, and the line does not say which.
    `_level_and_stop_reason_from_output_line` asks it for each line of a request with `OutputLineOwners.names_another_target` set, also for a request that names no target, e.g. `apt-get update` beside `curl https://a.org/x -o x` under `Could not resolve host: cdn.b.net`.
    On `True` the line shows only that the program ran, EXECUTED with NOT_VISIBLE. On `False` it shows the level that the same line would show if it named the target of the request.
    A use is such a line of a request.

    Provisional. No earlier code chose, and no evidence beyond the run claims least.
    """
    use_counts[treat_line_naming_another_target_as_no_evidence_of_answer.__name__] += 1
    return True


def treat_command_without_own_evidence_as_no_evidence_of_run(
    *, use_counts: Counter[str]
) -> bool:
    """Read a request whose command has no evidence of its own that it ran as not known to have run, e.g. `curl -s u` in `curl -s u | tar xz` with exit 0, `curl -s u` inside `fetch.sh` run by `bash fetch.sh`, or a `curl u` whose call timed out.

    Exit 0 of a text shows the run only of the commands that `succeeded_if_text_exits_zero` marks, and curl of `curl -s u | tar xz` is not one of them.
    The text of a file or of `bash -c` is not the text of the call, and a call that timed out, was killed or is still running gives no exit code.
    So the trajectory does not say whether such a command ran.
    `_execution_evidence_of` asks it once for each request that gets no evidence of its run from the status of its call, the exit code of its command text or the failure of a command before it, also when lines of the request show more.
    On `True` the run gives no evidence, ATTEMPTED with NOT_VISIBLE. On `False` it gives EXECUTED with NOT_VISIBLE.
    A use is such a request.

    Provisional. No earlier code chose, and not known to have run claims least.
    """
    use_counts[treat_command_without_own_evidence_as_no_evidence_of_run.__name__] += 1
    return True


def treat_line_beside_shown_file_or_page_text_as_not_a_trace(
    *, use_counts: Counter[str]
) -> bool:
    """Read a line that a request owns in a result that may also show the text of a file or of a page as no sure trace of that request, e.g. `curl: (7) Connection refused` in the result of `cat notes.md; curl -sS https://a.org/x` where no call wrote `notes.md`.

    The line may have been written in the file or the page, so the trajectory does not say whether the request printed it.
    `_output_line_evidence_of` asks it for each line that a request owns in a place where `OutputPlaceSources.may_show_file_content` or `may_show_page_text` is set. A line without an owner there is only counted.
    On `True` the evidence of the line rests on this rule, so it makes no result CONFIRMED and does not raise the certainty of the request. On `False` the line is a trace of the request like a line in any other place.
    A use is such a line of a request.

    Provisional. No earlier code chose, and evidence that rests on a rule claims least.
    """
    use_counts[treat_line_beside_shown_file_or_page_text_as_not_a_trace.__name__] += 1
    return True


def treat_file_use_that_may_not_have_happened_as_assumed_evidence(
    *, use_counts: Counter[str]
) -> bool:
    """Take a later use of the content of a file where a request saved its content as assumed evidence when the trajectory does not show that the use happened, e.g. `tar xzf a.tgz` in `test -f a.tgz || tar xzf a.tgz` after `curl -o a.tgz https://a.org/a.tgz`.

    The use may not have run, may have failed, or may be of another file of the same path, e.g. `tar xzf a.tgz; ls`, a `tar xzf` whose call ended with exit 2, or `x.tgz` written both to `/a/` and `/b/`.
    `_file_use_evidence_with_level_of` asks it for each `FileUse` of the use USES_CONTENT that is not sure to have happened, i.e. its path fits several written files, its command is not in the text of the call, may be read with a wrong structure or sits in a function or case branch, its text did not end finished with exit 0 for a command that succeeds when its text does, or a program outside the using program is not known to end with the exit code of the next, e.g. xargs in `xargs tar xzf a.tgz`.
    On `True` the use gives a `FileUseEvidence` with RECEIVED and no stop reason, resting on this rule. On `False` it gives no evidence.
    A use is such a file use.

    Provisional. No earlier code chose. The use is taken as assumed, since no evidence would contradict the use that the trajectory shows.
    """
    use_counts[
        treat_file_use_that_may_not_have_happened_as_assumed_evidence.__name__
    ] += 1
    return True


def treat_failure_before_server_as_stopping_next_command(
    *, use_counts: Counter[str]
) -> bool:
    """Read a line of a request that failed before reaching a server as stopping the command that runs only if that command succeeds, e.g. `Failed to connect to a.org` for the request of `pip install y` in `curl -sS https://a.org/x && pip install y`.

    A program can print such a line and still end with exit 0, e.g. after a retry, so the line does not say whether the next command ran.
    `_stopping_line_evidence_of` asks it for a request of command b in `a && b` when a request of a owns a line that shows EXECUTED with FAILED and that may belong to no other request.
    On `True` the request of b is ATTEMPTED with FAILED, with that line as its evidence, resting on this rule. On `False` the line gives the request of b nothing.
    A line of a server that refused, e.g. `HTTP/1.1 404`, never asks it, since curl ends with exit 0 after a 404 without `-f`.
    A use is such a request.

    Provisional. No earlier code chose. The stop is taken as assumed, since leaving b unknown would contradict the failure that the trajectory shows.
    """
    use_counts[treat_failure_before_server_as_stopping_next_command.__name__] += 1
    return True


def treat_tls_or_proxy_failure_as_before_server_answer(
    output_line_kind: OutputLineKind, *, use_counts: Counter[str]
) -> bool:
    """Read a line of a failed TLS handshake or of a proxy that refused as a failure before the server of the request answered, e.g. `SSL certificate problem` or `ProxyError`.

    A connection was made, to the server or to the proxy, so the line does not say whether the request reached the server.
    `_level_and_stop_reason_from_output_line` asks it for each line of the kind TLS_FAILED or PROXY_REFUSED that a request owns. Any other kind raises `ValueError`.
    On `True` the line shows EXECUTED with FAILED, resting on this rule. On `False` it shows REACHED with FAILED.
    A use is such a line of a request.

    Provisional. No earlier code chose, and a failure before the server claims least.
    """
    if output_line_kind not in (
        OutputLineKind.TLS_FAILED,
        OutputLineKind.PROXY_REFUSED,
    ):
        raise ValueError(f"{output_line_kind} is no TLS or proxy failure")
    use_counts[treat_tls_or_proxy_failure_as_before_server_answer.__name__] += 1
    return True


def treat_stop_reasons_of_one_level_as_first_in_fixed_order(
    stop_reasons: Collection[NetworkRequestResultStopReason | None],
    *,
    use_counts: Counter[str],
) -> NetworkRequestResultStopReason | None:
    """Pick one stop reason when the evidence of a request at its highest level gives several, by the fixed order of no stop reason, FAILED, NOT_NEEDED and NOT_VISIBLE, e.g. `HTTP/1.1 404` and `HTTP/1.1 200` in the output of `curl -i -L u`.

    A program can try again or follow a redirect, so the lines may show steps of one request, and the trajectory does not say which of them ended it.
    `_level_and_stop_reason_for` asks it for a request whose evidence at its highest level gives two or more of no stop reason, FAILED and NOT_NEEDED, or gives FAILED beside evidence of NOT_VISIBLE that shows the request may have gone on after the failure.
    It returns the first of the given stop reasons in the fixed order, and the result rests on this rule. It raises `ValueError` when it is given fewer than two different stop reasons.
    A use is such a request.

    Provisional. No earlier code chose. The result that rests on this rule is assumed, so it counts toward no lower bound of the trials that received something.
    """
    if len(set(stop_reasons)) < 2:
        raise ValueError("a stop reason is picked only among two or more")
    use_counts[treat_stop_reasons_of_one_level_as_first_in_fixed_order.__name__] += 1
    return next(
        stop_reason
        for stop_reason in _STOP_REASONS_IN_FIXED_ORDER
        if stop_reason in stop_reasons
    )


def treat_shown_content_of_saved_file_as_assumed_content(
    *, use_counts: Counter[str]
) -> bool:
    """Take a later call that shows the file where a request saved its content as showing the content asked for, e.g. `cat page.html` in a later call after `curl -o page.html https://a.org/x`.

    `curl -o` without `-f` saves the body of a 404 too, so the shown text may be the content asked for or a saved error page.
    `_file_use_evidence_with_level_of` asks it for each `FileUse` of the use SHOWS_CONTENT of a file where the request saved its content.
    On `True` the use gives a `FileUseEvidence` with RECEIVED and no stop reason, resting on this rule. On `False` it gives no evidence.
    A use is such a file use.

    Provisional. No earlier code chose. The content is taken as assumed, since no evidence would contradict the text that the trajectory shows.
    """
    use_counts[treat_shown_content_of_saved_file_as_assumed_content.__name__] += 1
    return True


def treat_connected_line_as_assumed_server_answer(*, use_counts: Counter[str]) -> bool:
    """Read a line that says a connection was made as an assumed answer of the server, e.g. `* Connected to a.org` in the output of `curl -v -o /dev/null https://a.org/x`, or `connected.` from wget.

    A connection shows that the server took it, not that the server answered the request.
    `_level_and_stop_reason_from_output_line` asks it for each line of the kind CONNECTED that a request owns, unless `treat_line_naming_another_target_as_no_evidence_of_answer` has taken the line.
    On `True` the line shows REACHED with NOT_VISIBLE, resting on this rule. On `False` it shows EXECUTED with NOT_VISIBLE.
    A use is such a line of a request.

    Provisional. No earlier code chose. The answer is taken as assumed, since the connection that the trajectory shows went further than the run alone.
    """
    use_counts[treat_connected_line_as_assumed_server_answer.__name__] += 1
    return True


def treat_line_that_unknown_printer_may_have_printed_as_shared(
    *, use_counts: Counter[str]
) -> bool:
    """Read a line that a run whose lines are not known may have printed as evidence that the request may share with another, e.g. `HTTP/1.1 200 OK` in the result of `mytool https://a.org/x`, or `Connection refused` in the result of `curl -s u; ./test.sh`.

    No catalog says which lines such a run prints, so the line may come from the request or from the run, and the trajectory does not say which.
    `_unknown_printer_reasons_of` asks it once for each line that a request owns, also one that other requests own too, when the run of the request has no known lines, or when the line may be printed by any program and a run that is not read reaches the same place.
    A line that only named programs print and that the known lines of the run of the request name stays the evidence of that request alone, e.g. `npm ERR! code E404` beside `tsc` in `npx tsc`, and does not ask it.
    On `True` the line gets an `UnknownProgramOutputLinesAssumptionReason`, an `UnknownRunBesideAssumptionReason` or both, so it makes no result CONFIRMED and does not raise the certainty of the request. On `False` it gets neither, so it is the evidence of this request alone unless other requests own it too.
    A use is such a line of a request.

    Provisional. No earlier code chose, and evidence that may belong to another request claims least.
    """
    use_counts[treat_line_that_unknown_printer_may_have_printed_as_shared.__name__] += 1
    return True


def treat_already_present_line_without_matching_target_as_assumed_not_needed(
    *, use_counts: Counter[str]
) -> bool:
    """Read a line that says what was asked is already there as assumed when the line names no target or the request names none, e.g. `Requirement already satisfied: x` under `pip install -r reqs.txt`, or `Audited 3 packages` from uv.

    The line does not say whether it covers everything that the request asked for.
    `_level_and_stop_reason_from_output_line` asks it for each line of the kind ALREADY_PRESENT that a request owns and that does not name the target of the request, unless `treat_line_naming_another_target_as_no_evidence_of_answer` has taken the line.
    On `True` the line shows EXECUTED with NOT_NEEDED, resting on this rule. On `False` it shows EXECUTED with NOT_VISIBLE.
    A use is such a line of a request.

    Provisional. No earlier code chose. NOT_NEEDED is taken as assumed, since NOT_VISIBLE would contradict the line that the trajectory shows.
    """
    use_counts[
        treat_already_present_line_without_matching_target_as_assumed_not_needed.__name__
    ] += 1
    return True


def treat_lost_connection_as_after_server_answer(*, use_counts: Counter[str]) -> bool:
    """Read a line that says a connection was lost as a failure after the server was reached, e.g. `Connection reset by peer` in the output of `pip install x`.

    The connection was made before it was lost, but the line does not say whether the server answered before it was cut.
    `_level_and_stop_reason_from_output_line` asks it for each line of the kind CONNECTION_LOST that a request owns.
    On `True` the line shows REACHED with FAILED, resting on this rule. On `False` it shows EXECUTED with FAILED.
    A use is such a line of a request.

    Provisional. No earlier code chose. REACHED is taken as assumed, since the connection that the trajectory shows went further than the run alone.
    """
    use_counts[treat_lost_connection_as_after_server_answer.__name__] += 1
    return True
