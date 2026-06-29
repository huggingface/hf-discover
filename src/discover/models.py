from __future__ import annotations

import re
import warnings
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FederationMode = Literal["auto", "referrals", "none"]
_URN_AIR_BODY = (
    r"(?P<publisher>(?=.{1,253}:)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63})"
    r":[A-Za-z0-9._~!$&'()*+,;=@%-]+"
    r"(?::[A-Za-z0-9._~!$&'()*+,;=@%-]+)*$"
)
URN_AIR_IDENTIFIER_RE = re.compile(r"^urn:air:" + _URN_AIR_BODY)
# DEPRECATED(urn:ai): legacy ARD prefix accepted during transition; remove with urn:ai support.
URN_AI_LEGACY_IDENTIFIER_RE = re.compile(r"^urn:ai:" + _URN_AIR_BODY)


class CatalogEntry(BaseModel):
    """ARD catalog entry using v0.5 field names."""

    model_config = ConfigDict(extra="allow")

    identifier: str
    displayName: str
    type: str
    url: str | None = None
    data: dict[str, Any] | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    representativeQueries: list[str] = Field(default_factory=list)
    version: str | None = None
    updatedAt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    trustManifest: dict[str, Any] | None = None

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if URN_AIR_IDENTIFIER_RE.fullmatch(value) is not None:
            return value
        # DEPRECATED(urn:ai): accept legacy prefix and warn; remove with urn:ai support.
        if URN_AI_LEGACY_IDENTIFIER_RE.fullmatch(value) is not None:
            warnings.warn(
                f"ARD identifier {value!r} uses the deprecated 'urn:ai:' prefix; "
                "the spec has renamed it to 'urn:air:'. Update publishers before "
                "'urn:ai:' support is removed.",
                DeprecationWarning,
                stacklevel=2,
            )
            return value
        raise ValueError(
            "identifier must use domain-anchored ARD URN format "
            "urn:air:<publisher-fqdn>:<namespace-or-name>[:<agent-name>...] "
            "(legacy 'urn:ai:' is accepted with a deprecation warning during transition)"
        )

    @model_validator(mode="after")
    def validate_value_or_reference(self) -> CatalogEntry:
        if (self.url is None) == (self.data is None):
            raise ValueError("exactly one of url or data must be present")
        return self


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        description="Natural-language search query, for example 'remove image background'.",
        examples=["remove image background"],
    )
    filter: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured field-path constraints. Use `type` to constrain artifact media "
            "types, for example `{'type': ['application/mcp-server-card+json']}`."
        ),
        examples=[
            {"type": ["application/ai-skill"]},
            {"type": ["application/vnd.huggingface.space+json"]},
            {"type": ["application/mcp-server-card+json"]},
        ],
    )


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: SearchQuery
    federation: FederationMode = Field(
        default="auto",
        description="Federation mode requested by the client: auto, referrals, or none.",
    )
    pageSize: int = Field(default=10, ge=1, le=100, description="Maximum results to return.")
    pageToken: str | None = Field(
        default=None,
        description="Opaque pagination token from a previous response, when supported.",
    )


class SearchResult(CatalogEntry):
    score: int = Field(ge=0, le=100)
    source: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
    referrals: list[CatalogEntry] = Field(default_factory=list)
    pageToken: str | None = None
