from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from discover.filters import apply_entry_filters
from discover.models import CatalogEntry, SearchRequest, SearchResponse, SearchResult

from .models import ENVIRONMENT_MEDIA_TYPE, Card, RepositorySource, SnapshotHeader

if TYPE_CHECKING:
    from pathlib import Path

MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_TOKEN_BYTES = 4096
MAX_QUERY_LENGTH = 8192
SUPPORTED_FILTERS = frozenset(
    {
        "type",
        "tags",
        "capabilities",
        "publisher",
        "data.license",
        "data.name",
        "data.source.provider",
        "data.artifact_availability",
    }
)
CONTROL_NAMES = frozenset({"reset", "step", "state", "get_state"})


class CatalogReadError(ValueError):
    """The configured inventory cannot currently be read as a complete snapshot."""


class CatalogQueryError(ValueError):
    """The request is outside the configured consumer profile."""


@dataclass(frozen=True)
class Snapshot:
    digest: str
    entries: list[CatalogEntry]


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogReadError("Duplicate metadata key")
        result[key] = value
    return result


def _invalid_number(_: str) -> None:
    raise CatalogReadError("Non-finite metadata number")


def _digest(payload: dict[str, Any]) -> str:
    try:
        data = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    except (ValueError, TypeError, RecursionError) as error:
        raise CatalogReadError("Catalog contains unsupported JSON values") from error
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_CATALOG_BYTES + 1)
        if len(data) > MAX_CATALOG_BYTES:
            raise CatalogReadError("Catalog exceeds the size limit")
        payload = json.loads(data, object_pairs_hook=_object, parse_constant=_invalid_number)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise CatalogReadError("Cannot read the configured environment catalog") from error
    if not isinstance(payload, dict):
        raise CatalogReadError("Catalog must be a complete snapshot object")
    return payload


def _snapshot_header(payload: dict[str, Any]) -> SnapshotHeader:
    try:
        header = SnapshotHeader.model_validate(
            {key: value for key, value in payload.items() if key != "entries"}
        )
    except ValidationError as error:
        raise CatalogReadError("Environment catalog header is incomplete or unsupported") from error
    if not header.complete:
        raise CatalogReadError("Environment catalog is incomplete")
    if any(item.severity == "error" for item in header.issues):
        raise CatalogReadError("Environment catalog contains inventory failures")
    unsigned = {key: value for key, value in payload.items() if key != "digest"}
    if header.digest != _digest(unsigned):
        raise CatalogReadError("Environment catalog digest does not match its contents")
    return header


def _entry(raw: object, source: RepositorySource, publisher: str) -> CatalogEntry:
    entry = CatalogEntry.model_validate(raw)
    if entry.type != ENVIRONMENT_MEDIA_TYPE or entry.data is None or entry.url is not None:
        raise CatalogReadError("Environment catalog requires complete inline cards")
    card = Card.model_validate(entry.data)
    if any(
        getattr(card.source, key) != getattr(source, key)
        for key in ("provider", "id", "uri", "revision")
    ):
        raise CatalogReadError("Entry differs from the recorded inventory source")
    if not entry.identifier.startswith(f"urn:air:{publisher}:") or not entry.identifier.endswith(
        ":" + card.source.revision
    ):
        raise CatalogReadError("Entry does not identify one published revision card")
    if any(name.casefold() in CONTROL_NAMES for name in entry.capabilities):
        raise CatalogReadError("Agent capabilities contain simulation controls")
    if entry.capabilities and not any(item.role == "agent-tools" for item in card.interfaces):
        raise CatalogReadError("Agent capabilities require a source-bound tool declaration")
    return entry


def _entries(payload: dict[str, Any], header: SnapshotHeader) -> list[CatalogEntry]:
    raw = payload.get("entries")
    if not isinstance(raw, list):
        raise CatalogReadError("Catalog entries are missing")
    try:
        return [_entry(item, header.source, header.publisher) for item in raw]
    except ValidationError as error:
        raise CatalogReadError("Environment metadata is incomplete or unsupported") from error


def load_snapshot(path: Path) -> Snapshot:
    payload = _read_payload(path)
    header = _snapshot_header(payload)
    entries = _entries(payload, header)
    found = [Card.model_validate(entry.data).source.path for entry in entries]
    if sorted(found) != sorted(header.inventory.paths):
        raise CatalogReadError("Catalog does not cover its declared inventory")
    if len(found) != len(set(found)) or len(entries) != len(
        {entry.identifier for entry in entries}
    ):
        raise CatalogReadError("Catalog contains duplicate environment identities")
    return Snapshot(digest=header.digest, entries=entries)


def _query_hash(request: SearchRequest) -> str:
    return _digest(request.query.model_dump(mode="json"))


def _page_offset(request: SearchRequest, snapshot: Snapshot) -> int:
    if request.pageToken is None:
        return 0
    if len(request.pageToken) > MAX_TOKEN_BYTES:
        raise CatalogQueryError("Invalid catalog page token")
    try:
        decoded = json.loads(base64.urlsafe_b64decode(request.pageToken))
        valid = decoded["snapshot"] == snapshot.digest and decoded["query"] == _query_hash(request)
        offset = decoded["offset"]
    except (ValueError, KeyError, TypeError) as error:
        raise CatalogQueryError("Invalid catalog page token") from error
    if not valid or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise CatalogQueryError("Catalog page token is stale or belongs to another query")
    return offset


def _score(entry: CatalogEntry, query: set[str]) -> int:
    words = " ".join(
        [entry.displayName, entry.description or "", *entry.representativeQueries, *entry.tags]
    )
    available = set(re.findall(r"[^\W_]+", words.casefold()))
    return round(100 * len(query & available) / len(query)) if query else 0


def _rank(snapshot: Snapshot, request: SearchRequest) -> list[SearchResult]:
    query = set(re.findall(r"[^\W_]+", request.query.text.casefold()))
    results = []
    for entry in snapshot.entries:
        score = _score(entry, query)
        if query and score == 0:
            continue
        result = entry.model_dump(exclude_none=True)
        result.update(source=snapshot.digest, score=score)
        results.append(SearchResult.model_validate(result))
    filtered = apply_entry_filters(results, request.query.filter)
    return sorted(filtered, key=lambda item: (-item.score, item.identifier))


def search_catalog(path: Path | None, request: SearchRequest) -> SearchResponse:
    """Search a configured local snapshot without credentials or candidate requests."""
    if path is None:
        raise CatalogReadError("No environment catalog is configured")
    if request.query.filter.keys() - SUPPORTED_FILTERS:
        raise CatalogQueryError("Unsupported environment catalog filter")
    if len(request.query.text) > MAX_QUERY_LENGTH:
        raise CatalogQueryError("Environment query exceeds the supported size limit")
    snapshot = load_snapshot(path)
    offset = _page_offset(request, snapshot)
    results = _rank(snapshot, request)
    stop = offset + request.pageSize
    token = None
    if stop < len(results):
        payload = {"snapshot": snapshot.digest, "query": _query_hash(request), "offset": stop}
        token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return SearchResponse(results=results[offset:stop], pageToken=token)
