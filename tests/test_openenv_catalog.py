from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from discover import cli
from discover.server import create_app

if TYPE_CHECKING:
    from pathlib import Path

MEDIA_TYPE = "application/vnd.openenv.environment-card+json"
REVISION = "a" * 40


def snapshot_payload() -> dict[str, Any]:
    source = {
        "provider": "github",
        "id": "example/environments",
        "uri": "https://github.com/example/environments.git",
        "revision": REVISION,
    }
    entries = []
    for name, description in (
        ("echo_env", "Echo messages for client smoke testing."),
        ("chess_env", "Play a game of chess against an opponent."),
    ):
        entries.append(
            {
                "@context": "https://agenticresourcediscovery.org/context/v1",
                "identifier": f"urn:air:example.org:openenv:{name}:{REVISION}",
                "displayName": name,
                "type": MEDIA_TYPE,
                "description": description,
                "data": {
                    "schema_version": "0.1-draft",
                    "name": name,
                    "description": description,
                    "owner": {"authority": "github.com", "id": "example"},
                    "source": {**source, "path": f"envs/{name}"},
                    "artifact_availability": "resolvable",
                    "artifacts": [
                        {
                            "kind": "git",
                            "uri": source["uri"],
                            "path": f"envs/{name}",
                            "revision": REVISION,
                        }
                    ],
                    "license": "unknown",
                    "interfaces": [{"role": "orchestration", "protocol": "openenv"}],
                },
                "tags": [],
                "capabilities": [],
                "representativeQueries": [],
                "metadata": {},
            }
        )
    return {
        "schema_version": "0.1-draft",
        "publisher": "example.org",
        "source": source,
        "generator": {"name": "openenv-git-catalog", "version": "1"},
        "inventory": {"root": "envs", "paths": ["envs/chess_env", "envs/echo_env"]},
        "entries": entries,
        "complete": True,
        "issues": [],
    }


def write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    body = {key: value for key, value in payload.items() if key != "digest"}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    path.write_text(json.dumps({**body, "digest": f"sha256:{digest}"}))


def search_body(text="client smoke test", limit=10) -> dict[str, Any]:
    return {"query": {"text": text, "filter": {"type": [MEDIA_TYPE]}}, "pageSize": limit}


def test_unconfigured_environment_type_is_not_an_empty_success():
    response = TestClient(create_app()).post("/search", json=search_body())
    assert response.status_code == 503
    assert "configured" in response.text.lower()


def test_configured_snapshot_is_independent_of_running_spaces(tmp_path: Path):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    write_snapshot(path, payload)
    client = TestClient(create_app(environment_catalog=path))
    response = client.post("/search", json=search_body())
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["data"] == payload["entries"][0]["data"]
    assert result["identifier"] == payload["entries"][0]["identifier"]
    assert result["type"] == MEDIA_TYPE
    assert "runtimeStage" not in result.get("metadata", {})
    assert "url" not in result


def test_mcp_and_http_use_the_same_environment_consumer(tmp_path: Path):
    path = tmp_path / "catalog.json"
    write_snapshot(path, snapshot_payload())
    client = TestClient(create_app(environment_catalog=path))
    expected = client.post("/search", json=search_body()).json()
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search", "arguments": search_body()},
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["results"] == expected["results"]


def test_refresh_reads_withdrawal_but_fails_on_an_incomplete_replacement(tmp_path: Path):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    write_snapshot(path, payload)
    client = TestClient(create_app(environment_catalog=path))
    assert len(client.post("/search", json=search_body("")).json()["results"]) == 2
    payload["entries"] = payload["entries"][:1]
    payload["inventory"]["paths"] = ["envs/echo_env"]
    write_snapshot(path, payload)
    assert len(client.post("/search", json=search_body("")).json()["results"]) == 1
    payload["complete"] = False
    write_snapshot(path, payload)
    failed = client.post("/search", json=search_body(""))
    assert failed.status_code == 503
    assert "results" not in failed.json()


@pytest.mark.parametrize("mutation", ["mismatch", "unsupported", "duplicate", "digest"])
def test_invalid_source_metadata_is_not_promoted_to_an_environment(tmp_path: Path, mutation: str):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    card = payload["entries"][0]["data"]
    if mutation == "mismatch":
        card["artifacts"][0]["revision"] = "b" * 40
    elif mutation == "unsupported":
        card["schema_version"] = "unrecognized-version"
    elif mutation == "duplicate":
        payload["entries"].append(payload["entries"][0])
    write_snapshot(path, payload)
    if mutation == "digest":
        path.write_text(path.read_text().replace("Echo messages", "Changed messages"))
    response = TestClient(create_app(environment_catalog=path)).post("/search", json=search_body())
    assert response.status_code == 503
    assert "results" not in response.json()


def test_paging_is_bound_to_the_snapshot_and_filters(tmp_path: Path):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    write_snapshot(path, payload)
    client = TestClient(create_app(environment_catalog=path))
    request = search_body("", 1)
    first = client.post("/search", json=request).json()
    request["pageToken"] = first["pageToken"]
    second = client.post("/search", json=request).json()
    assert first["results"][0]["identifier"] != second["results"][0]["identifier"]
    payload["entries"][0]["description"] = "A corrected listing."
    write_snapshot(path, payload)
    assert client.post("/search", json=request).status_code == 400


def test_local_cli_search_does_not_contact_the_hub(tmp_path: Path):
    path = tmp_path / "catalog.json"
    write_snapshot(path, snapshot_payload())
    result = CliRunner().invoke(
        cli.app,
        ["environments", "client smoke test", "--catalog", str(path), "--json"],
    )
    assert result.exit_code == 0, result.output
    selected = json.loads(result.output)["results"][0]
    assert selected["data"]["name"] == "echo_env"
    assert selected["data"]["source"]["path"] == "envs/echo_env"


def test_catalog_content_cannot_supply_its_own_search_score_or_search_source(tmp_path: Path):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    payload["entries"][0]["score"] = 100
    payload["entries"][0]["source"] = "https://untrusted.example/search"
    write_snapshot(path, payload)
    response = TestClient(create_app(environment_catalog=path)).post(
        "/search", json=search_body("client absent-word")
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["score"] < 100
    assert result["source"].startswith("sha256:")


def test_malformed_inventory_returns_a_source_error_instead_of_crashing(tmp_path: Path):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    payload["inventory"]["paths"] = [None, 123]
    write_snapshot(path, payload)
    response = TestClient(create_app(environment_catalog=path)).post("/search", json=search_body())
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("publisher", ""),
        ("publisher", "not a publisher"),
        ("source", {}),
        ("generator", {"name": "openenv-git-catalog", "version": "future"}),
        ("inventory", {"paths": []}),
        ("issues", [{"severity": "unrecognized"}]),
    ],
)
def test_invalid_empty_snapshot_cannot_authorize_withdrawal(
    tmp_path: Path, field: str, value: object
):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    payload["entries"] = []
    payload["inventory"]["paths"] = []
    payload[field] = value
    write_snapshot(path, payload)
    response = TestClient(create_app(environment_catalog=path)).post(
        "/search", json=search_body("")
    )
    assert response.status_code == 503
    assert "results" not in response.json()


def test_complete_empty_snapshot_is_an_explicit_withdrawal(tmp_path: Path):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    payload["entries"] = []
    payload["inventory"]["paths"] = []
    write_snapshot(path, payload)
    response = TestClient(create_app(environment_catalog=path)).post(
        "/search", json=search_body("")
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_capabilities_require_a_matching_agent_tool_declaration(tmp_path: Path):
    path = tmp_path / "catalog.json"
    payload = snapshot_payload()
    payload["entries"][0]["capabilities"] = ["echo_message"]
    write_snapshot(path, payload)
    response = TestClient(create_app(environment_catalog=path)).post("/search", json=search_body())
    assert response.status_code == 503
    assert "results" not in response.json()

    payload["entries"][0]["data"]["interfaces"].append(
        {
            "role": "agent-tools",
            "protocol": "mcp",
            "status": "declared",
            "source_revision": REVISION,
        }
    )
    write_snapshot(path, payload)
    response = TestClient(create_app(environment_catalog=path)).post("/search", json=search_body())
    assert response.status_code == 200
    assert response.json()["results"][0]["capabilities"] == ["echo_message"]
