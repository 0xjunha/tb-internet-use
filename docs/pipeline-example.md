# Pipeline example

Six made-up tool calls of one trial go through the [pipeline](../README.md#pipeline), from the trajectory to the exported rows. Step 0 gives the trial itself its record, from the files beside the trajectory.
The values below are those that `run_steps_of_trial` in `pipeline.py` gives for the six calls as Claude Code calls, with the catalogs of the repo and the hosts read as [Input](#input) says. Fields that hold their empty value are left out.

## What the steps have to find out

For each request the pipeline wants to know what was asked for, how far it got, and how sure that is.
This is hard only because a request or its output is often not in the call that caused it. It can be in three places, and each case below shows one of them.

| Case | Where the request and its output are | What the case shows |
|---|---|---|
| A | In the call itself | One output line fits two requests, so neither owns it |
| B | Elsewhere in the trajectory | The request is in a script that an earlier call wrote, and the output shows up in two later calls |
| C | Not in the trajectory | No call wrote the script that ran, so its output shows a download that no request is made for |

## Input

c1 to c6 are the calls, in order. The result of each call is shortened to the lines that matter. Hosts under example.org are reserved for examples, which `export_rows` reads as of unknown internet use. Here they are read as public hosts, as `export_rows` reads a made-up name such as a.files-mirror.org by the judgment rule `treat_dotted_host_name_as_public`.

| Call | Case | Tool | Arguments | Result |
|---|---|---|---|---|
| c1 | A | `Bash` | `command: curl -sS --connect-timeout 30 -O https://a.example.org/x.tgz; curl -sS --connect-timeout 30 -O https://b.example.org/y.tgz; echo done` | `curl: (28) Connection timed out after 30001 milliseconds`, `done` |
| c2 | B | `Write` | `file_path: fetch.sh`, `content: curl -sS -O https://data.example.org/a.tgz` | `File created successfully at: fetch.sh` |
| c3 | B | `Bash` | `command: bash fetch.sh > fetch.log 2>&1 \|\| pip install requests`, `run_in_background: true` | `Command running in background with ID: task-1` |
| c4 | B | `TaskOutput` | `task_id: task-1` | `Downloading requests-2.32.3`, `Successfully installed requests-2.32.3` |
| c5 | B | `Read` | `file_path: fetch.log` | `curl: (6) Could not resolve host: data.example.org` |
| c6 | C | `Bash` | `command: bash setup.sh` | `Downloading torch-2.3.0`, `Successfully installed torch-2.3.0` |

## Where this ends

The pipeline ends with one row per request, one row per trial and one row per category of request of a trial. The steps below show how each column is reached.

| Request | Case | Asked for | Category | How far it got | Why it stopped | How sure |
|---|---|---|---|---|---|---|
| r1 | A | The file x.tgz from a.example.org | Fetched file | Executed | Failed to connect | Assumed. The one error line may be r2's, and then r1 may have received its file |
| r2 | A | The file y.tgz from b.example.org | Fetched file | Executed | Failed to connect | Assumed, in the same way |
| r3 | B | The file a.tgz from data.example.org | Fetched file | Executed | The host name did not resolve | Confirmed by its own line in c5 |
| r4 | B | The package requests | Package | Reached | Nothing further is visible | Confirmed by its own line in c4 that a download began |

Case C makes no request, so it has no row. The trial's rows for each category answer the two questions of the README, as a lower and an upper bound.

| Category | The trial has a request | The trial received one |
|---|---|---|
| Fetched file | Yes in both bounds | No in the lower bound, yes in the upper |
| Package | Yes in both bounds | No in the lower bound, yes in the upper |

## The steps at a glance

| Step | Question it answers | Case A | Case B | Case C |
|---|---|---|---|---|
| 1. Convert tool calls | What did the trajectory record? | c1 with its three commands | c2 to c5, with c3 still running | c6 with one command |
| 2. Expand tool calls | What did each call actually run, and where does that output show up? | Nothing beyond its own text, and all output is in c1's result | c3 also ran the curl line of fetch.sh. curl's output shows up in c5, pip's in c4 | setup.sh ran, and what it ran is unknown |
| 3. Extract network requests | Which of what ran is a request, and for which target? | r1 and r2 | r3 and r4 | None |
| 4. Decide request results | How far did each request get, and on what evidence? | r1 and r2 share one line | r3 and r4 each have lines of their own | Lines that no request owns are counted, and no request is made |
| 5. Export rows | Which category is each request, and what do the rows say? | Two fetched files, received only in the upper bound | A fetched file not received, and a package received only in the upper bound | No row |

Steps 1 and 2 are built to know nothing about the internet.
Outside knowledge is the facts that no trajectory holds. Each step asks for it through one class of its own, e.g. `ToolCallKnowledge`, and gets a value or unknown.

## Step 0: collect trials

Each trial folder gets a `Trial`, also when its trajectory could not be read, since a trial without requests still counts in the share of trials of its task that have one.
The values are those that the trial's `detail.json` (written by the service that ran the trial) and `status.json` (written by the script that collected the trials) hold, kept as written. Nothing outside the two files is asked, so the step has no `...Knowledge` class.

| Field | Where it comes from in the made-up trial |
|---|---|
| `task_name`, `harness`, `harness_version`, `model_name` | `task_name` and `agent_info` of `detail.json` |
| `reward` | `verifier_result.rewards.reward` of `detail.json`, as a float. It is None when the file has no verifier result |
| `benchmark_version`, `leaderboard_row_id` | The one item of `memberships` of `status.json` |
| `unreadable_trajectory` | Whether `read_trajectory` read the trajectory. It is None here, since the trajectory holds c1 to c6 |

```python
trial = Trial(
    trial_id="t1",  # the name of the trial folder
    benchmark_version="4-0-0",
    task_name="terminal-bench/fetch-data",
    leaderboard_row_id="row-1",
    harness="claude-code",
    harness_version="2.1.0",
    model_name="model-a",
    reward=0.0,
    unreadable_trajectory=None,
)
```

A trial whose trajectory file is missing gets `unreadable_trajectory=UnreadableTrajectory(MISSING)` with the same task and reward, and the later steps make no rows of requests for it.

## Step 1: convert tool calls

Each call is converted from its harness's own format into a `ToolCall`, which holds what the call asked for (its action) and what came back (its output).
The command string (`command_str`) of each `RunCommandAction` is a shell text, split into commands by shell grammar alone, with when each runs and where its output goes, into its `parsed_shell_text`. Command ids are 0-based and unique within a call.

| Asked through `ToolCallKnowledge` | Answer in this example |
|---|---|
| What does the tool `Bash` do? | It runs a command |
| How is c1's result read? | By the result format `bare_output`, the output of a command that Claude Code did not judge an error. Its result has no `Exit code` line, so `treat_bash_output_without_exit_code_line_as_finished` reads it as finished, and since the structured result beside the text says it was not interrupted, `treat_bash_output_without_exit_code_line_as_exit_code_0` gives it exit code 0 |
| How is c3's result read? | By the result format `background`, a command left running in the background, with the handle task-1 |

```python
c1.action = RunCommandAction(
    command_str="curl -sS --connect-timeout 30 -O https://a.example.org/x.tgz; curl -sS ... -O https://b.example.org/y.tgz; echo done",
    parsed_shell_text=ParsedShellText(
        commands=(
            ShellCommand(id=0, words=("curl", "-sS", "--connect-timeout", "30", "-O", "https://a.example.org/x.tgz")),
            ShellCommand(id=1, words=("curl", "-sS", "--connect-timeout", "30", "-O", "https://b.example.org/y.tgz")),
            ShellCommand(id=2, words=("echo", "done"), succeeded_if_text_exits_zero=True),
        ),
        variable_assignments=(),
    ),
)
# The exit code is echo's, so it says nothing about either curl. Only echo has `succeeded_if_text_exits_zero`.
c1.result = ToolCallResult(tool_output_text="curl: (28) ...\ndone", execution_status=FINISHED, exit_code=0, harness_result_format=MatchedFormat("bare_output"))

c3.action = RunCommandAction(
    command_str="bash fetch.sh > fetch.log 2>&1 || pip install requests",
    parsed_shell_text=ParsedShellText(
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
        variable_assignments=(),
    ),
)
c3.result = ToolCallResult(execution_status=RUNNING, handles=(ExecutionHandle(COMMAND, "task-1"),), harness_result_format=MatchedFormat("background"))
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
    ran_texts=(
        # This is c3's own command text, with the two commands that step 1 split it into.
        RanShellText(
            source=CallCommandText(),
            ran_commands=(
                RanCommand(bash_fetch_sh, program_invocations=(ProgramInvocation("bash", arguments=("fetch.sh",)),), stdout_routes=(OutputRoute((), FileDestination("fetch.log", appends=False), WHOLE),), ...),
                RanCommand(pip_install_requests, program_invocations=(ProgramInvocation("pip", subcommand_words=("install",), arguments=("requests",)),), stdout_routes=(OutputRoute((), ResultDestination(), WHOLE),), ...),
            ),
        ),
        # c2 wrote fetch.sh, and command 0 runs it. Its curl command gets id 2 and the redirects of command 0.
        RanShellText(
            source=FileText(runner_command_id=0, path="fetch.sh", writer_tool_call_key=c2),
            ran_commands=(
                RanCommand(
                    curl_a_tgz,
                    program_invocations=(
                        ProgramInvocation("curl", options=(ProgramOption("-s"), ProgramOption("-S"), ProgramOption("-O")), arguments=("https://data.example.org/a.tgz",)),
                    ),
                    stdout_routes=(OutputRoute((), FileDestination("fetch.log", appends=False), WHOLE),),
                    ...
                ),
            ),
        ),
    ),
    # c3 returned while running, so the end state is the one its poll c4 saw.
    command_text_status=CommandTextStatus(FINISHED, exit_code=0, reporter_tool_call_key=c4),
    # Only pip's output reaches a result, c3's own and that of its poll c4.
    output_places=(OutputPlace(c3, command_ids=(1,)), OutputPlace(c4, command_ids=(1,))),
    written_files=(
        # The output of bash and curl went to fetch.log, and c5 reads it with the read tool.
        WrittenFile("fetch.log", writers=(WrittenFileWriter(0, STDOUT), WrittenFileWriter(0, STDERR), WrittenFileWriter(2, STDOUT), WrittenFileWriter(2, STDERR)), file_uses=(FileUse(c5, None, SHOWS_CONTENT),)),
        # curl writes this file itself if it succeeds. No later call uses it.
        WrittenFile("a.tgz", writers=(WrittenFileWriter(2, OWN_OUTPUT_FILE),), file_uses=()),
    ),
    file_uses_without_known_writer=(),
)

c6_expanded = ExpandedToolCall(
    tool_call=c6,
    ran_texts=(
        RanShellText(source=CallCommandText(), ran_commands=(RanCommand(bash_setup_sh, ...),)),
        # No call of the trial wrote setup.sh, so what it ran is unknown.
        UnknownRanText(source=FileTextWithoutKnownWriter(runner_command_id=0, path="setup.sh"), reason=NOT_WRITTEN_IN_TRIAL),
    ),
    command_text_status=CommandTextStatus(FINISHED, exit_code=0, reporter_tool_call_key=c6),
    output_places=(OutputPlace(c6, command_ids=(0,)),),
    written_files=(),
    # A line in c6's result can be content of setup.sh, which the task image holds.
    file_uses_without_known_writer=(FileUseWithoutKnownWriter(0, "setup.sh", USES_CONTENT),),
)
```

Fields that hold their empty value are left out as `...`, and the test `tests/expanded_tool_call/test_expand_tool_calls.py` checks the same values. The entry function `expand_tool_calls` gets them by calling its pieces in this order.

| Piece | What it gives |
|---|---|
| `expand_poll_links` | c4 polls task-1, which c3 started |
| `expand_ran_texts` | The texts each call ran, following fetch.sh as c2 wrote it, and each touch of a file |
| `expand_command_text_status` | The end state of c3's text, from c4 |
| `expand_output_places` | The results where the output of each call's commands shows |
| `expand_written_files` | fetch.log and a.tgz with their writers, and c5's read of fetch.log |
| `expand_file_uses_without_known_writer` | c6's use of setup.sh |

In case A, `c1_expanded` holds only c1's own text. All three commands reach c1's result, and the two curl commands are to write x.tgz and y.tgz, which no later call uses.

## Step 3: extract network requests

For everything a call ran, the step asks whether it fetches its target.
When the answer is yes, the step makes one request per target and marks it as a confirmed request. When the answer is no, it makes none.
When the answer is unknown, the step makes an uncertain request only if a URL that may be public is visible, e.g. for `mytool https://a.example.org/x`.
A program that runs another text the trial holds gives no request itself, e.g. bash of `bash fetch.sh`, since the commands of that text give them.
The step looks only at what ran, and step 4 reads what came back.

| Asked through `NetworkRequestKnowledge` | Answer in this example |
|---|---|
| Does curl fetch? | Yes. Each URL argument is a target, and what it receives goes to stdout unless the command writes a file of its own |
| What do curl's `-s`, `-S`, `--connect-timeout` and `-O` change about the request? | Nothing. The file that `-O` writes comes from step 2 |
| Does `pip install` fetch? | Yes. Each package name is a target, and pip keeps what it receives in files of its own |
| Does `echo` fetch? | No |
| Does `bash` fetch? | There is no row, and it runs fetch.sh, whose commands give the requests |

An option that has no row in the catalog of this step makes the request uncertain, since it may be one that sends nothing, e.g. `--version`. The catalog has rows for the options of fetching programs that the sample of trials uses, e.g. `-s`, `-L` and `-X POST` of curl, `-q` of pip and `-y` of apt-get, while `curl -X $1 u` stays uncertain because `$1` may be `HEAD`.

```python
# c3's own text has `bash fetch.sh` with id 0 and `pip install requests` with id 1, and the curl of fetch.sh gets the next id 2 of the call.
# The requests of a call follow the command ids, then the code texts, then the web tool steps, and are numbered from 0 in the call.
r4 = NetworkRequest(
    tool_call_key=c3,
    index_in_tool_call=0,
    source=FromCommand(command_id=1, ran_text_source=CallCommandText(), program_invocation=ProgramInvocation("pip", subcommand_words=("install",), arguments=("requests",))),
    target="requests",
    target_kind=PACKAGE_NAME,
    # No index option names a host.
    host_names=(),
    # pip keeps what it receives in files of its own, which the words do not name.
    received_content_destination=ContentSaved(path=None),
    certainty=CONFIRMED,
    uncertainty_reason=None,
)
r3 = NetworkRequest(
    tool_call_key=c3,
    index_in_tool_call=1,
    # c3 ran it, though c2 wrote fetch.sh.
    source=FromCommand(command_id=2, ran_text_source=FileText(runner_command_id=0, path="fetch.sh", writer_tool_call_key=c2), program_invocation=ProgramInvocation("curl", options=(ProgramOption("-s"), ProgramOption("-S"), ProgramOption("-O")), arguments=("https://data.example.org/a.tgz",))),
    target="https://data.example.org/a.tgz",
    target_kind=URL,
    host_names=("data.example.org",),
    # Step 2 recorded a.tgz as the file that curl writes itself.
    received_content_destination=ContentSaved(path="a.tgz"),
    certainty=CONFIRMED,
    uncertainty_reason=None,
)
```

The test `tests/network_request/test_extract_network_requests.py` checks the same values. r1 and r2 of case A look like r3, with `tool_call_key=c1`, `command_id=0` and `1`, the call's own text as the source and `ContentSaved` of x.tgz and y.tgz. echo gives no request.
Case C gives no request here. `bash` runs setup.sh, whose content is unknown, and the words of the command show no URL.
The entry function `extract_network_requests` calls these pieces for each call.

| Piece | What it gives |
|---|---|
| `extract_command_network_requests` | The requests of each command by its id, r1, r2, r4 and r3 |
| `extract_code_network_requests` | The requests of each Python or JavaScript code text, none here |
| `extract_web_tool_network_requests` | The requests of each web search, fetch or find, none here |

Each run, code call or URL in code that gives no request is counted by its reason, e.g. echo of c1 as a program that does not fetch.

## Step 4: decide request results

The step reads the result of every call, including those that no request reaches, and keeps the lines that an output line pattern fits.
A line goes to the requests whose output reaches its place, whose run can print it and whose target it does not contradict.

| Requests that own the line | What the line becomes |
|---|---|
| One | That request's own evidence |
| Several | Evidence they share. A result that rests on it is only assumed |
| None | No evidence and no request. The line is counted by its reason, e.g. it shows a file's content after `cat README.md`, or a run whose content is unknown reaches its place |

Then each request is judged on its own evidence, i.e. its lines, the exit code of the text that ran it, the status of its call and later uses of the file it saved.
`request_certainty_after_evidence` says how sure the pipeline is that something is a request, and `level_certainty` says how sure it is of how far the request got. An assumed result lists every reason of that in `assumption_reasons`, e.g. a line that other requests own too, named by where it is so that the results that share it can be found together, or a judgment rule. Line indexes are 0-based.

| Asked through `NetworkRequestResultKnowledge` | Answer in this example |
|---|---|
| What does `Could not resolve host: X` mean? | The host name did not resolve, and any program may print it |
| What does `Connection timed out` mean? | No connection was made, and any program may print it |
| What does `Successfully installed X` mean, and who prints it? | A package was installed, printed by pip |
| Which lines does a run of `pip install` print? | pip's |
| Which lines does a run of `curl -sS -O` print? | curl's |
| Which lines does a run of `curl -sS --connect-timeout 30 -O` print? | Unknown, since `--connect-timeout` has no row of `program_output_lines.csv`, so the run may print any line. The key `(curl, "", --connect-timeout)` is counted as an unknown input |

| Output place | Commands that reach it | Lines a pattern fits | Owner | Result |
|---|---|---|---|---|
| c1's result | curl x.tgz, curl y.tgz, echo | `Connection timed out` | r1 and r2 share it | Both executed, failed, assumed |
| c4's result | bash and pip of c3 | `Downloading requests-2.32.3`, `Successfully installed requests-2.32.3` | r4 | Reached, not visible, confirmed |
| c5's result | bash and curl of c3, through fetch.log | `Could not resolve host: data.example.org` | r3 | Executed, failed, confirmed |
| c6's result | bash of c6, which ran unknown content | `Downloading torch-2.3.0`, `Successfully installed torch-2.3.0` | None | Two lines counted as unused under `UNOWNED_LINE_IN_UNKNOWN_RUN`, and by the program `bash` that reaches the place |

```python
r1.result = NetworkRequestResult(
    network_request=r1,
    request_certainty_after_evidence=r1.certainty,
    level=EXECUTED,
    stop_reason=FAILED,
    # The only failure line may be r2's.
    level_certainty=ASSUMED,
    evidence=(OutputLineEvidence(showing_tool_call_key=c1, line_index=0, line_index_in_json_string=None, kind=CONNECTION_FAILED, is_shared_with_other_requests=True),),
    # r2's result names the same line.
    assumption_reasons=(SharedOutputLineAssumptionReason(showing_tool_call_key=c1, line_index=0, line_index_in_json_string=None),),
)
r4.result = NetworkRequestResult(
    network_request=r4,
    request_certainty_after_evidence=CONFIRMED,
    # A download began, so a server answered. `Successfully installed` alone does not show that the content arrived, since a cache can give it.
    level=REACHED,
    stop_reason=NOT_VISIBLE,
    level_certainty=CONFIRMED,
    evidence=(
        OutputLineEvidence(showing_tool_call_key=c4, line_index=0, line_index_in_json_string=None, kind=DOWNLOAD_STARTED, is_shared_with_other_requests=False),
        OutputLineEvidence(showing_tool_call_key=c4, line_index=1, line_index_in_json_string=None, kind=INSTALLED, is_shared_with_other_requests=False),
    ),
    assumption_reasons=(),
)
```

r3 owns its line alone, and no run whose lines are unknown reaches c5, so its failure is confirmed.
No request here gets evidence that it ran from an exit code. The exit code 0 of c1 belongs only to echo, the one command that `succeeded_if_text_exits_zero` marks, and in c3 no command is marked, since pip runs only if bash failed and curl is in fetch.sh. So each of the four requests counts `treat_command_without_own_evidence_as_no_evidence_of_run` once, and its level comes from its lines.
Case C gives no request. If setup.sh did fetch torch, that request is missing from both bounds, and only the count of unused lines shows it.
Had a later call unpacked x.tgz, that use would be r1's own evidence that its content arrived.
The entry function `decide_network_request_results` calls these pieces in order.

| Piece | What it gives |
|---|---|
| `decide_output_place_sources` | For each call whose result shows output, every command whose output reaches it, e.g. bash and curl of c3 for c5's read of fetch.log |
| `decide_output_line_meanings` | For each call, the lines of its result that a pattern fits, with their meaning |
| `decide_output_line_owners` | For each such line, the requests that own it, counting the lines without an owner by reason |
| `decide_network_request_result_evidence` | For each request, its evidence with the level and stop reason each piece shows |
| `decide_one_network_request_result` | For each request, the result from its evidence |

Some results need a choice that facts alone do not settle, e.g. whether a line that a run of unknown output may have printed is shared. Such choices are the provisional judgment rules of `network_request_result/judgment_rules.py`, and each use of one is counted.

## Step 5: export rows

Computed columns are added, credentials are redacted, and the rows of [Where this ends](#where-this-ends) are made.
The category is computed from what the request's own text shows, so the same command gets the same category whether it failed or not.

| Asked through `ExportKnowledge` | Answer in this example |
|---|---|
| Which service does the public host data.example.org give? | Unknown, since no row of `public_hosts.csv` names it, so the row's `host_service` is `unknown`. A known service would be e.g. a package registry or code hosting |
| Which registry does `pip install` ask when no setting names another? | `pypi`, at the host `pypi.org` |

| Column | What it gives here | Why |
|---|---|---|
| Category | Fetched file for r1 to r3, which save what a URL gives. Package for r4 | The category rules of the step |
| Internet use | Yes for all four | r1 to r3 name their hosts, which are read as public in this example. r4 names no host, so `treat_request_without_host_name_as_sent_to_default_registry_host` gives it the host of the default registry of `pip install`, `pypi.org`, which is public |
| Request bounds | Both bounds for r1 to r4 | Each is a confirmed request that is internet use. How far it got does not matter here |
| Received bounds | Neither for r3, the upper bound only for r1, r2 and r4 | r3's own line confirms that it failed. r1 and r2 share one error line, so their failure is assumed and `treat_assumed_failure_as_possibly_received` keeps them in the upper bound. r4's lines show that a download began but not that the package arrived |

Each category of the trial then gets one row with the strongest bounds of its requests, which gives the last table of [Where this ends](#where-this-ends). The trial row takes the strongest bounds of all requests that the task environment sent.
The lines of case C give no request and no row. `decide_network_request_results` only counts them as unused lines.
Some columns need a choice that facts alone do not settle, e.g. whether a request that names no host goes to the default registry of its program. Such choices are the provisional judgment rules of `export/judgment_rules.py`, and each use of one is counted.
The entry function `export_rows` calls these pieces in order.

| Piece | What it gives |
|---|---|
| `export_network_request_row` | For each request, its row, with the category from `export_network_request_category` and its text columns passed through `redact_credentials` |
| `export_trial_row` | The trial row, with the bounds of all requests that the task environment sent |
| `export_trial_category_measure_rows` | One row per category and sender of the trial's requests, with the strongest bounds of its requests |

`run_steps_of_trial` in `pipeline.py` runs all six steps on one trial folder, and `scripts/run_pipeline.py` runs it on every trial and writes the rows.

## What these cases leave out

- Output that passes through another command before it is shown, e.g. `curl u | tail -1`.
- A saved file that a later call uses, e.g. `tar xzf a.tgz`, as evidence that its content arrived.
- Loops and variables, e.g. `for p in a b; do pip install $p; done`.
- Code text, e.g. `python client.py`, which is not split into commands and is read for requests in step 3.
- Web tools, and text typed into a running process.
- Requests that are uncertain although the program is known: one that fetches only when something is missing, e.g. `npx tsc`, and one with an option that no fact covers.
- A request that needed to send nothing, e.g. pip printing `Requirement already satisfied`.
