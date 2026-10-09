# PowerSync Nir contributor rules

- Do not commit directly to `main`.
- Keep the Home Assistant domain/package `powersync_nir`; preserve the Android HTTP namespace `/api/power_sync/...` and its request/response contract.
- The fork replaces original PowerSync in an HA instance; do not implement simultaneous loading.
- Every upstream integration requires a short compatibility report and the relevant targeted tests, including Android-app contract tests.
- Automatic deployment is permitted only through defined updater gates with a verified rollback path.
- Keep changes scoped and use small, test-backed commits.
