"""Build made-up network request rows for the tests of the export package, kept out of conftest.py since the test folders share that module name and an import of it depends on which folder pytest collected last."""

from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
)
from tb_internet_use.network_request.model import NetworkRequestCertainty
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
)


def build_network_request_row(
    category: NetworkRequestCategory,
    sender: NetworkRequestSender,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
) -> NetworkRequestRow:
    """Build a request row of the trial `t1` for a `curl` that saved what it received, with the given category, sender and bounds."""
    return NetworkRequestRow(
        trial_id="t1",
        trajectory_id="main",
        step_id=1,
        call_index=0,
        request_index=0,
        source_kind=NetworkRequestSourceKind.COMMAND,
        source="command 0",
        made_by="curl",
        target="https://a.org/x",
        unknown_target_reason=None,
        target_kind=None,
        host_names="a.org",
        received_content_destination="saved",
        request_certainty=NetworkRequestCertainty.CONFIRMED,
        request_uncertainty_reason=None,
        level=NetworkRequestResultLevel.RECEIVED,
        stop_reason=None,
        level_certainty=NetworkRequestResultCertainty.CONFIRMED,
        evidence="",
        category=category,
        host_scope="public",
        host_service="unknown",
        package_registry="",
        is_internet_use=True,
        sender=sender,
        result_view=NetworkRequestResultView.RECEIVED,
        request_measure_bound=request_measure_bound,
        received_measure_bound=received_measure_bound,
    )
