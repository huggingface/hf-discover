# OpenEnv environment discovery

This consumer implements the declaration-only `0.1-draft` repository snapshot
profile from OpenEnv RFC 011. It is independently implemented in `discover.environments`;
it does not import OpenEnv or any candidate environment package.

## Local CLI

Generate a complete snapshot with `openenv catalog build`, then inspect it:

```bash
hf-discover environments "client smoke test" --catalog ./openenv-catalog.json --json
```

The output preserves the full inline ARD entry, source URI, environment path,
revision, unknowns and snapshot digest. Scores are deterministic lexical query
overlap, not environment quality or execution permission.

## HTTP and MCP

Set `DISCOVER_OPENENV_CATALOG` to an explicit local snapshot path before starting
the existing server. For tests or embedding, pass `environment_catalog=Path(...)`
to `create_app`.

Send the same ARD search request to `POST /search` or the MCP `search` tool:

```json
{
  "query": {
    "text": "client smoke test",
    "filter": {
      "type": ["application/vnd.openenv.environment-card+json"]
    }
  },
  "pageSize": 10
}
```

The initial profile is selected explicitly by type. Mixed live-Space/environment
type requests return an unsupported-profile error; existing unfiltered Skills
and Spaces behavior is unchanged. This avoids presenting unrelated ranking
scales as interchangeable. The environment path does not use `agents=true`,
running-state filters, generated skills, Space wake-ups or candidate endpoints.

Configured snapshot updates are read on each request, so correction and
withdrawal follow atomic file replacement. A missing, partial, unsupported,
tampered or inconsistent snapshot returns HTTP 503, never an empty successful
inventory. Unsupported filters or stale pagination tokens return HTTP 400.
Page tokens are bound to both the snapshot digest and query/filter values.

Supported exact field-path filters are `type`, `tags`, `capabilities`, `publisher`,
`data.license`, `data.name`, `data.source.provider`, and
`data.artifact_availability`.

The reader accepts complete inline cards only. It checks source/artifact revision
binding and rejects validated-interface claims because this profile supports
declarations, not RFC 008 report verification. It does not dereference
`license_url` or any other card reference. Request credentials are not passed
to this local metadata reader.

Publication, trusted publisher authority, private inventories and remote
snapshot retrieval are operator decisions outside this local-file profile.
