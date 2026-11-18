"""Read the package names in a text of an output line or a request target, without versions and in one spelling, so that the names a line gives can be compared with the package a request asks for.

The spelling is that of PEP 503, i.e. lowercase with each run of `-`, `_` and `.` as one `-`, so that `Typing_Extensions` in `pip install Typing_Extensions` and `typing-extensions` in `Successfully installed typing-extensions-4.12.2` are the same name.
"""

import re

from tb_internet_use.network_request_result.model import UnreadablePackageNamesText

# A wheel or source archive file or its metadata, whose name ends at the first dash before a digit, e.g. `requests-2.32.3-py3-none-any.whl.metadata`.
_ARCHIVE_FILE = re.compile(r"^(.+?)-\d.*\.(?:whl|tar\.gz|zip|tgz)\b")
# Where a version, an extra, an architecture or a list separator starts after a name, e.g. `==` in `requests==2.0`, `[` in `uvicorn[standard]` or `:` in `curl:amd64`.
_AFTER_NAME = re.compile(r"[=<>!~;@\[:,()]")
# A version after a dash at the end of a name, e.g. `-2.32.3` in `requests-2.32.3`.
# A dash before a digit inside a name stays, e.g. in the apt package `openjdk-17-jdk`.
_DASHED_VERSION_AT_END = re.compile(r"-\d[\w.+]*$")
# Runs of separators that PEP 503 treats as one, e.g. `_` and `.` in `Typing_Extensions`.
_SEPARATORS = re.compile(r"[-_.]+")
# A comma that starts another name rather than another version clause, e.g. in `a,b` but not in `requests>=2,<3`.
_COMMA_BEFORE_ANOTHER_NAME = re.compile(r",[^=<>!~]")


def parse_package_names_text(
    package_names_text: str,
) -> frozenset[str] | UnreadablePackageNamesText:
    """Read the package names in a text of words such as `Requests==2.0` or `requests-2.32.3-py3-none-any.whl`, one name for each word.

    The text is unreadable when it holds no word or a word holds no name, e.g. `==2.0`, since leaving that word out would compare the other names as if they were all of the text.
    A word that joins names with a comma, e.g. `a-1.0,b-2.0`, is unreadable for the same reason, since only its first name would be read.
    """
    package_names: set[str] = set()
    for word in package_names_text.split():
        package_name = _package_name_of(word)
        if not package_name:
            return UnreadablePackageNamesText()
        package_names.add(package_name)
    if not package_names:
        return UnreadablePackageNamesText()
    return frozenset(package_names)


def _package_name_of(word: str) -> str:
    """Find the package name at the start of one word in the PEP 503 spelling, keeping an npm scope, e.g. `@types/node` for `@types/node@20`, or "" when the word holds no name or more than one."""
    if _COMMA_BEFORE_ANOTHER_NAME.search(word):
        return ""
    scope = ""
    if word.startswith("@") and "/" in word:
        scope_name, word = word.split("/", 1)
        scope = scope_name.lower() + "/"
    archive_file_match = _ARCHIVE_FILE.match(word)
    if archive_file_match:
        name = archive_file_match.group(1)
    else:
        name = _DASHED_VERSION_AT_END.sub("", _AFTER_NAME.split(word, maxsplit=1)[0])
    if not name:
        return ""
    return scope + _SEPARATORS.sub("-", name).lower()
