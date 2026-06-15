#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Download a pinned Meilisearch binary and publish it to a Hugging Face bucket."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = ROOT / "hf-discover.toml"
DEFAULT_OUT = ROOT / "out" / "meilisearch"


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


def asset_url(version: str, platform: str) -> str:
    return f"https://github.com/meilisearch/meilisearch/releases/download/v{version}/meilisearch-{platform}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, path.open("wb") as handle:  # noqa: S310
        shutil.copyfileobj(response, handle)
    path.chmod(0o755)


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True)  # noqa: S603


def bucket_id(bucket: str) -> str:
    return bucket.removeprefix("hf://buckets/").rstrip("/")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--version")
    parser.add_argument("--platform")
    parser.add_argument("--bucket")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-upload", action="store_true", help="Only build local vendor artifact")
    parser.add_argument(
        "--force", action="store_true", help="Download even if binary already exists"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.settings)
    version = args.version or nested(settings, "meilisearch", "vendor", "version") or "1.44.0"
    platform = (
        args.platform or nested(settings, "meilisearch", "vendor", "platform") or "linux-amd64"
    )
    bucket = args.bucket or nested(settings, "meilisearch", "vendor", "bucket")
    if not isinstance(bucket, str) or not bucket:
        raise SystemExit("Missing bucket. Set meilisearch.vendor.bucket or pass --bucket.")

    target_dir = args.out_dir / f"v{version}" / platform
    binary = target_dir / "meilisearch"
    url = asset_url(version, platform)

    if args.force or not binary.exists():
        print(f"Downloading {url}")
        download(url, binary)
    else:
        print(f"Using existing {binary}")

    digest = sha256(binary)
    (target_dir / "SHA256SUMS").write_text(f"{digest}  meilisearch\n", encoding="utf-8")
    manifest = {
        "name": "meilisearch",
        "version": version,
        "platform": platform,
        "source": url,
        "binary": "meilisearch",
        "sha256": digest,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))

    if args.no_upload:
        return

    run(["uvx", "hf", "buckets", "create", bucket_id(bucket), "--exist-ok"])
    run(
        [
            "uvx",
            "hf",
            "buckets",
            "sync",
            str(args.out_dir / f"v{version}"),
            f"{bucket.rstrip('/')}/v{version}",
            "--delete",
        ]
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
