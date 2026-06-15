# Hugging Face Spaces Search Notes

This project uses `huggingface_hub.HfApi.search_spaces()` as the first ARD
registry backend for Hugging Face Spaces.

## Spaces semantic search

`HfApi.search_spaces()` calls the Hub endpoint:

```text
GET /api/spaces/semantic-search?q=...
```

The SDK documents this endpoint as semantic search for multi-word queries and full-text
search for single-word queries. It returns `SpaceSearchResult` objects with fields useful
for ARD responses:

- `id` — Space id, for example `mcp-tools/FLUX.1-Kontext-Dev`
- `author`
- `title`
- `emoji`
- `sdk` — for example `gradio`, `docker`, or `static`
- `likes`
- `private`
- `tags`
- `runtime`
- `ai_short_description`
- `ai_category`
- `semantic_relevancy_score` — float from `0..1`
- `trending_score`

`discover` scales `semantic_relevancy_score` to a `0..100` ARD `score`.

## MCP server detection

The `huggingface_hub` source does not currently expose a dedicated typed field like
`mcp_enabled`, `mcp_server`, or `mcp_url` on `SpaceSearchResult` or `SpaceInfo`.

MCP enablement is visible through Space metadata, primarily via tags. MCP-enabled Spaces
appear with the tag:

```text
mcp-server
```

So the initial detection rule should be:

```python
def is_mcp_space(space) -> bool:
    return "mcp-server" in (space.tags or [])
```

For search queries that specifically ask for MCP servers, we can pass the same tag to
Hub search as a filter:

```python
api.search_spaces(
    query="generate images with flux",
    filter="mcp-server",
)
```

or combine it with other filters supported by the SDK.

The raw semantic-search endpoint also accepts an `agents=true` query parameter:

```text
GET /api/spaces/semantic-search?q=...&filter=mcp-server&agents=true
```

For ARD MCP searches, prefer sending both `filter=mcp-server` and
`agents=true` so the Hub applies the same agent-oriented filtering used by the web
experience. As of the current `huggingface_hub` version used by this project,
`HfApi.search_spaces()` exposes `filter` but does not expose `agents`, so supporting this
exact query shape may require a small raw endpoint adapter rather than the SDK helper.

Empirical inspection of this endpoint shows that `agents=true` behaves as a server-side
query parameter, not as a returned tag or field. Sample results still expose
`mcp-server` in `tags`, but do not expose an additional stable `agents` tag, ID, or
agent descriptor field in the semantic-search response. Therefore:

- use `mcp-server` as the MCP capability tag;
- use `agents=true` as an additional search parameter when querying the raw endpoint;
- do not rely on an `agents` response tag or field unless the Hub API adds one later.

## MCP endpoint materialization

The SDK source also does not expose a typed MCP endpoint URL for Spaces. MCP-tagged Gradio
Spaces expose an HTTP MCP endpoint under the Space app URL:

```text
https://{space-host}/gradio_api/mcp/
```

Prefer the domain returned in semantic-search runtime metadata
(`runtime.domains[].domain`) when present. If runtime domains are absent, fall back to the
standard `.hf.space` slug convention. `huggingface_hub.SpaceInfo` exposes `host` and
`subdomain`, but using `space_info()` for every search result would require an additional
Hub request per result; runtime domains are available in the raw semantic-search response.

The ARD mapping is:

```json
{
  "mediaType": "application/mcp-server+json",
  "url": "https://discover.example/mcp/huggingface/mcp-tools/FLUX.1-Kontext-Dev/server.json"
}
```

The adapter materializes that URL as an MCP Registry-style `server.json`. The route performs
a direct `GET https://huggingface.co/api/spaces/{owner}/{space}` lookup, verifies the Space
is tagged `mcp-server`, and returns a descriptor whose `remotes[]` contains the Gradio MCP
endpoint as a `streamable-http` remote. Non-MCP Spaces return an error instead of a
descriptor.

MCP entries should only be generated for Spaces returned by the agent-oriented Hub search
and tagged `mcp-server`. Unfiltered ARD searches may return both the generated
`application/ai-skill` entry and the `application/mcp-server+json` entry for the same
underlying Space.

## Space health / runtime status

`SpaceSearchResult` includes a `runtime` field. When present, it contains a `stage`, such as:

```text
RUNNING
BUILDING
STOPPED
PAUSED
RUNTIME_ERROR
```

The SDK's `search_spaces()` method also has:

```python
include_non_running: bool = False
```

When `include_non_running` is `True`, the SDK sends this query parameter to the Hub:

```text
includeNonRunning=true
```

When it is `False`, the SDK omits the parameter. The SDK documentation says this controls
whether non-running Spaces are included and defaults to `False`. Therefore, normal searches
should already exclude non-running Spaces at the Hub endpoint level.

`discover` also records the returned runtime stage in result metadata:

```json
{
  "metadata": {
    "runtimeStage": "RUNNING"
  }
}
```

## Filtering out non-running Spaces

There are two useful filtering layers:

1. **Server-side Hub filtering** — keep `include_non_running=False` when calling
   `HfApi.search_spaces()`. This is already the default and should exclude non-running
   Spaces according to the SDK docs.
2. **Client-side strict filtering** — after receiving results, drop any result whose
   `runtime.stage` is present and not `RUNNING`.

The second layer is stricter and useful if we want ARD to guarantee that all
returned Spaces are currently ready to call:

```python
def is_running(space) -> bool:
    return space.runtime is not None and space.runtime.stage == "RUNNING"
```

A less strict rule may be preferable if the Hub endpoint sometimes omits runtime metadata:

```python
def is_not_known_bad(space) -> bool:
    return space.runtime is None or space.runtime.stage == "RUNNING"
```

Current recommendation:

- Keep `include_non_running=False` by default.
- Continue surfacing `metadata.runtimeStage` in search results.
- Add an optional stricter `running_only` filter later if clients need guaranteed live
  Spaces rather than relevance-ranked discoverability.
