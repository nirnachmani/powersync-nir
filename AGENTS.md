# PowerSync private-fork contributor rules

- Do not commit directly to `main`.
- Keep the Home Assistant domain/package `power_sync`; preserve the Android HTTP namespace `/api/power_sync/...` and its request/response contract.
- The private repository remains `nirnachmani/powersync-nir`. Repository identity is separate from the Home Assistant integration domain.
- The fork replaces original PowerSync in an HA instance; do not implement simultaneous loading.
- Every upstream integration requires a short compatibility report and the relevant targeted tests, including Android-app contract tests.
- Deployment requires separate explicit authorization. Defined updater gates and a verified rollback path are prerequisites, not deployment authorization.
- Keep changes scoped and use small, test-backed commits.
