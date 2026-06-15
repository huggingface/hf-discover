#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

project_version="$(
  python - <<'PY'
import tomllib
from pathlib import Path

print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"])
PY
)"

expected_version="${1:-}"
if [[ -n "${expected_version}" && "${expected_version}" != "${project_version}" ]]; then
  echo "Expected version ${expected_version}, but pyproject.toml contains ${project_version}." >&2
  exit 1
fi

project_name="$(
  python - <<'PY'
import tomllib
from pathlib import Path

print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["name"])
PY
)"

echo "==> Checking release for ${project_name} ${project_version}"

echo "==> Syncing locked dependencies"
uv sync --locked

echo "==> Checking formatting"
uv run ruff format --check .

echo "==> Linting"
uv run ruff check .

echo "==> Type checking"
uv run ty check

echo "==> Running tests"
uv run python -m pytest

echo "==> Building source distribution and wheel"
uv build --clear

echo "==> Inspecting built artifacts"
python - <<'PY'
import tarfile
import zipfile
from pathlib import Path

dist = Path("dist")
artifacts = sorted(path for path in dist.iterdir() if not path.name.startswith("."))
if len(artifacts) != 2:
    names = ", ".join(path.name for path in artifacts) or "<none>"
    raise SystemExit(f"Expected exactly 2 release artifacts, found: {names}")

sdists = [path for path in artifacts if path.suffixes[-2:] == [".tar", ".gz"]]
wheels = [path for path in artifacts if path.suffix == ".whl"]
if len(sdists) != 1 or len(wheels) != 1:
    raise SystemExit(
        "Expected one .tar.gz source distribution and one .whl wheel; "
        f"found: {', '.join(path.name for path in artifacts)}"
    )

with zipfile.ZipFile(wheels[0]) as wheel:
    names = set(wheel.namelist())
    if not any(name.endswith(".dist-info/METADATA") for name in names):
        raise SystemExit(f"{wheels[0].name} is missing wheel metadata")
    if not any(name.endswith(".dist-info/entry_points.txt") for name in names):
        raise SystemExit(f"{wheels[0].name} is missing console script entry points")
    if "discover/cli.py" not in names:
        raise SystemExit(f"{wheels[0].name} is missing package modules")

with tarfile.open(sdists[0], "r:gz") as sdist:
    names = set(sdist.getnames())
    if not any(name.endswith("/pyproject.toml") for name in names):
        raise SystemExit(f"{sdists[0].name} is missing pyproject.toml")
    if not any(name.endswith("/README.md") for name in names):
        raise SystemExit(f"{sdists[0].name} is missing README.md")

for path in artifacts:
    print(f"  {path}")
PY

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

echo "==> Smoke-installing wheel in a clean virtual environment"
uv venv "${tmpdir}/venv" --python 3.14
uv pip install --python "${tmpdir}/venv/bin/python" dist/*.whl
"${tmpdir}/venv/bin/discover" --help >/dev/null

echo "==> Release artifacts are ready in dist/"
