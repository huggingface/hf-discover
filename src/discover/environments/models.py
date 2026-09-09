from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ENVIRONMENT_MEDIA_TYPE = "application/vnd.openenv.environment-card+json"
Text = Annotated[str, StringConstraints(min_length=1, max_length=8192, pattern=r"\S")]
Revision = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(ProfileModel):
    provider: Literal["github"]
    id: Text
    uri: Text
    path: Text
    revision: Revision

    @model_validator(mode="after")
    def source_identity(self) -> Source:
        parsed = urlsplit(self.uri)
        expected_path = f"/{self.id}.git"
        if (parsed.scheme, parsed.netloc, parsed.path) != ("https", "github.com", expected_path):
            raise ValueError("Unsupported or inconsistent repository identity")
        owner, separator, repository = self.id.partition("/")
        if (
            parsed.query
            or parsed.fragment
            or not separator
            or not owner
            or not repository
            or "/" in repository
        ):
            raise ValueError("Invalid repository identity")
        if self.path != "." and (
            "\\" in self.path or any(part in ("", ".", "..") for part in self.path.split("/"))
        ):
            raise ValueError("Invalid environment locator")
        return self


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
