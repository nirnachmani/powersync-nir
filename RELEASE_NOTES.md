<!-- release: v2.12.1447-nir.2 -->

## PowerSync Nir private fork

- Port three previously rejected AI explanation updates: defer unused ChatGPT host registration, avoid opening unselected ChatGPT credential storage at startup while restoring it on selection, and add a configurable 30–600-second local AI timeout with one request budget across retries.
- Preserve the existing shared logical-EV safeguards, Android API compatibility, and no-paywall optimiser boundary; no HA deployment was performed.
- Keep the fork private. This release is available from the private GitHub repository but is **not installable through standard HACS**, which does not support private repositories.
