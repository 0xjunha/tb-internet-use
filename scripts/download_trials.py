"""Download the trials of Harbor Hub leaderboards into a collection folder.

Each trial goes to `raw/<trial id>/`, the folder to give `run_pipeline.py`. The first run fixes the trial list in `targets.jsonl`, so a run again only fills in missing files and retries errors.

Run it as `uv run python -I scripts/download_trials.py <collection_dir> --leaderboard 4-1-0 [--skip-archives] [--limit N] [--workers N]`.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any, Protocol, Self
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# The Supabase project of Harbor Hub and its publishable key, the defaults of `harbor.auth.constants` in the `harbor` package on PyPI (0.20.0).
# Supabase makes publishable keys to be public. The rules of each table decide what a request with one may read.
HUB_API_URL = "https://ofhuhcpkvzjlejydnvyd.supabase.co"
HUB_API_KEY = "sb_publishable_Z-vuQbpvpG-PStjbh4yE0Q_e-d3MTIH"
# The page of a trial on Harbor Hub, written into `status.json` for a reader who wants to see the trial.
TRIAL_PAGE_URL = "https://hub.harborframework.com/jobs/{job_id}/trials/{trial_id}"
DEFAULT_PACKAGE = "terminal-bench/terminal-bench"
LEADERBOARD_ENDPOINT = "/functions/v1/leaderboard-read"
ROW_TRIAL_ENDPOINT = "/rest/v1/leaderboard_row_trial"
TRIAL_DETAIL_ENDPOINT = "/rest/v1/rpc/get_trial_detail"
# 100 rows is the page size of the Hub page of a leaderboard. 1000 is the most rows Harbor Hub returns for one request of a table.
LEADERBOARD_PAGE_SIZE = 100
ROW_TRIAL_PAGE_SIZE = 1000
# Each request is tried up to 4 times, waiting 1, 2 and 4 seconds between tries, since Harbor Hub drops a request now and then.
ATTEMPT_COUNT = 4
# Seconds to wait for an answer. An asset may be tens of megabytes, so it gets longer.
REQUEST_TIMEOUT_SECONDS = 90
ASSET_TIMEOUT_SECONDS = 180
# Threads, not processes, since the work waits on the network. 4 keeps the load on Harbor Hub low.
DEFAULT_WORKER_COUNT = 4
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
# Progress goes to stderr after this many trials, and after each trial with an error.
PROGRESS_TRIAL_COUNT = 25
# Trial ids and leaderboard row ids are UUIDs and name files, so an id of another form, e.g. `../x`, stops the run instead of writing outside the collection folder.
HUB_ID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
# A leaderboard name is part of the names of the snapshot files, so it may hold no `/`.
LEADERBOARD_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
# The assets that the detail names by a storage path, by their key in `status.json`, with the key of the path in the detail and the name of the file in the trial folder.
TRIAL_ASSETS = {
    "trajectory": ("trajectory_path", "trajectory.json"),
    "archive": ("archive_path", "trial.tar.gz"),
}
# `urllib` raises `OSError` for a failed connection or an HTTP error status, and `http.client` raises `HTTPException` for an answer cut short. This script raises `ValueError` for an answer of the wrong shape.
DOWNLOAD_ERRORS = (OSError, HTTPException, ValueError)
DOWNLOADED = "downloaded"
UNAVAILABLE = "unavailable"
SKIPPED = "skipped"
ERROR = "error"


class HubApi(Protocol):
    """Access to Harbor Hub, which tests replace with a made-up hub."""

    def fetch_response_bytes(
        self,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> bytes:
        """Give the body of an answer of an endpoint."""
        ...

    def open_asset(self, storage_path: str) -> AssetResponse:
        """Open an asset of the public storage."""
        ...


class AssetResponse(Protocol):
    """Answer of an asset, read in chunks."""

    headers: Any

    def read(self, size: int) -> bytes: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, *exception: object) -> None: ...


def main() -> None:
    """Download the trials that the arguments choose, ending with exit code 1 when one has an error."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("collection_dir", type=Path)
    parser.add_argument(
        "--leaderboard",
        action="append",
        required=True,
        help="a leaderboard name of the package on Harbor Hub, e.g. 4-1-0, repeatable",
    )
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument(
        "--skip-archives",
        action="store_true",
        help="leave out trial.tar.gz, which the pipeline does not read and which makes most of the bytes",
    )
    trial_choice = parser.add_mutually_exclusive_group()
    trial_choice.add_argument(
        "--limit", type=int, help="only the first N trials by trial id"
    )
    trial_choice.add_argument(
        "--trial-id", action="append", help="only this trial, repeatable"
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKER_COUNT)
    arguments = parser.parse_args()
    if arguments.workers < 1 or (arguments.limit is not None and arguments.limit < 1):
        parser.error("--workers and --limit must be positive")
    error_count = download_trials(
        HarborHub(),
        arguments.collection_dir,
        package=arguments.package,
        leaderboard_names=arguments.leaderboard,
        skip_archives=arguments.skip_archives,
        limit=arguments.limit,
        trial_ids=arguments.trial_id,
        worker_count=arguments.workers,
        script_path=Path(__file__),
    )
    sys.exit(1 if error_count else 0)


def download_trials(
    hub: HubApi,
    collection_dir: Path,
    *,
    package: str,
    leaderboard_names: Sequence[str],
    skip_archives: bool = False,
    limit: int | None = None,
    trial_ids: Sequence[str] | None = None,
    worker_count: int = DEFAULT_WORKER_COUNT,
    script_path: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Download the chosen trials into the collection folder and give the number of trials with an error."""
    for leaderboard_name in leaderboard_names:
        if not LEADERBOARD_NAME_PATTERN.fullmatch(leaderboard_name):
            raise ValueError(
                f"the leaderboard name {leaderboard_name!r} is not a name such as 4-1-0"
            )
    collection_dir.mkdir(parents=True, exist_ok=True)
    leaderboard_choice = write_leaderboard_choice(
        collection_dir, package, leaderboard_names
    )
    collection = {"finished_at": None, **leaderboard_choice}
    write_json(collection_dir / "collection.json", collection)
    targets = read_or_download_targets(
        hub, collection_dir, package, leaderboard_choice["leaderboards"], sleep=sleep
    )
    selected_targets = selected_targets_from(targets, limit=limit, trial_ids=trial_ids)
    error_count = 0
    manifest_part_path = collection_dir / "manifest.jsonl.part"
    with (
        manifest_part_path.open("w") as manifest,
        ThreadPoolExecutor(max_workers=worker_count) as pool,
    ):
        trial_statuses = pool.map(
            lambda target: download_trial(
                hub, collection_dir, target, skip_archives=skip_archives, sleep=sleep
            ),
            selected_targets,
        )
        for done_count, trial_status in enumerate(trial_statuses, 1):
            trial_has_error = has_error(trial_status)
            error_count += trial_has_error
            manifest.write(json.dumps(trial_status, ensure_ascii=False) + "\n")
            manifest.flush()
            if (
                done_count % PROGRESS_TRIAL_COUNT == 0
                or done_count == len(selected_targets)
                or trial_has_error
            ):
                print(
                    f"Downloaded {done_count}/{len(selected_targets)} trials, {error_count} with errors",
                    file=sys.stderr,
                    flush=True,
                )
    manifest_part_path.replace(collection_dir / "manifest.jsonl")
    several_membership_count = sum(len(target["memberships"]) > 1 for target in targets)
    if several_membership_count:
        print(
            f"{several_membership_count} trials are listed by more than one leaderboard row, which collect_trials does not take",
            file=sys.stderr,
        )
    collection |= {
        "finished_at": datetime.now(UTC).isoformat(),
        "population_trials": len(targets),
        "selected_trials": len(selected_targets),
        "trials_with_several_memberships": several_membership_count,
        "errors": error_count,
        "targets_sha256": sha256_of(collection_dir / "targets.jsonl"),
        "script_sha256": sha256_of(script_path) if script_path else None,
        "python": sys.version,
    }
    write_json(collection_dir / "collection.json", collection)
    return error_count


def write_leaderboard_choice(
    collection_dir: Path, package: str, leaderboard_names: Sequence[str]
) -> dict[str, Any]:
    """Write the package and leaderboard names on the first run, and raise ValueError on a later run with others."""
    path = collection_dir / "leaderboards.json"
    leaderboard_choice = {
        "package": package,
        "leaderboards": sorted(set(leaderboard_names)),
    }
    if path.exists():
        saved_leaderboard_choice = json.loads(path.read_bytes())
        if saved_leaderboard_choice != leaderboard_choice:
            raise ValueError(
                f"{collection_dir} holds {saved_leaderboard_choice}, not {leaderboard_choice}. A new choice of leaderboards needs a new collection folder."
            )
        return leaderboard_choice
    if (collection_dir / "targets.jsonl").exists():
        raise ValueError(
            f"{collection_dir} holds a targets.jsonl without leaderboards.json, so the leaderboards it lists are not known"
        )
    write_json(path, leaderboard_choice)
    return leaderboard_choice


def read_or_download_targets(
    hub: HubApi,
    collection_dir: Path,
    package: str,
    leaderboard_names: Sequence[str],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Give each trial with the leaderboard rows that list it, from `targets.jsonl` or else from Harbor Hub."""
    path = collection_dir / "targets.jsonl"
    if path.exists():
        return [json.loads(line) for line in path.read_text().splitlines()]
    snapshots_dir = collection_dir / "snapshots"
    targets_by_trial_id: dict[str, dict[str, Any]] = {}
    for leaderboard_name in leaderboard_names:
        leaderboard_rows = download_leaderboard_rows(
            hub, snapshots_dir, package, leaderboard_name, sleep=sleep
        )
        for leaderboard_row in leaderboard_rows:
            row_id = leaderboard_row["id"]
            row_trial_ids = download_row_trial_ids(
                hub, snapshots_dir, row_id, sleep=sleep
            )
            if leaderboard_row.get("n_trials") not in (None, len(row_trial_ids)):
                raise ValueError(
                    f"leaderboard row {row_id} has n_trials {leaderboard_row['n_trials']} but lists {len(row_trial_ids)} trials"
                )
            for trial_id in row_trial_ids:
                target = targets_by_trial_id.setdefault(
                    trial_id, {"trial_id": trial_id, "memberships": []}
                )
                target["memberships"].append(
                    {"version": leaderboard_name, "row_id": row_id}
                )
    targets = [
        targets_by_trial_id[trial_id] for trial_id in sorted(targets_by_trial_id)
    ]
    write_text(path, "".join(json.dumps(target) + "\n" for target in targets))
    return targets


def download_leaderboard_rows(
    hub: HubApi,
    snapshots_dir: Path,
    package: str,
    leaderboard_name: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Give the rows of one leaderboard, raising ValueError when its pages do not add up to the total it reports."""
    leaderboard_rows: list[dict[str, Any]] = []
    page_number = 1
    while True:
        leaderboard_page = download_response_json(
            hub,
            snapshots_dir / f"board-{leaderboard_name}-{page_number}.json",
            LEADERBOARD_ENDPOINT,
            body={
                "package": package,
                "name": leaderboard_name,
                "page": page_number,
                "page_size": LEADERBOARD_PAGE_SIZE,
            },
            is_expected=is_leaderboard_page,
            sleep=sleep,
        )
        leaderboard_rows.extend(leaderboard_page["rows"])
        print(
            f"Leaderboard {leaderboard_name}, page {page_number}, {len(leaderboard_page['rows'])} rows",
            file=sys.stderr,
            flush=True,
        )
        pagination = leaderboard_page["pagination"]
        if page_number >= pagination["total_pages"]:
            break
        page_number += 1
    row_ids = [
        hub_id_from(leaderboard_row["id"]) for leaderboard_row in leaderboard_rows
    ]
    if not row_ids:
        raise ValueError(f"the leaderboard {leaderboard_name} of {package} has no rows")
    if len(set(row_ids)) != len(row_ids) or len(row_ids) != pagination["total"]:
        raise ValueError(
            f"the pages of the leaderboard {leaderboard_name} give {len(set(row_ids))} distinct rows of {len(row_ids)}, but Harbor Hub reports {pagination['total']}, so the leaderboard changed between pages. Remove its board files under snapshots/ and run again."
        )
    return leaderboard_rows


def is_leaderboard_page(answer: Any) -> bool:
    """Tell whether an answer of `leaderboard-read` has the rows and totals read here."""
    match answer:
        case {
            "rows": list(rows),
            "pagination": {"total": int(), "total_pages": int()},
        }:
            return all(isinstance(row, dict) and "id" in row for row in rows)
    return False


def download_row_trial_ids(
    hub: HubApi,
    snapshots_dir: Path,
    row_id: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Give the trial ids of one leaderboard row, raising ValueError when they do not rise from page to page, e.g. when Harbor Hub drops the offset."""
    trial_ids: list[str] = []
    while True:
        row_trial_links = download_response_json(
            hub,
            snapshots_dir / f"row-{row_id}-{len(trial_ids)}.json",
            ROW_TRIAL_ENDPOINT,
            params={
                "select": "trial_id,created_at",
                "row_id": "eq." + row_id,
                "order": "trial_id",
                "offset": len(trial_ids),
                "limit": ROW_TRIAL_PAGE_SIZE,
            },
            is_expected=is_row_trial_page,
            sleep=sleep,
        )
        page_trial_ids = [hub_id_from(link["trial_id"]) for link in row_trial_links]
        if page_trial_ids != sorted(set(page_trial_ids)) or (
            trial_ids and page_trial_ids and page_trial_ids[0] <= trial_ids[-1]
        ):
            raise ValueError(
                f"the trial ids of leaderboard row {row_id} do not rise from offset {len(trial_ids)}"
            )
        trial_ids.extend(page_trial_ids)
        if len(page_trial_ids) < ROW_TRIAL_PAGE_SIZE:
            return trial_ids


def is_row_trial_page(answer: Any) -> bool:
    """Tell whether an answer of `leaderboard_row_trial` is a list of links with trial ids."""
    return isinstance(answer, list) and all(
        isinstance(link, dict) and "trial_id" in link for link in answer
    )


def hub_id_from(value: object) -> str:
    """Give an id from Harbor Hub, raising ValueError when it is no UUID."""
    if not isinstance(value, str) or not HUB_ID_PATTERN.fullmatch(value):
        raise ValueError(f"Harbor Hub gave an id of an unknown form: {value!r}")
    return value


def download_response_json(
    hub: HubApi,
    path: Path,
    endpoint: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, str | int] | None = None,
    is_expected: Callable[[Any], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Give the JSON of an answer, saved at `path` only once `is_expected` accepts it."""
    if not path.exists():
        response_bytes = call_with_attempts(
            lambda: hub.fetch_response_bytes(endpoint, body=body, params=params),
            sleep=sleep,
        )
        if not is_expected(json.loads(response_bytes)):
            raise ValueError(
                f"Harbor Hub gave an answer of another shape for {path.name}"
            )
        write_bytes(path, response_bytes)
    return json.loads(path.read_bytes())


def selected_targets_from(
    targets: Sequence[dict[str, Any]],
    *,
    limit: int | None,
    trial_ids: Sequence[str] | None,
) -> list[dict[str, Any]]:
    """Give the targets that `limit` or `trial_ids` keep, or all of them."""
    if trial_ids:
        targets_by_trial_id = {target["trial_id"]: target for target in targets}
        unlisted_trial_ids = sorted(set(trial_ids) - set(targets_by_trial_id))
        if unlisted_trial_ids:
            raise ValueError(
                f"the leaderboards do not list the trials {unlisted_trial_ids}"
            )
        return [targets_by_trial_id[trial_id] for trial_id in dict.fromkeys(trial_ids)]
    if limit is not None:
        return list(targets[:limit])
    return list(targets)


def download_trial(
    hub: HubApi,
    collection_dir: Path,
    target: dict[str, Any],
    *,
    skip_archives: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Download the detail and assets of one trial and give the `status.json` written for it."""
    trial_id = target["trial_id"]
    trial_dir = collection_dir / "raw" / hub_id_from(trial_id)
    trial_dir.mkdir(parents=True, exist_ok=True)
    trial_status: dict[str, Any] = {**target, "assets": {}}
    try:
        detail_path = trial_dir / "detail.json"
        detail = download_response_json(
            hub,
            detail_path,
            TRIAL_DETAIL_ENDPOINT,
            body={"p_trial_id": trial_id},
            is_expected=lambda answer: (
                isinstance(answer, dict) and answer.get("id") == trial_id
            ),
            sleep=sleep,
        )
        job_id = detail.get("job_id")
        trial_status.update(
            task_name=detail.get("task_name"),
            job_id=job_id,
            trial_url=(
                TRIAL_PAGE_URL.format(job_id=job_id, trial_id=trial_id)
                if job_id
                else None
            ),
        )
        trial_status["assets"]["metadata"] = {
            "status": DOWNLOADED,
            "path": str(detail_path.relative_to(collection_dir)),
            "sha256": sha256_of(detail_path),
            "bytes": detail_path.stat().st_size,
        }
        for asset_name, (storage_path_key, file_name) in TRIAL_ASSETS.items():
            file_path = trial_dir / file_name
            if (
                asset_name == "archive"
                and skip_archives
                and not receipt_path_of(file_path).exists()
            ):
                trial_status["assets"][asset_name] = {"status": SKIPPED}
                continue
            try:
                trial_status["assets"][asset_name] = download_asset(
                    hub,
                    collection_dir,
                    file_path,
                    detail.get(storage_path_key),
                    sleep=sleep,
                )
            except DOWNLOAD_ERRORS as error:
                trial_status["assets"][asset_name] = {
                    "status": ERROR,
                    "error": str(error),
                }
    except DOWNLOAD_ERRORS as error:
        trial_status["error"] = str(error)
    write_json(trial_dir / "status.json", trial_status)
    return trial_status


def download_asset(
    hub: HubApi,
    collection_dir: Path,
    file_path: Path,
    storage_path: object,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Download one asset to `file_path` and give its state, keeping a file that still fits its receipt."""
    if not storage_path:
        return {"status": UNAVAILABLE, "storage_path": None}
    if (
        not isinstance(storage_path, str)
        or storage_path.startswith("/")
        or ".." in storage_path.split("/")
    ):
        raise ValueError(f"the storage path {storage_path!r} is not a relative path")
    receipt_path = receipt_path_of(file_path)
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_bytes())
        if (
            receipt.get("storage_path") != storage_path
            or not file_path.exists()
            or sha256_of(file_path) != receipt.get("sha256")
        ):
            raise ValueError(
                f"{file_path} or its storage path differs from its receipt"
            )
        return receipt
    size, sha256 = call_with_attempts(
        lambda: write_asset_file(hub, storage_path, file_path), sleep=sleep
    )
    receipt = {
        "status": DOWNLOADED,
        "path": str(file_path.relative_to(collection_dir)),
        "storage_path": storage_path,
        "bytes": size,
        "sha256": sha256,
    }
    write_json(receipt_path, receipt)
    return receipt


def receipt_path_of(file_path: Path) -> Path:
    """Give the path of the receipt of an asset file, beside it."""
    return file_path.with_name(file_path.name + ".receipt.json")


def write_asset_file(
    hub: HubApi, storage_path: str, file_path: Path
) -> tuple[int, str]:
    """Write one asset to `file_path` and give its size and SHA-256, raising ValueError when it came short."""
    part_path = file_path.with_name(file_path.name + ".part")
    digest = hashlib.sha256()
    size = 0
    with hub.open_asset(storage_path) as response, part_path.open("wb") as file:
        while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
            file.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        expected_size = response.headers.get("Content-Length")
    if expected_size is not None and int(expected_size) != size:
        part_path.unlink()
        raise ValueError(f"{size} of {expected_size} bytes came for {storage_path}")
    part_path.replace(file_path)
    return size, digest.hexdigest()


def call_with_attempts[T](
    action: Callable[[], T], *, sleep: Callable[[float], None] = time.sleep
) -> T:
    """Give the value of `action`, calling it up to `ATTEMPT_COUNT` times."""
    for attempt in range(ATTEMPT_COUNT):
        try:
            return action()
        except DOWNLOAD_ERRORS:
            if attempt == ATTEMPT_COUNT - 1:
                raise
            sleep(2**attempt)
    raise AssertionError("unreachable")


def has_error(trial_status: dict[str, Any]) -> bool:
    """Tell whether the trial or one of its assets ended in an error."""
    return "error" in trial_status or any(
        asset_state["status"] == ERROR
        for asset_state in trial_status["assets"].values()
    )


def write_json(path: Path, value: object) -> None:
    """Write a value as indented JSON."""
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, text: str) -> None:
    """Write a text."""
    write_bytes(path, text.encode())


def write_bytes(path: Path, data: bytes) -> None:
    """Write bytes through a `.part` file, so that a stopped run leaves no half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part_path = path.with_name(path.name + ".part")
    part_path.write_bytes(data)
    part_path.replace(path)


def sha256_of(path: Path) -> str:
    """Give the SHA-256 of a file as hex."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


class HarborHub:
    """Access to Harbor Hub over HTTP."""

    def fetch_response_bytes(
        self,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> bytes:
        """Give the body of an answer, posting `body` as JSON when it is given."""
        url = HUB_API_URL + endpoint + ("?" + urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        request = Request(url, data=data, headers=hub_headers())
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()

    def open_asset(self, storage_path: str) -> AssetResponse:
        """Open an asset of the storage bucket `results`."""
        url = (
            HUB_API_URL + "/storage/v1/object/results/" + quote(storage_path, safe="/")
        )
        return urlopen(
            Request(url, headers=hub_headers()), timeout=ASSET_TIMEOUT_SECONDS
        )


def hub_headers() -> dict[str, str]:
    """Give the headers of every request to Harbor Hub, with the publishable key."""
    return {"apikey": HUB_API_KEY, "Content-Type": "application/json"}


if __name__ == "__main__":
    main()
