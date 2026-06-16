from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from discover.hf_spaces import AI_SKILL_MEDIA_TYPE, SpaceResultKind
from discover.models import SearchResult
from discover.server import MCP_PROTOCOL_VERSION, MCP_TOOL_NAME, create_app


class EmptySpacesSearch:
    def __call__(
        self,
        query: str,
        *,
        limit: int = 10,
        include_non_running: bool = False,
        token: bool | str | None = None,
        kind: SpaceResultKind = "skill",
        base_url: str = "http://testserver",
    ) -> list[SearchResult]:
        return []


class RecordingSkillsSearch:
    def __init__(self) -> None:
        self.queries: list[tuple[str, int]] = []

    def __call__(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        self.queries.append((query, limit))
        return [
            SearchResult(
                identifier="urn:ai:github.com:huggingface:skills:image",
                displayName="Image Skill",
                type=AI_SKILL_MEDIA_TYPE,
                url="https://github.com/huggingface/skills/tree/main/skills/image",
                description="Edit images.",
                score=97,
                source="https://github.com/huggingface/skills",
            )
        ]


def _request(
    method: str,
    *,
    request_id: int = 1,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def test_mcp_initialize_advertises_2025_06_tools_capability() -> None:
    client = TestClient(create_app(search_skills=RecordingSkillsSearch()))

    response = client.post(
        "/mcp",
        json=_request(
            "initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        ),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"]["name"] == "hf-discover"


def test_mcp_initialized_notification_is_accepted_without_body() -> None:
    client = TestClient(create_app(search_skills=RecordingSkillsSearch()))

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    assert response.status_code == 202
    assert not response.content


def test_mcp_ping_returns_empty_result() -> None:
    client = TestClient(create_app(search_skills=RecordingSkillsSearch()))

    response = client.post("/mcp", json=_request("ping"))

    assert response.status_code == 200
    assert response.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_mcp_tools_list_exposes_search_tool_and_ard_output_schema() -> None:
    client = TestClient(create_app(search_skills=RecordingSkillsSearch()))

    response = client.post("/mcp", json=_request("tools/list"))

    assert response.status_code == 200
    tool = response.json()["result"]["tools"][0]
    assert tool["name"] == MCP_TOOL_NAME
    assert tool["inputSchema"]["properties"]["query"]["$ref"] == "#/$defs/SearchQuery"
    assert tool["outputSchema"]["required"] == ["results"]
    assert tool["outputSchema"]["additionalProperties"] is False
    result_properties = tool["outputSchema"]["properties"]["results"]["items"]["properties"]
    assert {"identifier", "displayName", "type", "score", "source"} <= set(result_properties)


def test_mcp_tools_call_returns_search_response_as_structured_content_and_text() -> None:
    search = RecordingSkillsSearch()
    client = TestClient(create_app(search_skills=search, search_spaces=EmptySpacesSearch()))

    response = client.post(
        "/mcp",
        json=_request(
            "tools/call",
            params={
                "name": MCP_TOOL_NAME,
                "arguments": {
                    "query": {"text": "edit images", "filter": {"type": [AI_SKILL_MEDIA_TYPE]}},
                    "federation": "none",
                    "pageSize": 5,
                },
            },
        ),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert search.queries == [("edit images", 5)]
    assert result["structuredContent"]["results"][0]["displayName"] == "Image Skill"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_mcp_unsupported_method_returns_http_400_json_rpc_error() -> None:
    client = TestClient(create_app(search_skills=RecordingSkillsSearch()))

    response = client.post("/mcp", json=_request("prompts/list"))

    assert response.status_code == 400
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert body["error"]["code"] == -32601
