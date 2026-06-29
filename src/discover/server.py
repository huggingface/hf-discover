from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import TYPE_CHECKING, Annotated, Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import Body, FastAPI, Header, HTTPException, Request, Response
from fastapi.openapi.models import Example
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from discover.filters import apply_entry_filters
from discover.hf_skills import search_hf_skills
from discover.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    HF_SPACE_MEDIA_TYPE,
    LEGACY_MCP_SERVER_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SPACES_URL_PREFIX,
    SpaceResultKind,
    build_space_mcp_server_json,
    build_space_skill_markdown,
    hf_space_agents_md_url,
    is_mcp_space,
    search_hf_spaces,
    split_space_id,
)
from discover.models import CatalogEntry, SearchRequest, SearchResponse, SearchResult

if TYPE_CHECKING:
    from collections.abc import Mapping

BEARER_PREFIX = "Bearer "
AI_CATALOG_MEDIA_TYPE = "application/ai-catalog+json"
AI_REGISTRY_MEDIA_TYPE = "application/ai-registry+json"
HF_ENDPOINT = "https://huggingface.co"
HTTP_NOT_FOUND = 404
PUBLIC_BASE_URL_ENV = "DISCOVER_PUBLIC_BASE_URL"
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_TOOL_NAME = "search"
MCP_JSONRPC_ERROR_METHOD_NOT_FOUND = -32601
MCP_JSONRPC_ERROR_INVALID_PARAMS = -32602
SEARCH_REQUEST_EXAMPLES: dict[str, Example] = {
    "skill": Example(
        summary="Generated AI skill results",
        description="Return Hugging Face Spaces as generated `application/ai-skill` entries.",
        value={
            "query": {
                "text": "remove background from image",
                "filter": {"type": ["application/ai-skill"]},
            },
            "pageSize": 5,
        },
    ),
    "huggingface-space": Example(
        summary="Raw Hugging Face Space descriptors",
        description=(
            "Return matching Spaces as `application/vnd.huggingface.space+json` entries with "
            "inline Space metadata."
        ),
        value={
            "query": {
                "text": "generate images with flux",
                "filter": {"type": ["application/vnd.huggingface.space+json"]},
            },
            "pageSize": 5,
        },
    ),
    "mcp": Example(
        summary="MCP server discovery request",
        description=(
            "`application/mcp-server-card+json` returns MCP server card entries for Hugging "
            "Face Spaces tagged `mcp-server`. The Hub search request is constrained with "
            "`filter=mcp-server&agents=true`. The legacy `application/mcp-server+json` filter "
            "is accepted as a transition alias."
        ),
        value={
            "query": {
                "text": "image generation mcp server",
                "filter": {"type": ["application/mcp-server-card+json"]},
            },
            "pageSize": 5,
        },
    ),
}


class SearchSpaces(Protocol):
    def __call__(
        self,
        query: str,
        *,
        limit: int = 10,
        include_non_running: bool = False,
        token: bool | str | None = None,
        kind: SpaceResultKind = "skill",
        base_url: str = SPACES_URL_PREFIX,
    ) -> list[SearchResult]: ...


class SearchSkills(Protocol):
    def __call__(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[SearchResult]: ...


class FetchSpaceInfo(Protocol):
    def __call__(self, space_id: str, *, token: bool | str | None = None) -> HfSpaceInfo: ...


@dataclass
class HfSpaceRuntimeInfo:
    stage: str | None
    raw: dict[str, object]


@dataclass
class HfSpaceInfo:
    id: str
    author: str
    title: str
    host: str | None
    subdomain: str | None
    emoji: str | None
    sdk: str | None
    likes: int
    private: bool
    tags: list[str] | None
    runtime: HfSpaceRuntimeInfo | None
    ai_short_description: str | None
    ai_category: str | None
    semantic_relevancy_score: float | None
    trending_score: int | None
    card_data: dict[str, object]


def _base_url(request: Request) -> str:
    configured = os.environ.get(PUBLIC_BASE_URL_ENV)
    if configured is not None:
        stripped = configured.strip().rstrip("/")
        if stripped:
            return stripped
    return str(request.base_url).rstrip("/")


def _spaces_registry_search_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/registries/huggingface/spaces/search"


def _spaces_registry_base_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/registries/huggingface/spaces"


def _spaces_registry_referral(base_url: str) -> CatalogEntry:
    return CatalogEntry(
        identifier="urn:air:huggingface.co:registry:spaces",
        displayName="Hugging Face Spaces Registry",
        type=AI_REGISTRY_MEDIA_TYPE,
        url=_spaces_registry_search_url(base_url),
        description=(
            "Search generated skills, Space descriptors, and MCP entries from running "
            "Hugging Face Spaces."
        ),
        tags=["huggingface", "spaces", "registry"],
    )


def _spaces_registry_catalog_entry(base_url: str) -> CatalogEntry:
    return CatalogEntry(
        identifier="urn:air:huggingface.co:registry:spaces",
        displayName="Hugging Face Spaces Registry",
        type=AI_REGISTRY_MEDIA_TYPE,
        url=_spaces_registry_base_url(base_url),
        description=(
            "Search generated skills, Space descriptors, and MCP entries from running "
            "Hugging Face Spaces."
        ),
        tags=["huggingface", "spaces", "registry"],
    )


def _registry_catalog_entry(base_url: str) -> CatalogEntry:
    return CatalogEntry(
        identifier="urn:air:huggingface.co:registry:discover",
        displayName="Hugging Face Discover Registry",
        type=AI_REGISTRY_MEDIA_TYPE,
        url=base_url.rstrip("/"),
        description="Search indexed Hugging Face Skills and running Hugging Face Spaces.",
        tags=["huggingface", "registry", "search"],
    )


def _catalog_payload(base_url: str) -> dict[str, object]:
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "Hugging Face Discover",
            "identifier": "huggingface.co",
            "documentationUrl": "https://github.com/huggingface/hf-discover",
        },
        "entries": [
            _registry_catalog_entry(base_url).model_dump(
                exclude_none=True,
                exclude_defaults=True,
            ),
            _spaces_registry_catalog_entry(base_url).model_dump(
                exclude_none=True,
                exclude_defaults=True,
            ),
        ],
    }


def _skills_configured(search_skills: SearchSkills) -> bool:
    return search_skills is not search_hf_skills or bool(os.environ.get("DISCOVER_MEILI_URL"))


def _health_payload(search_skills: SearchSkills) -> dict[str, object]:
    return {
        "status": "ok",
        "registries": {
            "huggingface": {
                "configured": _skills_configured(search_skills),
                "path": "/search",
                "description": "Combined Hugging Face Skills and Spaces search.",
            },
            "huggingface/skills": {
                "configured": _skills_configured(search_skills),
                "path": "/search",
                "description": "Included in the combined root registry.",
            },
            "huggingface/spaces": {
                "configured": True,
                "path": "/registries/huggingface/spaces/search",
                "description": "Targeted Spaces-only nested registry.",
            },
        },
    }


def _project_version() -> str:
    try:
        return package_version("hf-discover")
    except PackageNotFoundError:
        return "unknown"


def _result_kind(artifact_type: str) -> SpaceResultKind | None:
    kinds: dict[str, SpaceResultKind] = {
        AI_SKILL_MEDIA_TYPE: "skill",
        HF_SPACE_MEDIA_TYPE: "space",
        MCP_SERVER_MEDIA_TYPE: "mcp",
        LEGACY_MCP_SERVER_MEDIA_TYPE: "mcp",
    }
    return kinds.get(artifact_type)


def _filter_values(raw_filter: dict[str, Any], field: str) -> list[Any]:
    if field not in raw_filter:
        return []
    value = raw_filter[field]
    if isinstance(value, list):
        return value
    return [value]


def _type_filters(request: SearchRequest) -> list[str]:
    return [
        value for value in _filter_values(request.query.filter, "type") if isinstance(value, str)
    ]


def _space_kinds_for_types(artifact_types: list[str]) -> list[SpaceResultKind]:
    if not artifact_types:
        return ["all"]

    kinds: list[SpaceResultKind] = []
    for artifact_type in artifact_types:
        kind = _result_kind(artifact_type)
        if kind is not None and kind not in kinds:
            kinds.append(kind)
    return kinds


def _includes_skill_index(artifact_types: list[str]) -> bool:
    return not artifact_types or AI_SKILL_MEDIA_TYPE in artifact_types


def _apply_entry_filters(results: list[SearchResult], request: SearchRequest) -> list[SearchResult]:
    return apply_entry_filters(results, request.query.filter)


def _bearer_token(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith(BEARER_PREFIX):
        return None
    token = value[len(BEARER_PREFIX) :].strip()
    return token or None


def hf_token_from_headers(headers: Mapping[str, str]) -> str | None:
    """Return a request-scoped HF token from supported headers, in precedence order."""
    x_hf_authorization = _bearer_token(headers.get("X-HF-Authorization"))
    if x_hf_authorization is not None:
        return x_hf_authorization

    authorization = _bearer_token(headers.get("Authorization"))
    if authorization is not None:
        return authorization

    hf_token = headers.get("HF_TOKEN")
    if hf_token is None:
        return None
    token = hf_token.strip()
    return token or None


def effective_hf_token(
    *,
    request_token: str | None,
    configured_token: bool | str | None,
) -> bool | str | None:
    return request_token or configured_token


def search_discover(
    request: SearchRequest,
    *,
    base_url: str = SPACES_URL_PREFIX,
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_skills: SearchSkills = search_hf_skills,
    search_spaces: SearchSpaces = search_hf_spaces,
) -> SearchResponse:
    results: list[SearchResult] = []
    artifact_types = _type_filters(request)
    space_kinds = _space_kinds_for_types(artifact_types)
    if artifact_types and not space_kinds and not _includes_skill_index(artifact_types):
        return SearchResponse(results=[])

    if _includes_skill_index(artifact_types):
        results.extend(search_skills(request.query.text, limit=request.pageSize))
    for kind in space_kinds:
        results.extend(
            search_spaces(
                request.query.text,
                limit=request.pageSize,
                include_non_running=include_non_running,
                token=token,
                kind=kind,
                base_url=base_url,
            )
        )
    results = _apply_entry_filters(results, request)
    results.sort(key=lambda result: result.score, reverse=True)

    referrals = []
    if request.federation in {"auto", "referrals"}:
        referrals.append(_spaces_registry_referral(base_url))

    return SearchResponse(results=results[: request.pageSize], referrals=referrals)


def search_spaces_discover(
    request: SearchRequest,
    *,
    base_url: str = SPACES_URL_PREFIX,
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_spaces: SearchSpaces = search_hf_spaces,
) -> SearchResponse:
    artifact_types = _type_filters(request)
    space_kinds = _space_kinds_for_types(artifact_types)
    if not space_kinds:
        return SearchResponse(results=[])

    results: list[SearchResult] = []
    for kind in space_kinds:
        results.extend(
            search_spaces(
                request.query.text,
                limit=request.pageSize,
                include_non_running=include_non_running,
                token=token,
                kind=kind,
                base_url=base_url,
            )
        )
    results = _apply_entry_filters(results, request)
    results.sort(key=lambda result: result.score, reverse=True)
    return SearchResponse(results=results[: request.pageSize])


def fetch_agents_md(space_id: str) -> str:
    url = hf_space_agents_md_url(space_id)
    request = UrlRequest(url, headers={"User-Agent": "discover/0.1"})  # noqa: S310 - public HF URL
    with urlopen(request, timeout=30) as response:  # noqa: S310 - public HF URL
        return response.read().decode("utf-8")


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)]


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _space_short_description(data: dict[str, object], card_data: dict[str, object]) -> str | None:
    direct = _optional_string(data.get("ai_short_description"))
    if direct is not None:
        return direct
    return _optional_string(card_data.get("short_description"))


def _space_title(data: dict[str, object], card_data: dict[str, object]) -> str:
    return _string(data.get("title")) or _string(card_data.get("title")) or _string(data.get("id"))


def _space_info_from_payload(data: dict[str, object]) -> HfSpaceInfo:
    runtime_data = _dict(data.get("runtime"))
    card_data = _dict(data.get("cardData"))
    return HfSpaceInfo(
        id=_string(data.get("id")),
        author=_string(data.get("author")),
        title=_space_title(data, card_data),
        host=_optional_string(data.get("host")),
        subdomain=_optional_string(data.get("subdomain")),
        emoji=_optional_string(data.get("emoji")),
        sdk=_optional_string(data.get("sdk")) or _optional_string(card_data.get("sdk")),
        likes=_integer(data.get("likes")),
        private=data.get("private") is True,
        tags=_string_list(data.get("tags")),
        runtime=(
            HfSpaceRuntimeInfo(stage=_optional_string(runtime_data.get("stage")), raw=runtime_data)
            if runtime_data
            else None
        ),
        ai_short_description=_space_short_description(data, card_data),
        ai_category=_optional_string(data.get("ai_category")),
        semantic_relevancy_score=None,
        trending_score=_optional_integer(data.get("trendingScore")),
        card_data=card_data,
    )


def fetch_space_info(space_id: str, *, token: bool | str | None = None) -> HfSpaceInfo:
    owner, name = split_space_id(space_id)
    url = f"{HF_ENDPOINT}/api/spaces/{quote(owner, safe='')}/{quote(name, safe='')}"
    headers = {"User-Agent": "discover/0.1"}
    if isinstance(token, str):
        headers["Authorization"] = f"Bearer {token}"
    request = UrlRequest(url, headers=headers)  # noqa: S310 - public HF API endpoint
    with urlopen(request, timeout=30) as response:  # noqa: S310 - public HF API endpoint
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Unexpected Hugging Face Space info response")
    return _space_info_from_payload(data)


def _json_schema_string(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if description is not None:
        schema["description"] = description
    return schema


def _catalog_entry_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["identifier", "displayName", "type"],
        "properties": {
            "identifier": _json_schema_string("Globally unique ARD identifier."),
            "displayName": _json_schema_string("Human-readable name."),
            "type": _json_schema_string("AI artifact media type."),
            "url": _json_schema_string("URL to retrieve the full artifact."),
            "data": {"type": "object", "additionalProperties": True},
            "description": _json_schema_string("Short description."),
            "tags": {"type": "array", "items": _json_schema_string()},
            "capabilities": {"type": "array", "items": _json_schema_string()},
            "representativeQueries": {"type": "array", "items": _json_schema_string()},
            "version": _json_schema_string("Artifact version."),
            "updatedAt": _json_schema_string("ISO 8601 update timestamp."),
            "metadata": {"type": "object", "additionalProperties": True},
            "trustManifest": {"type": "object", "additionalProperties": True},
        },
    }


def _search_response_json_schema() -> dict[str, Any]:
    search_result_schema = _catalog_entry_json_schema()
    search_result_schema["required"] = ["identifier", "displayName", "type", "score", "source"]
    search_result_schema["properties"] = {
        **search_result_schema["properties"],
        "score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Semantic relevance rating computed by the registry.",
        },
        "source": _json_schema_string("Registry or source where this entry was indexed."),
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["results"],
        "properties": {
            "results": {"type": "array", "items": search_result_schema},
            "referrals": {
                "type": "array",
                "description": "Upstream registries recommended to the client.",
                "items": _catalog_entry_json_schema(),
            },
            "pageToken": _json_schema_string("Token for paging subsequent results."),
        },
    }


def _mcp_search_tool() -> dict[str, Any]:
    return {
        "name": MCP_TOOL_NAME,
        "title": "Hugging Face Agent Resource Discovery (ARDs) Search",
        "description": (
            "Search Hugging Face Skills, Spaces, and MCP server Cards using the Agent Resource "
            "Discovery (ARDs) SearchRequest envelope."
        ),
        "inputSchema": SearchRequest.model_json_schema(),
        "outputSchema": _search_response_json_schema(),
    }


def _mcp_initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": "hf-discover",
            "title": "Hugging Face Discover",
            "version": _project_version(),
        },
        "instructions": "Use the search tool to discover agentic Hugging Face resources.",
    }


def _mcp_response(request_id: str | int, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _mcp_error(
    request_id: str | int,
    *,
    code: int,
    message: str,
    data: object | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": error},
        status_code=400,
    )


def _mcp_request_id(message: dict[str, Any]) -> str | int:
    request_id = message.get("id")
    if isinstance(request_id, str) or (
        isinstance(request_id, int) and not isinstance(request_id, bool)
    ):
        return request_id
    raise HTTPException(status_code=400, detail="MCP requests must include a string or integer id")


def _mcp_search_result(response: SearchResponse) -> dict[str, Any]:
    structured = response.model_dump(
        mode="json",
        exclude_none=True,
        exclude_defaults=True,
    )
    return {
        "content": [{"type": "text", "text": json.dumps(structured, indent=2)}],
        "structuredContent": structured,
    }


def _mcp_call_arguments(message: dict[str, Any]) -> dict[str, Any] | None:
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    if params.get("name") != MCP_TOOL_NAME:
        return None
    arguments = params.get("arguments", {})
    return arguments if isinstance(arguments, dict) else None


def _mcp_accepted_notification(message: dict[str, Any]) -> bool:
    return message.get("method") == "notifications/initialized" and "id" not in message


def _mcp_accepted_response(message: dict[str, Any]) -> bool:
    return "method" not in message and ("result" in message or "error" in message)


async def _mcp_message(request: Request) -> dict[str, Any]:
    try:
        message = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC body") from exc
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC message")
    return message


def _mcp_simple_request(method: object, request_id: str | int) -> JSONResponse | None:
    if method == "initialize":
        return _mcp_response(request_id, _mcp_initialize_result())
    if method == "ping":
        return _mcp_response(request_id, {})
    if method == "tools/list":
        return _mcp_response(request_id, {"tools": [_mcp_search_tool()]})
    return None


def _mcp_search_request(
    message: dict[str, Any],
    request_id: str | int,
) -> SearchRequest | JSONResponse:
    arguments = _mcp_call_arguments(message)
    if arguments is None:
        return _mcp_error(
            request_id,
            code=MCP_JSONRPC_ERROR_INVALID_PARAMS,
            message="Expected tools/call params for the search tool",
        )
    try:
        return SearchRequest.model_validate(arguments)
    except ValidationError as exc:
        return _mcp_error(
            request_id,
            code=MCP_JSONRPC_ERROR_INVALID_PARAMS,
            message="Invalid search arguments",
            data=exc.errors(),
        )


def _mcp_tool_call_response(
    message: dict[str, Any],
    request: Request,
    request_id: str | int,
    *,
    include_non_running: bool,
    token: bool | str | None,
    search_skills: SearchSkills,
    search_spaces: SearchSpaces,
) -> JSONResponse:
    search_request = _mcp_search_request(message, request_id)
    if isinstance(search_request, JSONResponse):
        return search_request
    response = search_discover(
        search_request,
        base_url=_base_url(request),
        include_non_running=include_non_running,
        token=effective_hf_token(
            request_token=hf_token_from_headers(request.headers),
            configured_token=token,
        ),
        search_skills=search_skills,
        search_spaces=search_spaces,
    )
    return _mcp_response(request_id, _mcp_search_result(response))


def _mcp_request_response(
    message: dict[str, Any],
    request: Request,
    *,
    include_non_running: bool,
    token: bool | str | None,
    search_skills: SearchSkills,
    search_spaces: SearchSpaces,
) -> JSONResponse | Response:
    if _mcp_accepted_notification(message) or _mcp_accepted_response(message):
        return Response(status_code=202)

    request_id = _mcp_request_id(message)
    simple_response = _mcp_simple_request(message.get("method"), request_id)
    if simple_response is not None:
        return simple_response
    if message.get("method") == "tools/call":
        return _mcp_tool_call_response(
            message,
            request,
            request_id,
            include_non_running=include_non_running,
            token=token,
            search_skills=search_skills,
            search_spaces=search_spaces,
        )
    return _mcp_error(
        request_id,
        code=MCP_JSONRPC_ERROR_METHOD_NOT_FOUND,
        message=f"Unsupported MCP method: {message.get('method')}",
    )


def _add_mcp_route(
    app: FastAPI,
    *,
    include_non_running: bool,
    token: bool | str | None,
    search_skills: SearchSkills,
    search_spaces: SearchSpaces,
) -> None:
    @app.post("/mcp", response_class=JSONResponse, response_model=None)
    async def mcp(request: Request) -> Response:
        return _mcp_request_response(
            await _mcp_message(request),
            request,
            include_non_running=include_non_running,
            token=token,
            search_skills=search_skills,
            search_spaces=search_spaces,
        )


def _add_spaces_search_route(
    app: FastAPI,
    *,
    include_non_running: bool,
    token: bool | str | None,
    search_spaces: SearchSpaces,
) -> None:
    @app.post(
        "/registries/huggingface/spaces/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_defaults=True,
        summary="Search Hugging Face Spaces",
        description=(
            "Search running Hugging Face Spaces through the ARD search envelope. "
            "Optional request-scoped Hugging Face tokens may be supplied with "
            "`X-HF-Authorization`, `Authorization`, or `HF_TOKEN` headers; they are used only "
            "for the downstream Spaces search request."
        ),
    )
    async def spaces_search(
        request_body: Annotated[SearchRequest, Body(openapi_examples=SEARCH_REQUEST_EXAMPLES)],
        request: Request,
        x_hf_authorization: Annotated[
            str | None,
            Header(
                alias="X-HF-Authorization",
                description=(
                    "Optional request-scoped Hugging Face token. Use `Bearer hf_...`. "
                    "Highest precedence."
                ),
            ),
        ] = None,
        authorization: Annotated[
            str | None,
            Header(
                alias="Authorization",
                description=(
                    "Optional request-scoped Hugging Face token. Use `Bearer hf_...`. "
                    "Used when `X-HF-Authorization` is absent."
                ),
            ),
        ] = None,
        hf_token: Annotated[
            str | None,
            Header(
                alias="HF_TOKEN",
                description=(
                    "Optional request-scoped Hugging Face token without a Bearer prefix. "
                    "Used when authorization headers are absent."
                ),
            ),
        ] = None,
    ) -> SearchResponse:
        _ = x_hf_authorization, authorization, hf_token
        return search_spaces_discover(
            request_body,
            base_url=_base_url(request),
            include_non_running=include_non_running,
            token=effective_hf_token(
                request_token=hf_token_from_headers(request.headers),
                configured_token=token,
            ),
            search_spaces=search_spaces,
        )


def _add_mcp_server_json_route(
    app: FastAPI,
    *,
    token: bool | str | None,
    fetch_space: FetchSpaceInfo,
) -> None:
    @app.get(
        "/mcp/huggingface/{owner}/{space_name}/server.json",
        response_class=JSONResponse,
    )
    async def hf_space_mcp_server_json(
        owner: str,
        space_name: str,
        request: Request,
        x_hf_authorization: Annotated[
            str | None,
            Header(
                alias="X-HF-Authorization",
                description=(
                    "Optional request-scoped Hugging Face token. Use `Bearer hf_...`. "
                    "Highest precedence."
                ),
            ),
        ] = None,
        authorization: Annotated[
            str | None,
            Header(
                alias="Authorization",
                description=(
                    "Optional request-scoped Hugging Face token. Use `Bearer hf_...`. "
                    "Used when `X-HF-Authorization` is absent."
                ),
            ),
        ] = None,
        hf_token: Annotated[
            str | None,
            Header(
                alias="HF_TOKEN",
                description=(
                    "Optional request-scoped Hugging Face token without a Bearer prefix. "
                    "Used when authorization headers are absent."
                ),
            ),
        ] = None,
    ) -> JSONResponse:
        _ = x_hf_authorization, authorization, hf_token
        space_id = f"{owner}/{space_name}"
        try:
            space = await run_in_threadpool(
                fetch_space,
                space_id,
                token=effective_hf_token(
                    request_token=hf_token_from_headers(request.headers),
                    configured_token=token,
                ),
            )
        except HTTPError as exc:
            if exc.code == HTTP_NOT_FOUND:
                raise HTTPException(
                    status_code=HTTP_NOT_FOUND,
                    detail="Hugging Face Space not found",
                ) from exc
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch Hugging Face Space info: HTTP {exc.code}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch Hugging Face Space info: {exc}",
            ) from exc

        if not is_mcp_space(space):
            raise HTTPException(
                status_code=HTTP_NOT_FOUND,
                detail="Hugging Face Space is not tagged as an MCP server",
            )
        return JSONResponse(build_space_mcp_server_json(space), media_type="application/json")


def _add_catalog_route(app: FastAPI) -> None:
    @app.get(
        "/.well-known/ai-catalog.json",
        response_class=JSONResponse,
        summary="AI Catalog discovery document",
        description=(
            "Return an ARD v0.5-compatible AI Catalog advertising the primary "
            "Hugging Face Discover registry and nested Spaces registry."
        ),
    )
    async def well_known_ai_catalog(request: Request) -> JSONResponse:
        return JSONResponse(
            _catalog_payload(_base_url(request)),
            media_type=AI_CATALOG_MEDIA_TYPE,
        )


def _add_explore_route(app: FastAPI) -> None:
    @app.post("/explore")
    async def explore() -> None:
        raise HTTPException(status_code=501, detail="Explore is not implemented")


def create_app(
    *,
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_skills: SearchSkills = search_hf_skills,
    search_spaces: SearchSpaces = search_hf_spaces,
    fetch_space: FetchSpaceInfo = fetch_space_info,
) -> FastAPI:
    app = FastAPI(title="Hugging Face Discover")

    @app.get("/health")
    async def health() -> dict[str, object]:
        return _health_payload(search_skills)

    _add_catalog_route(app)

    @app.post(
        "/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_defaults=True,
        summary="Search Hugging Face Skills and Spaces",
        description=(
            "Search indexed Hugging Face Skills and running Hugging Face Spaces through one "
            "ARD search envelope. The nested Spaces registry remains available for "
            "clients that want targeted Spaces-only search or explicit federation traversal."
        ),
    )
    async def search(
        request_body: Annotated[SearchRequest, Body(openapi_examples=SEARCH_REQUEST_EXAMPLES)],
        request: Request,
        x_hf_authorization: Annotated[
            str | None,
            Header(
                alias="X-HF-Authorization",
                description=(
                    "Optional request-scoped Hugging Face token for the Spaces portion of "
                    "combined search. Use `Bearer hf_...`. Highest precedence."
                ),
            ),
        ] = None,
        authorization: Annotated[
            str | None,
            Header(
                alias="Authorization",
                description=(
                    "Optional request-scoped Hugging Face token for the Spaces portion of "
                    "combined search. Use `Bearer hf_...`. Used when `X-HF-Authorization` is "
                    "absent."
                ),
            ),
        ] = None,
        hf_token: Annotated[
            str | None,
            Header(
                alias="HF_TOKEN",
                description=(
                    "Optional request-scoped Hugging Face token without a Bearer prefix for "
                    "the Spaces portion of combined search. Used when authorization headers "
                    "are absent."
                ),
            ),
        ] = None,
    ) -> SearchResponse:
        _ = x_hf_authorization, authorization, hf_token
        return search_discover(
            request_body,
            base_url=_base_url(request),
            include_non_running=include_non_running,
            token=effective_hf_token(
                request_token=hf_token_from_headers(request.headers),
                configured_token=token,
            ),
            search_skills=search_skills,
            search_spaces=search_spaces,
        )

    _add_mcp_route(
        app,
        include_non_running=include_non_running,
        token=token,
        search_skills=search_skills,
        search_spaces=search_spaces,
    )
    _add_explore_route(app)
    _add_spaces_search_route(
        app,
        include_non_running=include_non_running,
        token=token,
        search_spaces=search_spaces,
    )

    _add_mcp_server_json_route(app, token=token, fetch_space=fetch_space)

    @app.get(
        "/skills/huggingface/{owner}/{space_name}/SKILL.md",
        response_class=PlainTextResponse,
    )
    async def hf_space_skill(owner: str, space_name: str) -> PlainTextResponse:
        space_id = f"{owner}/{space_name}"
        try:
            agents_md = await run_in_threadpool(fetch_agents_md, space_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch Hugging Face Space agents.md: {exc}",
            ) from exc

        return PlainTextResponse(
            build_space_skill_markdown(space_id=space_id, agents_md=agents_md),
            media_type="text/markdown; charset=utf-8",
        )

    @app.get(
        "/spaces/huggingface/{owner}/{space_name}/agents.md",
        response_class=PlainTextResponse,
    )
    async def hf_space_agents_md(owner: str, space_name: str) -> PlainTextResponse:
        space_id = f"{owner}/{space_name}"
        try:
            agents_md = await run_in_threadpool(fetch_agents_md, space_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch Hugging Face Space agents.md: {exc}",
            ) from exc
        return PlainTextResponse(agents_md, media_type="text/markdown; charset=utf-8")

    return app
