# Read-only maintainer-cycle cron specification

This is a reusable remote-server specification for the isolated
`powersync-maintainer` profile. The companion portable installer creates a
paused job only when a remote operator explicitly passes `--apply`; it does not
contact a server or enable the job by itself.

## Schedule contract

Run **every 3 days**. The portable installer encodes this as the Hermes `3d`
schedule, creates the named job paused, attaches `powersync-private-updates`,
fixes its workdir to the explicit checkout root, and uses `local` delivery for
both normal and failure output. Hermes owns any scheduler jitter; the installer
adds no unbounded delay or secondary scheduler. The job must use the
`powersync-maintainer` profile and the private-fork checkout only.

Pass all artifact locations and endpoints explicitly. A remote operator may add
`--fetch` only when updating the named read-only upstream tracking reference is
intended for that invocation; without that flag the cycle must not fetch.

```bash
python /path/to/private-fork/scripts/private-fork/maintainer_cycle.py \
  --repo /path/to/private-fork \
  --upstream-remote upstream \
  --baseline <explicit-ledger-checkpoint-sha-or-tag> \
  --target <explicit-upstream-sha-or-tag> \
  --state /var/lib/powersync-maintainer/review-state.json \
  --report-json /var/lib/powersync-maintainer/reports/latest.json \
  --report-markdown /var/lib/powersync-maintainer/reports/latest.md
```

The operator may supply `--inventory /path/to/private-fork/docs/private-fork/local-change-inventory.md`
when the inventory is stored outside the checkout default.

Before the read-only comparison, initialize the durable sequential ledger with
`scripts/private-fork/maintainer_ledger.py init` from an explicit baseline and
honest migration boundary/reference. For the existing server state, run its
safe `migrate --legacy-state` form once, with a baseline exactly matching its
legacy checkpoint; it never changes the legacy file or invents pre-ledger
v1418 outcomes. Each actual integration cycle must use `maintainer_ledger.py
next` and `record` in strictly oldest to newest order; `summary` is the cron
JSON payload. The ledger is authoritative rather than a freeform last_reviewed_upstream checkpoint.

## Reusable Hermes prompt

```text
You are running the read-only PowerSync upstream maintainer cycle in the
powersync-maintainer profile. Use only the explicit private-fork repository,
upstream remote, baseline, target, ledger state JSON, JSON report, and Markdown
report paths supplied by the scheduler. Run maintainer_cycle.py with those exact
arguments. Add --fetch only if the scheduler explicitly supplies it.

Treat the resulting report as triage only. Do not merge, rebase, cherry-pick,
push, tag, create a candidate, deploy, restart services, or control Home
Assistant. If requires_candidate is true, report that fact and stop. Deployment
is forbidden until a later, separately implemented candidate/deployment process
exists and is explicitly authorised.
```

## Required output handling

Keep the JSON and Markdown artifacts for review. The ledger JSON records the
atomic terminal-decision history and checkpoint; the read-only cycle report is
not a replacement checkpoint. A malformed state file, a missing remote, or
missing endpoint must fail the run without replacing reports or state. The
cycle makes no candidate change regardless of classification.

## Paused installer contract

`scripts/private-fork/install_maintainer_cron.sh` requires all of `--apply`,
`--repo`, `--profile-home`, `--state`, and `--reports-dir`; `--dry-run` is the
non-mutating alternative to `--apply`. It refuses the default or wrong profile,
paths outside the supplied checkout/profile boundaries, a missing installed
skill, an origin that `gh` cannot verify as private, and an existing active job
with the fixed name `powersync-private-upstream-review`. It never resumes the
job. Its prompt requires `maintainer_ledger.py` with the explicit repository,
state, and report locations and forbids delivery to origin.
