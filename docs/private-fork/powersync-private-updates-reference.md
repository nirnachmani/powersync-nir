# Reference template: `powersync-private-updates`

Use this as a repository-side reference for a portable maintenance skill on the
private `nirnachmani/powersync-nir` repository, on a
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

For an isolated candidate whose reviewed classification is exactly
`no_overlap`, use `scripts/private-fork/integrate_candidate.py` with the
unchanged candidate manifest, expected candidate path, exact upstream target,
classification, and report path. It may merge and commit only in that registered
candidate after both gates pass. Any other classification requires a report and
compatible-resolution work; no automatic merge is permitted.

The validator is read-only and checks the restored
`custom_components/power_sync` component path, explicit selection/no first-profile
fallback, Generic/EVAC guard seams, reconciler isolation from hardware and mode
calculation, Android contract coverage, and the diagnostics route.

## No-paywall upstream classification

Never wholesale rebase or merge upstream `1404+`. Review every proposed port
as manually reviewed source hunks, including its paths, imports, symbols,
tests, and licence notices. An optimiser hunk is eligible only after that manual
hunk review and only when it can be adapted into the existing no-paywall
optimiser.

Reject `custom_components/power_sync/licensing/**`, licensing imports,
optimiser-access entitlement or permission guards, optimiser entitlement
pairing UI, hosted `api.powersync.cc/ha-license` APIs, subscription UI,
entitlement storage, command/service fences, and licence recovery wrappers.
In particular, do not introduce `optimizer_access`, `subscription_required`,
or `LicensedBatteryController`. A hunk coupled to licensing is **incompatible
until disentangled**, rather than a reason to copy its guard or recovery code.

These rejections are intentionally path/symbol-specific: unrelated provider
authentication tokens and provider pairing flows remain allowed. Preserve
source attribution and licence notices for every adapted hunk and keep the
private fork's noncommercial scope. Before proposing any candidate, run the
current source-only gates:

```bash
python scripts/private-fork/validate_local_architecture.py
scripts/private-fork/run_private_tests.sh
```

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
