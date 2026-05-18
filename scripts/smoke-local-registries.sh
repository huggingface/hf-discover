#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${AGENTFINDER_SMOKE_BASE_URL:-http://127.0.0.1:8080}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 127
  fi
}

post_search() {
  local url="$1"
  local body="$2"
  curl -fsS \
    -H 'content-type: application/json' \
    -d "${body}" \
    "${url}"
}

assert_jq() {
  local json="$1"
  local filter="$2"
  local message="$3"
  if ! jq -e "${filter}" >/dev/null <<<"${json}"; then
    echo "Assertion failed: ${message}" >&2
    echo "${json}" | jq . >&2
    exit 1
  fi
}

require_command curl
require_command jq

echo "Checking health at ${BASE_URL}"
health="$(curl -fsS "${BASE_URL}/health")"
assert_jq "${health}" '.status == "ok"' "health status is ok"
assert_jq "${health}" '.registries["huggingface/skills"].path == "/search"' "skills registry path"
assert_jq "${health}" '.registries["huggingface/spaces"].path == "/registries/huggingface/spaces/search"' "spaces registry path"

echo "Searching primary skills registry"
skills_response="$(
  post_search \
    "${BASE_URL}/search" \
    '{"query":{"text":"upload files to a dataset repo","mediaType":"application/ai-skill"},"pageSize":5}'
)"
assert_jq "${skills_response}" '.results | length > 0' "skills search returns results"
assert_jq "${skills_response}" '.results[0].mediaType == "application/ai-skill"' "skills result media type"
assert_jq "${skills_response}" '.results[0].metadata.sourceType == "huggingface-skills"' "skills source type"
assert_jq "${skills_response}" '.results[0].score > 0' "skills result score"

echo "Searching primary registry with referrals"
referral_response="$(
  post_search \
    "${BASE_URL}/search" \
    '{"query":{"text":"remove background from image","mediaType":"application/ai-skill","federation":"referrals"},"pageSize":3}'
)"
assert_jq "${referral_response}" '.referrals | length > 0' "referral search returns referrals"
assert_jq "${referral_response}" '.referrals[0].mediaType == "application/ai-registry+json"' "referral media type"
assert_jq "${referral_response}" '.referrals[0].url | endswith("/registries/huggingface/spaces/search")' "spaces referral URL"

echo "Searching nested Spaces registry"
spaces_response="$(
  post_search \
    "${BASE_URL}/registries/huggingface/spaces/search" \
    '{"query":{"text":"remove background from image","mediaType":"application/ai-skill"},"pageSize":3}'
)"
assert_jq "${spaces_response}" '.results | length > 0' "spaces search returns results"
assert_jq "${spaces_response}" '.results[0].mediaType == "application/ai-skill"' "spaces result media type"
assert_jq "${spaces_response}" '.results[0].metadata.sourceType == "huggingface-space"' "spaces source type"

echo "Searching nested Spaces registry for MCP entries"
mcp_response="$(
  post_search \
    "${BASE_URL}/registries/huggingface/spaces/search" \
    '{"query":{"text":"image generation mcp server","mediaType":"application/mcp-server+json"},"pageSize":3}'
)"
assert_jq "${mcp_response}" '.results | length > 0' "MCP search returns results"
assert_jq "${mcp_response}" '.results[0].mediaType == "application/mcp-server+json"' "MCP result media type"
assert_jq "${mcp_response}" '.results[0].data.transport == "http"' "MCP transport"

echo "All local registry smoke checks passed."
