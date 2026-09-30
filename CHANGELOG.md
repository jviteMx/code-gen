# Changelog

## 0.3.0 — 2026-09-30

### Added

- Read-only assistant mode for questions and public-web research at CLI startup.
- Public `web_search`, `web_fetch`, and `github_read` tools with bounded results and source URLs.
- Optional isolated Chromium browser tools to inspect JavaScript pages and use search forms.
- Session-wide web approval with `/web on`, `/web off`, and `/web ask` controls.
- Visible progress while web and browser tools run.

### Security

- Public destination checks, redirect validation, and limits on response size and browser requests.
- Browser sessions use temporary profiles; downloads and form POST navigation are blocked.

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
