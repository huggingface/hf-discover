#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Configure the ARD Space volumes and runtime variables."""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = ROOT / "hf-discover.toml"


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def nested(data: dict[str, Any], *keys: str) -> Any | None:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def bucket_id(bucket: str) -> str:
    return bucket.removeprefix("hf://buckets/").rstrip("/")


def should_create_bucket(bucket: str) -> bool:
    return bucket_id(bucket) != "huggingface/skills"


def run(command: list[str]) -> None:
    redacted = [
        "MEILI_MASTER_KEY=<redacted>" if arg.startswith("MEILI_MASTER_KEY=") else arg
        for arg in command
    ]
    print("+", " ".join(redacted))
    subprocess.run(command, check=True)  # noqa: S603


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--space-id")
    parser.add_argument("--meilisearch-bucket")
    parser.add_argument("--skills-index-bucket")
    parser.add_argument("--meilisearch-version")
    parser.add_argument("--platform")
    parser.add_argument("--set-secret", action="store_true", help="Set MEILI_MASTER_KEY secret")
    parser.add_argument(
        "--generate-secret",
        action="store_true",
        help="Generate MEILI_MASTER_KEY if the local environment variable is absent",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.settings)

    space_id = args.space_id or nested(settings, "space", "id")
    meili_bucket = args.meilisearch_bucket or nested(settings, "meilisearch", "vendor", "bucket")
    skills_bucket = args.skills_index_bucket or nested(settings, "skills_index", "bucket")
    meili_mount = nested(settings, "space", "meilisearch_mount") or "/mnt/meilisearch"
    skills_mount = nested(settings, "space", "skills_index_mount") or "/mnt/skills"
    public_base_url = nested(settings, "space", "public_base_url")
    version = (
        args.meilisearch_version or nested(settings, "meilisearch", "vendor", "version") or "1.44.0"
    )
    platform = (
        args.platform or nested(settings, "meilisearch", "vendor", "platform") or "linux-amd64"
    )

    if not all(
        isinstance(value, str) and value for value in [space_id, meili_bucket, skills_bucket]
    ):
        raise SystemExit("Missing space id or bucket setting.")

    run(["uvx", "hf", "buckets", "create", bucket_id(meili_bucket), "--exist-ok"])
    if should_create_bucket(skills_bucket):
        run(["uvx", "hf", "buckets", "create", bucket_id(skills_bucket), "--exist-ok"])
    run(
        [
            "uvx",
            "hf",
            "spaces",
            "volumes",
            "set",
            space_id,
            "-v",
            f"{meili_bucket.rstrip('/')}:{meili_mount}:ro",
            "-v",
            f"{skills_bucket.rstrip('/')}:{skills_mount}:ro",
        ]
    )

    meili_bin = f"{meili_mount}/v{version}/{platform}/meilisearch"
    run(
        [
            "uvx",
            "hf",
            "spaces",
            "variables",
            "add",
            space_id,
            "-e",
            f"DISCOVER_MEILI_BIN={meili_bin}",
            "-e",
            f"DISCOVER_MEILI_MANIFEST={meili_mount}/v{version}/{platform}/manifest.json",
            "-e",
            f"DISCOVER_SKILLS_ARTIFACT_DIR={skills_mount}/index/latest",
            "-e",
            f"DISCOVER_SKILLS_DISTRIBUTION_DIR={skills_mount}/distribution/latest",
            "-e",
            "DISCOVER_SKILLS_DISTRIBUTION_BASE_URL=https://huggingface.co/buckets/huggingface/skills/resolve/distribution%2Flatest",
            "-e",
            "DISCOVER_MEILI_URL=http://127.0.0.1:7700",
            "-e",
            "DISCOVER_MEILI_INDEX=hf_skills",
            *(
                ["-e", f"DISCOVER_PUBLIC_BASE_URL={public_base_url.rstrip('/')}"]
                if isinstance(public_base_url, str) and public_base_url
                else []
            ),
        ]
    )

    if args.set_secret:
        key = os.environ.get("MEILI_MASTER_KEY")
        if not key and args.generate_secret:
            key = secrets.token_urlsafe(32)
        if not key:
            raise SystemExit("Set MEILI_MASTER_KEY locally or pass --generate-secret.")
        run(["uvx", "hf", "spaces", "secrets", "add", space_id, "-s", f"MEILI_MASTER_KEY={key}"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
