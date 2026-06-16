---
title: HF Discover
emoji: 🔎
colorFrom: yellow
colorTo: blue
sdk: docker
app_port: 7860
base_path: /docs
---

# HF Discover

ARD registry adapter for Hugging Face Skills and Spaces.

This Docker Space runs the latest published `hf-discover` package on Python 3.14 at
container start:

```bash
/home/user/app/start-discover.sh
```

The startup wrapper can run a vendored Meilisearch binary from an attached bucket and load
the generated Hugging Face Skills index before starting the ARD API. If the
Meilisearch bucket or skills index artifact is not mounted, the Space still starts and the
combined primary search still returns Hugging Face Spaces results; indexed Skills results
are added when Meilisearch is available.

Plain deployment sketch:

1. `scripts/vendor-meilisearch.py` downloads a pinned Meilisearch release binary, writes a
   checksum/manifest next to it, and syncs that folder to the configured binary bucket.
2. `scripts/configure-space-runtime.py` creates configured writable buckets when needed,
   attaches the Meilisearch binary bucket and public `huggingface/skills` bucket as Space
   volumes, sets runtime variables, and stores `MEILI_MASTER_KEY` as a Space secret.
3. `start-discover.sh` copies the mounted Meilisearch binary locally, verifies its
   checksum from the mounted manifest, starts Meilisearch on `127.0.0.1:7700`, loads the
   mounted `index/latest/hf-skills.ndjson` artifact into `hf_skills`, then starts the ARD
   API. Search results use `distribution/latest/index.json` to point GitHub-repo-based
   directory skills at their bucket-hosted `.tar.gz` artifacts.

This document is an orientation record. The scripts above are the detailed evidence and
should be read directly for exact command behavior, paths, and failure handling.

Expected runtime variables:

- `DISCOVER_MEILI_BIN`, e.g.
  `/mnt/meilisearch/v1.44.0/linux-amd64/meilisearch`
- `DISCOVER_MEILI_MANIFEST`, e.g.
  `/mnt/meilisearch/v1.44.0/linux-amd64/manifest.json`
- `DISCOVER_SKILLS_ARTIFACT_DIR`, e.g.
  `/mnt/skills/index/latest`
- `DISCOVER_SKILLS_DISTRIBUTION_DIR`, e.g.
  `/mnt/skills/distribution/latest`
- `DISCOVER_SKILLS_DISTRIBUTION_BASE_URL`, defaulting to
  `https://huggingface.co/buckets/huggingface/skills/resolve/distribution%2Flatest`
- `DISCOVER_MEILI_URL`, default `http://127.0.0.1:7700`
- `DISCOVER_MEILI_INDEX`, default `hf_skills`
- `DISCOVER_PUBLIC_BASE_URL`, optional canonical public URL used in discovery
  documents, referrals, and generated skill URLs when the runtime reports an internal
  base URL; leave unset/blank by default
- `MEILI_MASTER_KEY`, configured as a Space secret

Useful endpoints:

- `GET /health`
- `GET /.well-known/ai-catalog.json` for ARD / AI Catalog discovery
- `POST /search` for combined indexed Hugging Face Skills and Hugging Face Spaces
- `POST /registries/huggingface/spaces/search` for targeted Hugging Face Spaces search
- `GET /docs`
- `GET /skills/huggingface/{owner}/{space}/SKILL.md`
- `GET /spaces/huggingface/{owner}/{space}/agents.md`

Restarting or rebuilding the Space resolves the latest published `hf-discover` release
from PyPI.

Runtime setup helpers from the repo root:

```bash
uv run scripts/vendor-meilisearch.py
uv run scripts/configure-space-runtime.py --set-secret --generate-secret
```
