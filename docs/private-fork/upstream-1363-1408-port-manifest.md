# Upstream v2.12.1363–v2.12.1408 port manifest

## Scope and reproducibility

- **Baseline:** `v2.12.1363` / `85f99ea62a174cd9153d5ff2ce71023dda2c9a5c`
- **Target:** `v2.12.1408` / `e3e107409b18add2213a9de617cc23591e73c873`
- **Range command:** `python scripts/private-fork/collect_upstream_delta.py 85f99ea62a174cd9153d5ff2ce71023dda2c9a5c e3e107409b18add2213a9de617cc23591e73c873 --repo .`
- **Commit evidence command:** `git log --reverse --format="%H%x09%s" 85f99ea62a174cd9153d5ff2ce71023dda2c9a5c..e3e107409b18add2213a9de617cc23591e73c873`
- **Per-commit file evidence command:** `git diff-tree --no-commit-id --name-only -r -m <commit>`
- **Contract:** `tests/test_private_fork_upstream_delta.py` derives the range from Git and requires exactly one complete record for every commit. This document intentionally classifies review work; it authorizes no production-code port.

## Non-negotiable private gates

- Preserve `resolve_shared_loadpoint_command()` and no first-profile fallback.
- Preserve one physical ownership lease and logical-profile attribution for the two private profiles.
- Keep reconciliation observational; the established Solar Surplus, Smart Schedule, Scheduled Charging, and Price Level calculations remain authoritative.
- Reject `custom_components/power_sync/licensing/`, hosted optimiser entitlement/permission flows, and `optimization/chatgpt_auth.py`.
- Before any future selected port: `python scripts/private-fork/validate_local_architecture.py` and `scripts/private-fork/run_private_tests.sh`.

## Classification legend

- **low-risk compatible port:** candidate only; never an automatic cherry-pick.
- **manual semantic review:** source outcome may be useful but must be adapted behind private invariants and a RED/GREEN regression.
- **redundant/incompatible private shared-EV:** reject upstream shared-profile architecture; retain private model.
- **paywall/subscription reject:** reject all licensing, entitlement, hosted access, and ChatGPT subscription work.
- **excluded backend reject:** reject out-of-scope backend/protocol work.
- **admin/no-port:** retain no release/version/merge metadata.

## Exhaustive commit records

The key-file lists below are taken from the per-commit Git command above; an ellipsis means additional changed files exist in that commit, not inferred files.

### `9f7e0fb4baf347fe842ba3366f2c22afe591d9ba` — fix(goodwe): use whole-site solar sensor when an AC-coupled array is present
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/coordinator.py`, `custom_components/power_sync/inverters/entity_override.py`, `tests/test_goodwe_site_solar_override.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `b6de0913119859d16b6c185c718f0bb483ecb23f` — docs(release): clear RELEASE_NOTES.md after v2.12.1363
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `ae9f861b7c3f14438b737f95fc4cb6113fbfe326` — fix(goodwe): serialize automatic curtailment transitions
- **Classification:** low-risk compatible port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/__init__.py`, `custom_components/power_sync/manifest.json`, `docs/wiki/GoodWe.md` (+1 more)
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `4f2fa0c9a832f6fb93812441e2fe80c6ac1f9e64` — docs(release): clear RELEASE_NOTES.md after v2.12.1364
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `ce9f73bf4cec8312fd5784e39960f26fe4a9b3d2` — fix(optimizer): allow profitable solar refill before premium export
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/battery_optimizer.py`, `docs/wiki/Smart-Optimization.md`, `tests/test_battery_optimizer_export_guard.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `bc7ce91cc4d42660baa549b405dd0cf6c6b56758` — chore(manifest): bump version to 2.12.1365
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `502414c1ddc0ca26552386921bc08121706a760f` — docs(release): clear RELEASE_NOTES.md after v2.12.1365
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `1a92f31a95b91e328ffb7a05f10d1d1384df156f` — fix: preserve Tesla optimizer force commitment
- **Classification:** excluded backend reject
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/__init__.py`, `custom_components/power_sync/manifest.json`, `custom_components/power_sync/optimization/coordinator.py` (+1 more)
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `0f3c87be6433434e1fe13751ac75d178d433919e` — docs(release): clear RELEASE_NOTES.md after v2.12.1366
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `1198830f1e50cc8631aefc2613d713043d68715a` — fix(ev): enforce native home battery minimum
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/automations/ev_charging_planner.py`, `tests/test_ev_price_level_ownership.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `7bd558deaefe44e41118f0a0e16714055f14fac4` — chore(manifest): bump version to 2.12.1366
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `ebfd0ee0a494cd16ee0b7cf743cc3b457be47d3a` — chore(manifest): bump version to 2.12.1367
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `bbc67c037069f72c8a773a7b008f2737c52fdae1` — docs(release): clear RELEASE_NOTES.md after v2.12.1367
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `59c74b6cfd1c6e4b28b97b702b9c45143e01f185` — fix(globird): recover portal sensors after cold start failure
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/globird_coordinator.py`, `custom_components/power_sync/globird_sensors.py`, `custom_components/power_sync/sensor.py` (+1 more)
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `06bb8b17e05ede702a5537e294cc38242881e3cc` — chore(manifest): bump version to 2.12.1368
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `67adc400e5fb50a6fd8e8eb5c44741220ce585e7` — docs(release): clear RELEASE_NOTES.md after v2.12.1368
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `3f90add62c73db8037317d62ae4ae1cc213a9e0c` — Persist battery provenance inventory
- **Classification:** manual semantic review
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`, `custom_components/power_sync/optimization/coordinator.py`, `tests/test_battery_export_allowed_slots.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `706cff3d13fae849278e0acfc16774909becd054` — docs(release): clear RELEASE_NOTES.md after v2.12.1369
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `619382f20d566e79f6ae9140bcfdfbf98ce20331` — fix(goodwe): expose whole-site solar sensor in the UI; keep load correct when GoodWe reports negative load
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/coordinator.py`, `custom_components/power_sync/inverters/entity_override.py`, `custom_components/power_sync/strings.json` (+3 more)
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `c292346cdbc16598066e6072b4bd80aad8e1f0be` — fix: use resolved device IDs for child links
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/binary_sensor.py`, `custom_components/power_sync/const.py`, `custom_components/power_sync/globird_sensors.py`, `custom_components/power_sync/sensor.py` (+1 more)
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `0970a6f27ec6042927683c12cac4ffb9677ff458` — chore(manifest): bump version to 2.12.1370
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `8994d5b7d8f2e07588323c97aff0b9e13bae83ca` — docs(release): clear RELEASE_NOTES.md after v2.12.1370
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `b20bffb20b68633113eb8717657bddce9cb8f116` — fix: allow Cost Neutral grid top-up for reachable deadlines
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/battery_optimizer.py`, `tests/test_cost_neutral_optimizer.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `7fa4583fc47e7af2b047cc226cc0c52e56ed5341` — chore(manifest): bump version to 2.12.1371
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `e19e54b613740877b6eecfac0109de7e84165c00` — docs(release): clear RELEASE_NOTES.md after v2.12.1371
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `26874402f5f5a632fad0c8946c6feb2014296cc0` — fix: keep solar-only plans on solar budget
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/automations/ev_charging_planner.py`, `tests/test_ev_price_level_ownership.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `0ed4612cc25ea531f7386557aab10cf4223f942f` — chore(manifest): bump version to 2.12.1372
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `5a9e65354e0092984b3bf6cd25c65990f647f7e9` — docs(release): clear RELEASE_NOTES.md after v2.12.1372
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `6c2a95c4e50ec1d0eaabe01dbd16a8d03a4e6c7f` — fix: keep multi-resource Solcast forecasts complete
- **Classification:** low-risk compatible port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/coordinator.py`, `custom_components/power_sync/manifest.json`, `tests/test_solcast_multisite.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `18b8eb1f50dbb4b305411fc39fb7502b1f413c57` — docs(release): clear RELEASE_NOTES.md after v2.12.1373
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `7b3009ed5ab7c4b1078ff6f06827c3214cde91ab` — fix(goodwe): let the whole-site solar sensor be cleared; add setup-form strings
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/strings.json`, `custom_components/power_sync/translations/en.json`, `tests/test_goodwe_site_solar_config_flow.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `8e7a6a3fa64361a52221c68a9e002c95a57b7895` — fix(solaredge): forward curtailment write determinacy
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/coordinator.py`, `tests/test_solaredge_runtime.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `14905e185653063c90dfb15a4465586c0c3e8b9d` — chore(manifest): bump version to 2.12.1374
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `fc2ed57f4d4fb4e08cf8b6d736807dc6b13d1fa7` — docs(release): clear RELEASE_NOTES.md after v2.12.1374
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `a096707d202b2bfed4fb29a658953583474aef91` — fix(fronius): keep status pending until physical convergence
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/sensor.py`, `tests/test_ac_inverter_mode_status.py`, `tests/test_inverter_status_sensor.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `217f0edbff4cc4c1e1216e69f70389f912d1e052` — chore(manifest): bump version to 2.12.1375
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `20f2a735e44fb8473a22e2105f88d92db25cc6d5` — docs(release): clear RELEASE_NOTES.md after v2.12.1375
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `2d61cb2b30f1911d3a9dc3d74efd587b48d0613d` — fix(amber): enforce spike protection without lowering import prices
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/optimization/coordinator.py`, `custom_components/power_sync/sigenergy_api.py`, `custom_components/power_sync/strings.json` (+4 more)
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `50793e58a5c0edda95f791177efed553d13dffc1` — chore(manifest): bump version to 2.12.1376
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `6263269edf0ea1d71833e505036f2ed1f81f3845` — docs(release): clear RELEASE_NOTES.md after v2.12.1376
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `2d136000c248ced57ec34baf41da39edfe1b058c` — fix: support legacy Home Assistant device links
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/const.py`, `custom_components/power_sync/registry_compat.py`, `tests/test_device_registry_compat.py`, `tests/test_provider_pricing_integration.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `9ad67f7ec817480e67905dc587dddb9d333462af` — chore(manifest): bump version to 2.12.1377
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `5c506744e2f723c7226886438c19d849fa343f10` — docs(release): clear RELEASE_NOTES.md after v2.12.1377
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `b486916b2195b6b03e795d84dd0c3f79aaae28ea` — fix(goodwe): make the profile setup form the single setup source for the whole-site sensor
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/strings.json`, `custom_components/power_sync/translations/en.json`, `tests/test_goodwe_site_solar_config_flow.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `bee1e7a60275459601845afa3a10129402185d74` — fix(tesla): fence stale restore retries
- **Classification:** excluded backend reject
- **Key files:** `custom_components/power_sync/__init__.py`, `tests/test_force_mode_controls.py`
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `bdfb2174af3d07865845452ca28e741487bbd0c2` — chore(manifest): bump version to 2.12.1378
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `9af58ee29f9ea7c3a04a66c760997810645881df` — docs(release): clear RELEASE_NOTES.md after v2.12.1378
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `97c4f4b8162f29abec273117eaf29fa1d2ea8940` — fix: preserve persisted battery spec provenance
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/optimization/coordinator.py`, `tests/test_battery_spec_provenance.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `9375c5698d20488555056b3e3c7ae30bbe5add3a` — chore(manifest): bump version to 2.12.1379
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `7b082e2c2b10004ac9fc165cee1984d6a6a804e9` — docs(release): clear RELEASE_NOTES.md after v2.12.1379
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `698eb2be3a457348a96ffa106fc9c8eeaba7f8a0` — fix(aemo): respect disabled spike detection and restore active events
- **Classification:** excluded backend reject
- **Key files:** `custom_components/power_sync/__init__.py`, `tests/test_force_mode_controls.py`, `tests/test_generic_force_event_rearm.py`, `tests/test_money_event_manager_optimizer_gate.py` (+2 more)
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `11e2a23e87c3551c173b3c3d23c3366a91e43e65` — chore(manifest): bump version to 2.12.1380
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `fbcaf6a6c438e8f89568a7783de17e395d89c012` — docs(release): clear RELEASE_NOTES.md after v2.12.1380
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `8d849a5fa8cc98087edc482d57a4a75f18180efa` — fix(optimizer): gate Sungrow solar-export hold writes
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/coordinator.py`, `custom_components/power_sync/inverters/sungrow_sh.py`, `custom_components/power_sync/monitoring.py`, `custom_components/power_sync/optimization/coordinator.py` (+5 more)
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `87677764419b0a92dcae6aebc35251e821401813` — chore(manifest): bump version to 2.12.1381
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `9255f3bdce1dcf1272a702d2ffb46a07ee03a771` — docs(release): clear RELEASE_NOTES.md after v2.12.1381
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `963041fa9f05b2b26bdf3f5ff037b6f5899751a9` — fix(optimizer): preserve signed export prices for boost gates
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/coordinator.py`, `tests/test_battery_export_allowed_slots.py`, `tests/test_optimization_price_source.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `234120ea34a0ad42c6d90b3760b62b015759aadf` — chore(manifest): bump version to 2.12.1382
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `2ff7c136557ecfb088e56106021f781fc8b5d16d` — docs(release): clear RELEASE_NOTES.md after v2.12.1382
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `b0c6e7915a2f63d5b00ca47dc34204610dd40c36` — feat(optimizer): add opt-in Amber forecast confidence
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/const.py`, `custom_components/power_sync/optimization/coordinator.py` (+15 more)
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `3f922e821db66cb575ea6e34dcb0e32d76a31a9d` — chore(manifest): bump version to 2.12.1383
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `ff89a8a760edc986e15922cb4fd57100f6f2a6db` — docs(release): clear RELEASE_NOTES.md after v2.12.1383
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `57dd1af8cffe51ee28743666a804ca085ddce307` — fix(calendar): accept numeric statistic timestamps
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/__init__.py`, `tests/test_calendar_history_energy_summary.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `a165f24917f470e4266b2e39f5d667f45576894b` — release: v2.12.1384
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `f3745e0441b4cce742fe1ac4fc814fff8bb94795` — docs(release): clear RELEASE_NOTES.md after v2.12.1384
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `a5e03357bb1c4b87b0d0e3991effa3aceb17a81a` — fix(sigenergy): preserve PV during manual force discharge
- **Classification:** manual semantic review
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/inverters/sigenergy.py`, `custom_components/power_sync/manifest.json`, `tests/test_sigenergy_controller.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `841b8d296d884b5e35d1305963f9b18e6ddf06f2` — docs(release): clear RELEASE_NOTES.md after v2.12.1385
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `2cc05e2b4f24d91197c140279c13fc324eee88eb` — fix(optimizer): keep projected modes aligned with battery flows
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/battery_optimizer.py`, `tests/test_cost_neutral_optimizer.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `0376f88bb123cc67758166b4a40eaf1b0be48eee` — chore(manifest): bump version to 2.12.1386
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `693d9175b2d22b4eae8f4fbf337aec08e6ad214a` — docs(release): clear RELEASE_NOTES.md after v2.12.1386
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `db8683c6cf4e92e1dcf9686b58d88072a8b1c8e5` — fix(powerwall_local): read tesla-protocol 4.0.0 system info shape
- **Classification:** excluded backend reject
- **Key files:** `custom_components/power_sync/manifest.json`, `custom_components/power_sync/powerwall_local/transport.py`, `tests/test_powerwall_v1r_teslemetry_parity.py`
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `d3c4268a5c611a651614005ef4a56172f3e2a8d5` — Merge pull request #131 from ArChAnG3LsFuRy/fix/goodwe-site-solar-override
- **Classification:** admin/no-port
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/coordinator.py`, `custom_components/power_sync/inverters/entity_override.py` (+84 more)
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `fd50565189e96b274c3506cf3258e16b1ca6a8fe` — Merge pull request #133 from Teslemetry/fm/powersync-system-info-din-upstream
- **Classification:** admin/no-port
- **Key files:** `custom_components/power_sync/manifest.json`, `custom_components/power_sync/powerwall_local/transport.py`, `tests/test_powerwall_v1r_teslemetry_parity.py`, `custom_components/power_sync/__init__.py` (+7 more)
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `1ef7b0fe5ea2bc9df6a4ebc7403a81583f965318` — chore(manifest): bump version to 2.12.1387
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`, `docs/wiki/GoodWe.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `24141e85427569d199b47984ef4eabe49235f9e1` — docs(release): clear RELEASE_NOTES.md after v2.12.1387
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `f2c0e07fce92c44d63084edbb97d9bd59cd17a3e` — fix(ev): enforce generic and OCPP price policy with delayed start confirmation
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/automations/actions.py`, `custom_components/power_sync/automations/ev_charging_planner.py`, `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/const.py` (+5 more)
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `5404735c39a8f9cb97716b2132c63dbf7584585c` — fix(ev): preserve anonymous charger external control policies
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/automations/ev_ownership.py`, `tests/test_ev_ownership_runtime.py`, `tests/test_ev_price_level_ownership.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `762789b2b68853240bf4b581d0e1d358bb566a39` — chore(manifest): bump version to 2.12.1388
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `5ad1ab7c145d4148d1fbf5bb2eb2e8512f68aedb` — docs(release): clear RELEASE_NOTES.md after v2.12.1388
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `fbd33c0bdc7e34770b981faa2763daa346e9f708` — fix(ev): fence superseded Generic charger cleanup
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/automations/actions.py`, `tests/test_ev_ocpp_actions.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `c4f1155107cc554d87607ecc94b8e60f407918c7` — chore(manifest): bump version to 2.12.1389
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `f7ae18791a7013c07e1c4c822f5453ce11e6028a` — docs(release): clear RELEASE_NOTES.md after v2.12.1389
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `854fdf67af4a95387edd10b2ab7fb7c60a291e4a` — feat: add signed HA optimiser permission foundation in shadow mode
- **Classification:** paywall/subscription reject
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/licensing/__init__.py`, `custom_components/power_sync/licensing/admission.py`, `custom_components/power_sync/licensing/permission.py` (+5 more)
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `2a53f413d6e9c4e520db19de234b08823a705f4a` — fix(optimizer): retain native solar after clipped export
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/battery_optimizer.py`, `tests/test_cost_neutral_optimizer.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `31570e7fa61ee7588da5b6e81f9ddf5c257b099d` — chore(manifest): bump version to 2.12.1390
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `0d1b65c5c86366b8ebd94c6db58591776cc3c713` — docs(release): clear RELEASE_NOTES.md after v2.12.1390
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `37c055823d5487a38185f6170b09263269fbce3f` — feat(dashboard): add optional daily buy and sell price overlays
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/frontend/power-sync-strategy.js`, `tests/test_currency_tariffs.py`, `tests/test_dashboard_dependency_detection.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `60932d0d710b46e1e8aaaab7baa1b18e822830e9` — chore(manifest): bump version to 2.12.1391
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `6d7c1eea28de2e2e02854057d22c5698ab10dbb8` — docs(release): clear RELEASE_NOTES.md after v2.12.1391
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `2ce154261f1ff1fd1c190df3a8638688e0180d37` — fix(optimizer): account for home-serving discharge in displayed grid flows
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/coordinator.py`, `tests/test_battery_export_allowed_slots.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `d177329cf3fc1999dc4637a9bb074367adadb96e` — chore(manifest): bump version to 2.12.1392
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `40e5c728a5e366e912f22439a1087d12c705dcce` — docs(release): clear RELEASE_NOTES.md after v2.12.1392
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `9e9eb36845686cecb9858add14a0f17e1d4265e9` — feat: finish HA optimiser activation, command fencing and owned recovery
- **Classification:** paywall/subscription reject
- **Key files:** `README.md`, `custom_components/power_sync/__init__.py`, `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/licensing/admission.py` (+22 more)
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `616655ea987c951782b26d85412c407afb5014a4` — fix(optimizer): use unused native solar before deadline holds
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/battery_optimizer.py`, `tests/test_battery_optimizer_export_guard.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `6ddce665e3a9934ac0f526eb020eb517bcd2d770` — chore(manifest): bump version to 2.12.1393
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `5bda58759fb8e06bae922255b8afc6631462e95d` — docs(release): clear RELEASE_NOTES.md after v2.12.1393
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `2929d32f2862bb29cb323d359ca63930f8f9a149` — fix: keep optimiser scopes current across manual controls and preserve upstream fixes
- **Classification:** paywall/subscription reject
- **Key files:** `.github/discord-release-last-posted.txt`, `custom_components/power_sync/frontend/power-sync-strategy.js`, `custom_components/power_sync/licensing/admission.py`, `custom_components/power_sync/licensing/entry_routing.py` (+43 more)
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `cd1dd1b22552da0c4d89551b5fe7a55904fb6818` — fix(powerwall_local): keep Tesla protocol compatible with HA protobuf
- **Classification:** excluded backend reject
- **Key files:** `custom_components/power_sync/manifest.json`, `custom_components/power_sync/powerwall_local/transport.py`, `tests/test_powerwall_v1r_teslemetry_parity.py`, `tests/test_tesla_protocol_dependency.py`
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `f3561b211e486cd0628a2801ee6d47c595a4920d` — chore(manifest): bump version to 2.12.1394
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `9eaa76930a8ae4c68e974f817f215b99ca670484` — docs(release): clear RELEASE_NOTES.md after v2.12.1394
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `c7426a7324adcd250dc53544ecd53700590078e4` — fix: isolate Powerwall schemas and preserve projection failure provenance
- **Classification:** excluded backend reject
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/optimization/battery_optimizer.py`, `custom_components/power_sync/powerwall_local/__init__.py`, `custom_components/power_sync/powerwall_local/energy_device/LICENSE` (+32 more)
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `a15c728b555e455beeec0b060de00cde9256ed90` — chore(manifest): bump version to 2.12.1395
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `6b8da8064111d63cc004ef3338ad0b24a9131304` — docs(release): clear RELEASE_NOTES.md after v2.12.1395
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `dbaf64daed63e40707387df4dfce65610a31ab30` — fix(optimizer): reconcile subthreshold export accounting
- **Classification:** manual semantic review
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`, `custom_components/power_sync/optimization/battery_optimizer.py`, `tests/test_cost_neutral_optimizer.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `ee26bcd5b114e78cd8921a12ba4b6ca52d787b2f` — docs(release): clear RELEASE_NOTES.md after v2.12.1396
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `b64d9bc1e2b7279cfdba7ca4cadefa292b956025` — fix(ev): reconcile Zaptec pending price-level starts
- **Classification:** excluded backend reject
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/automations/actions.py`, `custom_components/power_sync/automations/ev_charging_planner.py`, `custom_components/power_sync/manifest.json` (+4 more)
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `43a625618c678da1ea9715c0120686857c542acb` — docs(release): clear RELEASE_NOTES.md after v2.12.1397
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `3831e3b880f1107fe94516a7e0e5cf7ac42ba583` — fix: keep Zaptec stop ownership until fresh readback
- **Classification:** excluded backend reject
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/__init__.py`, `custom_components/power_sync/automations/ev_charging_planner.py`, `tests/test_ev_loadpoint_status_view.py` (+1 more)
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `49c7117584ffeb01ddfe7c87e4eb2a2e918ca2d7` — chore(manifest): bump version to 2.12.1398
- **Classification:** admin/no-port
- **Key files:** `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `429c028d9d7e4babdb294f962dee5afe19dfde9e` — docs(release): clear RELEASE_NOTES.md after v2.12.1398
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `c07686688b70885f3f8457e11c88e65e15849fe6` — fix(amber): use fresh current interval for TOU sync
- **Classification:** low-risk compatible port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/__init__.py`, `custom_components/power_sync/manifest.json`, `custom_components/power_sync/tariff_converter.py` (+1 more)
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `7e5be5d4e53eb810b75a3150f0c42e4f000a7576` — docs(release): clear RELEASE_NOTES.md after v2.12.1399
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `004c6093fc0579d1dd7d07adc1b33e4a8f1e42f3` — fix(optimizer): avoid unnecessary Cost Neutral paid top-ups
- **Classification:** manual semantic review
- **Key files:** `custom_components/power_sync/optimization/battery_optimizer.py`, `tests/fixtures/cost_neutral_free_window_paid_topups.json`, `tests/test_cost_neutral_optimizer.py`
- **Rationale:** Touches optimizer or EV planning semantics; adapt the smallest outcome only after a private regression preserves profile, lease, and mode authority.
- **Intended gate:** Task-specific RED/GREEN private regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `d3f83beee19f236e5952475902d3a2272db75095` — chore(manifest): bump version to 2.12.1400
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `08461b92266850f6335c2d8945d4cd7f26966f21` — docs(release): clear RELEASE_NOTES.md after v2.12.1400
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `a1df6d70f7628baf5cc3addb62457371ad3964ff` — feat(ai): add ChatGPT subscription sign-in for plan explanations
- **Classification:** paywall/subscription reject
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/const.py`, `custom_components/power_sync/frontend/power-sync-strategy.js` (+10 more)
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `2b5514b9421b58c8f919670900b4c8afa9613a02` — fix(foxess): propagate self-consumption restore failures
- **Classification:** low-risk compatible port
- **Key files:** `custom_components/power_sync/__init__.py`, `tests/test_optimizer_restore_retry.py`
- **Rationale:** Provider, registry, forecast, or display behavior has no private shared-loadpoint ownership seam; port only with its focused regression.
- **Intended gate:** Focused upstream-equivalent regression + `validate_local_architecture.py` + `run_private_tests.sh`.

### `10558586ca19a67a5233725fe3ac51ce5aed103a` — chore(manifest): bump version to 2.12.1401
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `8573c17ee45459b84b974dfbed7c4234dfa5e587` — docs(release): clear RELEASE_NOTES.md after v2.12.1401
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `297bada9f54a72d2833ca50c7c0f45fb10d13afb` — Merge pull request #134 from pemontto/chatgpt-subscription-signin
- **Classification:** paywall/subscription reject
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/config_flow.py`, `custom_components/power_sync/const.py`, `custom_components/power_sync/frontend/power-sync-strategy.js` (+14 more)
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `54d47af22cda225f791826442c1a05f6b496eed9` — chore(manifest): bump version to 2.12.1402
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/const.py`, `custom_components/power_sync/manifest.json`, `tests/test_dashboard_dependency_detection.py`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `4d2287c0753ef27b5a32aed632195db3c0fefb32` — docs(release): clear RELEASE_NOTES.md after v2.12.1402
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `3ae4afe1c7e64704affef73e78a44c0fae74759b` — fix(setup): report retained Tesla dependency conflicts after upgrades
- **Classification:** excluded backend reject
- **Key files:** `custom_components/power_sync/__init__.py`, `custom_components/power_sync/strings.json`, `custom_components/power_sync/tesla_dependencies.py`, `custom_components/power_sync/translations/en.json` (+1 more)
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `49a90babee3770c867192fa60399f1034e70f5a4` — chore(manifest): bump version to 2.12.1403
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`, `custom_components/power_sync/strings.json`, `custom_components/power_sync/translations/en.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `20c238feaf0bb87001d45f7e3506b9ef792dcdec` — docs(release): clear RELEASE_NOTES.md after v2.12.1403
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `3dadae5bb775b61b148a187eaf3c285afd54a683` — Merge current HA releases and preserve licensing regressions
- **Classification:** paywall/subscription reject
- **Key files:** `.github/discord-release-last-posted.txt`, `custom_components/power_sync/__init__.py`, `custom_components/power_sync/automations/actions.py`, `custom_components/power_sync/automations/ev_charging_planner.py` (+91 more)
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `4375a3c7be1802f94c3237c527ba844bb7c04c93` — Accept bounded first-billing permissions without pausing healthy trials
- **Classification:** paywall/subscription reject
- **Key files:** `custom_components/power_sync/licensing/permission.py`, `docs/ha-optimizer-licensing.md`, `tests/fixtures/ha_optimizer_permission.json`, `tests/test_ha_optimizer_permission.py`
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `a4b617e2cda25ff7cb2b945be42cc5b65bb632ea` — chore(manifest): release HA optimiser subscription activation in 2.12.1404
- **Classification:** paywall/subscription reject
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `92ed2488d58625836df38a1541aa6ceae3d62c2a` — docs(release): clear RELEASE_NOTES.md after v2.12.1404
- **Classification:** paywall/subscription reject
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `6633a0c5c230eb58d87ffcf6b91bcfd4884ee8db` — docs: record verified optimiser subscription launch and cutoff
- **Classification:** paywall/subscription reject
- **Key files:** `docs/ha-optimizer-licensing.md`
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `1476c9925ca72b09ebcd709919233638e0fbb4de` — docs: record TestFlight availability and completed support-role verification
- **Classification:** paywall/subscription reject
- **Key files:** `docs/ha-optimizer-licensing.md`
- **Rationale:** Introduces or carries licensing, optimiser entitlement, hosted subscription, or ChatGPT subscription behavior, all forbidden in this no-paywall fork.
- **Intended gate:** No port; source review against forbidden `licensing/` and `optimization/chatgpt_auth.py` paths plus architecture validator.

### `f3748a4bab27983efc879c6d7b9b1a27d55063f4` — chore(manifest): bump version to 2.12.1405
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/const.py`, `custom_components/power_sync/frontend/power-sync-strategy.js`, `custom_components/power_sync/manifest.json` (+1 more)
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `ddb7423e85583478435e402b619fd07ef174ab44` — docs(release): clear RELEASE_NOTES.md after v2.12.1405
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `59d8618c1eac952cb88ee4b25bae2511085bcecc` — Add shared non-Tesla EV profile selection
- **Classification:** redundant/incompatible private shared-EV
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/__init__.py`, `custom_components/power_sync/automations/actions.py`, `custom_components/power_sync/automations/ev_loadpoint_profiles.py` (+6 more)
- **Rationale:** Upstream profile identity and selection storage conflict with the private selector-led two-logical-profile, one-physical-loadpoint model; do not import `power_sync.set_connected_ev` or `ev_loadpoint_profiles.py`.
- **Intended gate:** No port; retain private shared-loadpoint architecture validator and shared-loadpoint/reconciler focused tests.

### `7d91ad2adf5790afa6466e59e9b3fe0bb10e9733` — docs(release): clear RELEASE_NOTES.md after v2.12.1406
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `4d2910d6b365c26a0fdfb938f0c92d52d88a180f` — fix(tesla): honor rejected grid export writes
- **Classification:** excluded backend reject
- **Key files:** `custom_components/power_sync/__init__.py`, `tests/test_tesla_grid_export_service.py`
- **Rationale:** Targets a Tesla, Powerwall, AEMO, Zaptec, or other excluded protocol/backend outside the private-fork scope.
- **Intended gate:** No port; scope review and existing focused private gate.

### `5bef40e675591b746c0ef553946126dad4a4fc82` — chore(manifest): bump version to 2.12.1407
- **Classification:** admin/no-port
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/manifest.json`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `e30815b178048f3aff61993505c604a9fefddd56` — docs(release): clear RELEASE_NOTES.md after v2.12.1407
- **Classification:** admin/no-port
- **Key files:** `.github/discord-release-last-posted.txt`, `RELEASE_NOTES.md`
- **Rationale:** Release metadata, release-note clearing, version bookkeeping, or merge bookkeeping has no independent private behavior to port.
- **Intended gate:** No code port; manifest contract test only.

### `e3e107409b18add2213a9de617cc23591e73c873` — Improve Smart Schedule EV presentation
- **Classification:** manual semantic review
- **Key files:** `RELEASE_NOTES.md`, `custom_components/power_sync/automations/ev_charging_planner.py`, `custom_components/power_sync/frontend/power-sync-strategy.js`, `custom_components/power_sync/manifest.json` (+4 more)
- **Rationale:** Adapt presentation manually to private logical-profile IDs and snapshot alignment; do not import upstream physical/profile identity assumptions or command behavior.
- **Intended gate:** Task-specific RED/GREEN private schedule-presentation regression + `validate_local_architecture.py` + `run_private_tests.sh`.
