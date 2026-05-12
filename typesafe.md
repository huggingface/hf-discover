# Type Safety Standards

This project uses `ty` for type checking and Ruff for linting/formatting. Run the checks directly:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest
```

## Rules

- Target Python 3.14 and use modern typing syntax: `list[str]`, `dict[str, int]`, `X | None`.
- Annotate public APIs, FastAPI routes, CLI functions, and shared helpers.
- Prefer `Protocol`, `TypedDict`, `Literal`, and concrete Pydantic models over `Any` or loose
  `dict[str, object]` for structured data.
- Prefer `collections.abc` input types such as `Iterable`, `Sequence`, and `Mapping`; return
  concrete containers when callers rely on mutability.
- Narrow values with `isinstance`, `assert x is not None`, or small helper guards. Avoid
  `getattr` and `hasattr` unless the object is genuinely dynamic.
- In tests, prefer runtime assertions for narrowing over `cast(...)` when the behavior is
  enforceable.
- Use `# ty: ignore[rule]` only for narrow, justified exceptions. Avoid bare ignores.
- Keep type fixes behavior-preserving; check call sites before tightening flexible signatures.
