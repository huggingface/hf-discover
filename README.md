# hf-discover

A small ARD registry adapter for Hugging Face Skills and Spaces.

It exposes Hugging Face discovery as:

- a CLI: `hf-discover search "remove background from image"`
- version introspection: `hf-discover --version`
- a hosted ARD registry client: `hf-discover search "remove background from image"`
- a generic ARD registry client: `hf-discover search --registry-url https://registry.example "remove background from image"`
- a primary ARD REST API combining indexed Hugging Face Skills and Hugging Face
  Spaces: `POST /search`
- a targeted nested Hugging Face Spaces registry: `POST /registries/huggingface/spaces/search`
- generated skill artifacts for Spaces via `GET /skills/huggingface/{owner}/{space}/SKILL.md`
- generated MCP Registry descriptors for MCP Spaces via
  `GET /mcp/huggingface/{owner}/{space}/server.json`

The hosted REST API combines Skills and Spaces in the primary registry so simple clients
only need to call `POST /search`. The nested Spaces registry remains available for clients
that want targeted Spaces-only discovery or explicit registry traversal.

## Features

### Space Search and Skill Generation

`hf-discover` exposes Hugging Face Spaces semantic search in the primary `/search` endpoint
and as a targeted nested registry backend at `/registries/huggingface/spaces/search`.
Search requests use the Hub's agent-oriented semantic search (`agents=true`) and return
matching Spaces as ARD catalog entries. By default, results can include generated
`application/ai-skill` artifacts, plus `application/mcp-server-card+json` entries for
matching Spaces tagged `mcp-server`.

Search responses strictly include only Spaces whose runtime stage is `RUNNING`, so returned
entries are limited to Spaces that are currently ready to serve traffic. The runtime stage
is also surfaced in result metadata as `runtimeStage`.

The generated skill wraps the Space's `agents.md` instructions with the required skill
frontmatter (`name` and `description`) plus source metadata such as the Space ID, Hub URL,
app URL, and original `agents.md` URL. This lets clients discover a relevant Space, fetch
the generated skill, and install or load it using their normal skill flow.

For clients that want raw Space descriptors instead of skills, request
`application/vnd.huggingface.space+json` from either the primary search endpoint or the
nested Spaces search endpoint.

Requests for `application/mcp-server-card+json` add `filter=mcp-server` to the downstream
Hub search and return MCP server card catalog entries that point at this adapter's
generated `server.json` descriptor route. The legacy `application/mcp-server+json` filter
is accepted as a transition alias, but new responses use the `*-card+json` media type
from the pinned ARD spec. Fetching that descriptor performs a direct Hugging Face Space
info lookup, verifies the Space is tagged `mcp-server`, and synthesizes an MCP
Registry-style document whose `remotes[]` contains the Space's Gradio `streamable-http`
MCP endpoint. When Hub runtime metadata includes a Space domain, that domain is used for
app and MCP URLs; otherwise the adapter falls back to the standard `.hf.space` slug
convention.

The CLI queries the hosted hf-discover deployment by default and can query any
ARD-compatible registry by passing `--registry-url`. The value may be either a registry
base URL or the `/search` endpoint. In this mode the CLI POSTs an ARD
`SearchRequest` and renders the returned `SearchResponse` using the same JSON/table output
paths as the Hugging Face Spaces adapter. Pass `--local` to search directly from the
current process instead.

### Client-side Catalog Navigation

`hf-discover navigate URL QUERY` is a client-only ARD discovery helper. Given a website
URL, it fetches the site's `/.well-known/ai-catalog.json`, prints the catalog and registry
URLs it discovers, follows referenced `application/ai-catalog+json` catalogs within a
bounded depth, and POSTs the query to referenced `application/ai-registry+json` search
endpoints. It can optionally follow registry referrals with `--follow-referrals`.

Navigation is intentionally not exposed by the hosted server, because arbitrary URL
fetching belongs first in a user-controlled client and would need additional SSRF controls
before becoming a public HTTP feature.

### Combined Skills and Spaces Registry

The primary HTTP `POST /search` endpoint combines the Meilisearch-backed
`huggingface/skills` index with Hugging Face Spaces search. For omitted media type or
`application/ai-skill`, it can return both indexed `SKILL.md` artifacts and generated Space
skills in one ranked response. Section-level Skills index hits are grouped into skill-level
search results.

Indexed Hugging Face Skills are directory-style skills, so their search result `url` points
at the skill directory, not the contained `SKILL.md` file. Generated Space skills are
single-file artifacts materialized by this adapter and continue to point at the generated
`/skills/huggingface/{owner}/{space}/SKILL.md` URL.

For `application/vnd.huggingface.space+json` and `application/mcp-server-card+json`,
primary search routes directly to the Spaces backend because those media types are
Space-specific.

The registry uses the ARD v0.5 search envelope: artifact type constraints are
expressed as `query.filter.type`, response entries use the catalog `type` field, and
Hugging Face entries use domain-anchored `urn:ai:hf.co:...` identifiers. Catalog entry
models enforce the v0.5 strict value-or-reference rule, domain-anchored `urn:ai:<fqdn>:...`
identifiers, and integer 0-100 relevance scores.

Structured filters use the ARD v0.5 field-path semantics for exact matching after
retrieval: scalar filter values are treated like single-item arrays, values within one
filter key are ORed, different filter keys are ANDed, arrays on entries match when any
item matches, nested paths such as `metadata.sourceType` are supported, and `publisher`
is derived from the entry identifier's publisher domain.

The primary server exposes `GET /.well-known/ai-catalog.json` as an ARD discovery
document. It advertises the primary Hugging Face Discover registry and the nested
Spaces registry as `application/ai-registry+json` entries using v0.5 `type` fields and
domain-anchored `urn:ai:hf.co:...` identifiers.

By default, advertised registry, generated Space skill, and generated MCP `server.json`
URLs are derived from the incoming request base URL, because those URLs point at
materialized artifacts and search routes served by this adapter. Set
`DISCOVER_PUBLIC_BASE_URL` only when a reverse proxy, staging deployment, or self-hosted
runtime reports an internal base URL but clients need a different public prefix.
Space-owned URLs such as `agents.md`, app URLs, and MCP endpoints continue to point at
Hugging Face Space URLs derived from Hub/runtime metadata.

When clients request referrals with top-level `federation` set to `referrals` or `auto`, the
primary registry can still include a referral to the nested Hugging Face Spaces registry.
Simple clients can ignore referrals and use the combined results; traversal-capable clients
can use the referral for a follow-up Spaces-only search.

### Challenge Registry Server

`hf-discover challenge serve` runs a deterministic local fixture registry for client
development. It returns mixed ARD result types, including skills, MCP servers, A2A
agents, ai-catalog bundles, registry entries, referrals, empty registries, and nested
registries. Use it to test clients that need to follow registry trees and fetch referenced
artifacts without relying on Hugging Face or Meilisearch services.

`hf-discover challenge search` queries a running challenge registry and defaults to
requesting referrals, making it a convenient CLI path for agents that need to practice
ARD traversal. The generic `hf-discover search` command defaults to the hosted
deployment and also accepts `--registry-url` and `--federation none|referrals|auto`. When
registry-backed commands are run with `--json`, the CLI prints the registry's raw
`SearchResponse` body so clients can inspect exact `results`, `referrals`, `type`,
`url`, `data`, and `pageToken` fields returned by the server.

The challenge registry uses the same catalog-entry model and field-path filtering helper
as the primary server. Both registries expose `POST /explore` and return `501 Not
Implemented`, matching the ARD v0.5 behavior for registries that do not implement the
optional Explore facets API.

### Specification References

`spec/ard.md` remains the committed local ARD orientation snapshot. When a private pinned
upstream spec checkout is available locally at `spec/ard-spec/`, use its `spec/ard.md`,
ADRs, schemas, and conformance CLI as the authoritative artifacts for implementation
review. That checkout is intentionally gitignored.

The AI Catalog draft reference can be refreshed from the upstream `Agent-Card/ai-catalog`
repository with
`./scripts/update-ai-catalog-spec.sh`, which copies the latest Markdown and JSON assets
from its `specification/` folder into `spec/ai-catalog/`.

The vendored `spec/ai-catalog/` snapshot currently tracks the pre-merge content from
`Agent-Card/ai-catalog` PR #37, which updates catalog entries from `mediaType` to `type`.

### Roadmap

The next `hf-discover` version is expected to expand the CLI surface for arbitrary ARD
structured filters. Today the HTTP server accepts `query.filter` and applies exact-match
field-path filters after retrieval; the CLI exposes only the common media-type path
through `--kind`. Planned work includes improved server-side handling/pushdown for common
fields such as tags and Space SDK.

It will also use "auto" federation.

### Release Automation

Releases are built through the same quality gates as CI: locked dependency sync, Ruff
format/lint checks, `ty` type checking, and pytest. The package supports the same minimum
Python version as `huggingface_hub` (`>=3.10.0`). The hosted Hugging Face Space deployment
uses Python 3.14 for runtime performance.

Run the release check with:

```bash
./scripts/check-release.sh
```

Optionally assert the expected project version:

```bash
./scripts/check-release.sh 0.1.0
```

Release from `main` after the intended code changes are merged. Run the **Release** GitHub
Action from `main`, choose `patch`, `minor`, or `major` for the version bump, and enter
confirmation value `release`. The workflow commits the `pyproject.toml` and `uv.lock`
version bump directly to `main`, builds artifacts from that bumped commit, publishes them
to PyPI using trusted publishing, attaches the artifacts to the GitHub Release, and
restarts the Hugging Face Space when the `HF_TOKEN` secret is configured. Use bump value
`none` only when retrying a failed release for the version already on `main`.

For local preflight or manual version changes, use
`python scripts/bump-version.py --bump patch|minor|major`, then `uv lock`, then
`./scripts/check-release.sh`.

PyPI trusted publishing must be configured for project `hf-discover` with owner
`huggingface`, repository `hf-discover`, workflow `release.yml`, and environment `pypi`.
The GitHub `pypi` environment does not need secrets for trusted publishing, but it must
exist if the repository requires explicit environment configuration.

### Hugging Face Space Deployment

The project includes a reproducible Docker Space definition in `deploy/huggingface-space/`.
It uses the official uv Python image and runs the latest published `hf-discover` package
with `uvx --refresh`, so restarting or rebuilding the Space resolves the newest PyPI
release without committing generated application code to the Space repository. This keeps
the hosted Space lightweight while letting PyPI releases drive runtime updates.

The Space startup wrapper can optionally run a pinned Meilisearch binary from an attached
Hugging Face bucket and ingest a generated Hugging Face Skills index artifact from another
attached bucket. When Meilisearch starts successfully, the wrapper exports the configured
Meilisearch URL and index for the API process so `POST /search` includes loaded Skills
results alongside Spaces results. Helper scripts in `scripts/` vendor the pinned
Meilisearch binary, create the configured buckets, attach them as Space volumes, and
configure runtime variables without running unsupervised installer scripts in the Space.

The documentation here is intentionally an orientation record: it states the deployment
idea and points to the artifacts that contain the operational evidence. For details, read
`hf-discover.toml`, `scripts/vendor-meilisearch.py`,
`scripts/configure-space-runtime.py`, and
`deploy/huggingface-space/start-discover.sh`.

## Usage

The examples below use the standalone `hf-discover` command form.

`--kind skill` requests AI-skill results. In the combined registry this includes indexed,
directory-style Hugging Face Skills from Meilisearch and generated single-file Space skill
wrappers. `--kind space` requests raw Hugging Face Space descriptors. `--kind mcp` requests
MCP server entries for Spaces tagged `mcp-server`. `--kind all` asks for the default mixed
view.

```bash
> hf-discover --version
> hf-discover search "generate image" --limit 5
> hf-discover search "generate image" --kind skill --json
> hf-discover search "generate image" --kind space --json
> hf-discover search "generate image" --kind mcp --json
> hf-discover mcp-server-json mcp-tools/FLUX.1-Kontext-Dev
> hf-discover search --registry-url https://registry.example "generate image" --kind skill --json
> hf-discover navigate https://example.com "generate image" --kind skill
> hf-discover navigate https://example.com "generate image" --follow-referrals --json
> hf-discover search "generate image" --kind space --local
> hf-discover serve --port 8080
> hf-discover challenge serve --port 8090
> hf-discover challenge search "find tools and registries" --federation referrals --json
```

### Recommended `hf` extension usage

For Hugging Face CLI users, the recommended install path is as an `hf` extension:

```bash
> hf extensions install huggingface/hf-discover
> hf discover --version
> hf discover search "generate image" --kind space --limit 5
```

The project still documents examples as `hf-discover ...` because the same CLI is also
available as a standalone Python console script. When installed as an extension, replace
`hf-discover` with `hf discover`.

```bash
> curl -X POST http://localhost:8080/search \
  -H 'content-type: application/json' \
  -d '{"query":{"text":"upload files to a dataset repo","filter":{"type":["application/ai-skill"]}},"pageSize":5}'
```

Search the targeted nested Spaces registry:

```bash
> curl -X POST http://localhost:8080/registries/huggingface/spaces/search \
  -H 'content-type: application/json' \
  -d '{"query":{"text":"remove background from image","filter":{"type":["application/ai-skill"]}},"pageSize":5}'
```

Search the local challenge registry:

```bash
> curl -X POST http://localhost:8090/search \
  -H 'content-type: application/json' \
  -d '{"query":{"text":"find tools and registries"},"federation":"referrals","pageSize":10}'
```

Fetch a generated skill:

```bash
> curl http://localhost:8080/skills/huggingface/mcp-tools/FLUX.1-Kontext-Dev/SKILL.md
```

To get generic Hugging Face Space descriptors instead of skill wrappers, request:

```json
{"query":{"text":"remove background from image","filter":{"type":["application/vnd.huggingface.space+json"]}},"pageSize":5}
```

### HF_TOKEN handling

Primary and nested Spaces registry search requests can forward a request-scoped Hugging
Face token for the downstream Spaces search call. The server checks
`X-HF-Authorization: Bearer ...`, then `Authorization: Bearer ...`, then `HF_TOKEN: ...`;
a header token overrides any token configured when the server starts and is not stored
beyond the request.
