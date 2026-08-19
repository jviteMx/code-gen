# Changelog

## 0.2.0 — 2026-08-18

### Added

- Local model benchmark harness with 18 tasks across seven change levels.
- Headless `--oneshot` execution and `/benchmark` (`/bench`) session command.
- Deterministic F2P/P2P, Playwright, Schemathesis, oracle, and report workflows.
- Model context detection, controlled load/unload behavior, and benchmark metadata.

### Fixed

- Empty local-model responses are nudged instead of treated as completion.
- Benchmark subprocesses and reports use explicit UTF-8 on Windows.
- Oracle validation exits nonzero when any reference task fails.
- Normal pytest runs exclude benchmark fixtures that require harness injection.
- Windows ripgrep JSON parsing and fallback behavior are path-safe.
