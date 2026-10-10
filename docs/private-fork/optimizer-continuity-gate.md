# Optimizer continuity gate

Run the private gate from the repository root:

```bash
uv pip install --python .venv/bin/python -r requirements-test.txt
scripts/private-fork/run_private_tests.sh
```

`run_private_tests.sh` always invokes `run_optimizer_regression_tests.sh` before
its existing private-fork checks. The continuity runner uses only the project
`.venv`, runs its fixed 18-suite optimizer corpus, then runs
`test_home_load_telemetry.py` and `test_power_sync_surface_contract.py`.

The surface contract compares every Python source below
`custom_components/power_sync/optimization/` with immutable baseline commit
`85f99ea62a174cd9153d5ff2ce71023dda2c9a5c` (`v2.12.1363`). It therefore
requires Git and a non-shallow checkout that contains that tag. For GitHub
Actions, use `actions/checkout` with `fetch-depth: 0` (and ensure tags are
available); do not add this gate to a release workflow solely to obtain that
checkout.

`requirements-test.txt` is test tooling only. Do not copy `aiohttp` into the
Home Assistant integration manifest unless it becomes a genuine integration
runtime requirement.
