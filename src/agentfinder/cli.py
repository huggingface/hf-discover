from __future__ import annotations

import json
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from agentfinder.challenge import create_challenge_app
from agentfinder.hf_skills import search_hf_skills
from agentfinder.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    DEFAULT_BASE_URL,
    HF_SPACE_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SpaceResultKind,
    SpaceSearcher,
    search_hf_spaces,
)
from agentfinder.models import SearchQuery, SearchRequest, SearchResponse, SearchResult
from agentfinder.server import create_app

console = Console()
app = typer.Typer(help="Agent Finder registry adapters.", add_completion=False)
spaces_app = typer.Typer(help="Search and expose Hugging Face Spaces.", add_completion=False)
challenge_app = typer.Typer(
    help="Run deterministic Agent Finder challenge fixtures.",
    add_completion=False,
)
app.add_typer(spaces_app, name="spaces")
app.add_typer(challenge_app, name="challenge")

QueryArg = Annotated[str, typer.Argument(help="Natural-language Spaces search query.")]
LimitOpt = Annotated[int, typer.Option("--limit", "-n", min=1, max=100, help="Maximum results.")]
SdkOpt = Annotated[
    list[str] | None,
    typer.Option("--sdk", help="Filter by Space SDK. May be passed multiple times."),
]
FilterOpt = Annotated[
    list[str] | None,
    typer.Option("--filter", "-f", help="Filter by Space tag. May be passed multiple times."),
]
TokenOpt = Annotated[
    str | None,
    typer.Option(
        "--token",
        help="Hugging Face access token, or registry Bearer token when --registry-url is used.",
    ),
]
RegistryUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--registry-url",
        help=(
            "Agent Finder registry URL to query instead of Hugging Face Spaces. "
            "May be a registry base URL or its /search endpoint."
        ),
    ),
]
IncludeNonRunningOpt = Annotated[
    bool,
    typer.Option("--include-non-running", help="Include Spaces that are not currently running."),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Emit Agent Finder JSON response.")]
BaseUrlOpt = Annotated[
    str,
    typer.Option("--base-url", help="Base URL used for generated skill artifact URLs."),
]
KindOpt = Annotated[
    SpaceResultKind,
    typer.Option(
        "--kind",
        case_sensitive=False,
        help=(
            "Result artifact kind: skill, mcp, space, or all. "
            "The 'all' kind can return both skill and MCP entries for one Space."
        ),
    ),
]


def _registry_search_url(registry_url: str) -> str:
    normalized = registry_url.rstrip("/")
    if normalized.endswith("/search"):
        return normalized
    return urljoin(f"{normalized}/", "search")


def _media_type_for_kind(kind: SpaceResultKind) -> str | None:
    media_types: dict[SpaceResultKind, str | None] = {
        "all": None,
        "skill": AI_SKILL_MEDIA_TYPE,
        "mcp": MCP_SERVER_MEDIA_TYPE,
        "space": HF_SPACE_MEDIA_TYPE,
    }
    return media_types[kind]


def _registry_search_response(
    registry_url: str,
    query: str,
    *,
    limit: int,
    kind: SpaceResultKind = "all",
    token: str | None = None,
) -> SearchResponse:
    request_body = SearchRequest(
        query=SearchQuery(text=query, mediaType=_media_type_for_kind(kind)),
        pageSize=limit,
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "agentfinder/0.1",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    request = UrlRequest(  # noqa: S310 - user-supplied registry URL is the point.
        _registry_search_url(registry_url),
        data=request_body.model_dump_json(exclude_none=True, exclude_defaults=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            return SearchResponse.model_validate_json(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise typer.BadParameter(
            f"registry search failed with HTTP {exc.code}: {detail}",
            param_hint="--registry-url",
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise typer.BadParameter(
            f"registry search failed: {exc}",
            param_hint="--registry-url",
        ) from exc


def _search_response(
    query: str,
    *,
    limit: int,
    sdk: list[str] | None,
    filters: list[str] | None,
    include_non_running: bool,
    token: str | None,
    base_url: str,
    kind: SpaceResultKind = "all",
    searcher: SpaceSearcher | None = None,
) -> SearchResponse:
    return SearchResponse(
        results=search_hf_spaces(
            query,
            limit=limit,
            sdk=sdk,
            filters=filters,
            include_non_running=include_non_running,
            token=token,
            base_url=base_url,
            kind=kind,
            searcher=searcher,
        )
    )


def _skills_search_response(
    query: str,
    *,
    limit: int,
    kind: SpaceResultKind = "all",
) -> SearchResponse:
    if kind not in {"all", "skill"}:
        return SearchResponse(results=[])
    return SearchResponse(results=search_hf_skills(query, limit=limit))


def _result_type(result: SearchResult) -> str:
    if result.mediaType == AI_SKILL_MEDIA_TYPE:
        return "skill"
    if result.mediaType == MCP_SERVER_MEDIA_TYPE:
        return "mcp"
    if result.mediaType == HF_SPACE_MEDIA_TYPE:
        return "space"
    return result.mediaType


def _string_data_value(result: SearchResult, key: str) -> str:
    if result.data is None:
        return ""
    value = result.data.get(key)
    return value if isinstance(value, str) else ""


def _result_endpoint(result: SearchResult) -> str:
    if result.url is not None:
        return result.url
    return (
        _string_data_value(result, "url")
        or _string_data_value(result, "appUrl")
        or _string_data_value(result, "hubUrl")
    )


def _print_results(response: SearchResponse, *, title: str = "Search Results") -> None:
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("SDK")
    table.add_column("Stage")
    table.add_column("Endpoint")
    table.add_column("Description")

    for index, result in enumerate(response.results, 1):
        sdk = result.metadata.get("sdk")
        stage = result.metadata.get("runtimeStage")
        table.add_row(
            str(index),
            f"{result.score:.1f}",
            _result_type(result),
            result.displayName,
            sdk if isinstance(sdk, str) else "",
            stage if isinstance(stage, str) else "",
            _result_endpoint(result),
            result.description or "",
        )
    console.print(table)


@app.command("search")
def search_alias(  # noqa: PLR0913 - Typer command surface intentionally maps CLI options.
    query: QueryArg,
    limit: LimitOpt = 10,
    sdk: SdkOpt = None,
    filters: FilterOpt = None,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
    registry_url: RegistryUrlOpt = None,
    json_output: JsonOpt = False,
    base_url: BaseUrlOpt = DEFAULT_BASE_URL,
    kind: KindOpt = "all",
) -> None:
    """Search the primary Hugging Face Skills registry or a remote Agent Finder registry."""
    if registry_url is None:
        _ = sdk, filters, include_non_running, token, base_url
        response = _skills_search_response(query, limit=limit, kind=kind)
        title = "Hugging Face Skills"
    else:
        response = _registry_search_response(
            registry_url,
            query,
            limit=limit,
            kind=kind,
            token=token,
        )
        title = registry_url

    if json_output:
        console.print_json(response.model_dump_json(exclude_none=True, exclude_defaults=True))
    else:
        _print_results(response, title=title)


@spaces_app.command("search")
def spaces_search(  # noqa: PLR0913 - Typer command surface intentionally maps CLI options.
    query: QueryArg,
    limit: LimitOpt = 10,
    sdk: SdkOpt = None,
    filters: FilterOpt = None,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
    registry_url: RegistryUrlOpt = None,
    json_output: JsonOpt = False,
    base_url: BaseUrlOpt = DEFAULT_BASE_URL,
    kind: KindOpt = "all",
) -> None:
    """Search Hugging Face Spaces and return Agent Finder-shaped results."""
    if registry_url is None:
        response = _search_response(
            query,
            limit=limit,
            sdk=sdk,
            filters=filters,
            include_non_running=include_non_running,
            token=token,
            base_url=base_url,
            kind=kind,
        )
        title = "Hugging Face Spaces"
    else:
        response = _registry_search_response(
            registry_url,
            query,
            limit=limit,
            kind=kind,
            token=token,
        )
        title = registry_url

    if json_output:
        console.print_json(response.model_dump_json(exclude_none=True, exclude_defaults=True))
    else:
        _print_results(response, title=title)


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host", help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind.")] = 8080,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
) -> None:
    """Serve Agent Finder registries for Hugging Face Skills and Spaces."""
    uvicorn.run(
        create_app(include_non_running=include_non_running, token=token),
        host=host,
        port=port,
    )


@challenge_app.command("serve")
def challenge_serve(
    host: Annotated[str, typer.Option("--host", help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind.")] = 8090,
) -> None:
    """Serve deterministic mixed Agent Finder fixtures for client development."""
    uvicorn.run(create_challenge_app(), host=host, port=port)
