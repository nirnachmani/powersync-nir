<!-- release: v2.12.1478-nir.1 -->

## PowerSync Nir fork
- Bring the fork through upstream v2.12.1478 in strict chronological review. Port relevant Amber billing/current prices, Sigenergy export and manual-discharge controls, EV battery-hold release, optimiser reserve/export/normal-mode fixes, dashboard provenance, and AI explanation improvements; adapt the custom-duration no-op to avoid stale reload flags.
- Reserve shared managed-EV import headroom and level total site import across Sigenergy spread-charge windows, without Tesla-only dispatch controls. Reject native Tesla Powerwall-only controls and skip release bookkeeping. Preserve shared logical-EV safeguards, Android API compatibility, upstream attribution and the no-paywall optimiser boundary.
- Add this repository to HACS as a **custom integration repository** for installation and updates; it is not in the default HACS catalogue. This release did not deploy to Home Assistant.
