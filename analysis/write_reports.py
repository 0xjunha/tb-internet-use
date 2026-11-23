"""Save each report that the reading workflow returned as the report file that `check_reports.py` reads.

The workflow returns one object per reading with its `label`, `trial_id`, `reader_index`, `reading_group` and `report`, where `report` is null for a reading that failed, so such a reading gets no file and its label is printed to run it again. The reports can also be taken from the journals of workflow runs, e.g. of a run that stopped before it returned, where a line of type `started` ties an agent to the label of its reading and a line of type `result` holds its report.

Run it as `uv run python -I analysis/write_reports.py <out_dir> --workflow-result <json>` or `--journal <journal.jsonl> [<journal.jsonl> ...]`.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "out_dir", type=Path, help="the folder with readings.json, where reports/ goes"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--workflow-result",
        type=Path,
        help="a JSON file with the list that the reading workflow returned",
    )
    source.add_argument(
        "--journal",
        type=Path,
        nargs="+",
        help="the journal.jsonl of one or more runs of the reading workflow",
    )
    arguments = parser.parse_args()

    if arguments.workflow_result is not None:
        workflow_results = json.loads(arguments.workflow_result.read_text())
    else:
        readings = json.loads((arguments.out_dir / "readings.json").read_text())
        workflow_results = workflow_results_of_journals(
            [
                [
                    json.loads(line)
                    for line in path.read_text().splitlines()
                    if line.strip()
                ]
                for path in arguments.journal
            ],
            readings,
        )
    failed_labels = write_reports(workflow_results, arguments.out_dir / "reports")
    print(
        f"wrote {len(workflow_results) - len(failed_labels)} reports, {len(failed_labels)} readings without a report"
    )
    for label in failed_labels:
        print(f"  {label}")


def workflow_results_of_journals(
    journals: Sequence[Sequence[dict[str, Any]]], readings: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Give the objects that the workflow would have returned for the agents that the journals show starting, with the report of each agent's `result` line and a null report for an agent without one.

    The agent ids of one journal are its own, so each journal is read apart, and a reading of a later journal replaces one of an earlier journal only when it has a report.
    """
    readings_by_label = {reading["label"]: reading for reading in readings}
    results_by_label: dict[str, dict[str, Any]] = {}
    for journal in journals:
        labels_by_agent = {
            line["agentId"]: line["label"]
            for line in journal
            if line.get("type") == "started"
        }
        reports_by_agent = {
            line["agentId"]: line["result"]
            for line in journal
            if line.get("type") == "result"
        }
        for agent_id, label in labels_by_agent.items():
            reading = readings_by_label[label]
            report = reports_by_agent.get(agent_id)
            if report is None and label in results_by_label:
                continue
            results_by_label[label] = {
                "label": label,
                "trial_id": reading["trial_id"],
                "reader_index": reading["reader_index"],
                "reading_group": reading["reading_group"],
                "report": report,
            }
    return list(results_by_label.values())


def write_reports(
    workflow_results: Sequence[dict[str, Any]], reports_dir: Path
) -> list[str]:
    """Write each report that is not null to `<trial_id>_<reader_index>.json` in `reports_dir`, and give the labels of the readings whose report is null."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    failed_labels: list[str] = []
    for workflow_result in workflow_results:
        report = workflow_result.get("report")
        if report is None:
            failed_labels.append(workflow_result["label"])
            continue
        report_path = (
            reports_dir
            / f"{workflow_result['trial_id']}_{workflow_result['reader_index']}.json"
        )
        report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return failed_labels


if __name__ == "__main__":
    main()
