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
- A schema-versioned ledger at the explicit state path. Initialize it with
  `python scripts/private-fork/maintainer_ledger.py --repo <repo> init --state
  <state> --baseline <full-sha> --migration-boundary v2.12.1418
  --migration-reference <honest-pre-ledger-reference>`. For the server's legacy
  state, use only `migrate --legacy-state <old-state>` with an exactly matching
  baseline; it refuses to overwrite either state and records no invented
  per-commit v1418 history.

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
authentication tokens and provider pairing flows remain allowed. ChatGPT
plan-explanation sign-in is also distinct from optimiser licensing: it may be
considered only as a separately approved AI feature after a dedicated security
and API-contract review, and must never import optimiser entitlement,
permission, command-fencing, or hosted optimiser-access code. Preserve source attribution and this private fork's noncommercial scope for every adapted hunk.
Before proposing any candidate, run the current source-only gates:

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

## Relevance-first triage and proportionate testing

Before a candidate or test, answer: does this fix a problem the configured
Amber/Sigenergy/shared-home/private-EV setup can encounter; add a materially
useful capability; or supply shared infrastructure for likely relevant future
work? Reject a battery-vendor change unless it targets Sigenergy. Reject a
provider change unless it targets Amber. Keep generic optimiser/site changes
only when they can affect Sigenergy, Amber, solar/site flows, or private shared
EV behavior; record `irrelevant to configured setup` plus the unavailable
vendor/unused feature for the rest.

The updater classifies and preserves private-fork compatibility; it is not an
upstream quality-assurance role. Rely on upstream developer tests for a
compatible unamended update. Do not hunt for theoretical upstream defects or
re-prove every upstream behavior; later upstream releases normally carry those
fixes. If a relevant hunk has no plausible interaction with private
two-EV/external-session functionality, port it minimally without adding private
tests. Add a private interaction regression only when the fork must amend an
actual overlap. If compatibility is uncertain or a choice trades private
behavior against another required outcome, stop and ask the user for a
preference.

For relevant no-interaction and unamended-overlap hunks, classify and port, then
run the architecture validator and private compatibility gate once per update
cycle. For an amended overlap, add only the smallest private interaction test
needed for that amendment. Run the broader suite only for final release
validation or a clear regression discovered during an amendment. Do not create
speculative tests for unavailable vendors, theoretical scenarios, or ordinary
upstream behavior.

Do not reject an important upstream EV/external-session fix merely because it
uses a different upstream identity model. Adapt it through the private logical
profile selector, canonical physical loadpoint, lease, session, and reconciler
seams when that preserves the intended bug-fix outcome. Escalate only when
those private requirements conflict or the correct outcome is genuinely
uncertain.

Process upstream commits strictly oldest to newest. Every commit must reach a
terminal outcome (`ported`, `amended`, `rejected`, or `admin/no-port`) before
the processing checkpoint advances. Obtain the exact next SHA with
`maintainer_ledger.py next`, then record only that SHA using
`maintainer_ledger.py record --upstream-version <version>`; the atomic ledger
write stores upstream version, full SHA and subject, outcome, reason, applicable
private commit SHA(s) that resolve in the private checkout, and timestamp with
the new checkpoint. It rejects `deferred`, unknown or out-of-order SHAs,
nonexistent private commits, and missing required reasons/private commits. If a commit needs user input, do not
record it: stop at that commit and leave the checkpoint before it; resolve it
before considering newer updates. Use `maintainer_ledger.py summary` for the
cron's durable JSON end-of-cycle payload. This naturally ensures prerequisites
are handled before dependent fixes.

## End-of-cycle report

At the end of every update cycle, report every considered update in a concise
table: update, `ported`/`amended`/`rejected`/`admin/no-port`, and a one-sentence
reason. An `irrelevant to configured setup` entry must name the unavailable
vendor or unused feature; an `admin/no-port` entry must name the release,
version, or documentation bookkeeping. An uncertain compatibility choice must state the
alternatives and request the user's preference.

Send the completed report through the configured Resend MCP, using the same
sender/recipient defaults as the server's `ha-update` workflow. Keep the local
Markdown/JSON report as the durable record. If the email call fails, record the
failure in the cron output without exposing credentials.

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
