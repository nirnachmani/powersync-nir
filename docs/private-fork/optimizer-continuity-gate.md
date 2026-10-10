# Optimizer continuity gate

Run the private gate from the repository root:

```bash
scripts/private-fork/run_private_tests.sh
```

On a clean checkout, either private runner creates `.venv` with `uv venv .venv`
when it is absent; the optimizer continuity runner then installs the pinned
test-only requirements with `.venv/bin/python`. They never use or install into
a global Python environment.

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

`requirements-test.txt` is test tooling only and exactly pins the `aiohttp`,
`highspy`, and `pytest` versions verified for this optimizer gate. Before it
runs its corpus, the continuity runner proves that `.venv/bin/python -m pytest
--version` succeeds. Do not copy `aiohttp` into the Home Assistant integration
manifest unless it becomes a genuine integration runtime requirement.
