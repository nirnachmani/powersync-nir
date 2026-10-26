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
