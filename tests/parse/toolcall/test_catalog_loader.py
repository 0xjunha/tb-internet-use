"""Check the catalog loader and the labels in the real catalog."""

from dataclasses import fields
from pathlib import Path

import pytest

from tb_internet_use.parse.toolcall.catalog_loader import (
    ACTION_CLASSES,
    DEFERRED,
    ToolLabel,
    load_catalog,
)
from tb_internet_use.parse.toolcall.model import HarnessTool

_HEADER = "harness,tool,action_type,arg_name,action_field\n"


def _write_catalog(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "catalog.csv"
    path.write_text(_HEADER + rows)
    return path


def test_load_catalog_merges_rows_and_leaves_out_unmapped_args(tmp_path):
    path = _write_catalog(
        tmp_path,
        "h,t,PollAction,chars,input\n"
        "h,t,PollAction,session_id,handles\n"
        "h,t,PollAction,yield_time_ms,\n",
    )

    assert load_catalog(path) == {
        HarnessTool("h", "t"): ToolLabel(
            "PollAction", {"chars": "input", "session_id": "handles"}
        )
    }


def test_load_catalog_rejects_conflicting_action_types(tmp_path):
    path = _write_catalog(tmp_path, "h,t,OtherAction,a,\nh,t,UnknownAction,b,\n")

    with pytest.raises(ValueError, match="conflicting action types"):
        load_catalog(path)


def test_catalog_action_types_are_known():
    allowed = {DEFERRED, *ACTION_CLASSES}  # an empty label is not allowed either

    for tool, label in load_catalog().items():
        assert label.action_type in allowed, tool


def test_catalog_fields_exist_on_their_action_type():
    for tool, label in load_catalog().items():
        action_class = ACTION_CLASSES.get(label.action_type)
        # A Deferred tool has no Action class, so it can map no fields.
        allowed = {f.name for f in fields(action_class)} if action_class else set()

        assert set(label.arg_fields.values()) <= allowed, tool
