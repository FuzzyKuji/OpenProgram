# Environments

An environment is where a conversation's commands and file tools run: this computer (`local`), an SSH host (`ssh`), or a Docker container (`docker`). A channel (WeChat, Telegram, …) is a different axis. It decides where messages are mirrored and never moves the tools. The product page is [Run conversations on another machine](../../../../capabilities/environments.md).

## 1. Registry

The registry lives in `config.json`:

```json
"environments": {
  "default": "local",
  "items": [
    {"id": "devbox", "name": "devbox", "kind": "ssh", "ssh_target": "me@devbox", "workdir": "~/work"},
    {"id": "sandbox", "name": "sandbox", "kind": "docker", "image": "ubuntu:24.04"}
  ]
}
```

- `local` is built in. It is never stored and cannot be changed or removed.
- IDs match `^[a-z0-9][a-z0-9_-]{0,47}$`. `ssh_target` has no whitespace and no leading `-`, which keeps it out of ssh's option parsing. `workdir` is absolute or starts with `~`. An image has no whitespace and no leading `-`.
- An older install that configured `backend.terminal` / `ssh_target` / `docker_image` reads that entry as an environment named after its kind and makes it the default. The first write folds it into the `environments` section.
- Removing the default resets the default to `local`.

The code lives in `openprogram/host/environments/__init__.py`. All writes go through `update_config`, which holds the cross-process config lock. The CLI (`openprogram environments`), the setup wizard step and the WebSocket actions (`list_environments`, `save_environment`, `delete_environment`, `set_default_environment`, `test_environment`) are thin layers over it. Every mutation broadcasts an `environments` frame, so every open composer refreshes its list.

## 2. Conversation binding

A conversation stores `environment_id` in its session meta. That field is indexed, so lists can carry it.

- **Draft**: the composer keeps the pick in its composer settings (`ComposerSettings.environment`). The first `chat` frame carries it as `environment_id`.
- **First message**: `assign_new_session_environment` validates the pick (an unknown ID returns the `unknown_environment` error) and writes it, or the default when nothing was picked. The `chat_ack` reports the ID in force.
- **After that**: the ID never changes. A conversation that already stored an ID keeps it. A conversation that has history but no ID was created before environments existed. It keeps following the default and is not moved by a later pick.
- **Channel conversations** are created with the default environment's ID.

When the stored ID no longer exists, `resolve_for_session` raises `EnvironmentError`. The active backend then becomes `UnavailableBackend`, and every command returns the same explanation. Tools never fall back to this computer: running a conversation's commands on a different machine than the one the user chose is worse than refusing.

## 3. Turn binding

`TurnBindings.bind` resolves the session's environment and binds it to the `_current_environment` ContextVar for the turn. `current_environment()` reads the ContextVar first. Outside a turn it falls back to the current session's environment, then to the default.

- **SSH**: the turn's worktree ContextVar is set to the remote absolute working folder. `remote_workdir` runs `pwd` after `cd`, so `~` resolves on the host; the result is cached per environment. Relative tool paths join it with `posixpath` and never touch the host filesystem. The permission fence uses the same ContextVar, so it is checked against the remote folder.
- **Docker**: the worktree stays on the host, because the container mounts it at the same path.
- **Sandbox**: the host sandbox applies only to `local`. For SSH and Docker the turn binds sandbox policy off; isolation is the remote account or the container.
- The tool runtime block in the system prompt adds an "Environment:" line naming the SSH host or Docker image, so the model knows the commands do not run locally.

## 4. Backends

`openprogram/host/backend/__init__.py` `get_active_backend()` builds the backend from `current_environment()` and the current session:

| Kind | Backend | Command form |
|---|---|---|
| local | `LocalBackend` | subprocess on the host |
| ssh | `SshBackend(target, workdir)` | `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o ControlPath=<state>/ssh/%C -o ControlPersist=300 <target> 'cd <dir> && <cmd>'` |
| docker | `DockerBackend(image, container, mounts)` | `docker exec -i [-w cwd] <container> sh -c <cmd>` |

SSH connection sharing keeps each tool call to one round trip after the first. `%C` hashes host, port and user, so the socket path stays under the macOS `sun_path` limit. ControlMaster is skipped on Windows. A leading `~` in the folder reaches the remote shell unquoted so it expands there.

Each Docker conversation gets one long-lived container, `openprogram-<env>-<session>` (characters outside `[a-zA-Z0-9_.-]` become `-`), started with `docker run -d --init … tail -f /dev/null`. The session's working folder, project folder and additional working directories are bind-mounted at identical paths, so host paths stay valid inside. The first mount is the starting folder. A hash of image plus mounts is stored as the `openprogram.mounts` label. When the hash changes, the container is removed and recreated. When the hash matches, a stopped container is started again. A per-process cache skips the `docker inspect` probe after the first command. Deleting the session removes its containers in a background thread. Without a session ID (outside any conversation) the backend falls back to one-shot `docker run --rm`.

## 5. File tools

`read`, `write`, `edit`, `apply_patch`, `glob`, `grep` and `list` call `remote_target()` first. For an SSH environment it returns a `RemoteFS`, and the tool delegates to `openprogram/programs/tools/files/_remote.py`, whose output matches the local tool's format. Docker and local return `None` and keep the local code path, because Docker's folders are host folders.

`RemoteFS` (`openprogram/host/environments/remote.py`) is a thin layer over `SshBackend.run_bytes`:

- `stat`: one `test` command reports exists / directory / size.
- `read_bytes`: `cat`, capped at 32 MiB.
- `write_bytes`: `mkdir -p`, writes a temporary file in the same folder, then `mv` over the target. A reader never sees a half-written file.
- Exit code 255 is ssh's own failure and becomes `ConnectionError`. The tools report it as an error instead of as file content.

Discovery runs on the host: `glob` lists files with `find` and filters them with a regex translated from the glob. GNU `find -printf` gives mtimes; the BSD `stat` form is the fallback. `grep` uses `rg` when present, else `grep -rE`, capped by `head`. `list` uses a shell loop. PDF reads copy the bytes to a local temporary file and reuse the local PDF reader.

The read-before-edit rule holds remotely. A successful read or write records a sha256 keyed by (session, host, path). `write` (over an existing file), `edit` and `apply_patch` re-read the file and refuse when it was never read or its hash changed.

Remote files are outside the host's turn checkpoints, so revert / undo does not restore them. The local `write` tool's `source_path` option (copy a host file) is refused in SSH, because it would cross machines silently.

## 6. Composer

The environment row above the message box starts with two chips:

- **Environment chip** (always shown): the icon matches the kind (monitor / cpu / box) and the label is the environment name. The icon color is the worker connection tone that the old status chip showed. For a draft, it opens a list of environments plus a link to Settings → Environments, and the pick goes into the draft's composer settings. Once the conversation exists, the menu still opens but greys out the other environments and says the choice is fixed.
- **Channel chip** (always shown): a chat glyph, tinted by the channel health poll (`channelHealth`) once bound; the label is "No channel" or "WeChat · account". It opens the channel menu: accounts grouped under their platform name, the bound one checked, "Disconnect" while bound, and "Manage channels".

The chip is the only place the composer sets the channel; the **+** menu has no Channel entry. The channel menu and the channel chip share `channel-choices.ts`. It follows the composer's own pane (`useBoundChat`), so in a split view each pane reads and changes its own conversation.

The worker connection tone (`statusBadge`) and the channel health (`channelHealth`) are separate store slices, so neither can repaint the other's chip.

## Implementation status

Implemented: local / SSH / Docker; registry, CLI, wizard step, settings page and WebSocket actions; first-message pinning; SSH file tools; per-session Docker containers.

Not implemented:

- Per-project default environments. The default is global.
- WSL and cloud environments.
- Password or interactive SSH sign-in.
- Checkpoint / undo for remote files.
- Moving an existing conversation to another environment.
