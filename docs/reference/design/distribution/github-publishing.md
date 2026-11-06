# Publishing source to GitHub

The repository keeps three lines, each moving at its own pace. `dev` takes every small commit: a visual tweak tried and reverted, a fix to the fix, a step of a refactor. `stable` takes what has been checked on the development instance and promoted, and the stable App runs it. `main` is the slow line: one commit per version, made after dozens or hundreds of small changes have collected on `stable`, so its history reads as a list of versions instead of a working log. GitHub carries `main` and nothing else.

| | `dev` | `stable` | `main` |
| --- | --- | --- | --- |
| Commits | every commit any session makes | the commits of `dev` it is fast-forwarded to | one squashed commit per version |
| Moved by | `git commit` in the main checkout or a worktree | `openprogram dev promote` only | `scripts/publish-github.sh` only |
| Runs or feeds | the development instance (port 18200) | the stable App (port 18100) | GitHub's `main`: source installs, CI, release tags |

`dev` and `stable` share one history. `main` has its own: each version's commit holds a `stable` tree on top of the previous version, so no `dev` commit is ever its ancestor and the lines never merge. Nothing pulls GitHub's `main` back into `dev` or `stable`.

## Branches

Locally there are exactly these three. Feature branches and worktree branches are short-lived: a worktree's branch is merged into `dev` and then deleted, or deleted when abandoned. A branch worth keeping out of the way rather than deleting goes under `refs/archive/`, which no command lists as a branch and nothing pushes.

## Publishing a version

```bash
scripts/publish-github.sh -m "Sidebar run status, Launchpad, Agent cards" --dry-run
scripts/publish-github.sh -m "Sidebar run status, Launchpad, Agent cards"
```

The script squashes `stable` by default, because `stable` is the commit that has been deployed to the development instance, checked there and promoted. `--source <ref>` squashes another commit on `dev` instead.

1. It installs the guards (below) into the shared `.git/hooks`, so every worktree has them.
2. It refuses a source that is not on `dev`. When `main` already holds the source's tree there is no new version, and it goes straight to the push.
3. It scans the lines the version adds for live-looking credentials (GitHub tokens, Anthropic API keys, AWS access keys, private key blocks) and refuses to publish if it finds any. AWS's documented example key and one-line PEM strings in tests do not count.
4. It writes the commit message: the summary given with `-m`, the number of local commits since the previous version, and a `Local-Source:` trailer naming the commit the version was made from.
5. It creates the commit with `git commit-tree`: the source's tree, with the previous `main` commit as its only parent (the first version has none), moves `main` to it and records the source in `refs/publish/last`, where the next version starts counting.
6. It pushes `main` to GitHub after checking that GitHub's `main` is an earlier point of local `main`, so the push only fast-forwards. `--no-push` stops after step 5.

## The guards

`scripts/git-hooks/pre-push` refuses a push to `refs/heads/main` unless it comes from the script (the script sets `OPENPROGRAM_GITHUB_PUBLISH=1`) and sends local `main`. Pushing `dev` would upload the whole working history, so pushing any other branch is refused too. Deleting a remote branch and pushing tags are allowed.

`scripts/git-hooks/pre-commit` refuses a commit while `main` is checked out, so a session that still thinks of `main` as the place to commit fails at once instead of mixing working commits into the slow line.

The machine's global hooks (`core.hooksPath`) delegate `pre-push` and `pre-commit` to the repository's `.git/hooks`, which is why the script installs them there.

## Rules for sessions

- Commit to `dev` as often as the work needs; deploy and promote as [Stable and development instances](dev-instance.md) describes.
- Never commit on `main`, never `git push` it by hand, and never merge `main` into `dev` or `stable`.
- Do not push any other branch to GitHub, and do not open pull requests from local branches: their history is the `dev` line, so a pull request would list every local commit.
- Publish when a version is ready, after many promotions, not after every feature.

## Implementation status

- Implemented: `scripts/publish-github.sh` with dry run, `--no-push`, credential scan and `refs/publish/last`; the `pre-push` and `pre-commit` guards; the rules in `AGENTS.md`.
- Not yet: release tags are still created by hand on the published commit.
