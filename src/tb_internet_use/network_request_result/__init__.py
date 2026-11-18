"""Decide how far each network request of one trial got, why it stopped there and on what evidence in the trajectory."""

from tb_internet_use.network_request_result._decide_network_request_results import (
    decide_network_request_results,
)

__all__ = ["decide_network_request_results"]
