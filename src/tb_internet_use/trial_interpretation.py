"""Expand the calls of one trial into their runs and extract its candidate requests and observations, which linking then joins."""

from collections.abc import Sequence
from dataclasses import dataclass

from tb_internet_use.callrun.expand import expand_calls
from tb_internet_use.callrun.model import CallRun
from tb_internet_use.observation.extract import extract_observations
from tb_internet_use.observation.model import Observation
from tb_internet_use.request.extract import extract_candidate_requests
from tb_internet_use.request.model import CandidateRequest
from tb_internet_use.toolcall.model import ToolCall


@dataclass(frozen=True, slots=True)
class TrialLinkingInputs:
    """Inputs of linking for one trial, made by `interpret_trial_before_linking` and read when requests are linked to observations."""

    call_runs: tuple[CallRun, ...]  # one per call, in call order
    candidate_requests: tuple[CandidateRequest, ...]
    observations: tuple[Observation, ...]


def interpret_trial_before_linking(
    calls: Sequence[ToolCall],
) -> TrialLinkingInputs:
    """Expand a trial's converted calls into their runs, then extract the candidate requests and observations of each call."""
    call_runs = expand_calls(calls)
    return TrialLinkingInputs(
        call_runs=call_runs,
        candidate_requests=tuple(
            r for run in call_runs for r in extract_candidate_requests(run)
        ),
        observations=tuple(o for call in calls for o in extract_observations(call)),
    )
