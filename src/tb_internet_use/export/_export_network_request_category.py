"""Export the category of one network request by what it tried to get, from the materials in the text that sent it and the services of its public hosts.

The category never reads the response or how a saved file was used later, so a command gets the same category whether it succeeded or failed.
For example, `curl -o page.html u` is a fetched file even when a later call only runs `cat page.html`.

A request gets its category from the first condition below that fits it.

- A target kind that is not known gives `UNKNOWN`.
- A package name gives `PACKAGE`.
- A search query gives `SEARCH`.
- A request that asks for no content gives `CONNECTIVITY_CHECK`, unless its target is a repository, which a judgment rule decides.
- A request whose content is thrown away is decided by a judgment rule.
- A request for a host alone that may receive content is decided by a judgment rule.
- Saved content gives `FETCHED_FILE`, unless a host is a package registry, which a judgment rule decides.
- Content piped to a command that shows none of it is decided by a judgment rule, and otherwise gets the category of saved content.
- Content piped to a command that shows all or part of it is decided by a judgment rule, and otherwise gets the category of shown content.
- Shown content from a web tool or from a code hosting host gives `PAGE_READ`.
- Shown content from a search engine host is decided by a judgment rule.
- Shown content from a package registry or model hub host is decided by a judgment rule.
- Any other request gives `OTHER_WEB`, e.g. `curl https://a.org/x` or `curl u | mytool`.
"""

from collections import Counter
from collections.abc import Sequence
from typing import assert_never

from tb_internet_use.expanded_tool_call.model import OutputVisibility
from tb_internet_use.export.judgment_rules import (
    treat_content_piped_to_consuming_command_as_other_web,
    treat_content_piped_to_showing_command_as_other_web,
    treat_discarded_content_as_other_web,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_repository_request_for_no_content_as_other_web,
    treat_saved_content_from_package_registry_host_as_fetched_file,
    treat_shown_content_from_registry_or_model_hub_host_as_other_web,
    treat_shown_content_from_search_engine_host_as_other_web,
)
from tb_internet_use.export.model import (
    HostService,
    NetworkRequestCategory,
    PublicHost,
    UnknownPublicHost,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentPipedToCommand,
    ContentSaved,
    ContentShownInResult,
    FromWebTool,
    NetworkRequest,
    NetworkRequestTargetKind,
    NoContentRequested,
    UnknownNetworkRequestTargetKind,
)


def export_network_request_category(
    network_request: NetworkRequest,
    public_hosts: Sequence[PublicHost | UnknownPublicHost],
    *,
    judgment_rule_use_counts: Counter[str],
) -> NetworkRequestCategory:
    """Export the category of a request from the first condition of the module docstring that fits it, reading its target kind, its content destination, its source and the services of its hosts.

    `public_hosts` holds the answers of `ExportKnowledge` for the public hosts among `NetworkRequest.host_names`.
    A target kind that is not known gives `UNKNOWN`, while a target that is not known does not, e.g. `pip install $PKG` is `PACKAGE`.
    A request that asks for no content is `CONNECTIVITY_CHECK` whatever its host, e.g. `ping pypi.org`, unless it is for a repository, which `treat_repository_request_for_no_content_as_other_web` decides.
    A request for a URL or a repository whose content is saved is `FETCHED_FILE`, e.g. `git clone u`. Shown content is `PAGE_READ` from a web tool or a code hosting host, e.g. `curl https://github.com/a/b/README.md`.
    What host services and content destinations cannot tell apart is `OTHER_WEB`, e.g. `curl https://a.org/x` or `curl u | mytool`.
    Each judgment rule adds one to `judgment_rule_use_counts` under its name when it decides a condition.
    """
    target_kind = network_request.target_kind
    received_content_destination = network_request.received_content_destination
    if isinstance(target_kind, UnknownNetworkRequestTargetKind):
        return NetworkRequestCategory.UNKNOWN
    if target_kind == NetworkRequestTargetKind.PACKAGE_NAME:
        return NetworkRequestCategory.PACKAGE
    if target_kind == NetworkRequestTargetKind.SEARCH_QUERY:
        return NetworkRequestCategory.SEARCH
    if isinstance(received_content_destination, NoContentRequested):
        if target_kind != NetworkRequestTargetKind.REPOSITORY_URL:
            return NetworkRequestCategory.CONNECTIVITY_CHECK
        return _other_web_or_connectivity_check_for(
            treat_repository_request_for_no_content_as_other_web(
                network_request, use_counts=judgment_rule_use_counts
            )
        )
    if isinstance(received_content_destination, ContentDiscarded):
        return _other_web_or_connectivity_check_for(
            treat_discarded_content_as_other_web(
                network_request, use_counts=judgment_rule_use_counts
            )
        )
    if target_kind == NetworkRequestTargetKind.HOST:
        return _other_web_or_connectivity_check_for(
            treat_host_target_that_may_receive_content_as_other_web(
                network_request, use_counts=judgment_rule_use_counts
            )
        )
    # The conditions below are only for a URL or a repository, so a target kind added later fails here instead of taking them.
    if (
        target_kind != NetworkRequestTargetKind.URL
        and target_kind != NetworkRequestTargetKind.REPOSITORY_URL
    ):
        assert_never(target_kind)
    match received_content_destination:
        case ContentSaved():
            return _category_for_saved_content(
                network_request,
                public_hosts,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
        case ContentPipedToCommand(visibility_at_end=OutputVisibility.NONE):
            if treat_content_piped_to_consuming_command_as_other_web(
                network_request, use_counts=judgment_rule_use_counts
            ):
                return NetworkRequestCategory.OTHER_WEB
            return _category_for_saved_content(
                network_request,
                public_hosts,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
        case ContentPipedToCommand(
            visibility_at_end=OutputVisibility.WHOLE | OutputVisibility.PARTIAL
        ):
            if treat_content_piped_to_showing_command_as_other_web(
                network_request, use_counts=judgment_rule_use_counts
            ):
                return NetworkRequestCategory.OTHER_WEB
            return _category_for_shown_content(
                network_request,
                public_hosts,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
        case ContentShownInResult():
            return _category_for_shown_content(
                network_request,
                public_hosts,
                judgment_rule_use_counts=judgment_rule_use_counts,
            )
        case _:
            # A reader that no fact covers, e.g. `curl u | mytool`, or a destination that the trial does not show, e.g. code.
            return NetworkRequestCategory.OTHER_WEB


def _other_web_or_connectivity_check_for(is_other_web: bool) -> NetworkRequestCategory:
    """Give `OTHER_WEB` for a judgment rule that answers `True` and `CONNECTIVITY_CHECK` for one that answers `False`."""
    if is_other_web:
        return NetworkRequestCategory.OTHER_WEB
    return NetworkRequestCategory.CONNECTIVITY_CHECK


def _category_for_saved_content(
    network_request: NetworkRequest,
    public_hosts: Sequence[PublicHost | UnknownPublicHost],
    *,
    judgment_rule_use_counts: Counter[str],
) -> NetworkRequestCategory:
    """Give the category of a request for a URL or a repository whose content is saved, asking a judgment rule when a host is a package registry."""
    if _has_host_service(public_hosts, HostService.PACKAGE_REGISTRY):
        if treat_saved_content_from_package_registry_host_as_fetched_file(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return NetworkRequestCategory.FETCHED_FILE
        return NetworkRequestCategory.PACKAGE
    return NetworkRequestCategory.FETCHED_FILE


def _category_for_shown_content(
    network_request: NetworkRequest,
    public_hosts: Sequence[PublicHost | UnknownPublicHost],
    *,
    judgment_rule_use_counts: Counter[str],
) -> NetworkRequestCategory:
    """Give the category of a request for a URL or a repository whose content is shown in the result, by its source and the services of its hosts."""
    if isinstance(network_request.source, FromWebTool):
        return NetworkRequestCategory.PAGE_READ
    if _has_host_service(public_hosts, HostService.CODE_HOSTING):
        return NetworkRequestCategory.PAGE_READ
    if _has_host_service(public_hosts, HostService.SEARCH_ENGINE):
        if treat_shown_content_from_search_engine_host_as_other_web(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return NetworkRequestCategory.OTHER_WEB
        return NetworkRequestCategory.SEARCH
    if _has_host_service(public_hosts, HostService.PACKAGE_REGISTRY) or (
        _has_host_service(public_hosts, HostService.MODEL_HUB)
    ):
        if treat_shown_content_from_registry_or_model_hub_host_as_other_web(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return NetworkRequestCategory.OTHER_WEB
        return NetworkRequestCategory.PAGE_READ
    return NetworkRequestCategory.OTHER_WEB


def _has_host_service(
    public_hosts: Sequence[PublicHost | UnknownPublicHost], host_service: HostService
) -> bool:
    """Answer whether the host catalog gives one of the public hosts the service, so that a host without a row gives none."""
    return any(
        isinstance(public_host, PublicHost) and public_host.service == host_service
        for public_host in public_hosts
    )
