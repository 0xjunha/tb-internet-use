"""Make made-up harness tool calls for the tests of the network_request_result package, kept out of conftest.py since the test folders share that module name and an import of it depends on which folder pytest collected last."""

import json

from tb_internet_use.tool_call.model import HarnessTool, HarnessToolCall, ToolCallKey


def build_copilot_cli_bash_call_not_executed(
    tool_call_key: ToolCallKey, command: str
) -> HarnessToolCall:
    """Make a Copilot CLI `bash` call whose result says that Copilot CLI did not execute the command, so that its status is `NOT_RUN`.

    The result text holds the message twice with a JSON line between, and the content ends with the JSON line of a failed call, as Harbor writes it.
    The tests of a made-up mini-swe-agent trial take it for a call that did not run, since a mini-swe-agent result that says the action was not executed has an unknown status.
    """
    message = "Command not executed. The 'curl' command is not allowed."
    json_line = json.dumps(
        {"detailedContent": message, "structuredContent": {"shellId": "4"}}
    )
    failure_line = json.dumps({"code": "failure"})
    return HarnessToolCall(
        tool_call_key,
        HarnessTool("copilot-cli", "bash"),
        f"{tool_call_key.step_id}",
        {"command": command},
        {
            "content": f"{message}\n{json_line}\n{message}\n{failure_line}",
            "extra": {"success": False},
        },
    )
