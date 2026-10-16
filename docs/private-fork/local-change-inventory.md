# Local private-architecture inventory

This is a source-maintenance inventory for the private fork. It describes the
current repository only; it is not a deployment or upstream-update procedure.

## Reviewed upstream baseline

- The reviewed upstream baseline is `v2.12.1363` /
  `85f99ea62a174cd9153d5ff2ce71023dda2c9a5c`; the reviewed target is
  `v2.12.1414` / `c76675e1cfb14902dc240d81245482a00a223693`.
- `upstream-1363-1408-port-manifest.md` is the exhaustive, Git-derived
  classification for that range. It is a review record, not permission to
  cherry-pick or merge upstream production code.
- Any future selected port must preserve the inventory below and pass
  `validate_local_architecture.py` plus `run_private_tests.sh`; an unamended
  relevant no-interaction port preserves its upstream regression without adding
  a private test.

## Shared physical loadpoint selection and binding

- `custom_components/power_sync/automations/shared_loadpoint.py` defines the
  two logical IDs (`shared_ev_profile_a`, `shared_ev_profile_b`) and
  `SharedLoadpointBinding`.
- A binding requires a selector entity, distinct profile names, and distinct
  normalized selector states. `resolve_active_shared_profile()` returns `None`
  for absent, unknown, unavailable, or unmapped selection; it does not choose
  profile A or another fallback.
- `canonical_shared_loadpoint_id()` maps the selected logical profile to exactly
  one physical target: `generic_ev` or `sigenergy_charger`. It rejects missing,
  ambiguous, or backend-mismatched configuration.
- `resolve_shared_loadpoint_command()` is the shared gate. It rejects a
  Generic/EVAC command addressed to an unselected logical profile or directly
  to a legacy physical ID, then supplies canonical physical and logical IDs.

## Generic/EVAC physical command guards

The shared gate is enforced at these command boundaries:

- `automations/actions.py`:
  `_action_start_ev_charging`, `_action_stop_ev_charging`, and
  `_action_set_ev_charging_amps` call
  `_resolve_shared_loadpoint_direct_command()` before a Generic/EVAC write;
  `_set_vehicle_amps` and `_set_vehicle_amps_unchecked` use the same helper.
  The helper calls `resolve_shared_loadpoint_command()` and checks the physical
  ownership lease. Dynamic start and dynamic stop independently resolve the
  selected profile before runtime state or charger access.
- `automations/ev_charging_planner.py`: auto-schedule starts and the shared
  dynamic start/stop parameter builders call `resolve_shared_loadpoint_command()`.
- `__init__.py`: manual-app parameter construction calls the same resolver
  before manual lease acquisition or charger write.

The direct guard also has narrow internal stop capabilities for a fenced
profile handoff and an end-of-cycle external-session stop. Both remain bound to
canonical identity and ownership checks; they are not API payload bypasses.

## Reconciliation, override/yield, and adoption lifecycle

- `automations/external_session_reconciler.py` turns fresh Generic power or
  EVAC state reads into `SharedLoadpointObservation` and
  `ReconciliationState`. It does not dispatch hardware commands.
- `reconcile_selected_shared_loadpoint_cycle()` runs before policy evaluation
  from `__init__.py`, records observational cycle context, and has no policy or
  ownership mutation path.
- `resolve_end_of_cycle_external_shared_session()` runs after policy evaluation.
  For `yield`, an external observed session receives external ownership and no
  stop. For `override`, an allowed solar/scheduled/smart-schedule/price-level
  decision can adopt the observed session. Otherwise, a guarded stop occurs
  only through an external ownership lease and fresh idle readback.
- `stop_and_confirm_shared_handoff()` persists pending/failed/indeterminate
  state and finalizes only after fresh inactive proof. A selector handoff uses
  the same stop/readback fence; an idle handoff changes attribution only.

## Ownership, sessions, and adoption

- Physical ownership is keyed by the canonical loadpoint in
  `automations/ev_ownership.py`; logical attribution is kept as
  `active_profile_id`.
- `automations/actions.py` acquires or transfers the shared physical lease only
  after selection and, for transfer, fresh idle evidence. It preserves the
  existing session/controller during metadata-only idle handoff.
- Observed-session adoption helpers in `actions.py` create/update runtime and
  session bookkeeping for Solar Surplus, Scheduled, Smart Schedule, and Price
  Level without starting hardware or timers. Their provenance is
  `observed_external_session`.
- `automations/ev_charging_session.py` keys a shared session by `loadpoint_id`
  when supplied, separating physical session identity from logical vehicle
  attribution.

## Logical-profile SoC recovery

- Shared profiles read only their own configured SoC entity. Anonymous Generic
  primary/fallback SoC remains a legacy-only path and is never used for either
  logical profile.
- On planner storage normalization after restart, a shared binding retains only
  fresh finite 0–100 caches keyed exactly as `shared_ev_profile_a` or
  `shared_ev_profile_b`; ambiguous `_default`/`generic_ev`, malformed, and
  expired values are discarded. A cache is forecast-only, never control proof.
- A selector change clears the non-selected logical forecast; control remains
  fenced by a fresh selected profile plus physical loadpoint guard.

## Reviewed EV safety ports

- Upstream `1198830f` is ported only at the Price-Level home-battery read:
  `battery_energy_coordinator` is preferred over the legacy Tesla coordinator,
  and all coordinator/entity SoC values must be finite percentages. This is a
  physical site-safety input; it does not alter logical-profile identity,
  capacity, target, selector, command, lease, or session behavior.
- From upstream `26874402`, Solar Only now budgets only forecast solar after
  battery and already-reserved EV demand. Spare grid-import headroom cannot be
  labelled as solar. The private selected-profile gate continues to emit one
  physical demand; selector A/B handoff and unknown-selector zero demand are
  already covered by `test_shared_schedule_keeps_only_the_selected_profile_plan`
  and the shared-loadpoint optimizer tests.
- Upstream `5404735c` is rejected as incompatible: its anonymous `_default`
  profile-to-config mapping would reintroduce upstream profile selection and
  policy fields. The private resolver already derives `override`/`yield` only
  from the selected shared profile and fresh cycle evidence; no upstream
  mapping, OCPP, or profile-policy storage is imported.
- Upstream `fbd33c0b`'s delayed Generic pending-marker outcome is redundant
  with the private `2b12e687`/`cab62150` command-boundary fence. The compatible
  reconciliation adaptation additionally rejects a fresh but stale selected
  profile when an external physical lease is now attributed to another logical
  profile. That prevents `yield` from retagging it and `override` from stopping
  it for both Generic and Sigenergy EVAC; fresh evidence remains necessary for
  every resolver stop or cleanup.
- The upstream stale solar-controller rearm hunk is intentionally not ported.
  It infers that no owner means a stale session and clears executor state;
  private reconciliation/physical leases use owner absence as insufficient
  proof and require fresh telemetry before transfer or command. No upstream
  multi-profile identity or licensing code was imported.
- From upstream `f2c0e07f`, the Generic delayed-start/readback safety is adapted
  only at the private command boundary. A fresh delayed acknowledgement is
  rejected, and its cleanup suppressed, if `resolve_shared_loadpoint_command()`
  no longer selects the originating logical profile, the canonical physical
  lease/profile changes, a live handoff is fenced, the pending marker is
  replaced/cancelled, or its automated-cycle token is stale. The private action
  guard tests cover selector change, idle/live handoff, external ownership, and
  newer-cycle invalidation. OCPP price-policy changes and configuration/UI
  timeout model are intentionally excluded from this private safety slice.

## Android and diagnostics contracts

- `tests/test_android_app_contract.py` and
  `tests/contracts/android_app/fixtures/android-1.0.7-336-static-routes.json`
  protect the released Android app's registered HTTP route strings.
- `SharedLoadpointDiagnosticsView` in `__init__.py` registers the authenticated
  route `/api/power_sync/ev/shared_loadpoints/diagnostics`.
- `automations/shared_loadpoint_diagnostics.py` projects persisted physical
  evidence, ownership, last command, and selected decision without inventing
  ownership or converting unknown state into a control action.

## Directly coupled files

- `custom_components/power_sync/automations/shared_loadpoint.py`
- `custom_components/power_sync/automations/actions.py`
- `custom_components/power_sync/automations/ev_charging_planner.py`
- `custom_components/power_sync/automations/external_session_reconciler.py`
- `custom_components/power_sync/automations/ev_ownership.py`
- `custom_components/power_sync/automations/ev_charging_session.py`
- `custom_components/power_sync/automations/shared_loadpoint_diagnostics.py`
- `custom_components/power_sync/__init__.py`
- `tests/test_shared_loadpoint_*.py`, `tests/test_external_session_reconciler.py`,
  `tests/test_android_app_contract.py`, and
  `tests/test_android_app_multi_vehicle_contract.py`

Run `python scripts/private-fork/validate_local_architecture.py` for the
read-only deterministic gate, or `scripts/private-fork/run_private_tests.sh`
for the focused suite.
