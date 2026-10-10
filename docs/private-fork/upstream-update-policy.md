# Private-fork upstream update policy

## Purpose and safety boundary

`collect_upstream_delta.py` and `classify_delta.py` produce deterministic,
read-only review evidence for an explicit upstream range. They do not alter a
Git checkout, fetch, publish, integrate, create a worktree, deploy, or contact
Home Assistant. The public `upstream` remote is never a publication target.

A classification is triage, not permission to integrate or deploy. Any later
candidate work is subject to the private architecture validator and focused
private tests.

## Inputs and collection

Supply both endpoints explicitly: the last reviewed upstream SHA/tag and a
target SHA/tag. The collector resolves both to commits, rejects missing,
invalid, reversed, and non-ancestral ranges, and emits stable JSON containing:

- resolved and requested endpoint references;
- commits in forward chronological order;
- `git diff --name-status` path changes, including rename origins;
- changed Python source definitions and their added/deleted/modified status;
- changed test paths and test function names; and
- changed release-note/changelog paths.

Example (the caller, not the script, chooses where JSON is retained):

```bash
python scripts/private-fork/collect_upstream_delta.py \
  <last-reviewed-upstream-sha-or-tag> <target-upstream-sha-or-tag> \
  --repo /path/to/private-fork > upstream-delta.json
python scripts/private-fork/classify_delta.py upstream-delta.json \
  --root /path/to/private-fork
```

The scripts do not implicitly update a remote. If a maintainer separately
obtains public upstream references, they must still pass explicit resolved
endpoints to the collector.

## Deterministic classification

The classifier reads `docs/private-fork/local-change-inventory.md`, its listed
coupled source and test paths, local definitions in those source files, and the
collector's paths, source symbols, and test names. Its JSON result includes the
classification and exact evidence paths/symbols/tests.

| Classification | Deterministic evidence | Required follow-up |
| --- | --- | --- |
| `no-overlap` | No changed path matches an inventory coupling path. | Review release notes; candidate integration may be considered only through the normal gates. |
| `mechanical-overlap` | A coupled path overlaps, but no documented private symbol has a semantic source change. | Inspect the actual hunk before any candidate resolution. |
| `compatible-semantic-overlap` | A documented private symbol changes and upstream provides changed test evidence. | Prove every private invariant with adapted focused tests before considering integration. |
| `redundant-private-coverage` | A documented private symbol and a documented private test both overlap, and the changed test name is already locally covered. | Record an equivalence rationale and the reviewed upstream commit; do not copy code merely because it overlaps. |
| `incompatible-semantic-conflict` | A documented private symbol is deleted upstream. | Preserve an untouched candidate/report for human review; do not integrate or deploy. |

The classifier is intentionally conservative and structural. It cannot infer
that tests passed, that semantics are safe, or that a private implementation is
equivalent beyond its recorded evidence. A changed shared file alone is not an
incompatible conflict.

## Candidate and verification policy

Before an authorised candidate integration, record private revision, explicit
upstream range, working-tree status, and classifier JSON. For every candidate,
run:

```bash
python scripts/private-fork/validate_local_architecture.py
scripts/private-fork/run_private_tests.sh
```

### Disposable candidate preparation

`candidate_worktree.py` prepares only an isolated, detached local checkout; it
does not integrate, publish, tag, or deploy. Its required arguments are always
explicit: private checkout, candidate-root directory, private source ref,
upstream target ref, and manifest output path. It rejects a dirty private
checkout and an `origin` that is not `nirnachmani/powersync-nir`, unless an
explicit `--private-owner-repo owner/repository` policy is supplied. The
upstream target is recorded as review evidence only and is never a publication
target.

```bash
python scripts/private-fork/candidate_worktree.py prepare \
  --private-repo /path/to/powersync-nir \
  --candidate-root /path/to/disposable-candidates \
  --private-source-ref <private-source-sha-or-ref> \
  --upstream-target-ref <upstream-target-sha-or-ref> \
  --manifest /path/to/candidate-manifest.json
```

The manifest is written atomically and records starting/source/target SHAs,
the exact candidate path, and the `candidate-prepared-no-integration`
classification. If preflight or manifest writing fails after creation, the
script removes that disposable candidate. Removal is separate and requires the
exact registered candidate path directly beneath the supplied candidate root:

```bash
python scripts/private-fork/candidate_worktree.py cleanup \
  --private-repo /path/to/powersync-nir \
  --candidate-root /path/to/disposable-candidates \
  --worktree /path/to/disposable-candidates/<exact-candidate-name>
```

Do not weaken those gates or claim a semantic resolution from classification
output. Deployment, releases, public-repository updates, and remote publishing
are outside this policy and these tools.
