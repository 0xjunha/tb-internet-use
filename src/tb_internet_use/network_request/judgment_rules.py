"""Decide what the trajectory, the standards and the request catalogs do not settle about network requests, one named rule per situation, e.g. whether the host `files.acme.org` is public.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, `parse_host_name` reads `localhost` as local and `example.com` as reserved by the standards, but no standard says whether `files.acme.org` or `db` is on the internet, and only a rule says how they are read.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a `NetworkRequest`.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter

from tb_internet_use.expanded_tool_call.model import VariableValues
from tb_internet_use.network_request.model import (
    HostNameScope,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
)
from tb_internet_use.network_request.parse_url import parse_url

# The hosts whose URLs code writes as names of XML namespaces and schemas.
_NAMESPACE_HOST_NAMES = frozenset(
    {"schemas.openxmlformats.org", "www.w3.org", "purl.org", "json-schema.org"}
)


def treat_dotted_host_name_as_public(
    unknown_host_name_scope: UnknownHostNameScope, *, use_counts: Counter[str]
) -> HostNameScope | UnknownHostNameScope:
    """Read a host name with a dot that the standards do not settle as public, e.g. `files.acme.org`, which may also be a name inside the task's network.

    It is asked for the scope that `parse_host_name` gives a host name when the standards do not settle it.
    For the form DOTTED_NAME it returns PUBLIC, so the host counts as public wherever a public host is asked for. `export_rows` still counts a request to it toward the lower bound of internet use only when `public_hosts.csv` has a row of the name.
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


def treat_values_outside_their_for_loop_as_unknown_target(
    variable_values: VariableValues, *, use_counts: Counter[str]
) -> tuple[str, ...]:
    """Read a target word whose variable has several values that the command runs with only one of as a target that is not known, e.g. `pip install pkg$A` after `A=1` in one if branch and `A=2` in the other.

    The trial does not show which of the values the command ran with, since `takes_each_value_in_turn` is False.
    `extract_network_request_targets` asks it for a target word whose only variable of several values is such a variable.
    It returns the values that each give a request, here none, so the word gives one request whose target is unknown, with the reason `VALUE_SET_AT_RUN_TIME`, and no host is read from it.
    Were it to return all the values, each would give a request of its own, so the requests may count targets that never ran and the lower bound may be too high.
    A use is such a target word.

    Decided. The user decided on 2026-11-24 to return no value, since the trial does not show which value the command ran with, e.g. `U` of `curl -s $U -o x` after `U=http://localhost:8000/x` in one if branch and `U=https://a.org/x` in the other. The earlier code made a target of each value.
    """
    use_counts[treat_values_outside_their_for_loop_as_unknown_target.__name__] += 1
    return ()


def treat_url_of_namespace_host_as_no_target(
    url: str, *, use_counts: Counter[str]
) -> bool:
    """Read a URL in code whose host only names XML namespaces and schemas, and whose text after the last `/` has no dot, as a name and not as a target, e.g. `http://www.w3.org/2000/svg`.

    The hosts are `schemas.openxmlformats.org`, `www.w3.org`, `purl.org` and `json-schema.org`, compared as written, so `http://WWW.W3.ORG/2000/svg` is no namespace URL.
    `extract_code_network_requests` asks it for each URL with a host that would give an uncertain request, i.e. a URL in a call without a row, in a call that holds a target that no sending call reads, in a call that runs a program without a row or whose program it cannot find, or in code outside every call.
    On `True` the URL gives no request. On `False` it goes on to the question whether its host may be public, so `http://www.w3.org/2000/svg` would give an uncertain request.
    A last path part with a dot names a file, e.g. `http://www.w3.org/2001/XMLSchema.xsd`, which code may fetch, so it gives `False` and is not counted.
    The text after the last `/` holds the query and the fragment, and it is the host for a URL without a path, so these give `False` too, e.g. `http://www.w3.org`, `https://json-schema.org/`, the version `http://purl.org/dc/elements/1.1/` or `...svg#a.b`, and stay uncertain requests.
    A use is such a namespace URL.

    Provisional. It keeps the choice of the earlier code, which read these URLs as schema names, since that a host's URLs are only names cannot be checked against a manual.
    """
    if parse_url(url) not in _NAMESPACE_HOST_NAMES:
        return False
    if "." in url.rstrip("/").rsplit("/", 1)[-1]:
        return False
    use_counts[treat_url_of_namespace_host_as_no_target.__name__] += 1
    return True


def treat_web_find_as_uncertain_request(*, use_counts: Counter[str]) -> bool:
    """Read a web find, which looks for text in a page that a web tool opened, as uncertain requests, e.g. an uncertain request of https://a.org/guide for `WebFindAction(urls=("https://a.org/guide",))`.

    The harness may search a page it already holds without a new request, and the trajectory does not show whether it fetched the page again.
    `extract_web_tool_network_requests` asks it for each web find action, which gives one request per URL it names, or one without a target when it names none.
    On `True` those requests are uncertain with the reason `FINDS_TEXT_IN_OPENED_PAGE`, so they count toward the upper bound only. On `False` they are confirmed, like those of a web fetch.
    A use is such a find action.

    Provisional. The earlier code made a confirmed request of each web find, which counts a find that searched a page already held toward the lower bound. The review of 2026-11-24 recommended to make them uncertain, and the user has not yet confirmed it.
    """
    use_counts[treat_web_find_as_uncertain_request.__name__] += 1
    return True


def treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name(
    call_name: str, *, use_counts: Counter[str]
) -> bool:
    """Read a call in code whose name ends with the name of a row of the code call catalog, and has no row of its own or a first name part that the code text binds otherwise than by an import, as an uncertain call of that row, e.g. `self.page.goto(u)`, `route.fetch()` in JavaScript, `MyTok.from_pretrained(p)`, `GPT2TokenizerFast.from_pretrained(m)` after `from transformers import GPT2TokenizerFast` or `page.goto(u)` after `page = browser.new_page()`.

    The text does not give the type of the object that the call is made on, or the catalog has no row of the full name that an import gives, so the call may be another function of the same name.
    `extract_code_network_requests` asks it when only an end of the name has a row, of the name as written or of the full name that an import gives its first part, e.g. `page.goto` for `self.page.goto` or `from_pretrained` for `transformers.GPT2TokenizerFast.from_pretrained`. It also asks it when the whole name has a row and the text binds its first name part by an assignment, a parameter or a loop and does not import it, e.g. `page.goto` after `page = browser.new_page()`, when imports bind the first name part to several full names and one of them gives a row, e.g. `requests.get` for `http.get(u)` after `import requests as http` in a `try` and `import httpx as http` in its `except`, and when no full name from imports nor an end of it has a row but the name as written or its end has one, e.g. `fetch` for `fetch(u)` after `const fetch = require("node-fetch")`.
    It is not asked for a row that `treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row` sets aside, nor for a whole name with a row whose first part an import binds or the text neither imports nor binds, e.g. `u.urlopen(x)` after `import urllib.request as u`, `page.goto(u)` alone or `fetch(u)`, which keeps its row.
    On `True` a call whose row sends a request gives an uncertain request with the reason `CALL_NAME_MAY_BE_ANOTHER_FUNCTION`, a call whose row runs a program gives the uncertain requests that any program run by code gives, a call whose row holds a target gives it to the sending call that reads it, and a call whose row sends no request is a call without a row, since another function of that name may send one. On `False` the call takes the row as a call of it, so `self.page.goto(u)` gives a confirmed request.
    Were it to make such a call a call without a row, as the rule did from 2026-11-24, real calls would leave the upper bound, e.g. `globalThis.fetch(u)` or `this.page.goto(u)` with a URL that the code builds.
    A use is such a call name.

    Provisional. The earlier code matched a call by the end of its name and took the row as a call of it, i.e. `False`, which counts a method of any object with that name as a confirmed request. The review of 2026-11-24 made such a call a call without a row, and on 2026-11-25 it became an uncertain call, which keeps it in the upper bound and out of the lower bound. The user has not yet confirmed it.
    """
    use_counts[
        treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name.__name__
    ] += 1
    return True


def treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row(
    first_name_part: str,
    names_bound_by_assignment_parameter_or_loop: frozenset[str],
    *,
    use_counts: Counter[str],
) -> bool:
    """Read a Python call whose row of the code call catalog names a module, and whose first name part the code text binds to something else and does not import, as a call without a row, e.g. `requests.get(rid)` after `requests = {}` or `ctx.requests.get(rid)` where `ctx` is a parameter.

    `extract_code_network_requests` asks it for every Python call whose first name part no import of the text binds, whose whole name with a row the text does not keep, and whose row names a module in `module_name`, whatever the effect of the row, with the names that `parse_code` found bound by an assignment, a parameter or a loop. The row is that of the whole name or of the longest end of it with a row.
    A name that an import of the text binds is not asked about, since the import wins over an assignment. Its call takes the row of the full name that the import gives, e.g. `requests.get(rid)` after `import requests` and `requests = {}`, or an uncertain call of the row of an end of it, e.g. `requests.get(u)` after `from pip._vendor import requests`.
    On `True` the call takes `UnknownCodeCallLabel`, so a URL in its strings that may be public gives an uncertain request, and a call without such a URL gives none, e.g. `prev = requests.get(rid)`.
    On `False` the call keeps its row, e.g. `subprocess.run(cmd)` after `from helpers import *`, whose text neither imports nor binds `subprocess`, or, for a row of an end of its name, goes on to `treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name`, e.g. `foo.requests.get(u)` where nothing binds `foo`.
    Were it to return `False` always, a dict named `requests` would give confirmed requests of the library with a target built in code, and a dict held in an attribute named `requests` would give uncertain ones, e.g. `ctx.requests.get(rid)`. Were it to set aside every call whose module is not imported, it would also drop real calls of a module that comes from a star import, from `__import__` in another file or from a part of a file, and lower the upper bound.
    A use is such a call through a bound name.

    Decided. The user decided it on 2026-11-22 and narrowed it the same day to names that the text binds, since a call of a module name that the text binds to something else is no call of the library, while one that the text neither imports nor binds may still be. On 2026-11-25 it was widened to a row of an end of the name, e.g. `ctx.requests.get(rid)`, since the call is then made on a value that the text binds and not on the module, which the user has not yet confirmed.
    """
    if first_name_part not in names_bound_by_assignment_parameter_or_loop:
        return False
    use_counts[
        treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row.__name__
    ] += 1
    return True
