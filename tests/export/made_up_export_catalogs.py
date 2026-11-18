"""Write made-up catalogs of `ExportKnowledge` for the tests of the export package, kept out of conftest.py for the same reason as `made_up_network_request_rows.py`."""

from collections.abc import Sequence
from pathlib import Path

from tb_internet_use.knowledge.export_knowledge import (
    HARNESS_WEB_TOOLS_CSV,
    PROGRAM_PACKAGE_REGISTRIES_CSV,
    PUBLIC_HOSTS_CSV,
)

# The values of `checked_against`, `reviewed` and `note`, from which no answer is made.
_REVIEW_COLUMNS = ",a manual,,"


def write_made_up_export_catalogs(
    catalogs_dir: Path,
    *,
    public_host_rows: Sequence[str],
    harness_web_tool_rows: Sequence[str],
    program_package_registry_rows: Sequence[str],
) -> Path:
    """Write the three export CSVs into a new folder and return the folder, each row given as its columns before `checked_against`, e.g. `pypi.org,package_registry,pypi`."""
    catalogs_dir.mkdir()
    for file_name, header, rows in (
        (
            PUBLIC_HOSTS_CSV,
            "host_name,service,package_registry,checked_against,reviewed,note",
            public_host_rows,
        ),
        (
            HARNESS_WEB_TOOLS_CSV,
            "harness,tool,sender,checked_against,reviewed,note",
            harness_web_tool_rows,
        ),
        (
            PROGRAM_PACKAGE_REGISTRIES_CSV,
            "program_name,subcommand,package_registry,package_registry_host_names,checked_against,reviewed,note",
            program_package_registry_rows,
        ),
    ):
        lines = [header, *(row + _REVIEW_COLUMNS for row in rows)]
        (catalogs_dir / file_name).write_text("\n".join(lines) + "\n")
    return catalogs_dir
