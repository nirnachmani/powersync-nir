#!/usr/bin/env bash
# Install one paused upstream-maintenance cron job into an explicit profile.
set -euo pipefail

JOB_NAME="powersync-private-upstream-review"
PROFILE_NAME="powersync-maintainer"
SKILL_NAME="powersync-private-updates"

usage() {
  cat >&2 <<'EOF'
Usage: install_maintainer_cron.sh --apply|--dry-run --repo PATH --profile-home PATH --state PATH --reports-dir PATH

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
state=""
reports_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) apply=1 ;;
    --dry-run) dry_run=1 ;;
    --repo|--profile-home|--state|--reports-dir)
      [[ $# -ge 2 ]] || die "$1 requires a path"
      case "$1" in
        --repo) repo=$2 ;;
        --profile-home) profile_home=$2 ;;
        --state) state=$2 ;;
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
[[ -n $repo && -n $profile_home && -n $state && -n $reports_dir ]] || die "--repo, --profile-home, --state, and --reports-dir are all required"

# Never inspect or invoke the scheduler before the caller explicitly authorises it.
if [[ $apply -ne 1 && $dry_run -ne 1 ]]; then
  die "--apply is required"
fi

command -v git >/dev/null || die "git is required"
command -v gh >/dev/null || die "gh is required to verify origin visibility"
command -v hermes >/dev/null || die "hermes is required"

repo=$(realpath -e -- "$repo") || die "repository does not exist"
profile_home=$(realpath -e -- "$profile_home") || die "profile home does not exist"
reports_dir=$(realpath -e -- "$reports_dir") || die "reports directory does not exist"
state=$(realpath -m -- "$state") || die "state path is invalid"

[[ -d $repo ]] || die "--repo is not a directory"
[[ -d $profile_home ]] || die "--profile-home is not a directory"
[[ -d $reports_dir ]] || die "--reports-dir is not a directory"
[[ ${profile_home##*/} == "$PROFILE_NAME" ]] || die "--profile-home must be the named $PROFILE_NAME profile, never the default profile"
[[ $profile_home == */profiles/$PROFILE_NAME ]] || die "--profile-home must be inside a profiles/$PROFILE_NAME boundary"

repo_root=$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null) || die "--repo is not a Git checkout"
repo_root=$(realpath -e -- "$repo_root")
[[ $repo == "$repo_root" ]] || die "--repo must be the checkout root so the cron workdir is fixed"

case "$state" in "$profile_home"/*) ;; *) die "--state is outside the --profile-home boundary" ;; esac
case "$reports_dir" in "$profile_home"/*) ;; *) die "--reports-dir is outside the --profile-home boundary" ;; esac
[[ -f "$profile_home/skills/$SKILL_NAME/SKILL.md" ]] || die "installed $SKILL_NAME skill is missing from --profile-home"

origin_url=$(git -C "$repo" remote get-url origin 2>/dev/null) || die "origin remote is missing"
case "$origin_url" in
  git@github.com:*.git) origin_repo=${origin_url#git@github.com:}; origin_repo=${origin_repo%.git} ;;
  https://github.com/*.git) origin_repo=${origin_url#https://github.com/}; origin_repo=${origin_repo%.git} ;;
  https://github.com/*) origin_repo=${origin_url#https://github.com/} ;;
  *) die "origin must be a verifiable private GitHub repository, not: $origin_url" ;;
esac
is_private=$(gh repo view "$origin_repo" --json isPrivate --jq .isPrivate 2>/dev/null) || die "cannot verify origin visibility with gh"
[[ $is_private == "true" ]] || die "origin is not private (isPrivate: ${is_private:-unknown})"

report_json="$reports_dir/latest.json"
report_markdown="$reports_dir/latest.md"
prompt=$(cat <<EOF
Run the PowerSync private-fork upstream maintenance cycle in $repo. Use the installed $SKILL_NAME skill and update $state plus $report_json / $report_markdown.

Fetch upstream and classify every unreviewed update under the skill's relevance and private-compatibility policy. Reject and record irrelevant, excluded-backend, and optimiser-licensing updates. For a relevant update with no plausible interaction with private two-EV/external-session behavior, port it minimally, retain upstream tests where applicable, commit, and push the private feature branch. For an important upstream EV/external-session fix that overlaps private logical-EV behavior, preserve its bug-fix outcome by making the smallest amendment through the private selector, canonical physical loadpoint, lease, session, and reconciler seams; add only the necessary interaction test, then commit and push. When a relevant update depends on an earlier unported relevant change, process them as one ordered dependency cohort instead of indefinitely deferring the dependent: adapt the prerequisite first, then the completion. If those private requirements conflict or the correct outcome is genuinely uncertain, make no code change: record concise alternatives and stop that item for operator input.

Run the architecture validator and private compatibility gate once per completed update cycle. Never deploy, restart Home Assistant, alter .storage, operate a charger, rebase wholesale, or import optimiser licensing/access/entitlement code. End every cycle with the concise per-update report required by the skill; deliver it locally and save it at the supplied report paths.
EOF
)

create_cmd=(hermes --profile "$PROFILE_NAME" cron create 3d
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
