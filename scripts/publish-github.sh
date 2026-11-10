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
# Usage: scripts/publish-github.sh [-m "summary"] [--source <ref>] [--tag vX.Y.Z] [--no-push] [--dry-run]
#   -m         version summary; required when the source differs from main
#   --source   commit to squash (default: stable, the promoted build)
#   --tag      after pushing main, tag that commit and push the tag, which
#              starts the Release workflow; needs matching versions and notes
#   --no-push  add the version to local main only
#   --dry-run  show the version's message and checks, change nothing
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

summary=""
source_ref="stable"
tag=""
push=1
dry_run=0
while test "$#" -gt 0; do
  case "$1" in
    -m) summary="${2:-}"; shift 2 ;;
    --source) source_ref="${2:-}"; shift 2 ;;
    --tag) tag="${2:-}"; shift 2 ;;
    --no-push) push=0; shift ;;
    --dry-run) dry_run=1; shift ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

if test -n "$tag" && test "$push" -eq 0 && test "$dry_run" -eq 0; then
  printf -- '--tag publishes the tag, so it cannot be combined with --no-push\n' >&2
  exit 2
fi

# The guard hooks live in the shared .git/hooks, so every worktree gets them.
if test "$dry_run" -eq 0; then
  "$repo_root/scripts/git-hooks/install.sh"
fi

zero=0000000000000000000000000000000000000000
empty_tree="$(git hash-object -t tree /dev/null)"
source_commit="$(git rev-parse "$source_ref^{commit}")"
main_head="$(git rev-parse --verify --quiet 'refs/heads/main^{commit}' || true)"

if ! git merge-base --is-ancestor "$source_commit" refs/heads/dev; then
  printf '%s is not on dev\n' "$source_ref" >&2
  exit 1
fi

# A tag starts the Release workflow, which stops at its last step when the
# versions or the notes are wrong. Refuse here, before anything has moved.
check_tag() {
  if ! printf '%s\n' "$tag" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
    printf 'a release tag looks like v1.2.3, not %s\n' "$tag" >&2
    exit 2
  fi
  local version="${tag#v}" python_version desktop_version notes
  python_version="$(git show "$source_commit:pyproject.toml" | sed -n 's/^version = "\(.*\)"$/\1/p' | head -n 1)"
  desktop_version="$(git show "$source_commit:apps/desktop/package.json" | sed -n 's/^  "version": "\(.*\)",$/\1/p' | head -n 1)"
  if test "$python_version" != "$version" || test "$desktop_version" != "$version"; then
    printf 'tag %s does not match this source: pyproject.toml says %s, apps/desktop/package.json says %s. Change the versions or the tag.\n' \
      "$tag" "${python_version:-nothing}" "${desktop_version:-nothing}" >&2
    exit 1
  fi
  notes=".github/release-notes/$tag.md"
  if ! git cat-file -e "$source_commit:$notes" 2>/dev/null; then
    printf 'this source has no release notes for %s; write %s and commit it first.\n' "$tag" "$notes" >&2
    exit 1
  fi
  if test "$(git show "$source_commit:$notes" | head -n 1)" != "# OpenProgram $version Release Notes"; then
    printf '%s must start with the line: # OpenProgram %s Release Notes\n' "$notes" "$version" >&2
    exit 1
  fi
  if git rev-parse --verify --quiet "refs/tags/$tag" >/dev/null; then
    printf 'the tag %s already exists here, and a released tag never moves.\n' "$tag" >&2
    exit 1
  fi
}
if test -n "$tag"; then
  check_tag
fi

# The whole site leaves the machine, so every docs error stops a version. The
# check reads the commit being published, not whatever this checkout holds.
check_docs() {
  local python="${OPENPROGRAM_DOCS_PYTHON:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.venv/bin/python}"
  if ! test -x "$python"; then
    printf 'cannot check the docs: no Python at %s; refusing to publish\n' "$python" >&2
    exit 1
  fi
  local parent status=0
  parent="$(mktemp -d)"
  trap 'git worktree remove --force "$parent/tree" 2>/dev/null; rm -rf "$parent"; git worktree prune' EXIT
  git -c core.hooksPath=/dev/null worktree add --quiet --detach "$parent/tree" "$source_commit"
  (cd "$parent/tree" && "$python" -B -m scripts.docs_site.check --all) || status=$?
  git worktree remove --force "$parent/tree"
  rm -rf "$parent"
  git worktree prune
  trap - EXIT
  if test "$status" -ne 0; then
    printf 'refusing to publish: the docs check on %s exited %s; fix it on dev and promote\n' \
      "$(git rev-parse --short "$source_commit")" "$status" >&2
    exit 1
  fi
}

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

  check_docs

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
    if test -n "$tag"; then
      printf '\nwould tag the new main commit %s and push the tag, starting the Release workflow\n' "$tag"
    fi
    exit 0
  fi

  new_commit="$(git commit-tree "$source_commit^{tree}" ${main_head:+-p "$main_head"} -F "$message_file")"
  git update-ref -m "publish $source_commit" refs/heads/main "$new_commit" "${main_head:-$zero}"
  git update-ref refs/publish/last "$source_commit"
  main_head="$new_commit"
  printf '\nmain is now %s\n' "$(git rev-parse --short "$main_head")"
fi

if test "$dry_run" -eq 1 && test -n "$tag"; then
  printf 'would tag main %s as %s and push the tag, starting the Release workflow\n' \
    "$(git rev-parse --short "$main_head")" "$tag"
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
if test -n "$tag" && git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  printf 'GitHub already has the tag %s, and a released tag never moves; nothing was pushed.\n' "$tag" >&2
  exit 1
fi
OPENPROGRAM_GITHUB_PUBLISH=1 git push origin refs/heads/main:refs/heads/main
printf 'published %s to GitHub main\n' "$(git rev-parse --short "$main_head")"

if test -n "$tag"; then
  git tag "$tag" "$main_head"
  OPENPROGRAM_GITHUB_PUBLISH=1 git push origin "refs/tags/$tag:refs/tags/$tag"
  printf 'tagged %s as %s; the Release workflow builds it from here\n' "$(git rev-parse --short "$main_head")" "$tag"
fi
