- Agent Finder specification is in spec/agentfinder.md
- Keep a high level log of Features and Capabilities in README.md under ##features.
- Project documentation is a lightweight orientation record, not the full source of truth.
  It should help humans quickly understand the big idea and help future agents know which
  scripts, workflows, specs, and plans to inspect for detailed question-answering. Prefer
  concise summaries with explicit artifact pointers over duplicating shell/script logic.
- Do NOT test things that the `ty` typechecker automatically enforces.
- Any HF_TOKEN usage must only remain temporarily in memory during a request scope, and must never be stored or emitted in a plain format.
- Avoid mocking or `monkeypatch` for testing purposes, preferring to use typechecks, simple logic-focussed unit tests and stubs/simulators. Small integration or e2e tests are preferred over lots of unit tests for tightly coupled scenarios.
- Avoid testing properties and other data transfer scenarios unless transformations or other behaviour is involved.
- Prefer a functional style of programming where possible.
- Feature additions should consider the CLI surface as well as adherence to the Agent Finder specification. Both CLI and HTTP should wrap the same, clean, well factored core logic.
