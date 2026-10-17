# Maintainer-server bootstrap

This guide prepares a dedicated Hermes profile on the separate always-on
maintainer server. It is a manual procedure; this repository does not create a
profile, configure credentials, schedule a job, contact a remote, or deploy
PowerSync.

## Manual prerequisites

Before installing the tracked skill, an operator must provide:

- An Ubuntu server with Hermes already installed and a private-fork checkout.
- A named Hermes profile, `powersync-maintainer`, at
  `~/.hermes/profiles/powersync-maintainer/`; do not use the default profile.
- A working Python environment for the private fork and the required local test
  dependencies.
- A private GitHub credential with repository-scoped read/write access only to
  the private fork. Do not grant organisation administration, public-repository
  write access, or a token with broader scopes than the deploy repository
  requires.
- A documented, separately authorised deployment/rollback procedure. It is not
  installed or invoked by this bootstrap.

Create the profile manually if it does not already exist:

```bash
hermes profile create powersync-maintainer
hermes profile show powersync-maintainer
```

Set that profile's terminal working directory to the private-fork checkout using
the server's reviewed Hermes configuration. Keep the profile isolated: do not
clone default-profile credentials, Home Assistant tools, cron jobs, or existing
sessions into it.

## Verify private remote before authorising any write

From the private-fork checkout, inspect every configured remote and identify the
intended private deploy remote. Do not infer that `origin` is private.

```bash
git remote -v
git remote get-url origin
gh repo view --json nameWithOwner,visibility,url
```

Continue only when `visibility` is `PRIVATE`, the returned owner/name is the
approved private fork, and the push URL is the approved private GitHub URL. If
any result is missing, public, unexpected, or inaccessible, stop and repair the
server configuration outside an autonomous maintenance run. Never push to the
public `upstream` remote, force-push, delete branches, or change repository
visibility.

## Least-privilege profile policy

Enable only the capabilities necessary for source maintenance:

- terminal and file tools, constrained to the private-fork checkout and
  disposable candidate worktrees;
- web/GitHub read tools for explicit upstream review and private-repository
  verification;
- GitHub credentials restricted to the private repository.

Do not enable general Home Assistant control tools, deployment credentials,
cron-management tools, public-repository credentials, or secrets-discovery
capabilities. A separately reviewed deployment wrapper may be made available
later only if it is limited to the PowerSync integration and validates candidate
gates first; this bootstrap does not add one.

## Install the tracked skill

Run the repository script from a reviewed checkout, supplying the full named
profile path explicitly. The script copies one tracked `SKILL.md` locally. It
performs no network operation and makes no cron, Home Assistant, Git remote, or
deployment change.

```bash
cd /path/to/private-fork
scripts/private-fork/install_maintainer_skill.sh \
  "$HOME/.hermes/profiles/powersync-maintainer"
```

The script refuses a missing argument, a path not named
`powersync-maintainer`, and a nonexistent profile directory. It never targets
the default `~/.hermes` profile.

## Verify installation and maintenance readiness

```bash
PROFILE_HOME="$HOME/.hermes/profiles/powersync-maintainer"
test -f "$PROFILE_HOME/skills/powersync-private-updates/SKILL.md"
cmp docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md \
  "$PROFILE_HOME/skills/powersync-private-updates/SKILL.md"
hermes profile show powersync-maintainer
python scripts/private-fork/validate_local_architecture.py
scripts/private-fork/run_private_tests.sh
```

The first two commands verify the installed skill is exactly the repository
source. The remaining commands verify profile identity and local source gates;
they do not authorise a candidate merge, push, release, or deployment. Review
`docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md` before any
maintenance run. Deployment remains prohibited until a separate operator
authorisation and the approved server procedure are both present.

## Install the paused review cron explicitly

The repository supplies a portable installer, but it does nothing unless the
operator passes `--apply`. Run it only on the dedicated remote server after the
skill installation and private-origin checks above. All artifact paths are
explicit and must remain inside the named profile home; the checkout root is
the job's fixed work directory.

```bash
PROFILE_HOME="$HOME/.hermes/profiles/powersync-maintainer"
cd /path/to/private-fork
scripts/private-fork/install_maintainer_cron.sh --dry-run \
  --repo "$PWD" \
  --profile-home "$PROFILE_HOME" \
  --ledger-state "$PROFILE_HOME/state/maintainer_ledger.json" \
  --reports-dir "$PROFILE_HOME/reports"

scripts/private-fork/install_maintainer_cron.sh --apply \
  --repo "$PWD" \
  --profile-home "$PROFILE_HOME" \
  --ledger-state "$PROFILE_HOME/state/maintainer_ledger.json" \
  --reports-dir "$PROFILE_HOME/reports"
```

Create the `state/` and `reports/` directories first. If this server has the
old `$PROFILE_HOME/state/upstream.json`, inspect and back it up, then migrate it
once to the distinct ledger output:

```bash
python scripts/private-fork/maintainer_ledger.py --repo "$PWD" migrate \
  --state "$PROFILE_HOME/state/maintainer_ledger.json" \
  --legacy-state "$PROFILE_HOME/state/upstream.json" \
  --baseline <exact-legacy-checkpoint-sha> \
  --migration-boundary v2.12.1418 \
  --migration-reference <honest-pre-ledger-reference>
```

`upstream.json` remains read-only backup/reference and is never a ledger output.
The installer verifies
that `origin` is a private GitHub repository with `gh`, that the installed
`powersync-private-updates` skill exists, and that no active job with the same
name exists. It creates `powersync-private-upstream-review` **paused**, every
`3d`, with local/suppressed delivery only. It prints, but never runs, this
resume command:

```bash
hermes --profile powersync-maintainer cron resume powersync-private-upstream-review
```

Review the rendered dry-run command and the paused job before resuming it. Do
not change delivery to `origin`; review artifacts remain local.
