"""Make the targets of a candidate request from its words, with the hosts and package names they name.

A target can hold a variable, e.g. `pip install $p` in `for p in a b`, so one written word can give a target per value.
"""

import re
from collections.abc import Sequence

from tb_internet_use.callrun.model import VariableValues
from tb_internet_use.callrun.variable_values import filled_word, plain_variable_names
from tb_internet_use.network.hosts import host_from_name, host_name_in_url
from tb_internet_use.network.model import Host
from tb_internet_use.network.package_names import normalized_package_names
from tb_internet_use.program.model import AskedPackagesSource, RequestKind
from tb_internet_use.request.model import RequestTarget
from tb_internet_use.request.target_tables import (
    PROGRAMS_WITH_HOST_AS_EVERY_TARGET,
    PROGRAMS_WITH_HOST_AS_FIRST_TARGET,
    SCHEMELESS_URL_PROGRAMS,
)

# A remote git address without a scheme, e.g. github.com in `git@github.com:org/repo.git`.
# The host needs a user or a dot, so a refspec such as `main:main` in `git fetch origin main:main` is no address.
_SCP_LIKE_ADDRESS = re.compile(r"^(?:[\w.-]+@([\w.-]+)|([\w-]+(?:\.[\w-]+)+)):(?!//)")
# A host at the start of a URL without a scheme, e.g. pypi.org in `pypi.org/simple` or localhost in `localhost:8000/x`.
_SCHEMELESS_HOST = re.compile(r"^([\w.-]+)(?::\d+)?(?:/|$)")
# Targets that name a local path, a URL or an archive instead of a package, e.g. `./dist/x.whl`, `.` or `.[dev]`.
_PATH_OR_URL = re.compile(r"^(?:[/~]|\.\.?(?:/|\[|$))|://|\.(?:whl|zip|tar\.gz|tgz)$")


def request_targets(
    target_words: Sequence[str], variable_values: Sequence[VariableValues]
) -> tuple[RequestTarget, ...]:
    """Make the targets of written words, one per value of a variable with known values.

    A word with a variable of unknown value, or with two variables of several values, gives one target without a value.
    A loop variable gives one target per item even when a command substitution leaves the value unknown, since the command runs once per item, e.g. three targets without a value for `https://$u/$(date +%s)` over three items.
    """
    values_of_name = {values.name: values for values in variable_values}
    targets: list[RequestTarget] = []
    for word in target_words:
        names = plain_variable_names(word)
        if not any(c in word for c in "$`"):
            targets.append(RequestTarget(word, word, None))
            continue
        known = [values_of_name[name] for name in names if name in values_of_name]
        # Variables whose values give one target each, those with several values, or else the one loop variable of one item.
        multi_valued = [values for values in known if len(values.values) > 1]
        one_item_loops = [values for values in known if values.takes_each_value_in_turn]
        if not multi_valued and len(one_item_loops) == 1:
            multi_valued = one_item_loops
        filled = {
            values.name: values.values[0]
            for values in known
            if values not in multi_valued
        }
        if len(known) < len(names) or len(multi_valued) > 1:
            targets.append(RequestTarget(word, None, None))
        elif not multi_valued:
            targets.append(RequestTarget(word, _filled_or_none(word, filled), None))
        else:
            (variable,) = multi_valued
            loop_variable = variable.name if variable.takes_each_value_in_turn else None
            targets += [
                RequestTarget(
                    word,
                    _filled_or_none(word, filled | {variable.name: value}),
                    loop_variable,
                )
                for value in variable.values
            ]
    return tuple(targets)


def request_hosts(
    program_name: str,
    kind: RequestKind,
    targets: Sequence[RequestTarget],
    index_urls: Sequence[str],
) -> tuple[Host, ...]:
    """List the hosts that a command's targets and package index options name, e.g. pypi.org for `pip install -i https://pypi.org/simple x`.

    A host whose name holds a variable stays, with the kind TEMPLATED.
    """
    texts = [
        target.value if target.value is not None else target.written
        for target in targets
    ]
    names = [name for text in (*texts, *index_urls) if (name := host_name_in_url(text))]
    schemeless = [text for text in texts if "://" not in text]
    if kind == RequestKind.GIT:
        names += [
            m.group(1) or m.group(2)
            for text in schemeless
            if (m := _SCP_LIKE_ADDRESS.match(text))
        ]
    elif program_name in SCHEMELESS_URL_PROGRAMS:
        names += [
            m.group(1) for text in schemeless if (m := _SCHEMELESS_HOST.match(text))
        ]
    elif kind == RequestKind.REMOTE_HOST:
        names += _remote_host_names(program_name, schemeless)
    return tuple(dict.fromkeys(host_from_name(name) for name in names))


def asked_package_names(
    asked_packages_source: AskedPackagesSource,
    targets: Sequence[RequestTarget],
    names_packages_in_files: bool,
) -> frozenset[str] | None:
    """Normalize the package names a request asks for, or None when it may ask for packages its targets do not name.

    That is so for a run that reads them from a file or the project, a value the trial does not show, a path, a URL or an archive.
    """
    if asked_packages_source == AskedPackagesSource.NONE:
        return frozenset()
    if asked_packages_source == AskedPackagesSource.FILE_OR_PROJECT or not targets:
        return None
    if names_packages_in_files:
        return None
    values = [target.value for target in targets]
    if any(value is None or _PATH_OR_URL.search(value) for value in values):
        return None
    return normalized_package_names(
        " ".join(value for value in values if value is not None)
    )


def _filled_or_none(word: str, value_of_name: dict[str, str]) -> str | None:
    """Fill in the variables of a word, or None when an expansion is left whose value the trial does not show, e.g. `$(cat f)`."""
    filled = filled_word(word, value_of_name)
    return None if any(c in filled for c in "$`") else filled


def _remote_host_names(program_name: str, target_texts: Sequence[str]) -> list[str]:
    """Find the hosts a direct connection names, e.g. host for `nc host 80` or `rsync f host:/x`, and both for `dig @8.8.8.8 a.org`."""
    if program_name in PROGRAMS_WITH_HOST_AS_EVERY_TARGET:
        return list(target_texts)
    if program_name in PROGRAMS_WITH_HOST_AS_FIRST_TARGET:
        servers = [text[1:] for text in target_texts if text.startswith("@")]
        names = [text for text in target_texts if not text.startswith(("@", "+"))]
        return [_without_user(name) for name in (*servers, *names[:1])]
    # rsync names a remote host as `host:path`.
    return [
        _without_user(text.split(":", 1)[0])
        for text in target_texts
        if ":" in text and not text.startswith(("/", "."))
    ]


def _without_user(address: str) -> str:
    """Drop the user from an address such as `user@host`."""
    return address.rsplit("@", 1)[-1]
