# Local optimizer replay

This local-only developer tool adapts the solver replay portion of upstream PowerSync commit `5fb1d9db`, copyright its upstream contributors and subject to the repository's noncommercial licence. It does not install remote diagnostics, sharing, brokers, support access, or fleet collection.

Use the project test environment and private scratch storage:

```sh
.venv/bin/python scripts/replay_optimizer.py capture --case flat-tariff --currency AUD --output "$TMPDIR/case.json"
.venv/bin/python scripts/replay_optimizer.py validate "$TMPDIR/case.json"
.venv/bin/python scripts/replay_optimizer.py replay "$TMPDIR/case.json" --output "$TMPDIR/report.json"
.venv/bin/python scripts/replay_optimizer.py fingerprint --component-root "$PWD/custom_components/power_sync"
.venv/bin/python scripts/replay_optimizer.py compare "$TMPDIR/case.json" --candidate-root /path/to/reviewed/custom_components/power_sync --expected-candidate-sha256 REVIEWED_SHA256 --output "$TMPDIR/comparison.json"
```

Capture is off unless a local developer or test explicitly attaches a recorder. The solver boundary captures a bounded closed schema, including this fork's reason and manual-control command fields; unknown values are rejected. Recordings can contain sensitive site information and must remain private. Worker fingerprints, dependency pins, exact capture reconstruction and repeated runs are required; unsupported metrics and changed, unreviewed source surfaces cannot pass as covered. Coordinator preprocessing, hardware commands, EV policy/deadlines and Cost Neutral settlement are not established by solver replay. A replay pass does not authorize publication or deployment and does not prove physical behavior. Continue running all required fork gates and targeted tests.
