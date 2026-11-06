#!/usr/bin/env bash
# Squash the promoted build into the slow `main` line and publish it to GitHub.
#
# Three local lines: `dev` takes every small commit and feeds the development
# instance, `stable` moves only by promotion (`openprogram dev promote`) and
# runs the stable App, and `main` is the slow line GitHub carries: one commit
# per version, each holding a `stable` tree on top of the previous `main`
# commit, so it never contains dev's history. refs/publish/last records the
# commit the latest version was made from, so the next one lists only what is
# new.
#
# Usage: scripts/publish-github.sh [-m "summary"] [--source <ref>] [--no-push] [--dry-run]
#   -m         version summary; required when the source differs from main
#   --source   commit to squash (default: stable, the promoted build)
#   --no-push  add the version to local main only
#   --dry-run  show the version's message and checks, change nothing
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

summary=""
source_ref="stable"
push=1
dry_run=0
while test "$#" -gt 0; do
  case "$1" in
    -m) summary="${2:-}"; shift 2 ;;
    --source) source_ref="${2:-}"; shift 2 ;;
    --no-push) push=0; shift ;;
    --dry-run) dry_run=1; shift ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

# The guard hooks live in the shared .git/hooks, so every worktree gets them.
hooks_dir="$(git rev-parse --git-common-dir)/hooks"
for hook in pre-push pre-commit; do
  install -m 0755 "$repo_root/scripts/git-hooks/$hook" "$hooks_dir/$hook"
done

zero=0000000000000000000000000000000000000000
empty_tree="$(git hash-object -t tree /dev/null)"
source_commit="$(git rev-parse "$source_ref^{commit}")"
main_head="$(git rev-parse --verify --quiet 'refs/heads/main^{commit}' || true)"

if ! git merge-base --is-ancestor "$source_commit" refs/heads/dev; then
  printf '%s is not on dev\n' "$source_ref" >&2
  exit 1
fi

if test -n "$main_head" && test "$(git rev-parse "$source_commit^{tree}")" = "$(git rev-parse "$main_head^{tree}")"; then
  printf 'main already holds this tree; no new version\n'
else
  if test -z "$summary"; then
    printf 'a summary is required for a new version: -m "..."\n' >&2
    exit 2
  fi
  # A version lists the commits since the previous one; the first lists none.
  base=""
  if test -n "$main_head"; then
    base="$(git rev-parse --verify --quiet refs/publish/last || true)"
    if test -n "$base" && ! git merge-base --is-ancestor "$base" "$source_commit"; then
      printf 'refs/publish/last is not an ancestor of %s\n' "$source_ref" >&2
      exit 1
    fi
  fi

  # Refuse a version holding anything that looks like a live credential. AWS's
  # documented example key and one-line PEM fixtures in tests are not keys.
  added="$(git diff "${main_head:-$empty_tree}" "$source_commit" -U0 | grep -E '^\+' || true)"
  hits="$( { printf '%s\n' "$added" \
      | grep -Eo '(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-(api|admin)[0-9]{2}-[A-Za-z0-9_-]{40,}|AKIA[0-9A-Z]{16})' \
      | grep -v 'EXAMPLE$' || true
    printf '%s\n' "$added" | grep -E '^\+[[:space:]]*-----BEGIN [A-Z ]*PRIVATE KEY-----[[:space:]]*$' || true
  } | sort -u)"
  if test -n "$hits"; then
    printf 'possible credentials, refusing to publish:\n%s\n' "$hits" >&2
    exit 1
  fi

  message_file="$(mktemp)"
  trap 'rm -f "$message_file"' EXIT
  {
    printf '%s\n\n' "$summary"
    if test -n "$base"; then
      printf 'Squashes %s local commits.\n' "$(git rev-list --count "$base..$source_commit")"
    else
      printf 'First version on this line.\n'
    fi
    printf '\nLocal-Source: %s\n' "$source_commit"
  } >"$message_file"
  printf 'new version from %s on top of main %s\n\n' \
    "$(git rev-parse --short "$source_commit")" "${main_head:+$(git rev-parse --short "$main_head")}"
  cat "$message_file"
  git diff --shortstat "${main_head:-$empty_tree}" "$source_commit"
  if test "$dry_run" -eq 1; then
    exit 0
  fi

  new_commit="$(git commit-tree "$source_commit^{tree}" ${main_head:+-p "$main_head"} -F "$message_file")"
  git update-ref -m "publish $source_commit" refs/heads/main "$new_commit" "${main_head:-$zero}"
  git update-ref refs/publish/last "$source_commit"
  main_head="$new_commit"
  printf '\nmain is now %s\n' "$(git rev-parse --short "$main_head")"
fi

if test "$push" -eq 0 || test "$dry_run" -eq 1; then
  exit 0
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  printf 'no origin remote; main stays local\n' >&2
  exit 1
fi
# GitHub's main must be an earlier point of local main, so the push only
# fast-forwards it.
if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then
  git fetch --quiet origin main
  if ! git merge-base --is-ancestor FETCH_HEAD "$main_head"; then
    printf 'GitHub main %s is not part of local main; refusing to push\n' "$(git rev-parse --short FETCH_HEAD)" >&2
    exit 1
  fi
fi
OPENPROGRAM_GITHUB_PUBLISH=1 git push origin refs/heads/main:refs/heads/main
printf 'published %s to GitHub main\n' "$(git rev-parse --short "$main_head")"
