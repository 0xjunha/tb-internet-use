"""Read the text of one trial's status file into the leaderboard row that the trial belongs to.

The status file is the `status.json` of the trial folder, which the script that collected the trials wrote. Its `memberships` lists the leaderboard rows of the trial, and every trial of the collection belongs to exactly one.
"""

import json

from tb_internet_use.trial.model import TrialLeaderboardMembership


def parse_trial_status(
    status_text: str | bytes, trial_id: str
) -> TrialLeaderboardMembership:
    """Read the text of one trial's status file into the benchmark version and the id of the one leaderboard row of its `memberships`.

    The text can be the bytes of the file. Text that is not JSON, `memberships` with no item or with more than one, or an item whose `version` or `row_id` is missing or no text raises ValueError with the trial id as a note.
    """
    try:
        match json.loads(status_text):
            case {"memberships": [{"version": str(version), "row_id": str(row_id)}]}:
                return TrialLeaderboardMembership(
                    benchmark_version=version, leaderboard_row_id=row_id
                )
            case _:
                raise ValueError(
                    "the status file has no `memberships` of exactly one item with a text `version` and `row_id`"
                )
    except ValueError as error:
        error.add_note(f"trial_id: {trial_id}")
        raise
