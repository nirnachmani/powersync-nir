---
name: powersync-private-updates
description: "Use when maintaining the PowerSync Nir private fork against upstream."
version: 1.0.0
---

# PowerSync Nir private-fork upstream maintenance

## When to use

Use this skill in the dedicated `powersync-maintainer` Hermes profile on the
maintainer server to review, integrate, and validate upstream PowerSync changes
for the private `powersync-nir` fork.

## Scope and safety boundary

- Work only in the configured private-fork checkout and a disposable candidate
  worktree; never edit a deployed checkout directly.
- Confirm the target Git remote/repository is private before any push. Never
  publish to the public `upstream` remote.
- Preserve the architecture in `docs/private-fork/local-change-inventory.md`.
- Do not widen scope to Tesla, EVDC, OCPP, Zaptec, or other excluded backends.
- Do not weaken, delete, bypass, or misreport a failing validator or test.
- Never expose secrets, tokens, device addresses, or captures in commits or
  reports.
- Deployment is a separate gated phase. Never deploy, reload/restart Home
  Assistant, or control a physical charger without separate authorisation and
  the server's approved deployment procedure.

## Required inputs

Before work, establish:

1. The private-fork checkout, branch, and private deploy remote.
2. A clean worktree or explicitly recorded local changes.
3. The last reviewed upstream SHA/tag and target upstream range.
4. The current local-change inventory.
5. A working Python environment for the fork.

## Required gates

Run from the private-fork root before and after every candidate integration:

```bash
python scripts/private-fork/validate_local_architecture.py
scripts/private-fork/run_private_tests.sh
```

The focused runner includes Android-contract and private shared-loadpoint/
reconciliation tests. Use `--broader` only when required; report every failure
and do not suppress baseline failures.

## No-paywall upstream classification

- **Never wholesale rebase or merge upstream 1404+**. Treat each upstream
  change as a source-level classification and review its changed paths,
  imports, symbols, and tests before proposing a candidate.
- Reject every `custom_components/power_sync/licensing/**` file and any
  licensing import, optimiser-access entitlement/permission guard, entitlement
  pairing UI, hosted `api.powersync.cc/ha-license` dependency, subscription UI,
  entitlement storage, command/service fence, or licence-recovery wrapper.
- Do not port `subscription_required`, `LicensedBatteryController`,
  `optimizer_access`, or an optimiser entitlement pairing flow. These are
  concrete paywall symbols, not ordinary provider authentication mechanics.
- A hunk coupled to licensing is **incompatible until disentangled**. Do not
  resolve it by importing a guard, a recovery path, or an access-status UI.
- Port an eligible optimiser fix only as manually reviewed, minimal hunks into
  the existing no-paywall optimiser; never use a wholesale 1404+ integration
  as a substitute for hunk review.
- Preserve upstream source attribution and licence notices for every adapted
  hunk, and retain this private fork's noncommercial scope.
- Before a candidate can be proposed, run the current source-only gates:
  `python scripts/private-fork/validate_local_architecture.py` and
  `scripts/private-fork/run_private_tests.sh`.

## Workflow

1. Record `git status --short`, private starting SHA, last reviewed upstream
   SHA/tag, and target upstream SHA/tag.
2. Read `docs/private-fork/local-change-inventory.md` and
   `docs/private-fork/powersync-private-updates-reference.md`.
3. Fetch and compare the explicit upstream range deterministically using the
   repository tools; identify changed paths, symbols, tests, and release notes.
4. Apply the no-paywall classification above, then classify the delta as one of:
   - **No overlap:** no private modules/direct tests touched.
   - **Mechanical overlap:** same file, separable hunks.
   - **Compatible semantic overlap:** private invariants can be preserved with
     test-backed adaptation.
   - **Redundant:** the private fork already covers the upstream behaviour.
   - **Incompatible:** private behavioural invariants cannot be preserved
     safely.
5. Use `scripts/private-fork/candidate_worktree.py prepare` with explicit
   private repo, candidate root, source ref, upstream target ref, and manifest.
   It requires a clean private source and a policy-approved private GitHub
   `origin`, creates only a detached disposable worktree, and records that no
   integration occurred. Use its separate `cleanup` command only with the exact
   registered path beneath the candidate root.
6. Only for an exact `no_overlap` classifier result, use
   `scripts/private-fork/integrate_candidate.py` with the unchanged manifest,
   exact candidate path, target SHA, classification, and report path. It merges
   locally only in the registered candidate, runs every required gate, and
   commits only there after they pass. It must never publish, deploy, or control
   infrastructure.
7. For every overlap classification, stop with a report requiring
   compatible-resolution work; do not attempt an automatic merge.
8. For redundant changes, record the upstream SHA and equivalence rationale;
   retain the private implementation.
9. For incompatible changes or failed gates, retain the candidate untouched and
   report the precise conflict/failure. Do not push it as a release or deploy.

## Private invariants

Keep these true:

- Shared profile selection fails closed; there is no first-profile fallback.
- Generic and Sigenergy EVAC physical start/stop/current commands pass the
  shared guard and physical ownership path.
- Reconciliation observes/categorises state; it does not replace charging-mode
  calculations.
- Existing Solar Surplus, Smart Schedule, Scheduled Charging, and Price-Level
  decisions remain authoritative.
- Shared physical sessions, leases, and runtime keys preserve logical-profile
  attribution.
- Android existing routes and payload fields remain compatible; shared
  diagnostics is an optional separate endpoint.

## Report

Use this exact structure:

```text
Scope: <private revision and upstream range>
Start state: <private SHA>; working tree <clean/recorded changes>
Classification: <no overlap/mechanical/compatible/redundant/incompatible>
Changed: <files and one-line purpose>
Gates:
- validate_local_architecture.py: <pass/fail>
- run_private_tests.sh: <pass/fail>
- broader suite, if requested: <pass/fail; all failures counted>
Commit/candidate: <SHA or retained worktree>
Deployment: <not attempted / separately authorised result>
Blockers / follow-up: <none or factual items>
```

## Deployment handoff

A maintenance integration is not deployment proof. Deployment needs separate
authorisation, a fresh backup, a manual stop capability, staging prerequisites,
and post-deployment verification. If any are absent, report deployment as
deferred and continue only with safe source-maintenance work.
