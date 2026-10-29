<!-- release: v2.12.1517-nir.3 -->

## v2.12.1517-nir.3 — Sigenergy zero-export event-loop correction
- Mark the Sigenergy export-limit state-change listener as a Home Assistant event-loop callback. Previously the synchronous handler ran in an executor, where scheduling the guarded zero-export repair raised a thread-safety error before any Modbus work began. The existing `dc_zero` ownership, retry bounds, register readback and restore semantics are unchanged.
- A regression using Home Assistant's actual state-change event helper reproduced the thread-safety error before the correction and passed afterward; the Sigenergy test suite passed. Publication makes the fix installable through HACS; no Home Assistant installation, restart or inverter write is part of this source release.

<!-- release: v2.12.1517-nir.2 -->

## v2.12.1517-nir.2 — HACS-only PowerSync updates
- Retire PowerSync's notification-only `update.power_sync_update` platform, which checked the original upstream repository but could not install updates. HACS's install-capable update entity for the configured repository is now the only PowerSync update source; on integration setup, remove only the old PowerSync-owned update registry entry, leaving HACS update entities untouched.
- The separate scheduled auto-update feature is unchanged and remains opt-in; this release does not fix its upstream-release fallback or enable unattended installation/restarts. Existing `power_sync` configuration and Android routes are unchanged. Source release only; no Home Assistant installation, restart, or physical device command was performed.

<!-- release: v2.12.1517-nir.1 -->

## v2.12.1517-nir.1 — reviewed upstream through v2.12.1517
- Amber optimiser ignores timestamped price intervals outside its forecast horizon instead of rebasing them onto the current slot (adapted from upstream `9b5a62e6`); the exact no-paywall continuity gate and upstream pricing regressions passed.
- Sigenergy site energy estimates now include configured daily/monthly supply costs and keep local-day/month totals separate at midnight (vendor-neutral part of `ccf8f688`). GloBird ZeroHero bonus and credit logic was excluded.
- Solar Surplus offers an HA switch sharing the app's stored setting; disabling it still uses the private selected-logical-EV stop and physical ownership guard (`97c37ec4`). Existing Android POST behavior and routes remain compatible.
- The maintainer ledger now handles merge-branch upstream commits without replaying prior outcomes. The published Sigenergy export-limit ownership/repair fixes from the previous release were retained when reconciling the private branches.
- Private architecture, optimiser continuity, Android contract, shared-loadpoint and reconciliation gates passed. This is a source release only: no Home Assistant installation/restart, storage edit, or charger command was performed.

<!-- release: v2.12.1492-nir.5 -->

## v2.12.1492-nir.5 — Sigenergy export-limit ownership and fast zero repair
- The existing five-minute Sigenergy DC-curtailment handler remains the sole price/EV decision-maker. It grants zero-export ownership only after a confirmed write. A rise in the polled export-limit entity then triggers a guarded register-40038 read and zero repair only while that ownership is current; the event listener does not calculate tariff freshness or EV headroom independently. Fast attempts are limited to three in a rolling five minutes with at least ten seconds between attempts.
- Manual Force Discharge takes priority for its duration; ending it successfully invokes the existing DC check once. Unrelated Force Charge cleanup preserves a held zero. Standalone native handoff and optional export-cap actions are one-shot; durable Controls cap edits preserve current zero without overriding manual force. In-flight Modbus writes recheck ownership; ambiguous zero-write acknowledgements are reconciled on a later policy check. Disabling DC control fences scheduled writes during restore, while disabling only battery curtailment does not release DC zero. A same-endpoint AC Sigenergy controller cannot independently command this plant register.
- The owner is entry-local. After a restart, an already-zero physical limit without identifiable provenance is not automatically lifted on a profitable-price check; durable cross-restart recovery is not part of this release. Local focused regressions and the private architecture/optimizer gates passed. Source release only: no Home Assistant installation, restart or live inverter command was performed.

<!-- release: v2.12.1492-nir.4 -->

## v2.12.1492-nir.4 — Sigenergy zero-export drift correction
- When SAPN/Grid Service raises the Sigenergy plant export-limit register during active PowerSync DC curtailment, a change in the Sigen HA number now triggers one guarded native-register check and zero-export reassertion rather than waiting for the next periodic check. A successful write requires a zero register readback; retries are bounded and retain the original normal-export restore target.
- The fast path requires a current price in its applicable slot, the existing uneconomic-export decision, enabled native DC control, and no solar-surplus EV headroom, force/export ownership, or conflicting monitoring mode. It does nothing for profitable or stale prices, normal export operation, an absent number entity, or a legitimate release; the five-minute check remains the fallback. It does not suppress DNSP commands or guarantee uninterrupted zero if the inverter gives them priority.
- Source release only: no Home Assistant installation/restart or physical inverter command was performed during development.

## v2.12.1492-nir.3 — shared EV Scheduled and Price-Level commands
- Scheduled Charging and its external-session stop now resolve the currently selected logical EV before issuing Generic Charger or Sigenergy EVAC commands. The coordinator's direct start/stop paths do the same. Unavailable or unmapped selection issues no shared command; retired physical IDs remain rejected at the command boundary.
- Price-Level Charging now tracks A/B by logical identity, uses only the selected EV's SoC for recovery/opportunity decisions, and routes starts/stops through that profile. A selector change mid-decision cannot authorise the other EV. External-session adoption seeds the same logical state, avoiding a duplicate start; a sibling's decision cannot clear the old home-battery hold until a fresh idle observation confirms that the origin EV no longer owns the charger.
- Scheduled Charging retries the new selected EV after an A/B handoff within the same charging window instead of treating A's global charging flag as proof that B has started. Smart Schedule's existing physical-command path was verified for both A/B and Generic/EVAC. The nonshared/Tesla paths retain their prior selection. Focused charging-path and private architecture gates passed. Source publication only: no Home Assistant installation, restart, setting change, or charger action.

## v2.12.1492-nir.2 — Solar Surplus logical-EV selection
- With a shared Generic Charger or Sigenergy EVAC, Solar Surplus now considers only the currently selected logical EV for that physical charger. A retained, enabled legacy charger record can no longer win the first priority slot and have its start rejected by the shared safety guard. An unknown selector starts neither logical EV; saved legacy records are not deleted or changed.
- Focused A/B and Generic/EVAC selection regressions plus private compatibility gates passed. This release is source publication only; it does not install or restart Home Assistant or operate the charger.

## v2.12.1492-nir.1 — reviewed upstream through v2.12.1492
- Optimizer logs distinguish acceptance of a requested charge command from measured charging (reviewed part of upstream `9595199b`); the Powerwall-only SOC logic was excluded.
- After selecting Amber, a stale GloBird pricing device can be removed without permitting removal of an active provider or changing legacy pack cleanup (adapted from `731f0403`).
- The dashboard displays today's recorded import/export prices alongside the tariff model, with historical spikes and blank future hours (from `8d2e37f4`).
- Private architecture, optimizer continuity, Android app-contract, shared-loadpoint and reconciliation gates passed. This release is source publication only; it does not install or restart Home Assistant or operate the charger.

## Previously released: v2.12.1478-nir.5

## PowerSync Nir fork
- Both logical EVs now display the physical Generic Charger entities configured in integration options. Physical switch/current/status/power settings (or selected Sigenergy EVAC transport) remain owned by the integration, not separate per-EV app records; conflicting app edits are rejected and stale vehicle overrides cannot drive shared commands.
- Logical EV A and B usable capacities can be edited or explicitly cleared in integration options. They use the same per-EV vehicle records as the app/dashboard; an omitted field preserves its existing capacity. The old charger-wide Generic capacity no longer applies to bound logical EVs.
- Charging-schedule preview and Price-Level projection use each logical EV's own capacity instead of treating a Generic-backed logical EV as an anonymous charger.
- The fork's maintainer inventory and repository instructions now identify this split as an intentional upstream divergence requiring hunk-by-hunk review.
- Local private regression gates and focused capacity/app/preview tests passed. This release does not install or restart Home Assistant and does not operate the charger; update through HACS in an idle, backed-up window.
