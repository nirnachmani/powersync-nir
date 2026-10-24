<!-- release: v2.12.1478-nir.4 -->

## PowerSync Nir fork
- An idle Generic Charger with its switch off no longer appears as externally commanded just because its retained current limit reads 32 A. The physical 32 A limit remains visible as a target; no charging command or mode is changed.
- Logical EVs now read and save their own usable battery capacity, independently of the old charger-wide capacity fallback. Old charger-as-EV settings remain stored for rollback; no capacity is copied to A or B. Until a profile's own capacity is configured, its effective capacity is a **60 kWh default estimate**, not the other EV's 37.1 kWh.
- Focused tests and private regression gates passed. This release does not change live Home Assistant settings or operate the charger; update through HACS in an idle/rollback window.
