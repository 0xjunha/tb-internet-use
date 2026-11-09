"""Load the labeled harness tool catalog and build Actions from its labels."""

import csv
import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from tb_internet_use.toolcall.model import (
    Action,
    ExecutionHandleKind,
    HarnessTool,
    handles_from_ids,
    string_tuple,
)

ACTION_CLASSES = {cls.__name__: cls for cls in get_args(Action.__value__)}
CATALOGS_DIR = Path(__file__).parent / "catalogs"
CATALOG_CSV = CATALOGS_DIR / "harness_tool_catalog.csv"
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


@functools.cache
def tool_catalog() -> dict[HarnessTool, ToolLabel]:
    """The committed catalog, read once."""
    return load_catalog()


def _field_value(field_name: str, value: Any) -> Any:
    """Turn an argument in the trajectory into the type of its Action field."""
    match field_name:
        case "queries" | "urls":
            return string_tuple(value)
        case "handles":
            return handles_from_ids(ExecutionHandleKind.UNKNOWN, value)
        case "input":
            return value or None
        case "offset" | "limit":
            return value if isinstance(value, int) else None
        case _:
            return value


def action_from_label(label: ToolLabel, args: dict[str, Any]) -> Action:
    """Build a tool's Action from the arguments that the catalog maps."""
    fields = {
        label.arg_fields[arg_name]: _field_value(label.arg_fields[arg_name], value)
        for arg_name, value in args.items()
        if arg_name in label.arg_fields
    }
    return ACTION_CLASSES[label.action_type](**fields)
