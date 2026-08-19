# Benchmark criteria and scoring system

This document defines what the `code-agent` benchmark measures, how each change level
is graded, and the statistical protocol for comparing models. Every design choice is
grounded in the code-generation evaluation literature; references are at the end.

## 1. Methodology: execution-based grading

Following the consensus since HumanEval [1], correctness is established by **executing
tests**, never by comparing generated text to a reference. Surface-similarity metrics
such as CodeBLEU [9] are explicitly *not* used for scoring: similar-looking code is
routinely wrong, and correct code is routinely dissimilar [1].

The grading backbone is SWE-bench's two-suite methodology [4]:

- **Fail-to-Pass (F2P)** — hidden, task-specific tests that fail on the pristine app
  and must pass after the change. They are injected into the trial workspace **only
  after the agent has finished**, so they are not present in the project the agent is
  asked to modify or supplied in its context. Each task's F2P
  suite is validated in both directions: it must fail on the unmodified template
  (verified during task authoring) and pass under the task's reference patch
  (`--oracle` mode re-verifies this at any time).
- **Pass-to-Pass (P2P)** — the template app's committed test suite (39 backend tests,
  plus a 4-test Playwright smoke suite for frontend tasks). It guards against
  regressions. If the agent modifies these tests, they are restored from the baseline
  before grading and the trial is flagged `p2p_tampered`. Tasks that intentionally
  break an old contract (L5-02) list the affected tests in `p2p_ignore`, mirroring
  how SWE-bench excludes tests invalidated by the gold patch [4].

Every trial runs in a **fresh copy** of the template app on a native filesystem, with
a fresh seeded database per grader invocation, a fixed browser viewport, disabled CSS
animations, and a seeded, example-capped schemathesis run — grading is deterministic
up to the model's own behavior.

## 2. The seven change levels

The levels form an increasing-scope ladder. Each is anchored to published evidence
that its scope class measures a *distinct* capability, which is the reason for
reporting them separately instead of as one pooled score.

| Level | Scope | Literature anchor |
|---|---|---|
| L1 | Function change | HumanEval established function-level synthesis with test-based grading and pass@k [1]; MBPP replicated it at scale [2]. |
| L2 | Class change | ClassEval showed *all* models drop sharply from function-level to class-level generation, and that function-level scores do **not** predict class-level ability [3] — hence a separate level. |
| L3 | Module change | RepoBench [5] and CrossCodeEval [6] demonstrated that cross-file context retrieval and use is a separate failure mode from single-file generation. L3 tasks require creating/altering a module and wiring it into its consumers. |
| L4 | Service change | Issue-sized changes spanning schema, service, and route layers — the SWE-bench regime [4]: multi-file coordination inside one deployable unit. |
| L5 | API contract change | The graded artifact is the *contract*, not the code: the OpenAPI schema plus behavior under property-based fuzzing (Schemathesis [7]) and explicit conformance tests. Contract changes are graded with negative cases (rejected inputs) as well as positive ones. |
| L6 | Frontend/CSS change | Rendered-output grading follows Design2Code [8]: what matters is the *visual result* (element presence, computed styles, geometry/layout, color), not the source diff. We assert Design2Code's dimensions — block presence, position, color, text — via Playwright computed-style and bounding-box checks in a real browser at fixed viewports. |
| L7 | Architecture change | Repo-scale, cross-cutting changes with structural constraints, per DevBench [10] (which grades design/architecture phases separately) and EvoCodeBench [11] (repo-level, dependency-aware grading). L7-01 additionally grades a *structural invariant* (services must be SQL-free) via static source checks, and L7-02 spans schema→API→UI in one task. |

## 3. Per-trial score

Each trial gets five subscores in `[0, 1]`, combined as a weighted sum:

| Subscore | Weight | Definition |
|---|---|---|
| F2P | **0.50** | Fraction of hidden fail-to-pass units passing. Each pytest test is one unit; each Playwright test is one unit; a seeded Schemathesis run scoped to the task's affected API path counts as one unit (pass/fail). |
| P2P | **0.20** | Fraction of the committed suite still passing (backend ratio; averaged with the frontend smoke ratio for frontend tasks). |
| Localization | **0.10** | Precision of the edit footprint: `|modified ∩ expected| / |modified|`, where `expected_files` is the task's allowlist. Touching fewer files than allowed is not punished; stray edits are. (Auxiliary metric; SWE-bench grades none of this, but edit discipline matters for a *pair-programming* agent.) |
| Minimality | **0.10** | `min(1, ref_LOC / agent_LOC)` — changed lines (git numstat) relative to the reference patch. Penalizes bulk rewrites that happen to pass; capped so beating the reference is not rewarded beyond 1.0. |
| Gate | **0.10** | Sanity gates: backend byte-compiles; for frontend tasks, `vite build` succeeds (split 0.05/0.05). |

**`resolved` (the headline boolean, SWE-bench's "% resolved" [4]):** all F2P units
pass AND the P2P suite passes 100%. Partial credit exists only in the score, never in
`resolved`.

Efficiency — wall-clock seconds, model request count, and token usage (from
code-agent's `oneshot_stats.json`) — is **reported but never scored**, following the
practice of reporting cost alongside, not inside, capability metrics.

## 4. Statistical protocol

- **pass@k.** With `n` trials per task and `c` resolved, we report the unbiased
  estimator `pass@k = 1 − C(n−c, k)/C(n, k)` from Chen et al. [1] (k = 1 by default).
  Never estimate pass@1 by generating once.
- **Clustered uncertainty.** Per Miller [12], the *task* is the sampling unit:
  trial scores are averaged per task first; the reported per-level and overall
  `mean ± SE` is computed over task means (`SE = sd(task means)/√(#tasks)`). This
  prevents trial count from inflating confidence.
- **Comparing two models.** Run the same task set with the same trial count per
  model; compare **paired per-task means** (Miller [12], §"paired differences") —
  the per-task data needed for pairing is preserved in each run's `results.json`.
  With only 2–3 tasks per level, per-level SEs are wide; treat level tables as
  diagnostic, and the overall paired difference as the decision metric.
- **Trials.** Local models at low temperature are still nondeterministic (sampling,
  context truncation, tool-call flakiness). Use `--trials 3` minimum for comparisons;
  `--trials 5` for close calls [12].
- **Determinism of the harness itself.** Fixed schemathesis seed and example cap,
  fixed viewports, frozen animations, relative seeded dates (overdue logic never
  rots), fresh DB per grader, and `--oracle` as a self-test that every task grades
  1.00 under its reference patch.

## 5. Anti-gaming measures

- Hidden F2P tests are absent from the trial workspace and injected post-hoc [4].
- P2P tampering detected via git and reverted before grading; flagged in results.
- The prompt forbids editing `backend/tests/`; the guard enforces it regardless.
- Minimality caps at 1.0 — no reward for artificially small diffs beyond the
  reference footprint.
- `run_command` inside the agent is unrestricted, but trials run in disposable
  scratch copies outside the repository.

## 6. Threats to validity

- **Single app domain.** All tasks live in one FastAPI+React kanban app; scores may
  not transfer to other stacks. (Deliberate trade-off for determinism; the level
  ladder, not the app, is the object of measurement.)
- **Contamination.** The template is original code, but its *patterns* (FastAPI CRUD,
  React lists) are ubiquitous in training data. Treat absolute scores as
  app-relative; cross-model comparisons on identical tasks remain valid.
- **Few tasks per level.** 18 tasks across 7 levels bounds authoring cost; per-level
  SEs are wide. Add tasks before drawing fine-grained per-level conclusions.
- **Wall-clock noise.** Timings are single-machine and affected by background load;
  medians are reported, and timing is never part of the score.
- **Schemathesis stochasticity.** Seeded and example-capped, but server-side state
  interacts with generation; rare flakes are possible (observed ≈1 in 5 runs before
  the harness pinned the grading DB to a native filesystem; none after).
- **Local execution is not a security sandbox.** The agent receives no hidden-test
  paths or contents, but its shell tool is intentionally unrestricted. An adversarial
  model could search the host filesystem. Use the suite to measure normal coding
  behavior, not resistance to deliberate benchmark exfiltration.

## References

1. Chen, M. et al. (2021). *Evaluating Large Language Models Trained on Code.*
   arXiv:2107.03374. — HumanEval; functional correctness; unbiased pass@k.
2. Austin, J. et al. (2021). *Program Synthesis with Large Language Models.*
   arXiv:2108.07732. — MBPP; test-based grading at scale.
3. Du, X. et al. (2023). *ClassEval: A Manually-Crafted Benchmark for Evaluating LLMs
   on Class-level Code Generation.* arXiv:2308.01861.
4. Jimenez, C. E. et al. (2024). *SWE-bench: Can Language Models Resolve Real-World
   GitHub Issues?* ICLR 2024. arXiv:2310.06770. — F2P/P2P methodology; % resolved.
5. Liu, T. et al. (2023). *RepoBench: Benchmarking Repository-Level Code
   Auto-Completion Systems.* arXiv:2306.03091.
6. Ding, Y. et al. (2023). *CrossCodeEval: A Diverse and Multilingual Benchmark for
   Cross-File Code Completion.* arXiv:2310.11248.
7. Hatfield-Dodds, Z. & Dygalo, D. (2021). *Deriving Semantics-Aware Fuzzers from
   Web API Schemas.* arXiv:2112.10328. — Schemathesis; property-based API testing.
8. Si, C. et al. (2024). *Design2Code: Benchmarking Multimodal Code Generation for
   Automated Front-End Engineering.* NAACL 2025. arXiv:2403.03163. — block match,
   text, position, and color as the graded dimensions of rendered frontends.
9. Ren, S. et al. (2020). *CodeBLEU: a Method for Automatic Evaluation of Code
   Synthesis.* arXiv:2009.10297. — cited as the rejected alternative.
10. Li, B. et al. (2024). *DevBench: A Comprehensive Benchmark for Software
    Development.* arXiv:2403.08604.
11. Li, J. et al. (2024). *EvoCodeBench: An Evolving Code Generation Benchmark
    Aligned with Real-World Code Repositories.* arXiv:2404.00599.
12. Miller, E. (2024). *Adding Error Bars to Evals: A Statistical Approach to
    Language Model Evaluations.* arXiv:2411.00640.
