# Solar-only profitable-refill candidate evidence

- **Base:** `03ea78b19433b2883601dd149b44e9847a4b1aad` (`feature/shared-logical-evs`)
- **Upstream source hunk:** `ce9f73bf4cec8312fd5784e39960f26fe4a9b3d2`
- **Candidate code revision tested:** `1da7c50f90a84d7f2270b01a76dd5fb98d3181f4`
- **Classification:** compatible manual semantic adaptation. No licensing, profile-selection, lease, or shared-loadpoint code was imported.

## RED/GREEN and continuity

The new positive-acquisition-cost solar-only refill regression failed before the
predicate change: the low-FIT solar slot charged at `0.0 W` rather than above
`9000 W`. It passed after the exact bounded upstream predicate was applied.

- `tests/test_battery_optimizer_export_guard.py`: **140 passed**
- `scripts/private-fork/run_private_tests.sh`: **390 passed** optimizer-continuity tests; **287 passed** focused private tests
- `python scripts/private-fork/validate_local_architecture.py`: **pass**

`tests/test_power_sync_surface_contract.py` permits only an exact expected
`battery_optimizer.py` source variant built from `v2.12.1363`, alongside the
existing exact Amber coordinator exception. Its mutation test proves that
changing `acquisition_cost_kwh > 0` to `>= 0` fails the allowlist.

## Broader-suite baseline comparison

Both runs used `scripts/private-fork/run_private_tests.sh --broader` in the
project virtual environment. The broader suite remains failing; it is not a
pass gate for this candidate.

| Run | Result |
| --- | --- |
| Base `03ea78b1` | 193 failed, 5379 passed, 17 warnings |
| Candidate code `1da7c50f` | 193 failed, 5381 passed, 17 warnings |
| Candidate-added failure IDs | 0 |
| Baseline-resolved failure IDs | 0 |
| Unchanged failure IDs | 193 |

The canonical sorted stable `FAILED tests/...` ID set has the same SHA-256 in
both runs: `94b8d82ff7abdfbd62b1660ca6d09ac1857e76a7727fc5c767aa42df62a730a2`.
Thus no candidate-added or changed broader-suite failure ID was observed.
