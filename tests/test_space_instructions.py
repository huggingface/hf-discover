from email.message import Message
from urllib.error import HTTPError

import pytest

from discover.server import fetch_agents_md


def test_generated_instructions_are_preferred() -> None:
    calls: list[str] = []

    def read(url: str) -> str:
        calls.append(url)
        return "generated instructions"

    assert fetch_agents_md("alice/static-space", read=read) == "generated instructions"
    assert len(calls) == 1


@pytest.mark.parametrize("status", [400, 404])
def test_missing_generated_route_uses_repository_file(status: int) -> None:
    calls: list[str] = []

    def read(url: str) -> str:
        calls.append(url)
        if len(calls) == 1:
            raise HTTPError(url, status, "unavailable", Message(), None)
        return "repository instructions"

    assert fetch_agents_md("alice/static-space", read=read) == "repository instructions"
    assert calls == [
        "https://huggingface.co/spaces/alice/static-space/agents.md",
        "https://huggingface.co/spaces/alice/static-space/raw/main/agents.md",
    ]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_other_errors_do_not_trigger_fallback(status: int) -> None:
    calls: list[str] = []

    def read(url: str) -> str:
        calls.append(url)
        raise HTTPError(url, status, "unavailable", Message(), None)

    with pytest.raises(HTTPError) as error:
        fetch_agents_md("alice/static-space", read=read)
    assert error.value.code == status
    assert len(calls) == 1


def test_missing_repository_file_propagates() -> None:
    calls: list[str] = []

    def read(url: str) -> str:
        calls.append(url)
        raise HTTPError(url, 404, "missing", Message(), None)

    with pytest.raises(HTTPError):
        fetch_agents_md("alice/static-space", read=read)
    assert len(calls) == 2
