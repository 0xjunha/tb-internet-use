"""Test the trajectory dump of `analysis/write_reading_materials.py` on made-up trajectories with images, a subagent step, a long result and a subagent trajectory."""

import pytest
from analysis_modules import analysis_module

write_reading_materials = analysis_module("write_reading_materials")
HEAD = write_reading_materials.OBSERVATION_HEAD_CHARACTERS
TAIL = write_reading_materials.OBSERVATION_TAIL_CHARACTERS


def made_up_step(step_id: int, **fields):
    return {"step_id": step_id, "source": "agent", **fields}


def bash_step(step_id: int, command: str, content: object, **fields):
    return made_up_step(
        step_id,
        tool_calls=[
            {
                "tool_call_id": f"call-{step_id}",
                "function_name": "Bash",
                "arguments": {"command": command, "timeout": 60},
            }
        ],
        observation={
            "results": [{"source_call_id": f"call-{step_id}", "content": content}]
        },
        **fields,
    )


def test_a_step_shows_its_message_reasoning_call_arguments_and_result_with_its_sidechain_flag():
    trajectory = {
        "steps": [
            made_up_step(
                1,
                source="user",
                message="Solve the task.",
                extra={"is_sidechain": False},
            ),
            bash_step(
                2,
                "ls\npwd",
                "a.txt",
                message="Look around.",
                reasoning_content="First list files.",
                extra={"is_sidechain": True},
            ),
        ]
    }

    dump = write_reading_materials.trajectory_dump_text_of(trajectory)

    assert dump == (
        "[[[ step_id 1 | source user | is_sidechain false ]]]\n"
        "[[ message ]]\nSolve the task.\n\n"
        "[[[ step_id 2 | source agent | is_sidechain true ]]]\n"
        "[[ message ]]\nLook around.\n"
        "[[ reasoning ]]\nFirst list files.\n"
        "[[ tool call 0: Bash | tool_call_id call-2 ]]\ncommand: ls\npwd\ntimeout: 60\n"
        "[[ observation result 0 | for tool_call_id call-2 ]]\na.txt\n"
    )


def test_images_are_left_out_of_content_lists_and_data_uris():
    image_part = {
        "type": "image",
        "source": {"type": "base64", "data": "iVBORw0KGgo" * 50},
    }
    trajectory = {
        "steps": [
            bash_step(1, "view", [{"type": "text", "text": "plot:"}, image_part]),
            bash_step(2, "cat", "before data:image/png;base64,iVBORw0KGgo= after"),
        ]
    }

    dump = write_reading_materials.trajectory_dump_text_of(trajectory)

    assert "iVBOR" not in dump
    assert "plot:\n[image part left out]" in dump
    assert "before [image data left out] after" in dump


def test_a_long_result_keeps_its_start_and_end_around_a_marker_and_a_long_message_is_kept():
    long_text = "a" * HEAD + "x" * 10 + "z" * TAIL
    trajectory = {"steps": [bash_step(7, "cat big", long_text, message=long_text)]}

    dump = write_reading_materials.trajectory_dump_text_of(trajectory)

    result = dump.split("[[ observation result 0 | for tool_call_id call-7 ]]\n")[1]
    assert result == (
        "a" * HEAD
        + "\n[[ CUT here, 10 characters of this result left out, the whole result is in step_id 7 of trajectory.json ]]\n"
        + "z" * TAIL
        + "\n"
    )
    assert long_text in dump


def test_a_result_of_head_and_tail_length_is_kept_whole():
    text = "a" * (HEAD + TAIL)

    assert write_reading_materials.cut_text_of(text, 1) == text


def test_the_prompt_gives_the_numbers_of_the_cut():
    reading_prompt = analysis_module("reading_prompt")

    assert (
        f"An observation longer than {HEAD + TAIL:,} characters keeps its first {HEAD:,} and its last {TAIL:,} characters"
        in reading_prompt.COMMON_PART
    )


def test_a_result_that_is_a_json_object_of_plain_values_keeps_the_lines_of_its_output():
    content = '{"returncode": 1, "output": "line 1\\nline 2"}'
    nested = '{"output": {"text": "a"}}'
    trajectory = {"steps": [bash_step(1, "run", content), bash_step(2, "run", nested)]}

    dump = write_reading_materials.trajectory_dump_text_of(trajectory)

    assert "returncode: 1\noutput: line 1\nline 2\n" in dump
    assert nested in dump


def test_steps_of_a_subagent_trajectory_follow_those_of_the_agent_under_a_heading():
    trajectory = {
        "steps": [made_up_step(1, message="main")],
        "subagent_trajectories": [
            {"trajectory_id": "sub-1", "steps": [made_up_step(1, message="sub")]}
        ],
    }

    dump = write_reading_materials.trajectory_dump_text_of(trajectory)

    assert (
        dump.index("main")
        < dump.index("[[[ subagent trajectory sub-1,")
        < dump.index("sub\n")
    )
    assert dump.count("[[[ step_id 1 |") == 2


def test_the_prompt_names_the_heading_that_the_dump_writes_before_a_subagent_trajectory():
    reading_prompt = analysis_module("reading_prompt")
    trajectory_steps = analysis_module("trajectory_steps")
    trajectory = {
        "steps": [made_up_step(1), made_up_step(2)],
        "subagent_trajectories": [
            {"trajectory_id": "sub-1", "steps": [made_up_step(1), made_up_step(7)]}
        ],
    }

    dump = write_reading_materials.trajectory_dump_text_of(trajectory)

    assert (
        "Steps under a `[[[ subagent trajectory` line"
        in reading_prompt.SUBAGENT_STEPS_SENTENCE
    )
    assert "\n[[[ subagent trajectory sub-1," in dump
    assert trajectory_steps.main_step_ids_of(
        trajectory_steps.trajectory_steps_of(trajectory)
    ) == {1, 2}


def test_a_long_tool_call_id_is_shortened_in_both_headings():
    long_id = "c" * 40 + "d" * 5000
    step = bash_step(1, "ls", "a.txt")
    step["tool_calls"][0]["tool_call_id"] = long_id
    step["observation"]["results"][0]["source_call_id"] = long_id

    dump = write_reading_materials.trajectory_dump_text_of({"steps": [step]})

    assert "dd" not in dump
    assert dump.count("c" * 40 + "... (5000 more characters)") == 2


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # The output once, without the default metadata.
        (
            'a\nb\n\n[stdout]\na\nb\n[metadata] {"noOutputExpected": false}',
            "[stdout]\na\nb",
        ),
        # A stderr section and other metadata stay, and stdout keeps its leading spaces.
        (
            '  x\nwarn\n\n[stdout]\n  x\n[stderr]\nwarn\n[metadata] {"returnCodeInterpretation": "Files differ"}',
            '[stdout]\n  x\n[stderr]\nwarn\n[metadata] {"returnCodeInterpretation": "Files differ"}',
        ),
        # Only stderr, and an empty stderr section left out.
        ("oops\n\n[stderr]\noops", "[stderr]\noops"),
        ("done\n\n[stdout]\ndone\n[stderr]\n", "[stdout]\ndone"),
        # A first copy that differs from the sections, e.g. a preview, keeps the whole text.
        (
            "Preview\nab\n\n[stdout]\nabcdef\n[metadata] {}",
            "Preview\nab\n\n[stdout]\nabcdef\n[metadata] {}",
        ),
        ("no sections here", "no sections here"),
    ],
)
def test_output_that_a_result_repeats_is_printed_once(content, expected):
    assert write_reading_materials.observation_text_of(content) == expected
