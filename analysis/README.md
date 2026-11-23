# Trajectory analysis

Scripts that pick a small set of trials from a pipeline run, write what a reader of each trial gets, and check what the readers return. The readers are run by the workflow script that `write_reading_workflow.py` writes, one per reading.

| Script | What it does | Writes under `<out_dir>` |
|---|---|---|
| `pick_trials.py` | Recomputes the tasks to read from the rows of a run and fails when they differ from the task tables in `reading_groups.py`, then draws the trials of each reading group with a fixed seed | `picked_trials.csv`, `qualifying_trial_counts.csv` |
| `write_reading_materials.py` | Writes per picked trial its request rows and a text dump of its trajectory, with only the first 1,500 and last 1,000 characters of a long observation and images left out, beside a link to the raw trajectory | `trials/<trial_id>/requests.csv`, `trials/<trial_id>/trajectory_dump.txt`, `trials/<trial_id>/trajectory.json` |
| `reading_prompt.py` | Joins the prompt parts of each reading group, fills them with the trial's values and gives the JSON Schema of its report. A trial of `requested_and_solved` gets two readings | `readings.json`, `trials/<trial_id>/work_<reader_index>/prompt.txt` |
| `write_reading_workflow.py` | Writes the workflow script that runs one reader per reading, with the schemas and prompt paths embedded, since the tool that runs it reads no files | `reading_workflow.js` |
| `write_reports.py` | Saves each report of the list that the workflow returns, or of the journals of its runs, and prints the labels of readings that returned none | `reports/<trial_id>_<reader_index>.json` |
| `list_missing_readings.py` | Prints as a JSON list the labels of the readings without a report, optionally of one task, to resume a stopped run, and the count per task and reading group | nothing |
| `check_reports.py` | Flags what a schema cannot enforce in `reports/<trial_id>_<reader_index>.json`, e.g. a step id that is not in the trajectory, derives facts from the step ids of each request group, and writes the labels that `report_labels.py` derives from the facts a reader recorded, since readers pick no label | `report_flags.csv`, `derived_report_facts.csv`, `group_labels.csv`, `step_labels.csv`, `effects.csv`, `trial_use_summaries.csv` (with how the first request started and what reached the graded answer), `other_answers.csv` |
| `count_report_values.py` | Counts the recorded values and derived labels over all reports, per reading group, task, harness and pair, giving a trial read twice by reader 0, by both readers and by either reader | `trial_use_summary_counts.csv`, `first_request_start_counts.csv`, `effect_counts.csv`, `failed_request_counts.csv`, `without_entry_counts.csv`, `online_rule_counts.csv`, `disputed_row_counts.csv`, `content_kind_counts.csv`, `unconfirmed_command_entries.csv` |
| `write_task_materials.py` | Writes per task one Markdown file that a summary writer can read alone: the picked trials, derived labels and where readers differ, check flags, the hosts of the requests of all trials of the task from the pipeline rows, and the reports in compact form, marked as data | `task_materials/<task>.md` |
| `reader_agreement.py` | Compares the two readers of a trial on each request step, by its full and by a merged label (received, not received, access test only), since they may group steps differently, on the trial as a whole, and on their failed requests matched by shared steps | `reader_agreement.csv`, `step_comparisons.csv`, `step_label_confusion.csv`, `trial_comparisons.csv`, `entry_matches.csv`, `unmatched_entries.csv` |

Readers record facts and no labels, e.g. why the agent asked (`shown_before_request`, the first that fits of `failed_step`, `earlier_response_led_here`, `agent_wants_to_check_own_answer`, `agent_says_what_it_will_get`, ...). `first_request_start` judges all groups tied at the earliest first request step together: a failed step there, or before an access test that starts earlier, gives `after_failed_step`, and otherwise their prior candidates decide, whatever other reason is given. `trial_use_summary` counts only the effects of groups with a `wanted_content` or `success_only` step, which `effects.csv` marks in `group_has_received_step`, and takes the first that holds of `no_request`, `graded_answer_made_or_changed`, `graded_answer_checked_only`, `no_effect_on_graded_answer_shown`, `content_not_recorded` (a group whose steps are all `not_recorded`), `no_content_received` and `cannot_judge` (only `other` responses).

The other modules hold what the scripts share: `pipeline_rows.py` reads the rows of a run, `report_files.py` reads the picked trials with their reports, `report_labels.py` derives the labels of groups, steps and trials, `reading_groups.py` holds the groups, their tasks and conditions, `trajectory_steps.py` lists the steps of a trajectory and its subagent trajectories, and `output_files.py` writes CSV files.

## Order and commands

Run from the repo root. Every path is an argument. The run below is the one of 2026-11-22 on Terminal-Bench 4.1.

```sh
run=out/pipeline_all_4_1_11
raw=~/src/tb-internet-use-data/terminal-bench-4-1-0-20261119/raw
out=out/trajectory_analysis

nice -n 10 uv run python -I analysis/pick_trials.py $run $out --seed 0
nice -n 10 uv run python -I analysis/write_reading_materials.py $run $raw $out
nice -n 10 uv run python -I analysis/reading_prompt.py $run $out \
  --task-dirs ~/src/terminal-bench/tasks ~/src/terminal-bench/legacy
uv run python -I analysis/write_reading_workflow.py $out
# Run $out/reading_workflow.js and save the list it returns, e.g. as $out/workflow_result.json.
uv run python -I analysis/write_reports.py $out --workflow-result $out/workflow_result.json
# or, from the journals of workflow runs:
# uv run python -I analysis/write_reports.py $out --journal <journal.jsonl> ...
# Labels of the readings still without a report, to run them again:
# uv run python -I analysis/list_missing_readings.py $out [--task <name>]
uv run python -I analysis/check_reports.py $raw $out
uv run python -I analysis/reader_agreement.py $out
uv run python -I analysis/count_report_values.py $out
nice -n 10 uv run python -I analysis/write_task_materials.py $run $out
```

`--task-dirs` lists the folders that hold a folder per task, searched in order, since some tasks of 4.1 have moved from `tasks/` to `legacy/` of the benchmark repo.
