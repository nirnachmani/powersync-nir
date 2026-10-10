# Read-only maintainer-cycle cron specification

This is a reusable remote-server specification for the isolated
`powersync-maintainer` profile. It does not create a cron job, alter a profile,
or contact a server from this repository.

## Schedule contract

Run **every 3 days** with bounded **jitter** (for example, choose one execution
time uniformly within the first 90 minutes after the three-day interval). The
remote operator owns scheduling and must retain the concrete schedule outside
this repository. The job must use the `powersync-maintainer` profile and the
private-fork checkout only.

Pass all artifact locations and endpoints explicitly. A remote operator may add
`--fetch` only when updating the named read-only upstream tracking reference is
intended for that invocation; without that flag the cycle must not fetch.

```bash
python /path/to/private-fork/scripts/private-fork/maintainer_cycle.py \
  --repo /path/to/private-fork \
  --upstream-remote upstream \
  --baseline <last-reviewed-upstream-sha-or-tag> \
  --target <explicit-upstream-sha-or-tag> \
  --state /var/lib/powersync-maintainer/review-state.json \
  --report-json /var/lib/powersync-maintainer/reports/latest.json \
  --report-markdown /var/lib/powersync-maintainer/reports/latest.md
```

The operator may supply `--inventory /path/to/private-fork/docs/private-fork/local-change-inventory.md`
when the inventory is stored outside the checkout default.

## Reusable Hermes prompt

```text
You are running the read-only PowerSync upstream maintainer cycle in the
powersync-maintainer profile. Use only the explicit private-fork repository,
upstream remote, baseline, target, state JSON, JSON report, and Markdown report
paths supplied by the scheduler. Run maintainer_cycle.py with those exact
arguments. Add --fetch only if the scheduler explicitly supplies it.

Treat the resulting report as triage only. Do not merge, rebase, cherry-pick,
push, tag, create a candidate, deploy, restart services, or control Home
Assistant. If requires_candidate is true, report that fact and stop. Deployment
is forbidden until a later, separately implemented candidate/deployment process
exists and is explicitly authorised.
```

## Required output handling

Keep the JSON and Markdown artifacts for review. The state JSON records only the
reviewed resolved range and normalized classification. A malformed state file, a
missing remote, or missing endpoint must fail the run without replacing reports
or state. The cycle makes no candidate change regardless of classification.
