# Pipeline example

One made-up trial, to show how stages 3 to 11 of the [pipeline](../README.md#pipeline) turn tool calls in a trajectory into structured, interpreted data for internet use analysis.

This is an example, not a specification. Where each part comes from:

- **Stages 3 to 5:** what the current code gives, simplified like the trial.
- **Stage 6:** the types in [shell/model.py](../src/tb_internet_use/shell/model.py).
- **Stages 7 to 11:** sketches of the intent, following a trial implementation that is not part of the code. Each stage should choose a better form if the data calls for it.
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

## Stage 6: commands

One call's shell text becomes a flat list of simple commands. Each command records when it runs, where its stdout and stderr go, and whether the text's exit code 0 means that it exited 0. This stage records structure only and does not know what `fetch.sh` is.

```python
c2_text = ParsedShellText(
    commands=(
        ShellCommand(
            id=0,
            words=("bash", "fetch.sh"),
            stdout=FileDestination("fetch.log"),
            stderr=FileDestination("fetch.log"),
        ),
        ShellCommand(
            id=1,
            words=("pip", "install", "requests"),
            # only if command 0 failed
            runs_if=(RunCondition((0,), ExitOutcome.FAILURE),),
        ),
    )
)
```

`2>&1` sends stderr where stdout goes, so none of `bash fetch.sh`'s output reaches the result. The exit code of an `a || b` list says nothing about `a` or `b` alone, so `succeeded_if_text_exits_zero` is False for both. The harness runs the whole call in the background, not an `&` in the text, so `runs_in_background` is False for both.

Other destinations are the call's result (`ResultDestination`, the default), a pipe with the command that reads it (`PipeDestination`), a `$(...)` capture (`CaptureDestination`) and `/dev/null` (`DiscardDestination`).

## Stage 7: what each call runs

The whole trial is used to connect calls. This stage parses the written file with the stage 6 parser, and still does not ask about the network.

```python
files = {"fetch.sh": c1.action.content}
c2.runs = (
    ShellCommand(  # from fetch.sh
        id=2,
        words=("curl", "-sS", "-O", "https://data.example.org/a.tgz"),
        stdout=FileDestination("fetch.log"),
        stderr=FileDestination("fetch.log"),
    ),
    ShellCommand(
        id=1,
        words=("pip", "install", "requests"),
        runs_if=(RunCondition((0,), ExitOutcome.FAILURE),),
    ),
)
c2.result_readers = [c3]  # polls task-1
c2.file_readers = {"fetch.log": [c4]}
```

A command in a file runs when the command that ran the file runs, and its output goes where that command's output goes. So `curl` takes the destinations of `bash fetch.sh`.

## Stage 8: candidate requests

The first decision about the network. This stage looks at what ran, not at what came back. A request also carries what its run can show, read from a table of rules per program.

```python
r1 = Request(
    call=c2, origin=COMMAND, kind=URL, program="curl",
    targets=["https://data.example.org/a.tgz"], hosts=[Host("data.example.org", PUBLIC)],
    exit_zero_proves=RESPONSE,  # curl without -f exits 0 after any response
    prints_response=False,  # -O writes the body to a file
)
r2 = Request(
    call=c2, origin=COMMAND, kind=PACKAGE, program="pip",
    targets=["requests"], printers={PIP},  # whose output lines it can print
)
```

This stage drops no request, so stage 10 can still link the output of a request to a local host. A real trial would tag `example.org` as reserved. Read it here as a public host.

Some requests need a trace. For example `npx tsc` may run a local tool, and `curl "$URL"` names no host. They become internet requests only if a network line is linked to them.

## Stage 9: observations

Network traces in output lines and in result fields such as the HTTP status of a web fetch. This stage does not know which request they belong to, and could run before stage 8.

```python
o1 = Observation(call=c4, line_index=0, kind=NAME_NOT_RESOLVED, host=Host("data.example.org", PUBLIC))
o2 = Observation(call=c3, line_index=0, kind=DOWNLOAD_STARTED, subject="requests-2.32.3")
o3 = Observation(call=c3, line_index=1, kind=INSTALLED, printer=PIP)
```

## Stage 10: links

Requests meet observations, through the readers from stage 7, the printers and the host names. This is the only stage that decides what a call's result says about one of its requests.

```python
l1 = LinkedRequest(r1, observations=[o1], run_state=RAN, visibility=PLAIN)  # through fetch.log, same host
l2 = LinkedRequest(r2, observations=[o2, o3], run_state=RAN, visibility=PLAIN)  # through task-1
```

`r2` runs only if `bash fetch.sh` failed. Its own lines show that it ran. Without them its run state would be unknown. A command after `&&` with nothing against it is assumed to have run.

A line that more than one request can explain is shared, e.g. a download line in a call with two pip installs. A shared line cannot settle whether a request ran.

Call facts are decided here per request. The call's exit code 0 counts for a request only if the text's structure says so. The result text counts as a request's response only if nothing else in the call prints. The visibility says how much of its output the trial shows, e.g. quiet for `pip -q` or filtered for `| tail -1`.

A request can also start here. For example, a download line that no request explains would create an inferred request.

## Stage 11: how far each request got

```python
r1.result = Result(
    state=REQUEST, level=EXECUTED, grade=DIRECT, strict_level=EXECUTED,
    stop=NAME_NOT_RESOLVED, visibility=PLAIN, evidence=[(c4, line 0)],
)
r2.result = Result(
    state=REQUEST, level=RECEIVED, grade=DIRECT, strict_level=RECEIVED,
    stop=None, visibility=PLAIN, evidence=[(c3, line 1)],
)
```

Each observation kind maps to a level in a table, and a short list of named rules handles what depends on the other lines. For example, pip's `No matching distribution` after a connection error means the index was never reached.

The level is the highest that any evidence shows. The grade says how strong that evidence is, so that counts can be strict or lenient. The strict level counts direct evidence only, and a run that is only assumed shows nothing. The trial uses these grades.

| Grade | Evidence | In the trial, e.g. |
|---|---|---|
| Direct | A line or result field that only this request explains | A download line followed by an install line |
| Shared | A line that several requests of the call explain | Two pip installs and one download line |
| Call | The call's exit code or result text | `curl -s` alone with exit code 0 and text |
| Indirect | A line that something else can explain too | `Successfully installed` alone, which a cache can give |
| Status | Only that the call ran | No network line at all |

When no failure stopped a request below Received, the visibility tells why nothing further could be seen.

A request that needs a trace and has none, or that may not have run, keeps its own state and stays out of the level counts.

## What separates the stages

| Stage | Looks at | Question |
|---|---|---|
| 5 | One call | What did the trajectory record? |
| 6 | One call's text | How is the shell text structured? |
| 7 | The whole trial | What actually ran, and where did its output go? |
| 8 | What ran | Which of it was an internet request, and what can its run show? |
| 9 | The output | What network traces are there? |
| 10 | Requests and observations | Which belong together, and what does each call say about each request? |
| 11 | One linked request | How far did it get, how sure is that, and what stopped it or hid the rest? |
