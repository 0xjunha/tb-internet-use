# Pipeline example

One made-up trial, to show how stages 3 to 11 of the [pipeline](../README.md#pipeline) turn tool calls in a trajectory into structured, interpreted data for internet use analysis.

This is an example, not a specification. Where each part comes from:

- **Stages 3 to 5:** what the current code gives, simplified like the trial.
- **Stages 6 to 11:** sketches of the intent, not implemented. Each stage should choose a better form if the data calls for it.
- **The trial and its trajectory:** made up and simplified. Real results are messier.

## Input

Four calls from a `trajectory.json`, one per step. The agent writes a script, runs it in the background with a fallback, reads the background output, then reads the log.

| Step | Tool | Arguments | Result |
|---|---|---|---|
| 1 | `Write` | `file_path: fetch.sh`, `content: curl -sS -O https://data.example.org/a.tgz` | `File created successfully at: fetch.sh` |
| 2 | `Bash` | `command: bash fetch.sh > fetch.log 2>&1 \|\| pip install requests`, `run_in_background: true` | `Command running in background with ID: task-1` |
| 3 | `TaskOutput` | `task_id: task-1` | `Downloading requests-2.32.3`, `Successfully installed requests-2.32.3` |
| 4 | `Read` | `file_path: fetch.log` | `curl: (6) Could not resolve host: data.example.org` |

## Stages 3 and 4: types and labels

No data changes shape here. These stages supply what stage 5 uses: the types in [model.py](../src/tb_internet_use/toolcall/model.py) and the labels in the [tool catalog](../src/tb_internet_use/toolcall/catalogs/README.md).

| Tool | `action_type` | Arguments that map to fields |
|---|---|---|
| `Write` | `WriteFileAction` | `file_path` to `path`, `content` to `content` |
| `Bash` | `RunCommandAction` | `command` to `command_str` |
| `TaskOutput` | `PollAction` | `task_id` to `handles` |
| `Read` | `ReadFileAction` | `file_path` to `path` |

## Stage 5: common types

Each call in the trajectory becomes a `RawToolCall`, then a `ToolCall` with one action and one output.

```python
c1.action = WriteFileAction(
    path="fetch.sh", content="curl -sS -O https://data.example.org/a.tgz"
)
c2.action = RunCommandAction(
    command_str="bash fetch.sh > fetch.log 2>&1 || pip install requests"
)
c3.action = PollAction(handles=(ExecutionHandle(UNKNOWN, "task-1"),))
c4.action = ReadFileAction(path="fetch.log")

c1.output = ToolCallOutput(execution_status=FINISHED)
c2.output = ToolCallOutput(
    execution_status=RUNNING, handles=(ExecutionHandle(COMMAND, "task-1"),)
)
c3.output = ToolCallOutput(
    execution_status=FINISHED, tool_output_text="Downloading requests-2.32.3 ..."
)
c4.output = ToolCallOutput(
    execution_status=FINISHED, tool_output_text="curl: (6) Could not resolve host: ..."
)
```

## Stage 6: command tree

One call's text gets a structure. This stage does not know what `fetch.sh` is.

```python
c2.tree = Or(
    Cmd("bash", ["fetch.sh"], stdout="fetch.log"),
    Cmd("pip", ["install", "requests"]),
)
```

## Stage 7: what each call runs

The whole trial is used to connect calls. This stage parses the written file with the stage 6 parser, and still does not ask about the network.

```python
files = {"fetch.sh": c1.action.content}
c2.runs = Or(
    RunFile(
        "fetch.sh",
        Cmd("curl", ["-sS", "-O", "https://data.example.org/a.tgz"]),
        stdout="fetch.log",
    ),
    Cmd("pip", ["install", "requests"]),
)
later_output = {"task-1": c3, "fetch.log": c4}
```

## Stage 8: candidate requests

The first decision about the network. This stage looks at what ran, not at what came back.

```python
r1 = Request(call=c2, type="URL request", target="data.example.org/a.tgz", tool="curl")
r2 = Request(
    call=c2, type="package download", target="requests", tool="pip", conditional=True
)
```

`r2` is conditional because it follows `||`, so it may not have run.

## Stage 9: observations

Network traces in the output. This stage does not know which request they belong to, and could run before stage 8.

```python
o1 = Observation(source=c4, kind="dns_error", host="data.example.org")
o2 = Observation(source=c3, kind="download_line", package="requests")
```

## Stage 10: links

Requests meet observations, through `later_output` from stage 7 and the target names.

```python
r1.observations = [o1]  # through fetch.log, same host
r2.observations = [o2]  # through task-1, same package
```

A request can also start here. For example, a download line that no request explains would create an inferred request.

## Stage 11: how far each request got

```python
r1.result = Result(
    level="Executed", stopped="dns_error", evidence=(c4, "curl: (6) ...")
)
r2.result = Result(level="Received", stopped=None, evidence=(c3, "Downloading ..."))
```

The download line also settles the condition on `r2`: it ran. Without that line, `r2` would stay at Attempted.

## What separates the stages

| Stage | Looks at | Question |
|---|---|---|
| 5 | One call | What did the trajectory record? |
| 6 | One call's text | How is the shell text structured? |
| 7 | The whole trial | What actually ran, and where did its output go? |
| 8 | What ran | Which of it was an internet request? |
| 9 | The output | What network traces are there? |
| 10 | Requests and observations | Which belong together? |
| 11 | One linked request | How far did it get, and why did it stop? |
