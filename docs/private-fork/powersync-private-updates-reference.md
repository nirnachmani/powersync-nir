# Reference template: `powersync-private-updates`

Use this as a repository-side reference for a portable maintenance skill on a
separate server. It defines local source-maintenance gates only; it does not
deploy, install an update agent, or change a public upstream repository.

## Required inputs and state

- Repository checkout path and the exact target revision/branch.
- Clean or explicitly recorded working-tree state before work begins.
- Current upstream reference and the intended upstream comparison range.
- This fork's current `docs/private-fork/local-change-inventory.md`.
- A Python environment able to run the repository's pytest suite.
- The known broader-suite baseline, if one exists; do not infer failures from
  the focused private suite.

## Deterministic gates

1. Record `git status --short` and the starting commit.
2. Run `python scripts/private-fork/validate_local_architecture.py`.
3. Run `scripts/private-fork/run_private_tests.sh`.
4. If an upstream merge/rebase is in scope, repeat gates 2 and 3 after resolving
   conflicts and before creating a commit.
5. Record the exact commands, commit(s), and pass/fail output in the report.

The validator is read-only and checks explicit selection/no first-profile
fallback, Generic/EVAC guard seams, reconciler isolation from hardware and mode
calculation, Android contract coverage, and the diagnostics route.

## Allowed operations

- Inspect local git history, diffs, source, tests, and tracked documentation.
- Fetch or compare the explicitly supplied upstream reference.
- Create focused tests and minimal private-fork maintenance changes.
- Run the deterministic validator and focused tests.
- Create a local git commit after all required gates pass.

## Forbidden actions

- No deployment, Home Assistant reload/restart, remote service control, or
  production configuration changes.
- No update-agent implementation or scheduler setup.
- No edits to public/upstream repositories or upstream history rewriting.
- No bypassing, deleting, weakening, or marking a failing required gate as
  passing.
- No broad-suite failure suppression. The broader suite is opt-in and reports
  all failures; the current Tesla/BLE baseline note is informational only.
- No secrets, tokens, device addresses, or user captures in commits or reports.

## Report format

```text
Scope: <target revision and upstream range, or local-only maintenance>
Start state: <commit>; working tree <clean/recorded changes>
Changed: <files and one-line purpose>
Gates:
- validate_local_architecture.py: <pass/fail>
- run_private_tests.sh: <pass/fail>
- broader suite, if requested: <pass/fail; all failures counted>
Commit: <hash or not created>
Blockers / follow-up: <none or factual items>
```
