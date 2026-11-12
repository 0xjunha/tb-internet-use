"""Normalize package names, so that the packages a request asks for can be compared with those an output line names."""

import re

# A wheel or source archive file or its metadata, whose name ends at the first dash before a digit, e.g. `requests-2.32.3-py3-none-any.whl.metadata`.
_ARCHIVE_FILE = re.compile(r"^(.+?)-\d.*\.(?:whl|tar\.gz|zip|tgz)\b")
# Where a version, an extra, an architecture or a list separator starts after a name, e.g. == in `requests==2.0`.
_AFTER_NAME = re.compile(r"[=<>!~;@\[:,()]")
# A version after a dash at the end of a name, e.g. -2.32.3 in `requests-2.32.3`.
# A dash before a digit inside a name stays, e.g. in the apt package `openjdk-17-jdk`.
_DASHED_VERSION_AT_END = re.compile(r"-\d[\w.+]*$")
# Runs of separators that package indexes treat as one, e.g. `_` and `.` in `Typing_Extensions`.
_SEPARATORS = re.compile(r"[-_.]+")


def normalized_package_names(text: str) -> frozenset[str]:
    """Normalize the package names in words such as `Requests==2.0` or `requests-2.32.3-py3-none-any.whl`."""
    return frozenset(name for word in text.split() if (name := _package_name(word)))


def _package_name(word: str) -> str:
    """Normalize the package name at the start of one word, keeping an npm scope, e.g. `@types/node` for `@types/node@20`."""
    scope = ""
    if word.startswith("@") and "/" in word:
        scope_name, word = word.split("/", 1)
        scope = scope_name.lower() + "/"
    archive = _ARCHIVE_FILE.match(word)
    if archive:
        name = archive.group(1)
    else:
        name = _DASHED_VERSION_AT_END.sub("", _AFTER_NAME.split(word, maxsplit=1)[0])
    return scope + _SEPARATORS.sub("-", name).lower() if name else ""
