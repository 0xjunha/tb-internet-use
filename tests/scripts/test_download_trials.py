"""Tests for scripts/download_trials.py, i.e. the trial lists of leaderboards, the folders it writes and how a later run treats them, with a made-up Harbor Hub in place of the network."""

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Self

import pytest

from tb_internet_use.pipeline import read_trial_file_texts
from tb_internet_use.trial import collect_trials

_SPEC = importlib.util.spec_from_file_location(
    "download_trials", Path(__file__).parents[2] / "scripts/download_trials.py"
)
assert _SPEC is not None and _SPEC.loader is not None
download_trials_module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = download_trials_module
_SPEC.loader.exec_module(download_trials_module)

PACKAGE = "terminal-bench/terminal-bench"
TRIAL_A = "00000000-0000-4000-8000-00000000000a"
TRIAL_B = "00000000-0000-4000-8000-00000000000b"
TRIAL_C = "00000000-0000-4000-8000-00000000000c"
ROW_1 = "11111111-0000-4000-8000-000000000001"
ROW_2 = "11111111-0000-4000-8000-000000000002"
ROW_OLD = "11111111-0000-4000-8000-000000000000"
LEADERBOARD_ENDPOINT = download_trials_module.LEADERBOARD_ENDPOINT
ROW_TRIAL_ENDPOINT = download_trials_module.ROW_TRIAL_ENDPOINT
# The name under which `FakeHub.requests` records a request of an asset.
ASSET_REQUEST = "asset"


def trial_id_of(number: int) -> str:
    """Give a made-up trial id of the form Harbor Hub uses, one per number, rising with the number."""
    return f"00000000-0000-4000-8000-{number:012d}"


def detail_of(trial_id: str, **changes: Any) -> dict[str, Any]:
    """Give a made-up detail of a trial as `get_trial_detail` returns it, with storage paths of both assets."""
    return {
        "id": trial_id,
        "job_id": "job-1",
        "task_name": "terminal-bench/fix-git",
        "agent_info": {
            "name": "claude-code",
            "version": "2.1.0",
            "model_info": {"name": "model-a"},
        },
        "verifier_result": {"rewards": {"reward": 1.0}},
        "trajectory_path": f"{trial_id}/agent/trajectory.json",
        "archive_path": f"{trial_id}/trial.tar.gz",
    } | changes


def leaderboard_row(row_id: str, trial_count: int | None) -> dict[str, Any]:
    """Give a made-up row of a leaderboard as `leaderboard-read` returns it."""
    return {"id": row_id, "n_trials": trial_count, "status": "display"}


class FakeAssetResponse:
    """Made-up answer of an asset, which can claim more bytes than it holds or give no `Content-Length`."""

    def __init__(self, data: bytes, content_length: int | None) -> None:
        self.data = data
        self.offset = 0
        self.headers = (
            {} if content_length is None else {"Content-Length": str(content_length)}
        )

    def read(self, size: int) -> bytes:
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        pass


class FakeHub:
    """Made-up Harbor Hub that answers from dicts and records each request by endpoint."""

    def __init__(
        self,
        *,
        leaderboards: dict[str, list[list[dict[str, Any]]]],
        row_trial_ids: dict[str, list[str]],
        details: dict[str, Any] | None = None,
        assets: dict[str, bytes] | None = None,
        short_storage_paths: Sequence[str] = (),
        storage_paths_without_length: Sequence[str] = (),
        failing_request_count: int = 0,
        ignores_offset: bool = False,
        rows_added_between_pages: int = 0,
        answers_by_endpoint: dict[str, bytes] | None = None,
    ) -> None:
        # The pages of rows of each leaderboard by name.
        self.leaderboards = leaderboards
        self.row_trial_ids = row_trial_ids
        self.details = details or {}
        self.assets = assets or {}
        # Storage paths whose answer claims one byte more than it holds.
        self.short_storage_paths = short_storage_paths
        self.storage_paths_without_length = storage_paths_without_length
        # The first requests that raise, as a dropped connection does.
        self.failing_request_count = failing_request_count
        # Whether row trial pages always start at the first trial, as a Hub that drops the offset would.
        self.ignores_offset = ignores_offset
        # Rows that the reported total counts beyond the pages, as when rows are added while the pages are read.
        self.rows_added_between_pages = rows_added_between_pages
        # Fixed answers that replace those of an endpoint, e.g. an error text.
        self.answers_by_endpoint = answers_by_endpoint or {}
        self.requests: list[str] = []

    def fetch_response_bytes(
        self,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> bytes:
        self.requests.append(endpoint)
        if self.failing_request_count:
            self.failing_request_count -= 1
            raise OSError("connection reset")
        if endpoint in self.answers_by_endpoint:
            return self.answers_by_endpoint[endpoint]
        if endpoint == LEADERBOARD_ENDPOINT:
            assert body is not None and body["package"] == PACKAGE
            pages = self.leaderboards[body["name"]]
            answer: Any = {
                "rows": pages[body["page"] - 1],
                "pagination": {
                    "page": body["page"],
                    "total": sum(len(page) for page in pages)
                    + self.rows_added_between_pages,
                    "total_pages": len(pages),
                },
            }
        elif endpoint == ROW_TRIAL_ENDPOINT:
            assert params is not None
            trial_ids = self.row_trial_ids[str(params["row_id"]).removeprefix("eq.")]
            offset = 0 if self.ignores_offset else int(params["offset"])
            limit = int(params["limit"])
            answer = [
                {"trial_id": trial_id, "created_at": "2026-11-03"}
                for trial_id in trial_ids[offset : offset + limit]
            ]
        else:
            assert body is not None
            answer = self.details.get(body["p_trial_id"])
        return json.dumps(answer).encode()

    def open_asset(self, storage_path: str) -> FakeAssetResponse:
        self.requests.append(ASSET_REQUEST)
        data = self.assets[storage_path]
        if storage_path in self.storage_paths_without_length:
            return FakeAssetResponse(data, None)
        extra_byte_count = 1 if storage_path in self.short_storage_paths else 0
        return FakeAssetResponse(data, len(data) + extra_byte_count)


def hub_of_trials(trial_ids: Sequence[str], **options: Any) -> FakeHub:
    """Give a hub with one leaderboard `4-1-0` whose one row lists the trials, each with a detail and both assets."""
    assets: dict[str, bytes] = {}
    for trial_id in trial_ids:
        assets[f"{trial_id}/agent/trajectory.json"] = b'{"steps": []}'
        assets[f"{trial_id}/trial.tar.gz"] = b"archive " + trial_id.encode()
    return FakeHub(
        leaderboards={"4-1-0": [[leaderboard_row(ROW_1, len(trial_ids))]]},
        row_trial_ids={ROW_1: list(trial_ids)},
        details=options.pop(
            "details", {trial_id: detail_of(trial_id) for trial_id in trial_ids}
        ),
        assets=assets,
        **options,
    )


def run(
    hub: FakeHub,
    collection_dir: Path,
    leaderboard_names: Sequence[str] = ("4-1-0",),
    **options: Any,
) -> int:
    """Run `download_trials` without waiting between attempts and give its count of trials with errors."""
    return download_trials_module.download_trials(
        hub,
        collection_dir,
        package=PACKAGE,
        leaderboard_names=leaderboard_names,
        sleep=lambda seconds: None,
        **options,
    )


def status_of(collection_dir: Path, trial_id: str) -> dict[str, Any]:
    """Read the `status.json` of a trial of the collection."""
    return json.loads((collection_dir / "raw" / trial_id / "status.json").read_text())


def lines_of(path: Path) -> list[Any]:
    """Read a JSON lines file."""
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_downloaded_folders_give_collect_trials_the_leaderboard_row_and_version(
    tmp_path: Path,
):
    hub = hub_of_trials([TRIAL_A])

    assert run(hub, tmp_path) == 0

    trial_dir = tmp_path / "raw" / TRIAL_A
    assert (trial_dir / "trajectory.json").read_bytes() == b'{"steps": []}'
    (trial,) = collect_trials([read_trial_file_texts(trial_dir)], {})
    assert (trial.benchmark_version, trial.leaderboard_row_id, trial.task_name) == (
        "4-1-0",
        ROW_1,
        "terminal-bench/fix-git",
    )
    status = status_of(tmp_path, TRIAL_A)
    assert {name: state["status"] for name, state in status["assets"].items()} == {
        "metadata": "downloaded",
        "trajectory": "downloaded",
        "archive": "downloaded",
    }
    assert status["trial_url"] == (
        f"https://hub.harborframework.com/jobs/job-1/trials/{TRIAL_A}"
    )
    assert lines_of(tmp_path / "manifest.jsonl") == [status]
    collection = json.loads((tmp_path / "collection.json").read_text())
    assert collection["finished_at"] is not None
    assert (collection["population_trials"], collection["errors"]) == (1, 0)


def test_targets_join_every_page_and_every_leaderboard_that_lists_a_trial(
    tmp_path: Path,
):
    # The row of 4-1-0 lists 1001 trials, one more than a page of row trials holds, and its leaderboard has two pages of rows. 4-0-0 lists the first trial too.
    many_trial_ids = [trial_id_of(number) for number in range(1001)]
    hub = FakeHub(
        leaderboards={
            "4-0-0": [[leaderboard_row(ROW_OLD, 1)]],
            "4-1-0": [
                [leaderboard_row(ROW_1, 1001)],
                [leaderboard_row(ROW_2, None)],
            ],
        },
        # The made-up Hub lists the trials of ROW_2 out of order, so the targets must sort them.
        row_trial_ids={
            ROW_OLD: [many_trial_ids[0]],
            ROW_1: many_trial_ids,
            ROW_2: [TRIAL_C, TRIAL_B],
        },
        details={TRIAL_C: detail_of(TRIAL_C, trajectory_path=None, archive_path=None)},
    )

    with pytest.raises(ValueError, match="do not rise"):
        run(hub, tmp_path / "unsorted", ["4-1-0", "4-0-0"])
    hub.row_trial_ids[ROW_2] = [TRIAL_B, TRIAL_C]
    run(hub, tmp_path, ["4-1-0", "4-0-0"], trial_ids=[TRIAL_C])

    targets = lines_of(tmp_path / "targets.jsonl")
    assert len(targets) == 1003
    assert [target["trial_id"] for target in targets] == sorted(
        target["trial_id"] for target in targets
    )
    memberships_by_trial_id = {
        target["trial_id"]: target["memberships"] for target in targets
    }
    assert memberships_by_trial_id[many_trial_ids[0]] == [
        {"version": "4-0-0", "row_id": ROW_OLD},
        {"version": "4-1-0", "row_id": ROW_1},
    ]
    assert memberships_by_trial_id[TRIAL_C] == [{"version": "4-1-0", "row_id": ROW_2}]
    collection = json.loads((tmp_path / "collection.json").read_text())
    assert collection["trials_with_several_memberships"] == 1
    assert collection["selected_trials"] == 1
    assert sorted(path.name for path in (tmp_path / "snapshots").iterdir()) == [
        "board-4-0-0-1.json",
        "board-4-1-0-1.json",
        "board-4-1-0-2.json",
        f"row-{ROW_OLD}-0.json",
        f"row-{ROW_1}-0.json",
        f"row-{ROW_1}-1000.json",
        f"row-{ROW_2}-0.json",
    ]


def test_a_row_of_exactly_one_page_of_trials_asks_for_one_empty_page_more(
    tmp_path: Path,
):
    trial_ids = [trial_id_of(number) for number in range(1000)]
    hub = FakeHub(
        leaderboards={"4-1-0": [[leaderboard_row(ROW_1, 1000)]]},
        row_trial_ids={ROW_1: trial_ids},
    )

    run(hub, tmp_path, limit=1)

    assert len(lines_of(tmp_path / "targets.jsonl")) == 1000
    assert hub.requests.count(ROW_TRIAL_ENDPOINT) == 2


def test_a_hub_that_drops_the_offset_stops_the_run_instead_of_asking_without_end(
    tmp_path: Path,
):
    hub = FakeHub(
        leaderboards={"4-1-0": [[leaderboard_row(ROW_1, 1500)]]},
        row_trial_ids={ROW_1: [trial_id_of(number) for number in range(1500)]},
        ignores_offset=True,
    )

    with pytest.raises(ValueError, match="do not rise from offset 1000"):
        run(hub, tmp_path)


@pytest.mark.parametrize(
    ("hub", "message"),
    [
        pytest.param(
            FakeHub(
                leaderboards={"4-1-0": [[leaderboard_row(ROW_1, 3)]]},
                row_trial_ids={ROW_1: [TRIAL_A, TRIAL_B]},
            ),
            "n_trials 3 but lists 2",
            id="row with another trial count than it lists",
        ),
        pytest.param(
            FakeHub(leaderboards={"4-1-0": [[]]}, row_trial_ids={}),
            "has no rows",
            id="leaderboard without rows, e.g. a mistyped name",
        ),
        pytest.param(
            FakeHub(
                leaderboards={
                    "4-1-0": [[leaderboard_row(ROW_1, 1)], [leaderboard_row(ROW_1, 1)]]
                },
                row_trial_ids={ROW_1: [TRIAL_A]},
            ),
            "changed between pages",
            id="row on two pages",
        ),
        pytest.param(
            FakeHub(
                leaderboards={"4-1-0": [[leaderboard_row(ROW_1, 1)]]},
                row_trial_ids={ROW_1: [TRIAL_A]},
                rows_added_between_pages=1,
            ),
            "changed between pages",
            id="fewer rows than the reported total",
        ),
        pytest.param(
            FakeHub(
                leaderboards={"4-1-0": [[leaderboard_row(ROW_1, 1)]]},
                row_trial_ids={ROW_1: ["../outside"]},
            ),
            "unknown form",
            id="trial id of another form",
        ),
        pytest.param(
            FakeHub(
                leaderboards={"4-1-0": [[leaderboard_row("../outside", 1)]]},
                row_trial_ids={},
            ),
            "unknown form",
            id="row id of another form",
        ),
    ],
)
def test_lists_that_do_not_add_up_stop_the_run_before_any_target(
    tmp_path: Path, hub: FakeHub, message: str
):
    with pytest.raises(ValueError, match=message):
        run(hub, tmp_path)

    assert not (tmp_path / "targets.jsonl").exists()
    assert not (tmp_path / "raw").exists()
    assert json.loads((tmp_path / "collection.json").read_text())["finished_at"] is None


@pytest.mark.parametrize(
    ("endpoint", "answer"),
    [
        pytest.param(LEADERBOARD_ENDPOINT, b"<html>bad gateway</html>", id="not JSON"),
        pytest.param(
            LEADERBOARD_ENDPOINT, b'{"error": "not found"}', id="board without rows"
        ),
        pytest.param(
            ROW_TRIAL_ENDPOINT, b'{"message": "timeout"}', id="row page that is no list"
        ),
    ],
)
def test_an_answer_of_another_shape_is_not_saved_so_a_later_run_asks_again(
    tmp_path: Path, endpoint: str, answer: bytes
):
    hub = hub_of_trials([TRIAL_A], answers_by_endpoint={endpoint: answer})

    with pytest.raises(ValueError):
        run(hub, tmp_path)
    assert not any(
        path.name.startswith("board-" if endpoint == LEADERBOARD_ENDPOINT else "row-")
        for path in (tmp_path / "snapshots").glob("*")
    )

    assert run(hub_of_trials([TRIAL_A]), tmp_path) == 0


def test_a_leaderboard_name_with_a_slash_stops_the_run(tmp_path: Path):
    with pytest.raises(ValueError, match="not a name"):
        run(hub_of_trials([TRIAL_A]), tmp_path, ["../4-1-0"])


def test_a_later_run_reads_the_targets_of_the_first_and_keeps_its_files(
    tmp_path: Path,
):
    run(hub_of_trials([TRIAL_A, TRIAL_B]), tmp_path, limit=1)
    # The snapshots are gone and the leaderboard has gained a trial since, so only `targets.jsonl` can tell the run which trials the folder holds.
    for path in (tmp_path / "snapshots").iterdir():
        path.unlink()
    later_hub = hub_of_trials([TRIAL_A, TRIAL_B, TRIAL_C])

    assert run(later_hub, tmp_path) == 0

    assert (
        later_hub.requests
        == [download_trials_module.TRIAL_DETAIL_ENDPOINT] + [ASSET_REQUEST] * 2
    )
    assert sorted(path.name for path in (tmp_path / "raw").iterdir()) == [
        TRIAL_A,
        TRIAL_B,
    ]
    assert [status["trial_id"] for status in lines_of(tmp_path / "manifest.jsonl")] == [
        TRIAL_A,
        TRIAL_B,
    ]


def test_a_later_run_may_name_the_same_leaderboards_in_another_order(tmp_path: Path):
    hub = FakeHub(
        leaderboards={
            "4-0-0": [[leaderboard_row(ROW_OLD, 1)]],
            "4-1-0": [[leaderboard_row(ROW_1, 1)]],
        },
        row_trial_ids={ROW_OLD: [TRIAL_A], ROW_1: [TRIAL_B]},
        details={TRIAL_A: detail_of(TRIAL_A, trajectory_path=None, archive_path=None)},
    )
    run(hub, tmp_path, ["4-1-0", "4-0-0"], limit=1)

    assert run(hub, tmp_path, ["4-0-0", "4-1-0", "4-0-0"], limit=1) == 0


@pytest.mark.parametrize(
    ("later_package", "later_leaderboard_names"),
    [
        pytest.param(PACKAGE, ["4-1-0", "4-0-0"], id="another leaderboard"),
        pytest.param("other/benchmark", ["4-1-0"], id="another package"),
    ],
)
def test_a_later_run_with_another_choice_stops(
    tmp_path: Path, later_package: str, later_leaderboard_names: list[str]
):
    run(hub_of_trials([TRIAL_A]), tmp_path)

    with pytest.raises(ValueError, match="needs a new collection folder"):
        download_trials_module.download_trials(
            hub_of_trials([TRIAL_A]),
            tmp_path,
            package=later_package,
            leaderboard_names=later_leaderboard_names,
        )


def test_a_folder_of_the_script_before_this_one_stops_the_run(tmp_path: Path):
    (tmp_path / "targets.jsonl").write_text("")

    with pytest.raises(ValueError, match="without leaderboards.json"):
        run(hub_of_trials([TRIAL_A]), tmp_path)


def test_a_dropped_request_is_tried_again(tmp_path: Path):
    waits: list[float] = []
    hub = hub_of_trials([TRIAL_A], failing_request_count=2)

    error_count = download_trials_module.download_trials(
        hub,
        tmp_path,
        package=PACKAGE,
        leaderboard_names=["4-1-0"],
        sleep=waits.append,
    )

    assert error_count == 0
    assert waits == [1, 2]
    assert hub.requests[:3] == [LEADERBOARD_ENDPOINT] * 3


def test_an_asset_shorter_than_its_content_length_is_an_error_and_no_file(
    tmp_path: Path,
):
    hub = hub_of_trials(
        [TRIAL_A], short_storage_paths=[f"{TRIAL_A}/agent/trajectory.json"]
    )

    assert run(hub, tmp_path) == 1

    trial_dir = tmp_path / "raw" / TRIAL_A
    status = status_of(tmp_path, TRIAL_A)
    assert status["assets"]["trajectory"]["status"] == "error"
    assert status["assets"]["archive"]["status"] == "downloaded"
    assert sorted(path.name for path in trial_dir.iterdir()) == [
        "detail.json",
        "status.json",
        "trial.tar.gz",
        "trial.tar.gz.receipt.json",
    ]
    # 4 attempts for the trajectory and 1 for the archive.
    assert hub.requests.count(ASSET_REQUEST) == 4 + 1
    # A run again downloads the trajectory once Harbor Hub gives all of it.
    assert run(hub_of_trials([TRIAL_A]), tmp_path) == 0
    assert (trial_dir / "trajectory.json").read_bytes() == b'{"steps": []}'


def test_an_asset_without_content_length_is_kept_as_it_came(tmp_path: Path):
    hub = hub_of_trials(
        [TRIAL_A], storage_paths_without_length=[f"{TRIAL_A}/agent/trajectory.json"]
    )

    assert run(hub, tmp_path) == 0

    assert status_of(tmp_path, TRIAL_A)["assets"]["trajectory"]["bytes"] == 13


@pytest.mark.parametrize(
    "change_after_first_run",
    [
        pytest.param("file", id="file changed on disk"),
        pytest.param("storage path", id="storage path changed in the detail"),
    ],
)
def test_an_asset_that_no_longer_fits_its_receipt_is_an_error(
    tmp_path: Path, change_after_first_run: str
):
    run(hub_of_trials([TRIAL_A]), tmp_path)
    trial_dir = tmp_path / "raw" / TRIAL_A
    if change_after_first_run == "file":
        (trial_dir / "trajectory.json").write_text("{}")
    else:
        detail = json.loads((trial_dir / "detail.json").read_text())
        detail["trajectory_path"] = "moved/trajectory.json"
        (trial_dir / "detail.json").write_text(json.dumps(detail))

    assert run(hub_of_trials([TRIAL_A]), tmp_path) == 1

    assert status_of(tmp_path, TRIAL_A)["assets"]["trajectory"]["status"] == "error"


@pytest.mark.parametrize(
    ("trajectory_path", "expected_status"),
    [
        pytest.param(None, "unavailable", id="no storage path"),
        pytest.param("/etc/passwd", "error", id="absolute storage path"),
        pytest.param("a/../../b", "error", id="storage path that leaves its folder"),
    ],
)
def test_storage_paths_that_give_no_download(
    tmp_path: Path, trajectory_path: str | None, expected_status: str
):
    hub = hub_of_trials(
        [TRIAL_A],
        details={TRIAL_A: detail_of(TRIAL_A, trajectory_path=trajectory_path)},
    )

    run(hub, tmp_path)

    assert status_of(tmp_path, TRIAL_A)["assets"]["trajectory"]["status"] == (
        expected_status
    )
    assert not (tmp_path / "raw" / TRIAL_A / "trajectory.json").exists()
    assert hub.requests.count(ASSET_REQUEST) == 1


def test_skip_archives_leaves_out_an_archive_not_yet_downloaded(tmp_path: Path):
    hub = hub_of_trials([TRIAL_A])

    run(hub, tmp_path, skip_archives=True)

    assert status_of(tmp_path, TRIAL_A)["assets"]["archive"] == {"status": "skipped"}
    assert not (tmp_path / "raw" / TRIAL_A / "trial.tar.gz").exists()
    assert hub.requests.count(ASSET_REQUEST) == 1


def test_skip_archives_keeps_the_state_of_an_archive_already_downloaded(
    tmp_path: Path,
):
    run(hub_of_trials([TRIAL_A]), tmp_path)

    run(hub_of_trials([TRIAL_A]), tmp_path, skip_archives=True)

    archive_state = status_of(tmp_path, TRIAL_A)["assets"]["archive"]
    assert archive_state["status"] == "downloaded"
    assert archive_state["sha256"]


@pytest.mark.parametrize(
    "detail",
    [
        pytest.param(None, id="no detail"),
        pytest.param(detail_of(TRIAL_B), id="detail of another trial"),
    ],
)
def test_a_trial_without_its_detail_is_an_error_and_keeps_no_detail_file(
    tmp_path: Path, detail: dict[str, Any] | None
):
    hub = hub_of_trials([TRIAL_A], details={TRIAL_A: detail})

    assert run(hub, tmp_path) == 1

    assert "error" in status_of(tmp_path, TRIAL_A)
    assert not (tmp_path / "raw" / TRIAL_A / "detail.json").exists()


def test_a_detail_without_job_gives_no_trial_page(tmp_path: Path):
    hub = hub_of_trials([TRIAL_A], details={TRIAL_A: detail_of(TRIAL_A, job_id=None)})

    run(hub, tmp_path)

    assert status_of(tmp_path, TRIAL_A)["trial_url"] is None


def test_limit_keeps_the_first_trials_by_trial_id(tmp_path: Path):
    hub = hub_of_trials([TRIAL_A, TRIAL_B, TRIAL_C])

    run(hub, tmp_path, limit=2)

    assert sorted(path.name for path in (tmp_path / "raw").iterdir()) == [
        TRIAL_A,
        TRIAL_B,
    ]


def test_chosen_trial_ids_keep_their_order_once_each_and_must_be_listed():
    targets = [{"trial_id": TRIAL_A}, {"trial_id": TRIAL_B}, {"trial_id": TRIAL_C}]

    selected = download_trials_module.selected_targets_from(
        targets, limit=None, trial_ids=[TRIAL_C, TRIAL_A, TRIAL_C]
    )

    assert [target["trial_id"] for target in selected] == [TRIAL_C, TRIAL_A]
    with pytest.raises(ValueError, match="do not list"):
        download_trials_module.selected_targets_from(
            targets, limit=None, trial_ids=[trial_id_of(9)]
        )
