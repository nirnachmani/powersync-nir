# Android multi-vehicle feasibility — released app 1.0.7 build 336

## Confirmed client behaviour

Static analysis of the released `com.powersync.mobile` APK shows that its vehicle mapper copies `id`, `vehicle_id`, `vin`, `display_name`, `model`, `battery_level`, `charging_state`, `charge_limit_soc`, `charger_power`, `is_online`, `is_plugged_in`, and `data_updated_at` from each vehicle record. It does not require a Tesla VIN or model.

The Smart Schedule screen accepts a selected `vehicleId`, shows a vehicle selector when more than one record exists, and uses `display_name` as its visible label. The vehicle configuration client writes the selected `vehicle_id` to `/api/power_sync/ev/vehicle_config`. Commands target `/api/power_sync/ev/vehicles/{vehicle_id}/command`.

Therefore two stable, anonymous logical IDs such as `ev_profile_a` and `ev_profile_b` are compatible with the released client. Their persisted `display_name` values are the names shown in the app.

## Deliberate shared-policy boundary

The released app uses single global objects for Solar Surplus policy thresholds, Price-Level charging, and Scheduled Charging. The fork must not claim those settings are per-profile. Basic vehicle configuration and Smart Schedule remain profile-scoped.

## Implementation boundary

This document records app compatibility only. The backend maps the stable IDs `shared_ev_profile_a` and `shared_ev_profile_b` to one selected Generic or Sigenergy EVAC physical charger and enforces one active physical session.

For a configured shared binding, `/api/power_sync/ev/vehicles` replaces the physical `generic_ev` or `sigenergy_charger` row with exactly those two logical records. Each record reports only its own configured logical SoC, including while disconnected. Physical plug state, charging state, and charger power are projected only onto the selected profile; the sibling remains disconnected with no physical power. This projection is state-only and performs no charger refresh or control.
