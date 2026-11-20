"""Give the names and colors of the tabs of the spreadsheet of `build_spreadsheet.py`, in the order the tabs come.

The builder, `check_spreadsheet_formulas.py` and `publish_spreadsheet.py` all find tabs by these names.
"""

OVERVIEW_TAB_NAME = "Overview"
TASKS_TAB_NAME = "Tasks"
REQUESTED_ITEMS_TAB_NAME = "Requested items"
REGISTRIES_AND_HOSTS_TAB_NAME = "Registries and hosts"
WEB_TOOLS_TAB_NAME = "Web tools"
BOUNDS_TAB_NAME = "Bounds"
TRIAL_ROWS_TAB_NAME = "trial_rows"
TRIAL_CATEGORY_MEASURE_ROWS_TAB_NAME = "trial_category_measure_rows"
NETWORK_REQUEST_ROWS_TAB_NAME = "network_request_rows"
# `check_spreadsheet_formulas.py` expects its true or false cells to be true.
METHOD_AND_CHECKS_TAB_NAME = "Method & checks"
CHART_DATA_TAB_NAME = "Chart data"

# Tab colors by group.
OVERVIEW_TAB_COLOR = "294D8C"
RESULTS_TAB_COLOR = "8CB3D9"
EVIDENCE_TAB_COLOR = "6BAD99"
APPENDIX_TAB_COLOR = "999A9E"
