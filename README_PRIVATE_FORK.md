# PowerSync private fork

- **Repository/release slug:** `nirnachmani/powersync-nir` (private)
- **Home Assistant integration:** `PowerSync`
- HA domain/package: `power_sync`
- **Upstream:** `bolagnaise/PowerSync`, currently based on `v2.12.1363`

## Scope

This fork adds two logical EV profiles sharing one selected physical Generic Charger or Sigenergy EVAC loadpoint, and reconciles externally started EV sessions under the agreed policy.

## Android compatibility exception

The released PowerSync Android app hard-codes `/api/power_sync/...`. The private fork keeps that HTTP namespace and response contract. Therefore it replaces—not coexists with—the original PowerSync integration in an HA instance. The versioned static route/vehicle-field baseline and controlled-capture procedure are in [`tests/contracts/android_app/`](tests/contracts/android_app/README.md).

## Deployment

Deployment is separately authorized work, not an updater outcome. After explicit authorization, deploy only the private `main` branch through the documented updater gates. Disable/remove the original component before enabling this replacement. Roll back by restoring the prior verified private release and restarting Home Assistant.

## Non-goals

No Tesla emulation, no additional charger backends, no Android app modification, and no change to PowerSync core optimization calculations.
