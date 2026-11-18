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

    It is asked only for the forms SINGLE_LABEL and TEMPLATED, and a DOTTED_NAME raises `ValueError`, since `treat_dotted_host_name_as_public` decides that form.
    It returns whether such a URL in the words of a program without a row, in the strings of a code call without a row, or in code outside every call gives an uncertain request.
    On `True` it does, and the request counts only toward the upper bound. On `False` it gives no request, which lowers the upper bound.
    A use is such a host name.

    Provisional. The earlier code made no choice, and an uncertain request keeps the lower bound true while dropping it would lower the upper bound.
    """
    if unknown_host_name_scope.reason == UnknownHostNameScopeReason.DOTTED_NAME:
        raise ValueError(
            "a dotted host name is decided by treat_dotted_host_name_as_public"
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
    It returns the values that each give a request, here all of them, so the requests may count targets that never ran and the lower bound may be too high.
    Were it to return no value, the word would give one request whose target is unknown.
    A use is such a target word.

    Provisional. It keeps the choice of the earlier code, which made a target of each value.
    """
    use_counts[treat_values_outside_their_for_loop_as_one_request_each.__name__] += 1
    return variable_values.values
