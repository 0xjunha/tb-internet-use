# Pipeline example

An end-to-end example demonstrating stages 3 to 12 of the [pipeline](../README.md#pipeline), turning an ATIF `trajectory.json`
into structured data for internet use analysis.

The example tool calls are made up to showcase several representative tool calls and their output patterns.

## Input

Four calls from a `trajectory.json`, one per step.
The agent writes a script and runs it in the background, with `pip install requests` as a fallback if it fails (`||`). The redirect covers only the script, so the fallback's output shows up when the agent polls the background task, and the script's output when it reads fetch.log.


| Step | Tool | Arguments | Result |
|---|---|---|---|
| 1 | `Write` | `file_path: fetch.sh`, `content: curl -sS -O https://data.example.org/a.tgz` | `File created successfully at: fetch.sh` |
| 2 | `Bash` | `command: bash fetch.sh > fetch.log 2>&1 \|\| pip install requests`, `run_in_background: true` | `Command running in background with ID: task-1` |
| 3 | `TaskOutput` | `task_id: task-1` | `Downloading requests-2.32.3`, `Successfully installed requests-2.32.3` |
| 4 | `Read` | `file_path: fetch.log` | `curl: (6) Could not resolve host: data.example.org` |

## Summary of the stages

c1 to c4 are the calls of steps 1 to 4 above.

| Stage | Input | Output | Question | In this example |
|---|---|---|---|---|
| 5 | One trial's `trajectory.json` | A `ToolCall` per call | What did the trajectory record? | c1 to c4 as `ToolCall`s, with c2 still running |
| 6 | One shell text | `ParsedShellText` | How is the shell text structured? | c2's text gives `bash fetch.sh`, whose output goes to fetch.log, and `pip install requests`, which runs only if bash fails |
| 7 | Program names in all commands (6) | `program_catalog.csv` | What does each program do when a command runs it? | curl and pip install make requests, and their rows say what their runs can show |
| 8 | All calls of the trial (5), each text parsed by 6, and the program catalog (7) | A `CallRun` per call | What did each call actually run, including what its own text does not show, and which calls show its output? | c2's run also holds the curl line that c1 wrote into fetch.sh. c3 polls c2, and c4 reads fetch.log |
| 9 | One call's expanded run (8) and the program catalog (7) | `CandidateRequest`s | Which of it may be an internet request, and what facts does its run give? | c2 gives a curl request to data.example.org and a pip request for requests |
| 10 | One call's result (5) | `Observation`s | What network traces are there? | c3 gives two pip lines, and c4 a curl line saying the host did not resolve |
| 11 | The trial's requests (9), observations (10) and call runs (8) | Linked requests (sketch) | Which belong together, and what does each call say about each request? | The curl request links to c4's line through fetch.log, and the pip request to c3's lines through the poll |
| 12 | One linked request (11) | A result per request (sketch) | How far did it get, how sure is that, and what stopped it or hid the rest? | curl ran but stopped when the host did not resolve, and pip got as far as receiving the package |

## Stages 3 and 4: define types and labels

These stages define harness-agnostic common types in [model.py](../src/tb_internet_use/toolcall/model.py) and tool call labels in the [tool catalog](../src/tb_internet_use/toolcall/catalogs/README.md).

| Tool | `action_type` | Arguments that map to fields |
|---|---|---|
| `Write` | `WriteFileAction` | `file_path` to `path`, `content` to `content` |
| `Bash` | `RunCommandAction` | `command` to `command_str` |
| `TaskOutput` | `PollAction` | `task_id` to `handles` |
| `Read` | `ReadFileAction` | `file_path` to `path` |

## Stage 5: common types for tool calls

Each call is converted from its harness's own format into a `ToolCall`, holding what the call asked for (its action) and what it returned (its output), as the trajectory records them.

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

## Stage 6: parse commands

Parse one shell text into a flat list of simple commands, each recording when it runs and where its stdout and stderr go.
It looks at this one text alone, so it does not know what `fetch.sh` holds.

```python
c2_text = ParsedShellText(
    commands=(
        ShellCommand(
            id=0,
            words=("bash", "fetch.sh"),
            stdout=FileDestination("fetch.log", appends=False),
            # 2>&1 sends stderr where stdout goes
            stderr=FileDestination("fetch.log", appends=False),
            # False for both, since exit 0 of `a || b` says nothing about a or b alone
            succeeded_if_text_exits_zero=False,
            # False for both. The harness runs the call in the background, but the command text itself has no &
            runs_in_background=False,
        ),
        ShellCommand(
            id=1,
            words=("pip", "install", "requests"),
            # the redirect covers only command 0, so pip's output reaches the call's result
            stdout=ResultDestination(),
            stderr=ResultDestination(),
            # only if command 0 failed
            runs_if=(RunCondition((0,), ExitOutcome.FAILURE),),
            succeeded_if_text_exits_zero=False,
            runs_in_background=False,
        ),
    )
)
```

## Stage 7: label programs

The [program catalog](../src/tb_internet_use/program/catalogs/README.md) labels by hand what a program does when a command runs it, one row per program and subcommand.
The rows below are the two that make requests in this example, with some of their columns.
Rows of programs that make no request can label other things, e.g. `tail` has `reads_file_arguments=yes`, so stage 8 counts `tail fetch.log` as a read of fetch.log.

| `program` | `subcommand` | `request_kind` | `exit_zero_means` | `prints_response_body` | `asked_packages_source` |
|---|---|---|---|---|---|
| `curl` | | `url` | `server_responded` | `yes` | `none` |
| `pip` | `install` | `package` | `nothing` | `no` | `targets` |

## Stage 8: expand each call into everything it ran

Expand each call into one `CallRun` that holds everything the call actually ran, including what its own text does not show.
c2's text names only `bash fetch.sh`, but c2 also ran the curl line that c1 wrote into fetch.sh, so that line is in c2's `CallRun`.
The `CallRun` also follows the output through pipes to where it ends, and to the later calls that show it.
This stage still does not ask about the network. `k1` to `k4` stand for `c1.raw.key` to `c4.raw.key`.

```python
c2_run = CallRun(
    call=c2,
    shell_texts=(
        # c2's own command string, with commands 0 and 1 from stage 6
        RanShellText(CallCommandText(), commands=(bash_fetch_sh, pip_install)),
        # fetch.sh, which c1 wrote and command 0 runs, parsed with the stage 6 parser
        RanShellText(
            FileText(runner_command_id=0, path="fetch.sh", written_by=k1),
            commands=(curl,),
        ),
    ),
    code_texts=(),
    # c2 returned while running. c3 saw it finish but showed no exit code, so exit_code stays None
    command_text_status=CommandTextStatus(FINISHED, exit_code=None, reported_by=k3),
    # c3 polls task-1, which c2 started, so pip's output shows up in c3
    polls=(k3,),
    # c2's result names no file holding its whole output
    harness_output_file_readers=(),
    # c4 reads fetch.log with a read tool (command_id=None), so curl's output shows up in c4
    redirected_output_reads=(
        RedirectedOutputReads("fetch.log", readers=(FileReader(k4, command_id=None),)),
    ),
)

# c2_run.shell_texts[1].commands[0]
curl = RanCommand(
    # fetch.sh has no redirect, so curl takes the destinations of command 0, which runs fetch.sh
    command=ShellCommand(
        id=2,
        words=("curl", "-sS", "-O", "https://data.example.org/a.tgz"),
        stdout=FileDestination("fetch.log", appends=False),
        stderr=FileDestination("fetch.log", appends=False),
    ),
    variable_values=(),
    # no pipe readers, so both outputs end at fetch.log
    stdout_routes=(OutputRoute(pipe_reader_ids=(), end=FileDestination("fetch.log", appends=False)),),
    stderr_routes=(OutputRoute(pipe_reader_ids=(), end=FileDestination("fetch.log", appends=False)),),
)
```

## Stage 9: extract candidate requests from each call's expanded run

Extract candidate requests from the commands, code and web tool actions that stage 8 traced, before any output is read.
Each records facts about its run from the program catalog and its options.
A command that may not use the network stays a candidate, and its fields record why, e.g. `fetches_only_to_run_or_build=True` for `npx tsc`.

```python
r1 = CandidateRequest(
    # c2 ran it, though c1 wrote fetch.sh
    call=k2,
    # curl in fetch.sh, c2_run.shell_texts[1].commands[0]
    source=FromCommand(command_id=2),
    kind=URL,
    program_name="curl",
    targets=(RequestTarget(written="https://data.example.org/a.tgz", value="https://data.example.org/a.tgz", loop_variable=None),),
    # really RESERVED, read here as PUBLIC as if it were a real public host
    hosts=(Host("data.example.org", PUBLIC),),
    asked_package_names=frozenset(),
    printing_programs={CURL},
    fetches_only_to_run_or_build=False,
    has_offline_option=False,
    # curl without -f exits 0 after any response
    exit_zero_means=SERVER_RESPONDED,
    asks_for_no_content=False,
    # -O writes the body to a file
    prints_response_body=False,
    prints_status_code=False,
    # -s hides progress
    quiet_progress_lines=True,
    # -S shows errors again
    quiet_error_lines=False,
)
r2 = CandidateRequest(
    call=k2,
    # pip install requests in c2's own command string
    source=FromCommand(command_id=1),
    kind=PACKAGE,
    program_name="pip",
    targets=(RequestTarget(written="requests", value="requests", loop_variable=None),),
    # no index option names a host
    hosts=(),
    asked_package_names={"requests"},
    printing_programs={PIP},
    fetches_only_to_run_or_build=False,
    has_offline_option=False,
    # pip also exits 0 when the package is cached
    exit_zero_means=NOTHING,
    asks_for_no_content=False,
    prints_response_body=False,
    prints_status_code=False,
    quiet_progress_lines=False,
    quiet_error_lines=False,
)
```

## Stage 10: extract observations from each call's result

Extract observations of how far a request got from each call's output lines and result fields, such as the HTTP status of a web fetch.
This stage reads only the call's result, not stage 8 or 9, so it does not know which request a line belongs to.
A table of line patterns gives each line its kind and printing programs.

```python
# fields left out are empty or None
o1 = Observation(
    # c4's Read result, the curl error that went to fetch.log
    call=k4,
    # line 0 of c4's tool_output_text, which holds no JSON object
    place=OutputLine(line_index=0, line_index_in_json_string=None),
    kind=NAME_NOT_RESOLVED,
    # empty, since any program that looks up a host may print this line
    printing_programs=frozenset(),
    is_printed_by_other_programs_too=True,
    # read as PUBLIC, as in stage 9
    host=Host("data.example.org", PUBLIC),
)
o2 = Observation(
    # c3's poll result, the output of pip install requests
    call=k3,
    place=OutputLine(line_index=0, line_index_in_json_string=None),
    kind=DOWNLOAD_STARTED,
    # programs known to print `Downloading x`
    printing_programs={PIP, UV, PLAYWRIGHT, GIT, CODE},
    # e.g. cargo
    is_printed_by_other_programs_too=True,
    # normalized from requests-2.32.3
    package_names={"requests"},
)
o3 = Observation(
    call=k3,
    place=OutputLine(line_index=1, line_index_in_json_string=None),
    kind=INSTALLED,
    # only pip prints `Successfully installed x`
    printing_programs={PIP},
    is_printed_by_other_programs_too=False,
    package_names={"requests"},
)
```

## Stage 11: link candidate requests to observations (not implemented)

Link each candidate request to the observations about it, through the calls that stage 8 found showing its output and through matching printing programs and hosts.
Requests that only the output reveals are added here, e.g. for a download line that no candidate request explains.
This stage has no code yet. `LinkedRequest` below is a sketch from the trial implementation with some of its fields, and its rules are still open.

```python
l1 = LinkedRequest(
    r1,
    # c4 reads fetch.log, where curl's output went, and o1 names r1's host
    observations=[o1],
    # its own error line shows that it ran
    run_state=RAN,
    visibility=PLAIN,
)
l2 = LinkedRequest(
    r2,
    # c3 polls task-1, where pip's output went, and both lines can be pip's
    observations=[o2, o3],
    # it runs only if bash fetch.sh failed. Its own lines show that it ran, and without them its run state would be UNKNOWN
    run_state=RAN,
    # no quiet option, filter or redirect hides its output
    visibility=PLAIN,
)
```

## Stage 12: decide how far each request got (not implemented)

Decide for each linked request the highest level its evidence shows, how strong that evidence is, and what stopped it or hid the rest.
A table maps each observation kind to a level, and a few named rules handle what depends on other lines.
Like stage 11, this stage has no code yet. `RequestResult` below is a sketch from the trial implementation, and its rules and evidence grades are still open.

```python
r1.result = RequestResult(
    # counted at a level. A request that may not have run, or that needs a trace and has none, gets another state and stays out of the counts
    state=REQUEST,
    # the highest level any evidence shows. curl ran, but the host name did not resolve
    level=EXECUTED,
    # how strong the evidence for the level is. o1 is a line that only r1 explains
    grade=DIRECT,
    # the highest level that direct evidence shows
    strict_level=EXECUTED,
    # the failure that kept it at its level
    stop=NAME_NOT_RESOLVED,
    # without a stop, why nothing further could be seen
    visibility=PLAIN,
    # o1, line 0 of c4
    evidence=[(c4, line 0)],
)
r2.result = RequestResult(
    state=REQUEST,
    # pip installed the package
    level=RECEIVED,
    # a download line followed by an install line, which only r2 explains
    grade=DIRECT,
    strict_level=RECEIVED,
    stop=None,
    visibility=PLAIN,
    # o3, line 1 of c3
    evidence=[(c3, line 1)],
)
```

### Evidence grades

The trial grades evidence like this, so that counts can be strict or lenient.

| Grade | Evidence | In the trial, e.g. |
|---|---|---|
| Direct | A line or result field that only this request explains | A download line followed by an install line |
| Shared | A line that several requests of the call explain | Two pip installs and one download line |
| Call | The call's exit code or result text | `curl -s` alone with exit code 0 and text |
| Indirect | A line that something else can explain too | `Successfully installed` alone, which a cache can give |
| Status | Only that the call ran | No network line at all |
