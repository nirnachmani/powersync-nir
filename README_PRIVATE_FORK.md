# PowerSync Nir private fork

- **Repository/release slug:** `powersync-nir` (private)
- **Home Assistant integration:** `PowerSync Nir`
- **HA domain/package:** `powersync_nir`
- **Upstream:** `bolagnaise/PowerSync`, currently based on `v2.12.1363`

## Scope

This fork adds two logical EV profiles sharing one selected physical Generic Charger or Sigenergy EVAC loadpoint, and reconciles externally started EV sessions under the agreed policy.

## Android compatibility exception

The released PowerSync Android app hard-codes `/api/power_sync/...`. PowerSync Nir deliberately keeps that HTTP namespace and response contract. Therefore it replaces—not coexists with—the original PowerSync integration in an HA instance.

## Deployment

Deploy only the `main` branch through the documented updater gates. Disable/remove original PowerSync before enabling PowerSync Nir. Roll back by restoring the prior verified release and restarting Home Assistant.

## Non-goals

No Tesla emulation, no additional charger backends, no Android app modification, and no change to PowerSync core optimization calculations.
