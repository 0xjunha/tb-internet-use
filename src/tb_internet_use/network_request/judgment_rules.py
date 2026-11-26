"""Decide what the trajectory, the standards and the request catalogs do not settle about network requests, one named rule per situation, e.g. whether the host `files.acme.org` is public.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, `parse_host_name` reads `localhost` as local and `example.com` as reserved by the standards, but no standard says whether `files.acme.org` or `db` is on the internet, and only a rule says how they are read.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a `NetworkRequest`.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter
from collections.abc import Callable

from tb_internet_use.expanded_tool_call.model import VariableValues
from tb_internet_use.network_request.model import (
    HostNameScope,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
)
from tb_internet_use.network_request.parse_url import parse_url
from tb_internet_use.tool_call.model import WebFindAction

# The hosts whose URLs code writes as names of XML namespaces and schemas.
_NAMESPACE_HOST_NAMES = frozenset(
    {"schemas.openxmlformats.org", "www.w3.org", "purl.org", "json-schema.org"}
)


def treat_dotted_host_name_as_public(
    unknown_host_name_scope: UnknownHostNameScope, *, use_counts: Counter[str]
) -> HostNameScope | UnknownHostNameScope:
    """Read a host name with a dot that the standards do not settle as public, e.g. `files.acme.org`, which may also be a name inside the task's network.

    It is asked for the scope that `parse_host_name` gives a host name when the standards do not settle it.
    For the form DOTTED_NAME it returns PUBLIC, so the host counts as public wherever a public host is asked for.
    For any other form it returns the scope it was given and is not counted, since it does not decide that name.
    Were it to return the scope it was given for DOTTED_NAME too, the name would stay unknown, so a URL with it in the words of a program without a row would give no uncertain request and a request to it would not be known to be internet use.
    A use is such a dotted name.

    Provisional. It keeps the choice of the earlier code, which read a name with a dot that is no local or reserved name as public.
    """
    if unknown_host_name_scope.reason != UnknownHostNameScopeReason.DOTTED_NAME:
        return unknown_host_name_scope
    use_counts[treat_dotted_host_name_as_public.__name__] += 1
    return HostNameScope.PUBLIC


def treat_single_label_or_templated_host_name_as_possibly_public(
    unknown_host_name_scope: UnknownHostNameScope, *, use_counts: Counter[str]
) -> bool:
    """Read a host name without a dot or with a template as one that may be public where a visible public URL is asked for, e.g. `db` in `http://db:5432` or `$HOST` in `https://$HOST/x`.

    It is asked only for the forms SINGLE_LABEL and TEMPLATED. A DOTTED_NAME raises `ValueError`, since `treat_dotted_host_name_as_public` decides that form, and so does an EMPTY_LABEL, which the user decided on 2026-11-21.
    It returns whether such a URL in the words of a program without a row, in the strings of a code call without a row, or in code outside every call gives an uncertain request.
    On `True` it does. The request then counts only toward the upper bound for a templated name, and in no bound for a name without a dot, which `treat_single_label_host_name_as_not_internet_use` reads as no internet use. On `False` it gives no request.
    A use is such a host name.

    Provisional. The earlier code made no choice, and an uncertain request keeps the lower bound true while dropping it would lower the upper bound for a templated name.
    """
    if unknown_host_name_scope.reason not in (
        UnknownHostNameScopeReason.SINGLE_LABEL,
        UnknownHostNameScopeReason.TEMPLATED,
    ):
        raise ValueError(
            f"a host name of the form {unknown_host_name_scope.reason} is not decided here"
        )
    use_counts[
        treat_single_label_or_templated_host_name_as_possibly_public.__name__
    ] += 1
    return True


def treat_values_outside_their_for_loop_as_one_request_each(
    variable_values: VariableValues, *, use_counts: Counter[str]
) -> tuple[str, ...]:
    """Read each value of a variable that the command runs with only one of as the value of a request of its own, e.g. `pkg1` and `pkg2` for `pip install pkg$A` after `A=1` in one if branch and `A=2` in the other.

    The trial does not show which of the values the command ran with, since `takes_each_value_in_turn` is False.
    `extract_network_request_targets` asks it for a target word whose only variable of several values is such a variable.
    It returns the values that each give a request, here none, so the word gives one request whose target is unknown, with the reason `VALUE_SET_AT_RUN_TIME`, and no host is read from it.
    Were it to return all the values, each would give a request of its own, so the requests may count targets that never ran and the lower bound may be too high.
    A use is such a target word.

    Decided. The user decided on 2026-11-24 to return no value, since the trial does not show which value the command ran with, e.g. `U` of `curl -s $U -o x` after `U=http://localhost:8000/x` in one if branch and `U=https://a.org/x` in the other. The earlier code made a target of each value.
    """
    use_counts[treat_values_outside_their_for_loop_as_one_request_each.__name__] += 1
    return ()


def treat_url_of_namespace_host_as_no_target(
    url: str, *, use_counts: Counter[str]
) -> bool:
    """Read a URL in code whose host only names XML namespaces and schemas, and whose last path part has no dot, as a name and not as a target, e.g. `http://www.w3.org/2000/svg`.

    The hosts are `schemas.openxmlformats.org`, `www.w3.org`, `purl.org` and `json-schema.org`.
    `extract_code_network_requests` asks it for each URL that would give an uncertain request, i.e. a URL in a call without a row, in a program run by code or outside every call.
    On `True` the URL gives no request. On `False` it goes on to the question whether its host may be public, so `http://www.w3.org/2000/svg` would give an uncertain request.
    A last path part with a dot names a file, e.g. `http://www.w3.org/2001/XMLSchema.xsd`, which code may fetch, so it gives `False` and is not counted.
    A use is such a namespace URL.

    Provisional. It keeps the choice of the earlier code, which read these URLs as schema names, since that a host's URLs are only names cannot be checked against a manual.
    """
    if parse_url(url) not in _NAMESPACE_HOST_NAMES:
        return False
    if "." in url.rstrip("/").rsplit("/", 1)[-1]:
        return False
    use_counts[treat_url_of_namespace_host_as_no_target.__name__] += 1
    return True


def treat_web_find_as_request(
    web_find_action: WebFindAction, *, use_counts: Counter[str]
) -> tuple[str | None, ...]:
    """Read a web find, which looks for text in a page that a web tool opened, as one confirmed request per URL it names, or one without a target when it names none, e.g. one for `WebFindAction(urls=("https://a.org/guide",))`.

    `extract_web_tool_network_requests` asks it for each web find action and makes one request per value it returns, `None` being a request without a target.
    It returns the URLs, or `(None,)` for a find without one, so a find counts like a fetch although the harness may search a page it already holds without a new request.
    Were it to return `()`, a find would give no request.
    A use is such a find action.

    Provisional. It keeps the choice of the earlier code, which made a request of each web find.
    """
    use_counts[treat_web_find_as_request.__name__] += 1
    return web_find_action.urls or (None,)


def treat_call_name_that_ends_with_catalog_name_as_that_call(
    call_name: str, has_row: Callable[[str], bool], *, use_counts: Counter[str]
) -> str | None:
    """Read a dotted call name in code that has no row of the code call catalog as the call of the longest end of it that has one, e.g. `urlopen` for `urllib.request.urlopen` or `fetch` for `mylib.fetch` in JavaScript.

    `extract_code_network_requests` asks it only for a call name without a row, with `has_row` telling whether a name has a row of the code language.
    It drops the leading parts one by one and returns the first shorter name that has a row, so `mylib.fetch` takes the row of `fetch` although `mylib` may be any library.
    It returns None when no shorter name has a row, and the call stays a call without a row.
    Were it to return None always, `urllib.request.urlopen(u)` would be a call without a row, giving an uncertain request for a public URL and none for a URL the code builds.
    A use is such a call name that it maps to a shorter one.

    Provisional. It keeps the choice of the earlier code, whose patterns matched a call by its last name, e.g. `urlopen(` and `fetch(`.
    """
    name_parts = call_name.split(".")
    for start in range(1, len(name_parts)):
        shorter_call_name = ".".join(name_parts[start:])
        if has_row(shorter_call_name):
            use_counts[
                treat_call_name_that_ends_with_catalog_name_as_that_call.__name__
            ] += 1
            return shorter_call_name
    return None


def treat_call_of_module_name_that_code_binds_without_import_as_call_without_row(
    module_name: str,
    imported_module_names: frozenset[str],
    names_bound_by_assignment_parameter_or_loop: frozenset[str],
    *,
    use_counts: Counter[str],
) -> bool:
    """Read a Python call whose row of the code call catalog names a module that the code text binds to something else and does not import as a call without a row, e.g. `requests.get(rid)` after `requests = {}`.

    `extract_code_network_requests` asks it for every Python call whose row names a module in `module_name`, whatever the effect of the row, with the names that `parse_code` found imported as a module and those it found bound by an assignment, a parameter or a loop.
    On `True` the call takes `UnknownCodeCallLabel`, so a URL in its strings that may be public gives an uncertain request, and a call without such a URL gives none, e.g. `prev = requests.get(rid)`.
    On `False` the call keeps its row, e.g. `requests.get(u)` after `import requests`, or `subprocess.run(cmd)` after `from helpers import *`, whose text neither imports nor binds `subprocess`.
    Were it to return `False` always, a dict named `requests` would give confirmed requests of the library with a target built in code. Were it to set aside every call whose module is not imported, it would also drop real calls of a module that comes from a star import, from `__import__` in another file or from a part of a file, and lower the upper bound.
    A use is such a call of a bound name without the import.

    Decided. The user decided it on 2026-11-22 and narrowed it the same day to names that the text binds, since a call of a module name that the text binds to something else is no call of the library, while one that the text neither imports nor binds may still be.
    """
    if (
        module_name in imported_module_names
        or module_name not in names_bound_by_assignment_parameter_or_loop
    ):
        return False
    use_counts[
        treat_call_of_module_name_that_code_binds_without_import_as_call_without_row.__name__
    ] += 1
    return True
