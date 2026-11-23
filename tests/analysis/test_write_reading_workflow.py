"""Test the workflow script of `analysis/write_reading_workflow.py` on made-up readings."""

import json
import re
from pathlib import Path

import pytest
from analysis_modules import analysis_module

reading_prompt = analysis_module("reading_prompt")
reading_groups = analysis_module("reading_groups")
write_reading_workflow = analysis_module("write_reading_workflow")

ReadingGroup = reading_groups.ReadingGroup
OUT_DIR = Path("/out")


def made_up_reading(trial_id, reader_index, reading_group, commands=("npx",)):
    return {
        "trial_id": trial_id,
        "reader_index": reader_index,
        "reading_group": reading_group.value,
        "label": f"task {reading_group} {trial_id} reader {reader_index}",
        "prompt": "not embedded",
        "schema": reading_prompt.report_schema_of(reading_group, list(commands)),
    }


READINGS = [
    made_up_reading("t1", 0, ReadingGroup.REQUESTED_AND_SOLVED),
    made_up_reading("t1", 1, ReadingGroup.REQUESTED_AND_SOLVED),
    made_up_reading("t2", 0, ReadingGroup.REQUESTED_AND_SOLVED),
    made_up_reading("t3", 0, ReadingGroup.SOLVED_WITHOUT),
    made_up_reading("t4", 0, ReadingGroup.UNCONFIRMED_COMMAND, ("lake build",)),
    made_up_reading("t5", 0, ReadingGroup.UNCONFIRMED_COMMAND, ("npx",)),
]


def constant_of(text: str, name: str):
    """Read the JSON value of `const <name> = ...` up to the next `const`."""
    match = re.search(
        rf"^const {name} = (.*?)\n(?=const )", text, re.DOTALL | re.MULTILINE
    )
    assert match is not None
    return json.loads(match.group(1))


def test_the_script_starts_with_meta_and_gives_every_reading_its_schema_and_prompt_path():
    text = write_reading_workflow.reading_workflow_text_of(READINGS, OUT_DIR)

    assert text.startswith("export const meta = {\n  name: 'read-trajectories',")
    schemas = constant_of(text, "SCHEMAS")
    workflow_readings = constant_of(text, "READINGS")
    assert len(schemas) == 4
    for reading, workflow_reading in zip(READINGS, workflow_readings, strict=True):
        assert schemas[workflow_reading["schema_key"]] == reading["schema"]
        assert workflow_reading["prompt_path"] == (
            f"/out/trials/{reading['trial_id']}/work_{reading['reader_index']}/prompt.txt"
        )
    labels = [r["label"] for r in workflow_readings]
    assert len(set(labels)) == len(labels)
    assert "not embedded" not in text
    assert not re.search(r"Date\.now|Math\.random|require\(|process\.", text)


def test_two_readings_with_one_label_or_two_schemas_under_one_key_fail():
    with pytest.raises(ValueError):
        write_reading_workflow.reading_workflow_text_of(
            [READINGS[0], {**READINGS[1], "label": READINGS[0]["label"]}], OUT_DIR
        )
    with pytest.raises(ValueError):
        write_reading_workflow.reading_workflow_text_of(
            [READINGS[0], {**READINGS[2], "schema": READINGS[3]["schema"]}], OUT_DIR
        )
