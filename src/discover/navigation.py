from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from pydantic import ValidationError

from discover.filters import apply_entry_filters
from discover.hf_spaces import AI_SKILL_MEDIA_TYPE, HF_SPACE_MEDIA_TYPE, MCP_SERVER_MEDIA_TYPE
from discover.models import CatalogEntry, SearchQuery, SearchRequest, SearchResponse, SearchResult

AI_CATALOG_MEDIA_TYPES = {"application/ai-catalog+json", "application/ai-catalog"}
AI_REGISTRY_MEDIA_TYPES = {"application/ai-registry+json", "application/ai-registry"}
NavigationStatus = Literal["ok", "error", "skipped"]
MAX_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class DiscoveredResource:
    kind: Literal["catalog", "registry"]
    url: str
    status: NavigationStatus = "ok"
    detail: str = ""


@dataclass
class NavigationReport:
    response: SearchResponse
    discovered: list[DiscoveredResource] = field(default_factory=list)

    def model_dump(self) -> dict[str, object]:
        return {
            "discovered": [resource.__dict__ for resource in self.discovered],
            **self.response.model_dump(exclude_none=True, exclude_defaults=True),
        }

    def model_dump_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)


def well_known_catalog_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must be an absolute http(s) URL")
    if parsed.path.endswith(".json"):
        return url
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/ai-catalog.json"


def registry_search_url(registry_url: str) -> str:
    normalized = registry_url.rstrip("/")
    return normalized if normalized.endswith("/search") else urljoin(f"{normalized}/", "search")


def filter_for_kind(kind: str) -> dict[str, list[str]]:
    artifact_types = {
        "skill": AI_SKILL_MEDIA_TYPE,
        "mcp": MCP_SERVER_MEDIA_TYPE,
        "space": HF_SPACE_MEDIA_TYPE,
    }
    artifact_type = artifact_types.get(kind)
    return {} if artifact_type is None else {"type": [artifact_type]}


def fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = UrlRequest(  # noqa: S310 - validated user-requested CLI URL.
        url,
        headers={"Accept": "application/json", "User-Agent": "discover/0.1"},
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-requested CLI URL.
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def catalog_entries(catalog: dict[str, Any]) -> list[CatalogEntry]:
    entries = catalog.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("catalog `entries` must be a list")
    return [CatalogEntry.model_validate(entry) for entry in entries]


def search_registry(
    url: str,
    request_body: SearchRequest,
    *,
    timeout: float,
    token: str | None = None,
) -> SearchResponse:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "discover/0.1",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = UrlRequest(  # noqa: S310 - discovered from user-requested ARD catalog.
        registry_search_url(url),
        data=request_body.model_dump_json(exclude_none=True, exclude_defaults=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - discovered CLI URL.
        raw_body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw_body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    return SearchResponse.model_validate_json(raw_body.decode("utf-8"))


def _entry_haystack(entry: CatalogEntry) -> str:
    values = [
        entry.displayName,
        entry.description or "",
        " ".join(entry.tags),
        " ".join(entry.capabilities),
        " ".join(entry.representativeQueries),
    ]
    return " ".join(values).casefold()


def _static_result(entry: CatalogEntry, *, query: str, source: str) -> SearchResult | None:
    terms = [term for term in query.casefold().split() if term]
    haystack = _entry_haystack(entry)
    if terms and not any(term in haystack for term in terms):
        return None
    return SearchResult(
        **entry.model_dump(exclude_none=True),
        score=50,
        source=source,
    )


def _with_source(result: SearchResult, source: str) -> SearchResult:
    return result.model_copy(update={"source": source})


def merge_navigation_results(
    results: list[SearchResult], *, limit: int, max_per_source: int
) -> list[SearchResult]:
    by_identifier: dict[str, SearchResult] = {}
    for result in results:
        existing = by_identifier.get(result.identifier)
        if existing is None or result.score > existing.score:
            by_identifier[result.identifier] = result

    source_order: list[str] = []
    by_source: dict[str, list[SearchResult]] = {}
    for result in by_identifier.values():
        if result.source not in by_source:
            source_order.append(result.source)
            by_source[result.source] = []
        by_source[result.source].append(result)
    for source_results in by_source.values():
        source_results.sort(key=lambda result: result.score, reverse=True)

    selected: list[SearchResult] = []
    source_counts = {source: 0 for source in source_order}
    while len(selected) < limit:
        added = False
        for source in source_order:
            if len(selected) >= limit:
                break
            if source_counts[source] >= max_per_source:
                continue
            source_results = by_source[source]
            if not source_results:
                continue
            selected.append(source_results.pop(0))
            source_counts[source] += 1
            added = True
        if not added:
            break
    return selected


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        return str(exc.reason)
    return str(exc)


def navigate(  # noqa: C901, PLR0915 - traversal orchestration is clearer in one bounded loop.
    url: str,
    query: str,
    *,
    kind: str = "all",
    limit: int = 10,
    max_depth: int = 2,
    max_registries: int = 3,
    max_per_source: int = 3,
    follow_referrals: bool = False,
    timeout: float = 10.0,
    token: str | None = None,
) -> NavigationReport:
    request_body = SearchRequest(
        query=SearchQuery(text=query, filter=filter_for_kind(kind)),
        federation="referrals" if follow_referrals else "none",
        pageSize=min(limit, max_per_source),
    )
    discovered: list[DiscoveredResource] = []
    results: list[SearchResult] = []
    referrals: list[CatalogEntry] = []
    catalog_queue: list[tuple[str, int]] = [(well_known_catalog_url(url), 0)]
    visited_catalogs: set[str] = set()
    visited_registries: set[str] = set()

    def visit_registry(registry_url: str) -> None:
        search_url = registry_search_url(registry_url)
        if search_url in visited_registries or len(visited_registries) >= max_registries:
            return
        visited_registries.add(search_url)
        try:
            response = search_registry(search_url, request_body, timeout=timeout, token=token)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
        ) as exc:
            discovered.append(
                DiscoveredResource("registry", search_url, "error", _error_detail(exc))
            )
            return
        discovered.append(DiscoveredResource("registry", search_url))
        results.extend(_with_source(result, search_url) for result in response.results)
        referrals.extend(response.referrals)
        if follow_referrals:
            for referral in response.referrals:
                if referral.type in AI_REGISTRY_MEDIA_TYPES and referral.url is not None:
                    visit_registry(referral.url)

    while catalog_queue:
        catalog_url, depth = catalog_queue.pop(0)
        if catalog_url in visited_catalogs or depth > max_depth:
            continue
        visited_catalogs.add(catalog_url)
        try:
            entries = catalog_entries(fetch_json(catalog_url, timeout=timeout))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
        ) as exc:
            discovered.append(
                DiscoveredResource("catalog", catalog_url, "error", _error_detail(exc))
            )
            continue
        discovered.append(DiscoveredResource("catalog", catalog_url))
        for entry in entries:
            if entry.type in AI_REGISTRY_MEDIA_TYPES and entry.url is not None:
                visit_registry(entry.url)
            elif (
                entry.type in AI_CATALOG_MEDIA_TYPES and entry.url is not None and depth < max_depth
            ):
                catalog_queue.append((urljoin(catalog_url, entry.url), depth + 1))
            else:
                result = _static_result(entry, query=query, source=catalog_url)
                if result is not None:
                    results.append(result)

    results = apply_entry_filters(results, request_body.query.filter)
    results = merge_navigation_results(results, limit=limit, max_per_source=max_per_source)
    return NavigationReport(
        response=SearchResponse(results=results[:limit], referrals=referrals),
        discovered=discovered,
    )
