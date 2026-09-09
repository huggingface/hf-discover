from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

ENVIRONMENT_MEDIA_TYPE = "application/vnd.openenv.environment-card+json"
Text = Annotated[str, StringConstraints(min_length=1, max_length=8192, pattern=r"\S")]
Revision = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
Publisher = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=253,
        pattern=r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$",
    ),
]


def relative_path(value: str) -> str:
    if value != "." and (
        "\x00" in value
        or "\\" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError("Invalid repository-relative locator")
    return value


RelativePath = Annotated[Text, AfterValidator(relative_path)]


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RepositorySource(ProfileModel):
    provider: Literal["github"]
    id: Text
    uri: Text
    revision: Revision

    @model_validator(mode="after")
    def source_identity(self) -> RepositorySource:
        parsed = urlsplit(self.uri)
        expected_path = f"/{self.id}.git"
        if (parsed.scheme, parsed.netloc.lower(), parsed.path) != (
            "https",
            "github.com",
            expected_path,
        ):
            raise ValueError("Unsupported or inconsistent repository identity")
        if (
            parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.id)
            or any(part in (".", "..") for part in self.id.split("/"))
        ):
            raise ValueError("Invalid repository identity")
        return self


class Source(RepositorySource):
    path: RelativePath


class Generator(ProfileModel):
    name: Literal["openenv-git-catalog"]
    version: Literal["1"]


class Inventory(ProfileModel):
    root: RelativePath
    paths: list[RelativePath]


class CatalogIssue(ProfileModel):
    path: RelativePath
    code: Text
    message: Text
    severity: Literal["warning", "error"]


class SnapshotHeader(ProfileModel):
    schema_version: Literal["0.1-draft"]
    publisher: Publisher
    source: RepositorySource
    generator: Generator
    inventory: Inventory
    issues: list[CatalogIssue]
    complete: bool
    digest: Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class Artifact(ProfileModel):
    kind: Literal["git"]
    uri: Text
    path: Text
    revision: Revision


class Owner(ProfileModel):
    authority: Text
    id: Text


class Orchestration(ProfileModel):
    role: Literal["orchestration"]
    protocol: Literal["openenv"]


class AgentTools(ProfileModel):
    role: Literal["agent-tools"]
    protocol: Text
    status: Literal["declared"]
    source_revision: Revision


Interface = Annotated[Orchestration | AgentTools, Field(discriminator="role")]


class Card(ProfileModel):
    schema_version: Literal["0.1-draft"]
    name: Text
    description: Text
    owner: Owner | Literal["unknown"]
    source: Source
    artifact_availability: Literal["resolvable", "external", "unknown"]
    artifacts: list[Artifact] = Field(default_factory=list)
    license: Text
    license_url: Text | None = None
    interfaces: list[Interface]
    manifest_spec_version: int | str | None = None
    framework_requirement: Text | None = None

    @model_validator(mode="after")
    def artifact_binding(self) -> Card:
        if bool(self.artifacts) != (self.artifact_availability == "resolvable"):
            raise ValueError("Artifact availability and references disagree")
        expected = (self.source.uri, self.source.path, self.source.revision)
        if any((item.uri, item.path, item.revision) != expected for item in self.artifacts):
            raise ValueError("Artifact and source identify different subjects")
        if self.license == "other" and not self.license_url:
            raise ValueError("Other license needs evidence")
        return self

    @model_validator(mode="after")
    def interface_binding(self) -> Card:
        controls = [item for item in self.interfaces if item.role == "orchestration"]
        if len(controls) != 1:
            raise ValueError("One orchestration descriptor is required")
        tools = [item for item in self.interfaces if isinstance(item, AgentTools)]
        if len({item.protocol for item in tools}) != len(tools):
            raise ValueError("Duplicate tool protocol")
        if any(item.source_revision != self.source.revision for item in tools):
            raise ValueError("Tool evidence belongs to another revision")
        return self
