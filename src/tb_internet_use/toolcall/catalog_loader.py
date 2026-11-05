"""Load the labeled harness tool catalog."""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from tb_internet_use.toolcall.model import Action, HarnessTool

ACTION_CLASSES = {cls.__name__: cls for cls in get_args(Action.__value__)}
CATALOG_CSV = Path(__file__).parent / "catalogs" / "harness_tool_catalog.csv"
DEFERRED = "Deferred"  # the converter decides the Action type per call


@dataclass(frozen=True, slots=True)
class ToolLabel:
    """Maps one harness tool to common types."""

    action_type: str  # Action class name, or DEFERRED
    arg_fields: dict[str, str]  # argument name -> Action field


def load_catalog(path: Path = CATALOG_CSV) -> dict[HarnessTool, ToolLabel]:
    """Read the catalog CSV file and return each tool's Action type and argument mapping.

    The CSV has one row per tool argument, so a tool's rows are merged into one ToolLabel.
    Arguments with an empty `action_field` are left out of `arg_fields`.

    Raises ValueError if a tool's rows have different `action_type` values.
    """
    catalog: dict[HarnessTool, ToolLabel] = {}

    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            tool = HarnessTool(row["harness"], row["tool"])
            label = catalog.setdefault(tool, ToolLabel(row["action_type"], {}))
            if label.action_type != row["action_type"]:
                raise ValueError(f"conflicting action types for {tool}")
            if row["action_field"]:
                label.arg_fields[row["arg_name"]] = row["action_field"]

    return catalog
