---
title: HF Agent Finder
emoji: 🔎
colorFrom: yellow
colorTo: blue
sdk: docker
app_port: 7860
base_path: /docs
---

# HF Agent Finder

Agent Finder registry adapter for Hugging Face Spaces.

This Docker Space runs the latest published `hf-agentfinder` package on container start:

```bash
uvx --refresh --from hf-agentfinder agentfinder serve --host 0.0.0.0 --port 7860
```

Useful endpoints:

- `GET /health`
- `POST /search`
- `GET /docs`
- `GET /skills/huggingface/{owner}/{space}/SKILL.md`
- `GET /spaces/huggingface/{owner}/{space}/agents.md`

Restarting or rebuilding the Space resolves the latest published `hf-agentfinder` release
from PyPI.
