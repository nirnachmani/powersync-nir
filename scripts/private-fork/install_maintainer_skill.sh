#!/usr/bin/env bash
# Install the tracked maintainer skill into an explicitly selected named profile.
# This script deliberately performs local file copies only.
set -euo pipefail

usage() {
  printf 'Usage: %s /path/to/powersync-maintainer\n' "${0##*/}" >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 64
fi

profile_home=$1
if [[ ${profile_home##*/} != "powersync-maintainer" ]]; then
  printf 'Refusing destination: it must be the named powersync-maintainer profile home.\n' >&2
  exit 64
fi

if [[ ! -d $profile_home ]]; then
  printf 'Refusing destination: profile home does not exist: %s\n' "$profile_home" >&2
  exit 66
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source_skill="$script_dir/../../docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md"
if [[ ! -f $source_skill ]]; then
  printf 'Source skill is missing: %s\n' "$source_skill" >&2
  exit 66
fi

destination_dir="$profile_home/skills/powersync-private-updates"
mkdir -p -- "$destination_dir"
cp -- "$source_skill" "$destination_dir/SKILL.md"
printf 'Installed powersync-private-updates into %s\n' "$destination_dir" >&2
