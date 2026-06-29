from __future__ import annotations

from importlib.metadata import entry_points, version
from inspect import signature
from typing import Any, cast

import typer
from pydantic import ValidationError
from typer.main import get_command
from typer.testing import CliRunner

from discover import cli, server
from discover.models import SearchResponse

app = cli.app


class RecordingFetchSpaceInfo:
    def __init__(self, tags: list[str] | None = None) -> None:
        self.calls: list[tuple[str, bool | str | None]] = []
        self.space = server.HfSpaceInfo(
            id="alice/mcp",
            author="alice",
            title="Alice MCP",
            host="https://alice-mcp.hf.space",
            subdomain="alice-mcp",
            emoji=None,
            sdk="gradio",
            likes=1,
            private=False,
            tags=tags or ["gradio", "mcp-server"],
            runtime=server.HfSpaceRuntimeInfo(stage="RUNNING", raw={"stage": "RUNNING"}),
            ai_short_description="Alice MCP tools.",
            ai_category=None,
            semantic_relevancy_score=None,
            trending_score=None,
            card_data={"title": "Alice MCP", "license": "mit"},
        )

    def __call__(self, space_id: str, *, token: bool | str | None = None) -> server.HfSpaceInfo:
        self.calls.append((space_id, token))
        return self.space


def test_version_option_prints_installed_project_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"hf-discover {version('hf-discover')}\n"


def test_version_command_prints_installed_project_version() -> None:
    result = CliRunner().invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output == f"hf-discover {version('hf-discover')}\n"


def test_package_exposes_hf_extension_console_script() -> None:
    scripts = entry_points(group="console_scripts")

    assert scripts["hf-discover"].value == "discover.cli:app"
    assert [script.name for script in scripts if script.value == "discover.cli:app"] == [
        "hf-discover",
    ]


def test_search_commands_default_to_hosted_registry_urls() -> None:
    search_parameters = signature(cli.search_alias).parameters

    assert search_parameters["registry_url"].default == cli.DEFAULT_REGISTRY_URL
    assert search_parameters["base_url"].default == cli.DEFAULT_REGISTRY_URL
    assert search_parameters["local"].default is False


def test_search_command_hides_local_base_url_escape_hatch() -> None:
    command = cast("Any", get_command(app)).commands["search"]
    options_by_name = {parameter.name: parameter for parameter in command.params}

    assert options_by_name["registry_url"].hidden is False
    assert options_by_name["local"].hidden is False
    assert options_by_name["base_url"].hidden is True


def test_mcp_server_json_command_is_registered() -> None:
    command = cast("Any", get_command(app))

    assert "mcp-server-json" in command.commands


def test_mcp_server_json_helper_fetches_space_and_builds_descriptor() -> None:
    fetch_space = RecordingFetchSpaceInfo()
    token = f"hf_{'test-token'}"

    payload = cli._mcp_server_json_for_space(
        "alice/mcp",
        token=token,
        fetch_space=fetch_space,
    )

    assert fetch_space.calls == [("alice/mcp", token)]
    assert payload["name"] == "hf-space-alice-mcp"
    assert payload["description"] == "Alice MCP tools."
    assert payload["remotes"] == [
        {"type": "streamable-http", "url": "https://alice-mcp.hf.space/gradio_api/mcp/"}
    ]


def test_mcp_server_json_helper_rejects_non_mcp_spaces() -> None:
    fetch_space = RecordingFetchSpaceInfo(tags=["gradio"])

    try:
        cli._mcp_server_json_for_space("alice/not-mcp", fetch_space=fetch_space)
    except typer.BadParameter as exc:
        message = str(exc)
    else:
        raise AssertionError("expected non-MCP Space to fail")

    assert "not tagged as an MCP server" in message


def test_registry_response_error_message_explains_missing_v5_type_field() -> None:
    try:
        SearchResponse.model_validate(
            {
                "results": [
                    {
                        "identifier": "urn:air:example.com:skill",
                        "displayName": "Example Skill",
                        "url": "https://example.com/SKILL.md",
                        "score": 91,
                        "source": "https://example.com",
                    }
                ]
            }
        )
    except ValidationError as exc:
        message = cli._registry_response_error_message(exc)
    else:
        raise AssertionError("expected malformed SearchResponse to fail validation")

    assert "not an ARD v0.5 SearchResponse" in message
    assert "results.0.type" in message
    assert "include `type` media types" in message
    assert "older pre-v0.5 schema" in message


def test_registry_response_error_message_summarizes_many_missing_fields() -> None:
    try:
        SearchResponse.model_validate(
            {
                "results": [
                    {
                        "identifier": f"urn:air:example.com:skill:{index}",
                        "displayName": f"Example Skill {index}",
                        "url": f"https://example.com/{index}/SKILL.md",
                        "score": 91,
                        "source": "https://example.com",
                    }
                    for index in range(6)
                ]
            }
        )
    except ValidationError as exc:
        message = cli._registry_response_error_message(exc)
    else:
        raise AssertionError("expected malformed SearchResponse to fail validation")

    assert "results.0.type" in message
    assert "results.4.type" in message
    assert "results.5.type" not in message
    assert "(6 total)" in message
