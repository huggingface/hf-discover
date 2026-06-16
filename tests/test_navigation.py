from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from typer.testing import CliRunner
from typing_extensions import override

from discover import cli
from discover.cli import DEFAULT_NAVIGATE_URL, parse_navigate_args
from discover.models import SearchResult
from discover.navigation import (
    merge_navigation_results,
    navigate,
    registry_search_url,
    well_known_catalog_url,
)


class NavigationRecorder:
    request_body: dict[str, object] | None = None


class NavigationHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/.well-known/ai-catalog.json":
            self._json(
                {
                    "specVersion": "1.0",
                    "host": {"displayName": "Example", "identifier": "example.com"},
                    "entries": [
                        {
                            "identifier": "urn:ai:example.com:registry:tools",
                            "displayName": "Example Tools Registry",
                            "type": "application/ai-registry+json",
                            "url": self._url("/registry/search"),
                        }
                    ],
                }
            )
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/registry/search":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers["Content-Length"])
        NavigationRecorder.request_body = json.loads(self.rfile.read(length))
        self._json(
            {
                "results": [
                    {
                        "identifier": "urn:ai:example.com:skill:image",
                        "displayName": "Image Skill",
                        "type": "application/ai-skill",
                        "url": "https://example.com/skills/image",
                        "description": "Generate images.",
                        "score": 91,
                        "source": self._url("/registry/search"),
                    }
                ]
            }
        )

    def _url(self, path: str) -> str:
        return f"http://{self.headers['Host']}{path}"

    def _json(self, body: dict[str, object]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    @override
    def log_message(self, format: str, *args: object) -> None:
        return


def serve_navigation_fixture() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), NavigationHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test_well_known_catalog_url_uses_origin_for_websites() -> None:
    assert (
        well_known_catalog_url("https://example.com/docs/page")
        == "https://example.com/.well-known/ai-catalog.json"
    )
    assert (
        well_known_catalog_url("https://example.com/catalog.json")
        == "https://example.com/catalog.json"
    )


def test_registry_search_url_accepts_base_or_search_endpoint() -> None:
    assert (
        registry_search_url("https://example.com/registry") == "https://example.com/registry/search"
    )
    assert (
        registry_search_url("https://example.com/registry/search")
        == "https://example.com/registry/search"
    )


def test_parse_navigate_args_defaults_to_huggingface() -> None:
    assert parse_navigate_args(["generate image"]) == (DEFAULT_NAVIGATE_URL, "generate image")


def test_parse_navigate_args_accepts_explicit_url_and_multi_word_query() -> None:
    assert parse_navigate_args(["https://example.com", "generate", "image"]) == (
        "https://example.com",
        "generate image",
    )


def result(identifier: str, source: str, score: int) -> SearchResult:
    return SearchResult(
        identifier=f"urn:ai:example.com:skill:{identifier}",
        displayName=identifier,
        type="application/ai-skill",
        url=f"https://example.com/{identifier}",
        score=score,
        source=source,
    )


def test_merge_navigation_results_round_robins_sources_with_cap() -> None:
    results = [
        result("a1", "a", 100),
        result("a2", "a", 99),
        result("a3", "a", 98),
        result("b1", "b", 70),
        result("b2", "b", 69),
        result("c1", "c", 10),
    ]

    merged = merge_navigation_results(results, limit=5, max_per_source=2)

    assert [(item.source, item.displayName) for item in merged] == [
        ("a", "a1"),
        ("b", "b1"),
        ("c", "c1"),
        ("a", "a2"),
        ("b", "b2"),
    ]


def test_navigate_fetches_well_known_catalog_and_searches_referenced_registry() -> None:
    server, base_url = serve_navigation_fixture()
    try:
        report = navigate(base_url, "generate image", kind="skill", limit=3)
    finally:
        server.shutdown()

    assert [resource.kind for resource in report.discovered] == ["catalog", "registry"]
    assert report.discovered[0].url == f"{base_url}/.well-known/ai-catalog.json"
    assert report.discovered[1].url == f"{base_url}/registry/search"
    assert [result.displayName for result in report.response.results] == ["Image Skill"]
    assert NavigationRecorder.request_body == {
        "query": {"text": "generate image", "filter": {"type": ["application/ai-skill"]}},
        "federation": "none",
        "pageSize": 3,
    }


def test_cli_navigate_shows_discovered_registry_url() -> None:
    server, base_url = serve_navigation_fixture()
    try:
        result = CliRunner().invoke(
            cli.app,
            ["navigate", base_url, "generate image"],
            terminal_width=200,
        )
    finally:
        server.shutdown()

    assert result.exit_code == 0
    assert f"{base_url}/.well-known/ai-catalog.json" in result.output
    assert f"{base_url}/registry/search" in result.output
    assert "Image Skill" in result.output
