# Hugging Face Skills Search Plan

## Goal

Add first-class search over the [`huggingface/skills`](https://github.com/huggingface/skills)
repository to `discover`, backed by Meilisearch. `discover` should own the indexing
schema, ingestion pipeline, Meilisearch settings, and ARD API integration. The
`huggingface/skills` repository remains the source content repository only.

The intended production shape is:

```text
huggingface/skills repo
        |
        | publish-time script or manual command
        v
local generated artifact folder
  latest/ai-catalog.json
  latest/hf-skills.ndjson
  latest/manifest.json
  latest/_SUCCESS
        |
        | uploaded/synced to Hugging Face storage
        v
Hub-hosted artifact folder
  dataset repo, bucket, or mounted storage
        |
        | mounted or downloaded by
        v
discover runtime
        |
        | syncs if manifest is stale
        v
Meilisearch index hf_skills
```

Meilisearch is a rebuildable runtime projection of the portable NDJSON artifact. It is not
part of the publishing path and is not the source of truth.

## Decisions

- Use the Python `meilisearch` SDK rather than raw HTTP for ARD integration.
- Use a Hub-hosted artifact folder as the canonical portable publishing artifact.
- Include both `ai-catalog.json` for direct ARD catalog consumption and NDJSON for
  Meilisearch indexing.
- Generate that folder at skill publish time, or manually, then upload/sync it to Hugging Face
  storage.
- Do not require Meilisearch during publishing.
- Do not use Meilisearch dumps/snapshots as the source-of-truth artifact.
- Put ingestion, artifact, sync, and search code in this `discover` repo.
- Treat `huggingface/skills` as an external input source.
- Start with one document per Markdown section from `SKILL.md` files.
- Optionally support indexing supporting text files later.
- Expose Meilisearch ranking scores in ARD result metadata.

## Why NDJSON instead of Meilisearch dumps

NDJSON remains the long-lived Meilisearch ingest artifact because it is:

- portable across Meilisearch versions
- inspectable and easy to debug
- simple to regenerate locally, in GitHub Actions, or in a Hugging Face Job
- directly loadable into Meilisearch
- independent of Meilisearch internal dump/snapshot formats

Meilisearch dumps/snapshots can still be useful for operational backup, but they should not
be the canonical ingest artifact for the skills content.

`ai-catalog.json` should be generated from the same document/source pass and published in the
same artifact folder. It is the direct ARD catalog representation for clients that
want all skills without semantic search.

## Dependencies

Add the Meilisearch Python SDK:

```toml
meilisearch>=0.34
```

Exact version can be pinned during implementation based on current resolver output.

## Proposed package layout

```text
src/discover/skills_index/
  __init__.py
  documents.py      # clone/walk/parse/chunk huggingface/skills into documents
  artifacts.py      # write/read NDJSON and manifest files
  meili.py          # configure/load/search Meilisearch with the SDK
  sync.py           # compare manifest/index state and load only when stale

src/discover/hf_skills.py  # high-level Hugging Face skills source entrypoints
```

Potential CLI surface:

```bash
# Build a syncable artifact folder.
discover skills build \
  --repo https://github.com/huggingface/skills.git \
  --out-dir out/hf-skills/latest

# Optionally stage both latest/ and commits/<commit>/ for upload.
discover skills package \
  --artifact-dir out/hf-skills/latest \
  --out-dir out/hf-skills-upload

# Upload the generated folder to a Hub dataset repo or other bucket-like storage.
discover skills upload \
  --artifact-root out/hf-skills-upload \
  --repo-id your-org/discover-skills-index \
  --repo-type dataset

# Populate an externally managed Meilisearch index from an artifact folder.
discover skills index build \
  --artifact-dir /data/discover/hf-skills/latest \
  --meili-url http://localhost:7700 \
  --meili-api-key "$MEILI_MASTER_KEY" \
  --index hf_skills

# Search the populated index.
discover skills search \
  "dataset viewer SQL query" \
  --meili-url http://localhost:7700 \
  --meili-api-key "$MEILI_MASTER_KEY" \
  --index hf_skills
```

The upload command can be implemented with `huggingface_hub.HfApi.upload_folder`, or users
can call `hf upload` directly. The essential contract is the generated folder layout, not the
upload mechanism.

## Document schema

Initial Meilisearch document shape:

```json
{
  "id": "huggingface-skills-<commit>-skills-hf-cli-skill-md-003",
  "repo": "huggingface/skills",
  "branch": "main",
  "commit": "<source commit sha>",
  "skill": "hf-cli",
  "skill_name": "hf-cli",
  "skill_description": "...",
  "skill_meta": {},
  "path": "skills/hf-cli/SKILL.md",
  "url": "https://github.com/huggingface/skills/blob/<commit>/skills/hf-cli/SKILL.md",
  "kind": "skill_section",
  "title": "Repository management",
  "heading_path": ["Hugging Face CLI", "Repository management"],
  "content": "...",
  "text": "combined searchable text",
  "ordinal": 3,
  "part": 0
}
```

Notes:

- `id` must be stable for the source commit, path, section ordinal, and part ordinal.
- `text` is a convenience field combining skill name, description, path, headings, and content.
- `content` is the displayable chunk.
- `heading_path` preserves section context.
- `kind` starts as `skill_section`; reserve `supporting_file` for later.

## Chunking strategy

For `SKILL.md`:

1. Parse YAML frontmatter for at least `name` and `description`.
2. Split Markdown body by headings.
3. Preserve heading ancestry as `heading_path`.
4. Split very long sections into overlapping chunks.
5. Include frontmatter-derived metadata on every emitted document.

Suggested limits:

- `MAX_CHARS`: approximately 12,000
- `OVERLAP_CHARS`: approximately 800

This is intentionally simple and robust. We can improve later with Markdown AST parsing if
needed.

## Meilisearch settings

Configure the `hf_skills` index approximately as:

```json
{
  "searchableAttributes": [
    "skill_name",
    "skill_description",
    "title",
    "heading_path",
    "content",
    "text",
    "path"
  ],
  "displayedAttributes": [
    "id",
    "repo",
    "branch",
    "commit",
    "skill",
    "skill_name",
    "skill_description",
    "path",
    "url",
    "kind",
    "title",
    "heading_path",
    "content",
    "ordinal",
    "part"
  ],
  "filterableAttributes": [
    "repo",
    "branch",
    "commit",
    "skill",
    "kind",
    "path"
  ],
  "sortableAttributes": [
    "skill",
    "ordinal",
    "part"
  ],
  "rankingRules": [
    "words",
    "typo",
    "proximity",
    "attribute",
    "sort",
    "exactness"
  ]
}
```

Search requests should set:

```json
{
  "showRankingScore": true,
  "showRankingScoreDetails": false
}
```

Expose `_rankingScore` as the ARD result score/metadata. Optionally expose
`_rankingScoreDetails` behind a debug flag.

## Artifact format

Build commands should write a complete, syncable folder:

```text
ai-catalog.json
hf-skills.ndjson
manifest.json
_SUCCESS
```

Manifest shape:

```json
{
  "schema_version": 1,
  "source_repo": "huggingface/skills",
  "source_url": "https://github.com/huggingface/skills.git",
  "source_branch": "main",
  "source_commit": "<commit sha>",
  "generated_at": "2026-05-13T00:00:00Z",
  "document_count": 435,
  "index": "hf_skills",
  "artifacts": {
    "catalog": "ai-catalog.json",
    "documents": "hf-skills.ndjson"
  }
}
```

Recommended uploaded layout:

```text
discover/hf-skills/
  latest/
    ai-catalog.json
    hf-skills.ndjson
    manifest.json
    _SUCCESS
  commits/
    <commit>/
      ai-catalog.json
      hf-skills.ndjson
      manifest.json
      _SUCCESS
```

For a Hub dataset repo, this can simply be the repository file layout:

```text
your-org/discover-skills-index
  latest/ai-catalog.json
  latest/hf-skills.ndjson
  latest/manifest.json
  latest/_SUCCESS
  commits/<commit>/ai-catalog.json
  commits/<commit>/hf-skills.ndjson
  commits/<commit>/manifest.json
  commits/<commit>/_SUCCESS
```

To avoid partial reads, build into a temporary directory and promote atomically where the
storage backend supports it. If atomic rename is unavailable, write a completion marker only
after `ai-catalog.json`, `hf-skills.ndjson`, and `manifest.json` are flushed:

```text
_SUCCESS
```

The Space should only consume artifact directories containing `_SUCCESS`.

## Direct catalog artifact

Because the current skills catalog is small, the artifact folder should also include a direct
ARD catalog document:

```text
ai-catalog.json
```

This follows the spec's capability manifest shape and can list skills, MCP servers, A2A
agent cards, nested catalogs, registries, datasets, or other artifact types in one pass.
For the Hugging Face skills source, entries initially use `application/ai-skill` and point at
full `SKILL.md` artifacts.

Example shape:

```json
{
  "specVersion": "1.0",
  "host": {
    "displayName": "Hugging Face Skills",
    "identifier": "urn:huggingface:skills"
  },
  "entries": [
    {
      "identifier": "urn:huggingface:skill:hf-cli",
      "displayName": "hf-cli",
      "mediaType": "application/ai-skill",
      "url": "https://huggingface.co/datasets/your-org/discover-skills-index/resolve/main/skills/hf-cli/SKILL.md",
      "description": "Use the Hugging Face CLI.",
      "tags": ["huggingface", "skill"],
      "metadata": {
        "source": "huggingface/skills",
        "path": "skills/hf-cli/SKILL.md",
        "commit": "<source commit>"
      }
    }
  ]
}
```

Direct catalog retrieval is appropriate when a client wants the full small catalog without
semantic ranking. Semantic discovery should still use `POST /search`; deterministic browsing
can use the optional `GET /agents` API when implemented.


## Publish and upload plan

At skill publish time, or manually, run a command that produces the artifact folder locally.
No Meilisearch service is required for this step.

Example local generation:

```bash
discover skills build \
  --repo https://github.com/huggingface/skills.git \
  --branch main \
  --out-dir out/hf-skills/latest
```

Then upload/sync that folder to Hugging Face storage. For a Hub dataset repo, this can be
done with the Hugging Face CLI:

```bash
hf upload your-org/discover-skills-index \
  out/hf-skills/latest \
  latest \
  --repo-type dataset
```

Or with `huggingface_hub`:

```python
from huggingface_hub import HfApi

api = HfApi()
api.upload_folder(
    repo_id="your-org/discover-skills-index",
    repo_type="dataset",
    folder_path="out/hf-skills/latest",
    path_in_repo="latest",
    commit_message="Update skills search artifact",
)
```

A later convenience command may wrap this as `discover skills upload`, but the first
implementation can document direct `hf upload` / `HfApi.upload_folder` usage.

For rollback and reproducibility, prefer uploading both `latest/` and `commits/<commit>/`.
That can be done by staging a local upload root containing both directories and uploading the
root to the dataset repo.

## Runtime sync plan

On Space startup, local CLI sync, or an admin/manual refresh endpoint:

1. Locate the artifact folder. This can be a mounted path, a local directory, or a directory
   downloaded from a Hub dataset repo with `snapshot_download`.
2. Require `_SUCCESS` before consuming the folder.
3. Read `manifest.json`.
4. Compare `source_commit` and `schema_version` with the last loaded manifest.
5. If stale or missing, configure the `hf_skills` index and load `hf-skills.ndjson`.
6. Store the loaded manifest in a sidecar file in the writable runtime directory, or in a
   small metadata index/document if that later proves useful.

For the current data size, use simple full replacement rather than incremental indexing. The
index is small, rebuildable, and disposable.

If Meilisearch is unavailable, ARD should continue serving the existing Hugging Face
Spaces search backend and report skills-index unavailability in logs/health metadata.

## Artifact retrieval options

### Mounted folder

Best when a Space or Job can mount the bucket/dataset output:

```bash
DISCOVER_SKILLS_ARTIFACT_DIR=/data/discover/hf-skills/latest
```

### Hub dataset download

Best for local CLI, CI, and deployments without a mounted bucket:

```python
from huggingface_hub import snapshot_download

artifact_root = snapshot_download(
    repo_id="your-org/discover-skills-index",
    repo_type="dataset",
    allow_patterns=["latest/*"],
)
artifact_dir = f"{artifact_root}/latest"
```

## ARD API integration

There are three complementary discovery surfaces:

1. `ai-catalog.json` for direct full-catalog retrieval. This is ideal while the catalog is
   small and for clients that want every advertised skill in one pass.
2. `POST /search` for relevance-ranked natural-language discovery. This remains the required
   registry API surface and can use Meilisearch when configured.
3. Optional `GET /agents` for deterministic browse/list behavior with filtering,
   ordering, and pagination but no semantic ranking.

The existing `/search` endpoint should be able to include indexed skills in
`application/ai-skill` results.

Initial behavior options:

1. Add a source filter, e.g. `source=huggingface-skills`, to search only indexed skills.
2. Later merge indexed skills with existing Hugging Face Spaces generated skills.

Suggested direct catalog routes:

```text
GET /.well-known/ai-catalog.json
GET /catalogs/huggingface-skills/ai-catalog.json
GET /agents  # optional deterministic list endpoint
```

The direct catalog routes should return the generated `ai-catalog.json` from the mounted or
downloaded artifact folder. They should not require Meilisearch.

Returned entry shape should include:

```json
{
  "id": "huggingface-skills:<doc-id>",
  "name": "<skill_name>",
  "description": "<title or skill_description>",
  "mediaType": "application/ai-skill",
  "url": "<github blob url>",
  "score": 0.9679,
  "metadata": {
    "source": "huggingface/skills",
    "sourceType": "meilisearch",
    "skill": "huggingface-datasets",
    "path": "skills/huggingface-datasets/SKILL.md",
    "commit": "<commit>",
    "rankingScore": 0.9679
  }
}
```

Open question: ARD spec compatibility for a top-level `score` field should be
confirmed against `spec/ard.md`. If the spec does not allow top-level `score`, keep
it in `metadata.rankingScore`.

## Meilisearch runtime model

Meilisearch is optional and externally managed. `discover` does not install, download,
start, stop, or supervise the Meilisearch server. It only knows how to configure an index,
load documents from the portable artifact, and search an already reachable Meilisearch
endpoint.

Configuration may come from CLI options or environment variables. CLI options take
precedence.

```bash
DISCOVER_MEILI_URL=http://localhost:7700
DISCOVER_MEILI_API_KEY=...
DISCOVER_MEILI_INDEX=hf_skills
```

Equivalent CLI options:

```bash
--meili-url http://localhost:7700
--meili-api-key "$MEILI_MASTER_KEY"
--index hf_skills
```

Users can install/run Meilisearch however they prefer: Docker, package manager, direct binary,
managed service, or platform-provided sidecar. The project documentation can include examples,
but the CLI should not own installation or OS/architecture detection.

The main Meilisearch operation exposed by `discover` should be a build/sync command that
populates the index from a mounted, local, or downloaded artifact folder:

```bash
discover skills index build \
  --artifact-dir /data/discover/hf-skills/latest \
  --meili-url http://localhost:7700 \
  --meili-api-key "$MEILI_MASTER_KEY" \
  --index hf_skills
```

For current scale, this command can perform a full replacement load instead of incremental
updates.

## Implementation phases

### Phase 1: portable artifact pipeline

- Add document parsing/chunking and artifact read/write modules.
- Add `discover skills build --out-dir ...`.
- Write `ai-catalog.json`, `hf-skills.ndjson`, `manifest.json`, and `_SUCCESS`.
- Document direct upload with `hf upload` and `HfApi.upload_folder`.

Acceptance:

- `discover skills build` writes a complete syncable artifact folder containing both the
  direct catalog and Meilisearch ingest documents.
- The artifact can be uploaded to a Hub dataset repo without further transformation.
- The manifest records source commit, schema version, document count, and artifact names.

### Phase 2: Meilisearch index build/search

- Add `meilisearch` dependency.
- Add index configuration and full replacement load logic.
- Add `discover skills index build --artifact-dir ...` for an existing Meilisearch service.
- Add `discover skills search ...` for an existing Meilisearch service.
- Resolve Meilisearch configuration from CLI options first, then environment variables.

Acceptance:

- `discover skills index build` loads the artifact into an externally managed Meilisearch.
- Repeated builds skip reload when manifest metadata is unchanged, unless forced.
- `discover skills search "dataset viewer SQL query"` returns scored hits when Meilisearch is configured.
- When Meilisearch is not configured, existing Spaces search remains usable.

### Phase 3: runtime retrieval

- Support mounted artifact directories.
- Support downloading `latest/*` from a Hub dataset repo with `snapshot_download`.
- Serve direct catalog routes from the resolved artifact folder without requiring Meilisearch.
- Add startup/runtime sync hook for configured deployments.

Acceptance:

- Space can start with an empty Meilisearch index and load from a mounted or downloaded
  artifact.
- If Meilisearch is unavailable, existing Hugging Face Spaces search and direct catalog
  retrieval still work.

### Phase 4: API integration

- Add a Meilisearch-backed skill search adapter.
- Expose indexed skill results through `/search` behind a source/filter option.
- Preserve current HF Spaces behavior.

Acceptance:

- Existing Spaces tests continue to pass.
- `/search` can return indexed skills with ranking score metadata.
- Direct catalog routes can return all generated skills without semantic search.

## Testing strategy

Follow repo guidance: avoid mocks and monkeypatching.

Suggested tests:

- Pure document-building tests over small temporary fixture directories.
- Manifest read/write roundtrip tests.
- Meilisearch integration smoke test gated by an environment variable, e.g.
  `DISCOVER_MEILI_TEST_URL`, so normal unit tests do not require a running service.
- CLI smoke tests for build against local fixtures.
- Artifact upload tests should use local folder staging and avoid live Hub calls by default;
  live Hub upload can be a manually gated smoke test.

Do not test type-only DTO properties that `ty` already covers.

## Open questions

- Should indexed skills be merged with Space-generated skills by default, or require an
  explicit source filter initially?
- Should the default `/.well-known/ai-catalog.json` include only generated Hugging Face skills,
  or also advertise this registry and generated Space/MCP entries?
- Should `SKILL.md` result URLs point to GitHub blob URLs, raw URLs, or an ARD route
  that can return the skill section/full skill?
- Should we index only `SKILL.md`, or include supporting files in the first production pass?
- Should the Space use a colocated but externally launched Meilisearch process, or connect to a separately hosted Meilisearch instance?
- Where should loaded manifest metadata live: sidecar file initially, or a metadata document/index?
