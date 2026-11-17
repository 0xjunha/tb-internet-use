# Pipeline example

> **Work in progress.** This example follows steps 1 to 5 of the six steps that the pipeline is being rebuilt into. The steps, the output type of each step and the `...Knowledge` classes are settled by name and not built yet. What the types hold is a draft, which covers every new field, the types nested in the fields and their values. It is settled when each step is built. The example of the previous layout is in this file's history.

Six made-up tool calls of one trial go through the [pipeline](../README.md#pipeline), from the trajectory to the exported rows. Step 0 collects the list of trials and has nothing to show for one trial.

## What the steps have to find out

For each request the pipeline wants to know what was asked for, how far it got, and how sure that is.
This is hard only because a request or its output is often not in the call that caused it. It can be in three places, and each case below shows one of them.

| Case | Where the request and its output are | What the case shows |
|---|---|---|
| A | In the call itself | One output line fits two requests, so neither owns it |
| B | Elsewhere in the trajectory | The request is in a script that an earlier call wrote, and the output shows up in two later calls |
| C | Not in the trajectory | No call wrote the script that ran, so only its output tells that a request was made |

## Input

c1 to c6 are the calls, in order. The result of each call is shortened to the lines that matter. Hosts under example.org are reserved for examples, and here they are read as public hosts.

| Call | Case | Tool | Arguments | Result |
|---|---|---|---|---|
| c1 | A | `Bash` | `command: curl -sS --connect-timeout 30 -O https://a.example.org/x.tgz; curl -sS --connect-timeout 30 -O https://b.example.org/y.tgz; echo done` | `curl: (28) Connection timed out after 30001 milliseconds`, `done` |
| c2 | B | `Write` | `file_path: fetch.sh`, `content: curl -sS -O https://data.example.org/a.tgz` | `File created successfully at: fetch.sh` |
| c3 | B | `Bash` | `command: bash fetch.sh > fetch.log 2>&1 \|\| pip install requests`, `run_in_background: true` | `Command running in background with ID: task-1` |
| c4 | B | `TaskOutput` | `task_id: task-1` | `Downloading requests-2.32.3`, `Successfully installed requests-2.32.3` |
| c5 | B | `Read` | `file_path: fetch.log` | `curl: (6) Could not resolve host: data.example.org` |
| c6 | C | `Bash` | `command: bash setup.sh` | `Downloading torch-2.3.0`, `Successfully installed torch-2.3.0` |

## Where this ends

The pipeline ends with one row per request and one row per trial. The steps below show how each column is reached.

| Request | Case | Asked for | Category | How far it got | Why it stopped | How sure |
|---|---|---|---|---|---|---|
| r1 | A | The file x.tgz from a.example.org | Fetched file | Executed | Failed to connect | Assumed. The one error line may be r2's, and then r1 may have received its file |
| r2 | A | The file y.tgz from b.example.org | Fetched file | Executed | Failed to connect | Assumed, in the same way |
| r3 | B | The file a.tgz from data.example.org | Fetched file | Executed | The host name did not resolve | Confirmed by its own line in c5 |
| r4 | B | The package requests | Package | Received | | Confirmed by its own lines in c4 |
| r5 | C | The package torch | Package | Received | | The result is confirmed by its lines in c6. Whether such lines alone make a confirmed request is not decided |

The trial's row answers the two questions of the README for each category, as a lower and an upper bound.

| Category | The trial has a request | The trial received one |
|---|---|---|
| Fetched file | Yes in both bounds | No in the lower bound, yes in the upper |
| Package | Yes in both bounds | Yes in both bounds |

## The steps at a glance

| Step | Question it answers | Case A | Case B | Case C |
|---|---|---|---|---|
| 1. Convert tool calls | What did the trajectory record? | c1 with its three commands | c2 to c5, with c3 still running | c6 with one command |
| 2. Expand tool calls | What did each call actually run, and where does that output show up? | Nothing beyond its own text, and all output is in c1's result | c3 also ran the curl line of fetch.sh. curl's output shows up in c5, pip's in c4 | setup.sh ran, and what it ran is unknown |
| 3. Extract network requests | Which of what ran is a request, and for which target? | r1 and r2 | r3 and r4 | None |
| 4. Decide request results | How far did each request get, and on what evidence? | r1 and r2 share one line | r3 and r4 each have lines of their own | Lines that no request owns make r5 |
| 5. Export rows | Which category is each request, and what do the rows say? | Two fetched files, received only in the upper bound | A fetched file not received, a package received | A package received |

Steps 1 and 2 are built to know nothing about the internet.
Outside knowledge is the facts that no trajectory holds. Each step asks for it through one class of its own, e.g. `ToolCallKnowledge`, and gets a value or unknown.

## Step 1: convert tool calls

Each call is converted from its harness's own format into a `ToolCall`, which holds what the call asked for (its action) and what came back (its output).
The command text is split into commands by shell grammar alone, with when each runs and where its output goes. Command ids are 0-based and unique within a call.

| Asked through `ToolCallKnowledge` | Answer in this example |
|---|---|
| What does the tool `Bash` do? | It runs a command |
| How is c1's result read? | As the plain output of a finished command, with the exit code 0 that the trajectory holds beside the text |
| How is c3's result read? | As a command left running in the background, with the handle task-1 |

```python
c1.action = RunCommandAction(
    command_str="curl -sS --connect-timeout 30 -O https://a.example.org/x.tgz; curl -sS ... -O https://b.example.org/y.tgz; echo done",
    commands=(
        ShellCommand(id=0, words=("curl", "-sS", "--connect-timeout", "30", "-O", "https://a.example.org/x.tgz")),
        ShellCommand(id=1, words=("curl", "-sS", "--connect-timeout", "30", "-O", "https://b.example.org/y.tgz")),
        ShellCommand(id=2, words=("echo", "done")),
    ),
)
# The exit code is echo's, so it says nothing about either curl.
c1.output = ToolCallResult(execution_status=FINISHED, exit_code=0, tool_output_text="curl: (28) ...\ndone")

c3.action = RunCommandAction(
    command_str="bash fetch.sh > fetch.log 2>&1 || pip install requests",
    commands=(
        # The redirect covers only command 0, and `2>&1` sends stderr where stdout goes.
        ShellCommand(
            id=0,
            words=("bash", "fetch.sh"),
            stdout=FileDestination("fetch.log", appends=False),
            stderr=FileDestination("fetch.log", appends=False),
        ),
        # It runs only if command 0 failed, and its output goes to the call's result.
        ShellCommand(
            id=1,
            words=("pip", "install", "requests"),
            runs_if=(RunCondition((0,), ExitOutcome.FAILURE),),
        ),
    ),
)
c3.output = ToolCallResult(execution_status=RUNNING, handles=(ExecutionHandle(COMMAND, "task-1"),))
```

## Step 2: expand tool calls

Each call is expanded into everything it actually ran and the places where that output shows up, using all calls of the trial.
Each command is read once into its program, options and arguments, and later steps do not read it again.
Where the step cannot follow, it records what is unknown.

| Asked through `ExpandedToolCallKnowledge` | Answer in this example |
|---|---|
| What does `bash fetch.sh` run? | The file fetch.sh as shell text |
| How are the words of a curl command read? | `--connect-timeout` takes the next word as its value, `-s`, `-S` and `-O` take none, and the last word is an argument |
| What does curl's `-O` do to files? | It writes a file named after the last part of the URL |
| What does `echo` run? | Nothing |

```python
c3_expanded = ExpandedToolCall(
    tool_call=c3,
    ran_shell_texts=(
        # This is c3's own command text, with the two commands that step 1 split it into.
        RanShellText(source=CallCommandText(), commands=(bash_fetch_sh, pip_install_requests)),
        # c2 wrote fetch.sh, and command 0 runs it.
        # Its curl command gets id 2 and the output destination of command 0.
        RanShellText(
            source=FileText(runner_command_id=0, path="fetch.sh", written_by=c2),
            commands=(curl_a_tgz,),
        ),
    ),
    output_places=(
        # c3 returned while running and c4 polls task-1, so pip's output shows up in c4.
        OutputPlace(shown_in=c4, reached_through=Poll(handle="task-1"), command_ids=(1,)),
        # c5 reads fetch.log, where the output of bash and of curl went.
        OutputPlace(shown_in=c5, reached_through=FileRead(path="fetch.log"), command_ids=(0, 2)),
    ),
    # curl writes this file if it succeeds. No later call reads or uses it.
    written_files=(WrittenFile(command_id=2, path="a.tgz", later_uses=()),),
    unknowns=(),
)

curl_a_tgz.program_invocation = ProgramInvocation(
    program_name="curl",
    options=("-s", "-S", "-O"),
    arguments=("https://data.example.org/a.tgz",),
    unread_words=(),
)

c6_expanded = ExpandedToolCall(
    tool_call=c6,
    ran_shell_texts=(RanShellText(source=CallCommandText(), commands=(bash_setup_sh,)),),
    output_places=(OutputPlace(shown_in=c6, reached_through=OwnResult(), command_ids=(0,)),),
    written_files=(),
    # No call of the trial wrote setup.sh, so what it ran is unknown.
    unknowns=(UnknownFileContent(runner_command_id=0, path="setup.sh"),),
)
```

In case A, `c1_expanded` holds only c1's own text. All three commands reach c1's result, and the two curl commands are to write x.tgz and y.tgz, which no later call uses.

## Step 3: extract network requests

For everything a call ran, the step asks whether it fetches its target.
When the answer is yes, the step makes one request per target and marks it as a confirmed request. When the answer is no, it makes none.
When the answer is unknown, the step makes an uncertain request only if a public URL is visible, e.g. for `mytool https://a.example.org/x`.
The step looks only at what ran, and step 4 reads what came back.

| Asked through `NetworkRequestKnowledge` | Answer in this example |
|---|---|
| Does curl fetch? | Yes. Each URL argument is a target, and `-O` saves what is received |
| Does `pip install` fetch? | Yes. Each package name is a target |
| Does `echo` fetch? | No |

```python
r3 = NetworkRequest(
    # c3 ran it, though c2 wrote fetch.sh.
    source=FromCommand(tool_call=c3, command_id=2),
    means=("curl",),
    target="https://data.example.org/a.tgz",
    target_kind=URL,
    host="data.example.org",
    # The values this field can take are not decided.
    received_content_destination=SAVED,
    request_certainty=CONFIRMED,
)
r4 = NetworkRequest(
    source=FromCommand(tool_call=c3, command_id=1),
    means=("pip", "install"),
    target="requests",
    target_kind=PACKAGE_NAME,
    # No index option names a host.
    host=None,
    received_content_destination=SAVED,
    request_certainty=CONFIRMED,
)
```

r1 and r2 of case A look like r3, with `FromCommand(tool_call=c1, command_id=0)` and `command_id=1`.
Case C gives no request here. `bash` runs a file, the file's content is unknown, and the words of the command show no public URL.

## Step 4: decide request results

The step reads every output place that step 2 recorded, including those that no request reaches.
A line that says something about a request goes to the requests that reach that place and whose program can print it.

| Requests that reach the place and can print the line | What the line becomes |
|---|---|
| One | That request's own evidence |
| Several | Evidence they share. A result that rests on it is only assumed |
| None | A new request, unless the output comes from a program that only shows a file's content, e.g. `cat README.md` |

Then each request is judged on its own evidence. `request_certainty` from step 3 says how sure the pipeline is that something is a request, and `result_certainty` says how sure it is of how far the request got. Line indexes are 0-based.

| Asked through `NetworkRequestResultKnowledge` | Answer in this example |
|---|---|
| What does `Could not resolve host: X` say? | The request ran and reached no server |
| What does `Connection timed out` say? | No connection was made |
| Which program prints `Successfully installed X`? | pip |

| Output place | Commands that reach it | Lines about a request | Owner | How far the request got |
|---|---|---|---|---|
| c1's result | curl x.tgz, curl y.tgz, echo | `Connection timed out` | r1 and r2 share it | Both Executed, failed, assumed |
| c4's result | pip of c3 | `Downloading requests-2.32.3`, `Successfully installed requests-2.32.3` | r4 | Received, confirmed |
| c5's result | bash and curl of c3 | `Could not resolve host: data.example.org` | r3 | Executed, failed, confirmed |
| c6's result | bash of c6, which ran unknown content | `Downloading torch-2.3.0`, `Successfully installed torch-2.3.0` | None, so a new request r5 | Received, confirmed |

```python
r1.result = NetworkRequestResult(
    request=r1,
    # `;` runs it whatever came before, and `done` shows that the text ran to its end.
    level=EXECUTED,
    stop_reason=FAILED,
    # The only failure line may be r2's.
    result_certainty=ASSUMED,
    evidence=(SharedLine(shown_in=c1, line_index=0, kind=CONNECTION_FAILED, shared_with=(r2,)),),
)

# Step 4 makes this request, since no request reaches c6's result.
# The lines name one target. How the targets of one run are grouped into requests is not decided.
r5 = NetworkRequest(
    source=FromOutput(tool_call=c6, shown_in=c6),
    # What sent it is inside setup.sh.
    means=None,
    target="torch",
    target_kind=PACKAGE_NAME,
    host=None,
    received_content_destination=UNKNOWN,
    # Which lines alone make a confirmed request is a judgment rule still to be decided.
    request_certainty=...,
)
r5.result = NetworkRequestResult(
    request=r5,
    level=RECEIVED,
    stop_reason=None,
    result_certainty=CONFIRMED,
    evidence=(
        OwnLine(shown_in=c6, line_index=0, kind=DOWNLOAD_STARTED),
        OwnLine(shown_in=c6, line_index=1, kind=INSTALLED),
    ),
)
```

Had a later call unpacked x.tgz, that use would be r1's own evidence that its content arrived.
Some results need a choice that facts alone do not settle, e.g. whether `Successfully installed` without a download line means received, since a cache can give it. Such judgment rules belong to this step and are still to be decided.

## Step 5: export rows

Computed columns are added, credentials are redacted, and the rows of [Where this ends](#where-this-ends) are written.
The category is computed from what the request's own text shows, or from the lines that made it for a request like r5, so the same command gets the same category whether it failed or not.

| Asked through `ExportKnowledge` | Answer in this example |
|---|---|
| What kind of host is data.example.org? | Unknown, since no row names it. A known kind would be e.g. a package registry or a code host |

The rules behind three of the columns are drafts.

| Column | What the draft gives here | Not decided |
|---|---|---|
| Category | Fetched file for r1 to r3, which save what a URL gives. Package for r4 and r5 | The category rules |
| Internet use | Yes for all five. The hosts that r1 to r3 name are judged by their names alone, and are read as public in this example | How a request that names no host is counted |
| Bounds of the trial row | r1 to r4 are confirmed requests, so both categories have a request in both bounds. r4 is confirmed as received, and no fetched file is confirmed as received. One error line cannot be the failure of both r1 and r2, so the upper bound counts one of them as possibly received | How an assumed result counts in each bound, and whether r5 alone would count in the lower bound |

## What these cases leave out

- Output that passes through another command before it is shown, e.g. `curl u | tail -1`.
- A saved file that a later call uses, e.g. `tar xzf a.tgz`, as evidence that its content arrived.
- Loops and variables, e.g. `for p in a b; do pip install $p; done`.
- Code text, e.g. `python client.py`, which is not split into commands and is read for requests in step 3.
- Web tools, and text typed into a running process.
- Requests that are uncertain although the program is known: one that fetches only when something is missing, e.g. `npx tsc`, and one with an option that no fact covers.
- A request that needed to send nothing, e.g. pip printing `Requirement already satisfied`.
