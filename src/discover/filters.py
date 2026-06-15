from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from discover.models import SearchResult

URN_AI_PUBLISHER_PARTS = 3
TYPE_FILTER_ALIASES = {
    "application/mcp-server+json": "application/mcp-server-card+json",
}


def publisher_from_identifier(identifier: str) -> str | None:
    parts = identifier.split(":")
    if len(parts) >= URN_AI_PUBLISHER_PARTS and parts[0] == "urn" and parts[1] == "ai":
        return parts[2]
    return None


def entry_values_at_path(value: Any, path: list[str]) -> list[Any]:
    if not path:
        return value if isinstance(value, list) else [value]
    if isinstance(value, list):
        return [item for child in value for item in entry_values_at_path(child, path)]
    if not isinstance(value, dict):
        return []
    current = value.get(path[0])
    return [] if current is None else entry_values_at_path(current, path[1:])


def entry_filter_values(entry: SearchResult, field: str) -> list[Any]:
    if field == "publisher":
        publisher = publisher_from_identifier(entry.identifier)
        return [] if publisher is None else [publisher]

    payload = entry.model_dump(exclude_none=True)
    return entry_values_at_path(payload, field.split("."))


def matches_filter(entry: SearchResult, raw_filter: dict[str, Any]) -> bool:
    for field, expected in raw_filter.items():
        expected_values = expected if isinstance(expected, list) else [expected]
        if field == "type":
            expected_values = [
                TYPE_FILTER_ALIASES.get(value, value) if isinstance(value, str) else value
                for value in expected_values
            ]
        actual_values = entry_filter_values(entry, field)
        if not any(
            actual == expected_value
            for actual in actual_values
            for expected_value in expected_values
        ):
            return False
    return True


def apply_entry_filters(
    results: list[SearchResult],
    raw_filter: dict[str, Any],
) -> list[SearchResult]:
    if not raw_filter:
        return results
    return [result for result in results if matches_filter(result, raw_filter)]
