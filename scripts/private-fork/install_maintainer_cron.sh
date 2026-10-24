#!/usr/bin/env bash
# Install one paused upstream-maintenance cron job into an explicit profile.
set -euo pipefail

JOB_NAME="powersync-private-upstream-review"
PROFILE_NAME="powersync-maintainer"
SKILL_NAME="powersync-private-updates"

usage() {
  cat >&2 <<'EOF'
Usage: install_maintainer_cron.sh --apply|--dry-run --repo PATH --profile-home PATH --ledger-state PATH --reports-dir PATH

Creates a paused, local-delivery maintainer updater job. After explicit resume,
it directly ports compatible updates and reports only decisions that need review.
--apply is required for scheduler changes; --dry-run validates and prints the
exact create command.
EOF
}

die() {
  printf 'Refusing maintainer cron installation: %s\n' "$*" >&2
  exit 64
}

apply=0
dry_run=0
repo=""
profile_home=""
ledger_state=""
reports_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) apply=1 ;;
    --dry-run) dry_run=1 ;;
    --repo|--profile-home|--ledger-state|--reports-dir)
      [[ $# -ge 2 ]] || die "$1 requires a path"
      case "$1" in
        --repo) repo=$2 ;;
        --profile-home) profile_home=$2 ;;
        --ledger-state) ledger_state=$2 ;;
        --reports-dir) reports_dir=$2 ;;
      esac
      shift
      ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument: $1" ;;
  esac
  shift
done

[[ $apply -ne $dry_run ]] || die "choose exactly one of --apply or --dry-run; --apply is required for scheduler changes"
[[ -n $repo && -n $profile_home && -n $ledger_state && -n $reports_dir ]] || die "--repo, --profile-home, --ledger-state, and --reports-dir are all required"

# Never inspect or invoke the scheduler before the caller explicitly authorises it.
if [[ $apply -ne 1 && $dry_run -ne 1 ]]; then
  die "--apply is required"
fi

command -v git >/dev/null || die "git is required"
command -v hermes >/dev/null || die "hermes is required"

repo=$(realpath -e -- "$repo") || die "repository does not exist"
profile_home=$(realpath -e -- "$profile_home") || die "profile home does not exist"
reports_dir=$(realpath -e -- "$reports_dir") || die "reports directory does not exist"
ledger_state=$(realpath -m -- "$ledger_state") || die "ledger state path is invalid"

[[ -d $repo ]] || die "--repo is not a directory"
[[ -d $profile_home ]] || die "--profile-home is not a directory"
[[ -d $reports_dir ]] || die "--reports-dir is not a directory"
[[ ${profile_home##*/} == "$PROFILE_NAME" ]] || die "--profile-home must be the named $PROFILE_NAME profile, never the default profile"
[[ $profile_home == */profiles/$PROFILE_NAME ]] || die "--profile-home must be inside a profiles/$PROFILE_NAME boundary"

repo_root=$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null) || die "--repo is not a Git checkout"
repo_root=$(realpath -e -- "$repo_root")
[[ $repo == "$repo_root" ]] || die "--repo must be the checkout root so the cron workdir is fixed"

case "$ledger_state" in "$profile_home"/*) ;; *) die "--ledger-state is outside the --profile-home boundary" ;; esac
case "$reports_dir" in "$profile_home"/*) ;; *) die "--reports-dir is outside the --profile-home boundary" ;; esac
[[ ${ledger_state##*/} != "upstream.json" ]] || die "--ledger-state must be a distinct ledger output, never legacy upstream.json"
case "$ledger_state" in "$reports_dir"|"$reports_dir"/*) die "--ledger-state must be outside --reports-dir to prevent report collisions" ;; esac
[[ -f "$profile_home/skills/$SKILL_NAME/SKILL.md" ]] || die "installed $SKILL_NAME skill is missing from --profile-home"

origin_url=$(git -C "$repo" remote get-url origin 2>/dev/null) || die "origin remote is missing"
case "$origin_url" in
  git@github.com:*.git) origin_repo=${origin_url#git@github.com:}; origin_repo=${origin_repo%.git} ;;
  https://github.com/*.git) origin_repo=${origin_url#https://github.com/}; origin_repo=${origin_repo%.git} ;;
  https://github.com/*) origin_repo=${origin_url#https://github.com/} ;;
  *) die "origin must be the approved GitHub repository" ;;
esac
[[ $origin_repo == nirnachmani/powersync-nir ]] || die "origin is not the approved GitHub repository"
push_url=$(git -C "$repo" remote get-url --push origin 2>/dev/null) || die "origin push URL is missing"
case "$push_url" in
  git@github.com:nirnachmani/powersync-nir.git|https://github.com/nirnachmani/powersync-nir.git|https://github.com/nirnachmani/powersync-nir) ;;
  *) die "origin push URL is not the approved GitHub repository" ;;
esac

report_json="$reports_dir/latest.json"
report_markdown="$reports_dir/latest.md"
prompt=$(cat <<EOF
Run the PowerSync private-fork upstream maintenance cycle in $repo. Use the installed $SKILL_NAME skill and the enforced scripts/private-fork/maintainer_ledger.py CLI. The sole ledger output is $ledger_state; do not run maintainer_cycle.py against it. Write only the supplied report artifacts at $report_json and $report_markdown. The ledger is schema-versioned sequential history, never a freeform last_reviewed_upstream checkpoint. On a new server, preserve the legacy $profile_home/state/upstream.json as read-only input/backup and create $ledger_state only with: python scripts/private-fork/maintainer_ledger.py --repo $repo migrate --state $ledger_state --legacy-state $profile_home/state/upstream.json --baseline <exact-sha> --migration-boundary v2.12.1418 --migration-reference <honest-pre-ledger-reference>.

Fetch upstream and process every unreviewed update strictly oldest to newest under the skill's relevance and fork-compatibility policy. Use maintainer_ledger.py next --state $ledger_state --target refs/remotes/upstream/main to obtain the one exact next commit and maintainer_ledger.py record --state $ledger_state --target refs/remotes/upstream/main --private-ref feature/shared-logical-evs only after its terminal decision; record its upstream version, ported, amended, rejected, or admin/no-port outcome, factual reason, and fork commit SHA(s) for ported/amended work. Every recorded fork SHA must resolve in this checkout and be reachable from the intended fork ref (default feature/shared-logical-evs; use an explicit --private-ref only for the intended fork branch). The CLI atomically advances its checkpoint with that entry and rejects deferred, unknown, out-of-order, nonexistent, or wrong-branch fork commits. Finish with maintainer_ledger.py summary --state $ledger_state for the cron JSON payload. Reject irrelevant/excluded-only updates and optimizer-licensing-only hunks; assess mixed commits under the hunk-level rule below. For a relevant update with no plausible interaction with shared two-EV/external-session behavior, port it minimally, retain upstream tests where applicable, commit, and push the fork feature branch to the approved origin. For an important upstream EV/external-session fix that overlaps fork logical-EV behavior, preserve its bug-fix outcome by making the smallest amendment through the selector, canonical physical loadpoint, lease, session, and reconciler seams; add only the necessary interaction test, then commit and push. If those requirements conflict or the correct outcome is genuinely uncertain, make no code change and stop at that commit for operator input; do not process newer commits until it is resolved.

Treat follow-up fixes and enhancements to already-approved ChatGPT plan explanations and other existing explanation providers as normal relevant candidates even if the affected provider is not currently selected; do not demand a second blanket AI approval. Review new authentication scopes or storage contracts on their actual merits. Inspect licensing-adjacent commits hunk by hunk: exclude entitlement code, but port or minimally amend independently useful non-licensing behavior when separable, including private EV overlaps. Reject only when the useful behavior itself is inseparable from the excluded entitlement or irrelevant to this setup.

Run the architecture validator and private compatibility gate once per completed update cycle. Never deploy, restart Home Assistant, alter .storage, operate a charger, rebase wholesale, or import optimiser licensing/access/entitlement code. End every cycle with the concise per-update report required by the skill. The email body must include the complete per-update Markdown table (upstream version/commit, outcome, brief reason or amendment), not just a link to or attachment of a detailed report; keep the detailed maintenance report too. Send the report by email through the configured Resend MCP using the same defaults as the server's ha-update skill, then deliver it locally and save it at the supplied report paths. If email fails, retain the local report and state the failure without exposing credentials.

When and only when the cycle ports or amends updates, every commit through its upstream target has a terminal ledger outcome, and all gates pass: publish the verified feature head as an approved GitHub release on nirnachmani/powersync-nir. Set a unique version/tag v<latest-fully-processed-upstream-tag>-nir.<serial> in custom_components/power_sync/manifest.json and RELEASE_NOTES.md, commit it on feature/shared-logical-evs, fast-forward main to that verified head, push feature/shared-logical-evs and main to the approved origin, then create the matching GitHub release. Do not publish reject/admin-only cycles, unresolved work, or failed gates. Publication is not Home Assistant deployment; never claim it updates the installed integration. Live deployment needs separate authorization.
EOF
)

create_cmd=(hermes --profile "$PROFILE_NAME" cron create '0 1 */3 * *'
  --name "$JOB_NAME"
  --skill "$SKILL_NAME"
  --workdir "$repo"
  --deliver local
  --failure-deliver local
  --paused
  --paused-reason "Operator review required before enabling automatic compatible-update maintenance"
  "$prompt")
resume_cmd=(hermes --profile "$PROFILE_NAME" cron resume "$JOB_NAME")

if [[ $dry_run -eq 1 ]]; then
  printf 'Dry run: scheduler unchanged.\nCreate command: '
  printf '%q ' "${create_cmd[@]}"
  printf '\nResume only after review: '
  printf '%q ' "${resume_cmd[@]}"
  printf '\n'
  exit 0
fi

# Refuse only active duplicates; an existing paused job remains deliberately inert.
existing=$(hermes --profile "$PROFILE_NAME" cron list --all) || die "cannot inspect existing cron jobs"
listed_job_active=0
while IFS= read -r line; do
  if [[ $line == *"[active]"* ]]; then
    listed_job_active=1
  elif [[ $line == *"[paused]"* || $line == *"[disabled]"* || $line == *"[completed]"* ]]; then
    listed_job_active=0
  fi
  if [[ $line == *"$JOB_NAME"* && ( $listed_job_active -eq 1 || $line =~ (active|enabled|running|scheduled) ) ]]; then
    die "an active $JOB_NAME job already exists; refusing duplicate creation"
  fi
done <<< "$existing"

"${create_cmd[@]}"
printf 'Created paused %s with local/suppressed delivery.\n' "$JOB_NAME"
printf 'Resume to enable automatic compatible-update maintenance: '
printf '%q ' "${resume_cmd[@]}"
printf '\n'
