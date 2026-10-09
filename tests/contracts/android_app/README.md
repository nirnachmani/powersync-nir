# Android app contract baseline

This directory protects compatibility with the released Android app before private backend changes.

## Static baseline

`fixtures/android-1.0.7-336-static-routes.json` was derived by intersecting HTTP view URLs registered by PowerSync `v2.12.1363` with strings in the released `com.powersync.mobile` 1.0.7 build 336 APK. It contains no capture data or credentials.

The vehicle-list field list comes from decoded app code. It is intentionally limited to fields actually observed as copied into the app model.

## Controlled physical capture

When a user-owned HA/app capture is available, run:

```bash
python scripts/private-fork/capture_android_contract.py raw.json sanitised.json
```

The script retains JSON object/list structure and non-sensitive values while redacting sensitive keys and IP-address strings. Review the result before committing it. Do not commit raw captures.

## Manual smoke checklist

Before a private release:

1. Remove or disable original PowerSync, then install PowerSync Nir.
2. Confirm the app loads and shows the existing Generic or Sigenergy EVAC charger view.
3. Save an existing schedule control and confirm it persists.
4. Open status and history views.
5. Confirm no app-facing error is shown.
