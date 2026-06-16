from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from discover.hf_spaces import AI_SKILL_MEDIA_TYPE
from discover.models import SearchResult

HF_SKILLS_SOURCE = "https://github.com/huggingface/skills"
HF_SKILLS_PUBLISHER = "huggingface/skills"
HF_SKILLS_BUCKET_URL = "https://huggingface.co/buckets/huggingface/skills"
HF_BUCKET_URI_PREFIX = "hf://buckets/"
DEFAULT_DISTRIBUTION_BASE_URL = f"{HF_SKILLS_BUCKET_URL}/resolve/distribution%2Flatest"
DEFAULT_MEILI_INDEX = "hf_skills"
SKILL_MARKDOWN_FILENAME = "SKILL.md"


def _configured_meili_url(meili_url: str | None) -> str | None:
    value = meili_url or os.environ.get("DISCOVER_MEILI_URL")
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


def _meili_api_key(api_key: str | None) -> str | None:
    value = api_key if api_key is not None else os.environ.get("MEILI_MASTER_KEY")
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _string(hit: dict[str, Any], key: str) -> str | None:
    value = hit.get(key)
    return value if isinstance(value, str) and value else None


def _distribution_index_path() -> str | None:
    configured = os.environ.get("DISCOVER_SKILLS_DISTRIBUTION_INDEX")
    if configured:
        return configured

    directory = os.environ.get("DISCOVER_SKILLS_DISTRIBUTION_DIR")
    if directory:
        return str(Path(directory) / "index.json")

    return None


def _distribution_base_url() -> str:
    configured = os.environ.get("DISCOVER_SKILLS_DISTRIBUTION_BASE_URL")
    if not configured:
        return DEFAULT_DISTRIBUTION_BASE_URL
    return _bucket_uri_to_resolve_url(configured)


def _bucket_uri_to_resolve_url(uri: str) -> str:
    if not uri.startswith(HF_BUCKET_URI_PREFIX):
        return uri
    bucket_and_path = uri.removeprefix(HF_BUCKET_URI_PREFIX).strip("/")
    namespace, separator, rest = bucket_and_path.partition("/")
    bucket_name, _, path = rest.partition("/")
    if not separator or not namespace or not bucket_name:
        return uri
    base = f"https://huggingface.co/buckets/{namespace}/{bucket_name}"
    if not path:
        return base
    return f"{base}/resolve/{quote(path, safe='')}"


@lru_cache(maxsize=8)
def _load_distribution_index(path: str | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    skills = payload.get("skills") if isinstance(payload, dict) else None
    if not isinstance(skills, list):
        return {}
    return {
        name: skill
        for skill in skills
        if isinstance(skill, dict) and isinstance(name := skill.get("name"), str) and name
    }


def _skill_uri_to_url(uri: str, *, base_url: str) -> str:
    if uri.startswith("skill://"):
        path = quote(uri.removeprefix("skill://").lstrip("/"), safe="")
        separator = "%2F" if "/resolve/" in base_url else "/"
        return f"{base_url.rstrip('/')}{separator}{path}"
    return uri


def _distribution_entry_url(entry: dict[str, Any] | None) -> str | None:
    if entry is None:
        return None
    uri = entry.get("url")
    if not isinstance(uri, str) or not uri:
        return None
    return _skill_uri_to_url(uri, base_url=_distribution_base_url())


def _ranking_score(hit: dict[str, Any]) -> float:
    value = hit.get("_rankingScore")
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _score_percentage(ranking_score: float) -> int:
    return round(min(100.0, max(0.0, ranking_score * 100)))


def _skill_key(hit: dict[str, Any]) -> str:
    return _string(hit, "skill") or _string(hit, "path") or _string(hit, "id") or "unknown"


def _skill_identifier(skill: str) -> str:
    return f"urn:ai:github.com:huggingface:skills:{skill.replace('/', ':')}"


def _skill_directory_path(value: str) -> str:
    stripped = value.strip().rstrip("/")
    suffix = f"/{SKILL_MARKDOWN_FILENAME}"
    if stripped.endswith(suffix):
        return stripped[: -len(suffix)]
    if stripped == SKILL_MARKDOWN_FILENAME:
        return ""
    return stripped


def _github_tree_url_for_skill_artifact(url: str) -> str:
    directory_url = _skill_directory_path(url)
    return directory_url.replace("/blob/", "/tree/", 1)


def _source_url(hit: dict[str, Any]) -> str:
    url = _string(hit, "url")
    if url is not None:
        return _github_tree_url_for_skill_artifact(url)

    path = _string(hit, "path")
    if path is not None:
        directory_path = _skill_directory_path(path)
        if directory_path:
            return f"{HF_SKILLS_SOURCE}/tree/main/{directory_path}"

    raw_url = _string(hit, "raw_url")
    if raw_url is not None:
        return _github_tree_url_for_skill_artifact(raw_url)

    return f"{HF_SKILLS_SOURCE}/tree/main"


def _skill_url(hit: dict[str, Any], distribution: dict[str, dict[str, Any]]) -> str:
    artifact_url = _distribution_entry_url(distribution.get(_skill_key(hit)))
    return artifact_url or _source_url(hit)


def _metadata_value(hit: dict[str, Any], key: str) -> Any:
    value = hit[key]
    if key == "path" and isinstance(value, str):
        return _skill_directory_path(value)
    if key == "url" and isinstance(value, str):
        return _github_tree_url_for_skill_artifact(value)
    return value


def _search_result_from_hit(
    hit: dict[str, Any],
    distribution: dict[str, dict[str, Any]] | None = None,
) -> SearchResult:
    skill = _skill_key(hit)
    distribution_entry = (distribution or {}).get(skill)
    ranking_score = _ranking_score(hit)
    description = (
        _string(hit, "marketplace_description")
        or _string(hit, "skill_description")
        or _string(hit, "title")
    )
    metadata: dict[str, Any] = {
        "sourceType": "huggingface-skills",
        "publisher": HF_SKILLS_PUBLISHER,
        "rankingScore": ranking_score,
        "sourceUrl": _source_url(hit),
    }
    artifact_url = _distribution_entry_url(distribution_entry)
    if artifact_url is not None:
        metadata["artifactUrl"] = artifact_url
    if distribution_entry is not None:
        agent_skills_type = distribution_entry.get("type")
        digest = distribution_entry.get("digest")
        if isinstance(agent_skills_type, str):
            metadata["agentSkillsType"] = agent_skills_type
        if isinstance(digest, str):
            metadata["digest"] = digest
    for key in [
        "id",
        "repo",
        "skill",
        "skill_name",
        "path",
        "raw_url",
        "kind",
        "title",
        "heading_path",
        "version",
        "updated_at",
        "ordinal",
        "part",
    ]:
        if key in hit:
            metadata[key] = _metadata_value(hit, key)

    return SearchResult(
        identifier=_skill_identifier(skill),
        displayName=_string(hit, "skill_name") or skill,
        type=AI_SKILL_MEDIA_TYPE,
        url=_skill_url(hit, distribution or {}),
        description=description,
        tags=["huggingface", "skills"],
        metadata=metadata,
        score=_score_percentage(ranking_score),
        source=HF_SKILLS_SOURCE,
    )


def _best_skill_hits(hits: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    best_by_skill: dict[str, dict[str, Any]] = {}
    for hit in hits:
        skill = _skill_key(hit)
        current = best_by_skill.get(skill)
        if current is None or _ranking_score(hit) > _ranking_score(current):
            best_by_skill[skill] = hit
    return sorted(best_by_skill.values(), key=_ranking_score, reverse=True)[:limit]


def search_hf_skills(
    query: str,
    *,
    limit: int = 10,
    meili_url: str | None = None,
    index: str | None = None,
    api_key: str | None = None,
) -> list[SearchResult]:
    configured_url = _configured_meili_url(meili_url)
    if configured_url is None:
        return []

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "discover/0.1",
    }
    key = _meili_api_key(api_key)
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"

    body = {
        "q": query,
        "limit": limit * 3,
        "showRankingScore": True,
        "showRankingScoreDetails": False,
    }
    index_name = index or os.environ.get("DISCOVER_MEILI_INDEX", DEFAULT_MEILI_INDEX)
    request = UrlRequest(  # noqa: S310 - configured local/admin Meilisearch URL.
        f"{configured_url}/indexes/{index_name}/search",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []

    hits = payload.get("hits", [])
    if not isinstance(hits, list):
        return []
    dict_hits = [hit for hit in hits if isinstance(hit, dict)]
    distribution = _load_distribution_index(_distribution_index_path())
    return [
        _search_result_from_hit(hit, distribution) for hit in _best_skill_hits(dict_hits, limit)
    ]
