"""Decide whether two path strings in a trial can name the same file, without knowing each call's working directory.

Calls name one file in several ways, e.g. `fetch.log` after `cd /app` and `/app/fetch.log` in a later read.
"""

import re

# A leading component whose directory the text does not show, e.g. `$LOG` in `$LOG/out`, `~` or `..`.
_UNKNOWN_DIRECTORY = re.compile(r"^(?:\$|~|\.\.$)")


def can_name_same_file(path: str, other_path: str) -> bool:
    """Check whether two path strings can name one file, e.g. `fetch.log` and `/app/fetch.log`.

    Equal strings can, even when a variable hides the whole path, e.g. `$LOG` in `curl u > $LOG; tail $LOG`.
    Two absolute paths must be equal. Otherwise the relative one must end the other by whole components, never by the base name alone.
    """
    if path == other_path:
        return True
    is_absolute, components = _path_components(path)
    other_is_absolute, other_components = _path_components(other_path)
    if not components or not other_components:
        return False
    if is_absolute and other_is_absolute:
        return components == other_components
    # The relative path must be the ending, e.g. fetch.log of /app/fetch.log.
    if is_absolute:
        return _ends_with(components, other_components)
    if other_is_absolute:
        return _ends_with(other_components, components)
    shorter, longer = sorted((components, other_components), key=len)
    return _ends_with(longer, shorter)


def _path_components(path: str) -> tuple[bool, tuple[str, ...]]:
    """Split a path into whether it is absolute and its components, without `.`, empty ones and `x/..`.

    Leading components of an unknown directory are dropped, so the path counts as relative, e.g. out for `$LOG/out`.
    """
    is_absolute = path.startswith("/")
    components: list[str] = []
    for component in path.split("/"):
        if component in ("", "."):
            continue
        if component == ".." and components and components[-1] != "..":
            components.pop()
        else:
            components.append(component)
    while components and _UNKNOWN_DIRECTORY.match(components[0]):
        components.pop(0)
        is_absolute = False
    return is_absolute, tuple(components)


def _ends_with(components: tuple[str, ...], ending: tuple[str, ...]) -> bool:
    """Check whether a path's components end with the given components."""
    return len(ending) <= len(components) and components[-len(ending) :] == ending
