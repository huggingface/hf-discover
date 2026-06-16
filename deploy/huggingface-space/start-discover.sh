#!/usr/bin/env bash
set -euo pipefail

MEILI_URL="${DISCOVER_MEILI_URL:-http://127.0.0.1:7700}"
MEILI_INDEX="${DISCOVER_MEILI_INDEX:-hf_skills}"
MEILI_DB_PATH="${DISCOVER_MEILI_DB_PATH:-/home/user/app/data.ms}"
MEILI_SOURCE_BIN="${DISCOVER_MEILI_BIN:-}"
MEILI_LOCAL_BIN="${DISCOVER_MEILI_LOCAL_BIN:-/tmp/meilisearch}"
MEILI_MANIFEST="${DISCOVER_MEILI_MANIFEST:-}"
SKILLS_ARTIFACT_DIR="${DISCOVER_SKILLS_ARTIFACT_DIR:-}"
SKILLS_DISTRIBUTION_DIR="${DISCOVER_SKILLS_DISTRIBUTION_DIR:-}"
PORT="${PORT:-7860}"
MEILI_PID=""
export MEILI_URL MEILI_INDEX MEILI_DB_PATH MEILI_SOURCE_BIN MEILI_LOCAL_BIN MEILI_MANIFEST SKILLS_ARTIFACT_DIR SKILLS_DISTRIBUTION_DIR

cleanup() {
  if [[ -n "${MEILI_PID}" ]]; then
    kill "${MEILI_PID}" 2>/dev/null || true
    wait "${MEILI_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

copy_meilisearch() {
  if [[ -z "${MEILI_SOURCE_BIN}" ]]; then
    echo "DISCOVER_MEILI_BIN is not set; starting ARD without Meilisearch."
    return 1
  fi
  if [[ ! -f "${MEILI_SOURCE_BIN}" ]]; then
    echo "Meilisearch binary not found: ${MEILI_SOURCE_BIN}; starting without Meilisearch."
    return 1
  fi

  cp "${MEILI_SOURCE_BIN}" "${MEILI_LOCAL_BIN}"
  chmod +x "${MEILI_LOCAL_BIN}"

  if [[ -n "${MEILI_MANIFEST}" && -f "${MEILI_MANIFEST}" ]]; then
    python - <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

manifest_path = Path(os.environ["MEILI_MANIFEST"])
binary_path = Path(os.environ["MEILI_LOCAL_BIN"])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
expected = manifest.get("sha256")
if expected:
    digest = hashlib.sha256(binary_path.read_bytes()).hexdigest()
    if digest != expected:
        print("Meilisearch binary checksum mismatch.", file=sys.stderr)
        raise SystemExit(1)
PY
  fi
}

start_meilisearch() {
  local args=("${MEILI_LOCAL_BIN}" --db-path "${MEILI_DB_PATH}" --http-addr "127.0.0.1:7700" --env development --no-analytics)
  if [[ -n "${MEILI_MASTER_KEY:-}" ]]; then
    args+=(--master-key "${MEILI_MASTER_KEY}")
  fi
  "${args[@]}" &
  MEILI_PID="$!"

  for _ in $(seq 1 60); do
    if python - <<'PY' >/dev/null 2>&1
import os
import urllib.request

meili_url = os.environ.get("MEILI_URL", "http://127.0.0.1:7700").rstrip("/")
api_key = os.environ.get("MEILI_MASTER_KEY")
headers = {}
if api_key:
    headers["authorization"] = f"Bearer {api_key}"
request = urllib.request.Request(f"{meili_url}/health", headers=headers)
with urllib.request.urlopen(request, timeout=1) as response:
    raise SystemExit(0 if response.status < 500 else 1)
PY
    then
      echo "Meilisearch is available at ${MEILI_URL}."
      return 0
    fi
    sleep 1
  done

  echo "Meilisearch did not become healthy." >&2
  return 1
}

ingest_skills() {
  if [[ -z "${SKILLS_ARTIFACT_DIR}" ]]; then
    echo "DISCOVER_SKILLS_ARTIFACT_DIR is not set; skipping skills index ingest."
    return 0
  fi
  if [[ ! -f "${SKILLS_ARTIFACT_DIR}/_SUCCESS" || ! -f "${SKILLS_ARTIFACT_DIR}/hf-skills.ndjson" ]]; then
    echo "Skills artifact is incomplete or missing at ${SKILLS_ARTIFACT_DIR}; skipping ingest."
    return 0
  fi

  python - <<'PY'
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

meili_url = os.environ.get("DISCOVER_MEILI_URL", "http://127.0.0.1:7700").rstrip("/")
index = os.environ.get("DISCOVER_MEILI_INDEX", "hf_skills")
artifact_dir = Path(os.environ["DISCOVER_SKILLS_ARTIFACT_DIR"])
api_key = os.environ.get("MEILI_MASTER_KEY")

settings = {
    "searchableAttributes": [
        "skill_name",
        "marketplace_description",
        "skill_description",
        "title",
        "heading_path",
        "content",
        "supporting_files",
        "supporting_content",
        "text",
        "path",
    ],
    "displayedAttributes": [
        "id",
        "repo",
        "skill",
        "skill_name",
        "skill_description",
        "marketplace_description",
        "path",
        "url",
        "raw_url",
        "kind",
        "title",
        "heading_path",
        "content",
        "supporting_files",
        "version",
        "updated_at",
        "ordinal",
        "part",
    ],
    "filterableAttributes": ["repo", "skill", "kind", "path", "version"],
    "sortableAttributes": ["skill", "ordinal", "part"],
    "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"],
}


def request(method: str, path: str, *, data: bytes | None = None, content_type: str | None = None):
    headers = {}
    if content_type:
        headers["content-type"] = content_type
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{meili_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "DELETE":
            return None
        raise
    return json.loads(body) if body else None


def wait(task):
    if not task or "taskUid" not in task:
        return
    uid = task["taskUid"]
    for _ in range(240):
        data = request("GET", f"/tasks/{uid}")
        if data["status"] in {"succeeded", "failed", "canceled"}:
            error = data.get("error") or {}
            if data["type"] == "indexDeletion" and error.get("code") == "index_not_found":
                return
            if data["status"] != "succeeded":
                raise RuntimeError(json.dumps(data, indent=2))
            return
        time.sleep(0.25)
    raise TimeoutError(f"Meilisearch task {uid} did not finish")


wait(request("DELETE", f"/indexes/{index}"))
wait(
    request(
        "POST",
        "/indexes",
        data=json.dumps({"uid": index, "primaryKey": "id"}).encode(),
        content_type="application/json",
    )
)
wait(request("PATCH", f"/indexes/{index}/settings", data=json.dumps(settings).encode(), content_type="application/json"))
wait(
    request(
        "POST",
        f"/indexes/{index}/documents?primaryKey=id",
        data=(artifact_dir / "hf-skills.ndjson").read_bytes(),
        content_type="application/x-ndjson",
    )
)
manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
print(f"Loaded {manifest.get('document_count')} skills index documents into {index}.")
PY
}

if copy_meilisearch; then
  start_meilisearch
  export DISCOVER_MEILI_URL="${MEILI_URL}"
  export DISCOVER_MEILI_INDEX="${MEILI_INDEX}"
  ingest_skills
fi

exec uvx --refresh --from hf-discover hf-discover serve --host 0.0.0.0 --port "${PORT}"
