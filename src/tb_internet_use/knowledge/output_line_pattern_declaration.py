"""Define the types that output line patterns are declared in, and match one output line against a table of them.

A table is ordered and the first pattern that matches a line gives its meaning, so a specific pattern comes before a general one.
For example `curl: (6) Could not resolve host: a.org` matches a pattern that reads the host and a later one that only sees `curl: (6)`, and only the first keeps the host.
"""

import itertools
import re
from dataclasses import dataclass, field

from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    OutputLineMeaning,
    PrintingProgram,
)

# The names of the groups that fill the fields of an `OutputLineMeaning`, each a field of the same name.
_MEANING_GROUP_NAMES = (
    "host_name_text",
    "package_names_text",
    "missing_program_word",
    "status_code",
)
# A named group whose name is one of `_MEANING_GROUP_NAMES`, e.g. `(?P<host_name_text>`.
_MEANING_GROUP = re.compile(rf"\(\?P<({'|'.join(_MEANING_GROUP_NAMES)})>")
# Any named group, e.g. `(?P<status_code3>`.
_NAMED_GROUP = re.compile(r"\(\?P<\w+>")
# The number at the end of a group name that `OutputLinePattern` adds to keep names unique, e.g. 0 in `host_name_text0`.
_GROUP_NUMBER = re.compile(r"\d+$")


@dataclass(frozen=True, slots=True)
class OutputLinePattern:
    """Pattern of one kind of output line, declared in an `OutputLinePatternTable` and matched by `NetworkRequestResultKnowledge.output_line_meaning`.

    An alternative names a group after the field of `OutputLineMeaning` that it fills, e.g. `(?P<host_name_text>[\\w.-]+\\.\\w+)`.
    Alternatives of one pattern may use the same group name, since each group gets a number.
    """

    # The name that the uses of the pattern and its row in the review record carry, e.g. `pip_already_satisfied`.
    name: str
    kind: OutputLineKind
    printing_programs: frozenset[PrintingProgram]
    # Programs outside `printing_programs` print the same line too, e.g. `Connection refused`.
    is_printed_by_other_programs_too: bool
    # Regexes of which any one makes a line of this kind, searched anywhere in the line.
    alternatives: tuple[str, ...]
    # The alternatives joined into one regex, with numbered group names.
    regex: re.Pattern[str] = field(init=False)

    def __post_init__(self) -> None:
        numbers = itertools.count()
        object.__setattr__(
            self,
            "regex",
            re.compile(
                _MEANING_GROUP.sub(
                    lambda match: f"(?P<{match.group(1)}{next(numbers)}>",
                    "|".join(self.alternatives),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class OutputLinePatternTable:
    """Ordered output line patterns for one kind of result, e.g. program output, in which the first pattern that matches a line gives its meaning."""

    # The name that the uses of its patterns and the review record carry, e.g. `program_output`.
    name: str
    patterns: tuple[OutputLinePattern, ...]
    # All patterns as one regex without named groups, to skip quickly a line that no pattern matches.
    any_pattern_regex: re.Pattern[str] = field(init=False)

    def __post_init__(self) -> None:
        names = [pattern.name for pattern in self.patterns]
        if len(set(names)) != len(names):
            raise ValueError(f"two patterns of {self.name} have the same name")
        sources = (
            _NAMED_GROUP.sub("(?:", pattern.regex.pattern) for pattern in self.patterns
        )
        object.__setattr__(
            self,
            "any_pattern_regex",
            re.compile("|".join(f"(?:{source})" for source in sources)),
        )

    def matched_output_line_pattern_of(
        self, line: str
    ) -> MatchedOutputLinePattern | None:
        """Find the first pattern that matches a line, with the meaning it gives the line, or None when no pattern matches."""
        if self.any_pattern_regex.search(line) is None:
            return None
        for pattern in self.patterns:
            match = pattern.regex.search(line)
            if match is not None:
                return MatchedOutputLinePattern(
                    pattern, _output_line_meaning_from(pattern, match)
                )
        return None


@dataclass(frozen=True, slots=True)
class MatchedOutputLinePattern:
    """Pattern that matched an output line first and the meaning it gives the line, returned by `OutputLinePatternTable.matched_output_line_pattern_of`."""

    output_line_pattern: OutputLinePattern
    output_line_meaning: OutputLineMeaning


def _output_line_meaning_from(
    pattern: OutputLinePattern, match: re.Match[str]
) -> OutputLineMeaning:
    """Make the meaning of a line from the pattern that matched it, with the text of each group as the line writes it and the status code as a number."""
    texts = {
        _GROUP_NUMBER.sub("", name): text
        for name, text in match.groupdict().items()
        if text
    }
    status_code_text = texts.get("status_code")
    return OutputLineMeaning(
        kind=pattern.kind,
        printing_programs=pattern.printing_programs,
        is_printed_by_other_programs_too=pattern.is_printed_by_other_programs_too,
        host_name_text=texts.get("host_name_text"),
        package_names_text=texts.get("package_names_text"),
        missing_program_word=texts.get("missing_program_word"),
        status_code=None if status_code_text is None else int(status_code_text),
    )
