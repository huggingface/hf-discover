from __future__ import annotations

import pytest
from pydantic import ValidationError

from discover.hf_spaces import AI_SKILL_MEDIA_TYPE
from discover.models import CatalogEntry, SearchResult


def test_catalog_entry_requires_domain_anchored_urn_identifier() -> None:
    entry = CatalogEntry(
        identifier="urn:ai:example.com:skill:image-editor",
        displayName="Image Editor",
        type=AI_SKILL_MEDIA_TYPE,
        url="https://example.com/SKILL.md",
    )

    assert entry.identifier == "urn:ai:example.com:skill:image-editor"


@pytest.mark.parametrize(
    "identifier",
    [
        "urn:test:skill:image-editor",
        "urn:ai:example:skill:image-editor",
        "https://example.com/skill/image-editor",
    ],
)
def test_catalog_entry_rejects_non_ard_identifiers(identifier: str) -> None:
    with pytest.raises(ValidationError):
        CatalogEntry(
            identifier=identifier,
            displayName="Image Editor",
            type=AI_SKILL_MEDIA_TYPE,
            url="https://example.com/SKILL.md",
        )


def test_search_result_score_must_be_relevance_percentage() -> None:
    with pytest.raises(ValidationError):
        SearchResult(
            identifier="urn:ai:example.com:skill:image-editor",
            displayName="Image Editor",
            type=AI_SKILL_MEDIA_TYPE,
            url="https://example.com/SKILL.md",
            score=101,
            source="https://example.com",
        )
