# Stable and development instances

A source checkout drives two local instances. The stable instance is the one the owner works in every day. The development instance is where new commits run first, for testing and for showing use cases. Commits reach stable only by promotion. Stable can change and use the development instance at any time without restarting itself.

| | Stable | Development |
| --- | --- | --- |
| Code | the `stable` branch, moved only by promotion | the `dev` commit deployed to it last |
| Runs as | `/Applications/OpenProgram.app`, port 18100 | `/Applications/OpenProgram Dev.app` (macOS) or a browser, port 18200, runtime in `~/.openprogram-dev/runtime` |
| State | `~/.openprogram` (default profile) | `~/.openprogram-dev` (`dev` profile) |
| Updated by | `openprogram dev promote` → `scripts/refresh-local-app.sh` | `openprogram dev deploy` → `scripts/refresh-dev-instance.sh` |

`openprogram/operations/worker/dev_instance.py` holds the rules; `openprogram dev` is the command for them.

## Deploying to the development instance

`openprogram dev deploy [ref]` (default `dev`) checks the commit out into a managed detached worktree, `~/.openprogram-dev/source`, and runs `scripts/refresh-dev-instance.sh` there. The script:

1. refuses uncommitted changes;
2. builds the Web assets and the OpenProgram wheel;
3. installs a full CPython 3.12 inside the runtime once (`uv python install --install-dir`), syncs it to the locked dependency set a release installs, and reinstalls the wheels;
4. on macOS, builds the named helper `OpenProgram Dev.app` (bundle id `ai.openprogram.runtime.dev`) and points `runtime-manifest.json` at it, so the worker runs under its own identity and Screen Recording, Accessibility and similar permissions are granted to it separately from the stable runtime;
5. sets the `dev` profile's port to 18200 and binds the Program catalog;
6. installs or restarts only the `dev` worker as a login service (launchd or systemd), so it comes back after a reboot, waits for `/healthz`, and records the commit in `runtime/source-revision`;
7. on macOS, runs `scripts/install-dev-app.sh`, which installs the development App described below.

Nothing of the stable instance is stopped or written, so a conversation in the stable App can deploy, then open `http://127.0.0.1:18200` in its browser or call that API, and look at the result.

### The development App

`/Applications/OpenProgram Dev.app` (bundle id `ai.openprogram.desktop.dev`) is the deployed commit's Desktop shell over the development instance, so the owner tests in an App of its own while working in the stable one. It carries no runtime: `Contents/Resources/instance.json` names the `dev` profile, port 18200 and `~/.openprogram-dev/runtime`, and `apps/desktop/main/instance.js` reads it. With that file the shell connects to port 18200, starts and authenticates the worker through the development runtime under `OPENPROGRAM_PROFILE=dev`, keeps its Electron data in `~/Library/Application Support/OpenProgram Dev`, ignores the stable installers' lock and never checks for release updates.

`scripts/install-dev-app.sh` builds it next to, never into, the stable App. It builds the commit's whole Desktop shell with `scripts/release/build-desktop-shell.sh` (electron-builder with the release configuration minus the runtime), so the Electron that `apps/desktop/package.json` pins runs in the development App first. It then renames the bundle, writes `instance.json`, and signs it with the local identity (`local-macos-signing.py sign --development`, which signs the outer App alone because there is no bundled runtime). It swaps the bundle while the App is closed and reopens it if it was open.

Each App has its own browser debugging port, where the browser tool attaches to its web tabs: 9223 for the stable App and 9224 (`instance.json` `debugPort`) for the development App. `programs/applications/browser/chrome.py` picks the port by the active profile, so the development agent never drives the stable App's tabs.

A stable refresh replaces `app.asar` and keeps the App's Electron. When `package.json` pins another Electron than the installed one, `scripts/refresh-local-app.sh` builds the same shell and moves its frameworks, executable, `Info.plist` and locales into the stable App while it is closed, so promotion brings the Electron the development App already ran.

### Signing in

The worker mints a new owner token every time it starts, so every deploy signs out browsers that were signed in to the development instance. The development App fetches its new token itself; a plain browser cannot. `openprogram dev open` opens the instance in the default browser already signed in, and `openprogram dev auth-url` prints a sign-in link for another browser. A browser that loses its sign-in says so and names these commands.

### State and models

The development instance has its own state. Credentials are part of it: the credential store's root is the active profile's state dir, like every other path, so the `dev` profile never reads or refreshes the default profile's logins.

`openprogram dev copy-models` gives it the stable instance's model setup. It copies the provider settings (`providers`, `api_keys`, `last_used_model`), API-key credentials and CLI-delegated credentials, which read another tool's login by reference. It does not copy OAuth logins: their refresh tokens rotate, so two instances refreshing one login would sign each other out. Those are signed in again in the development instance if it needs them. Conversations, Agents and memory are never copied.

### From a conversation

With a `stable` branch, `self_update(action="prepare")` validates the candidate worktree as before but does not install it into the App. It starts `openprogram dev deploy <candidate>` detached, logs to `~/.openprogram-dev/deploy.log`, and returns the development URL. The stable App changes only by promotion, which needs the candidate merged into `dev` first, because promotion only fast-forwards `stable`.

## Promoting to stable

Promotion is a command on purpose, with no Settings button: it is a development step, run by the owner or by an Agent the owner asked. `openprogram dev promote [revision]` upgrades the stable instance to exactly what the development instance serves. It refuses unless all of these hold:

- the commit is the one recorded in `~/.openprogram-dev/runtime/source-revision`, and not a dirty build;
- the development instance answers `/healthz`;
- the commit contains the current `stable`, so the move is a fast-forward.

Then it backs up the stable profile (`openprogram backup`, label `pre-promote`) and moves `refs/heads/stable` with a compare-and-swap, so two promotions cannot overwrite each other. It checks the commit out into `~/.openprogram/release-source` and runs `scripts/refresh-local-app.sh`, which installs the App transactionally and restarts the stable worker. The backup runs while the old stable worker is still serving; promotion itself never opens the stable data stores. The restarted worker, on the new code, is the process that migrates the execution store and heals rows the old worker wrote late (see [Who migrates the execution store](../runtime/execution/control.html#store-schema-ownership)). The same rule keeps a repository `.venv/bin/openprogram` run against the default profile from upgrading stable's store underneath the running App.

`scripts/refresh-local-app.sh` installs only `refs/heads/stable` once that branch exists. A refresh started from `dev` or any other commit is refused with a pointer to the development instance. That keeps "every commit lands in the App" from coming back by habit.

## Publishing

Neither instance pushes anything. GitHub receives one squashed commit per version, published from `stable`; see [Publishing source to GitHub](github-publishing.md).

## Source checkout

Both commands find the repository through `OPENPROGRAM_SOURCE_REPO`, or else through `~/.openprogram/source-repo`, which both refresh scripts write. They record the main checkout, not the build worktree.

## Implementation status

- Implemented: both refresh scripts, the `stable` gate, `openprogram dev status|deploy|open|auth-url|copy-models|promote`, the promotion checks and backup, the development runtime's own macOS identity and login service, per-profile credentials, and in-chat self-update deploying to the development instance.
- Not yet: the development instance is reachable only from this machine.
