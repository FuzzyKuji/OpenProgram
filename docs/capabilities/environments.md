# Run conversations on another machine

An environment is where a conversation runs its commands and reads and writes files. OpenProgram has three kinds:

| Kind | Commands run | Files are read and written |
| --- | --- | --- |
| Local | On this computer | On this computer |
| SSH | On the remote host, starting in its remote folder | On the remote host |
| Docker | In a container for this conversation | On this computer; the conversation's folders are mounted into the container at the same paths |

Local always exists. You add SSH hosts and Docker containers yourself.

An environment is not a channel. A [channel](../integrations/channels.md) decides where a conversation's messages are mirrored, such as a WeChat or Telegram account. Binding a channel never moves where the tools run.

## Pick an environment for a new chat

The first chip above the message box shows the environment. In a new chat, click it and choose one. The choice is pinned when you send the first message. After that the chip shows the environment but cannot change it. To work somewhere else, start a new chat.

New chats start in the default environment. Conversations created before environments existed also use the default.

The chip's icon color shows the connection to the worker. Yellow means connecting or paused. Red means disconnected.

## Add an environment

In Web or the App, open **Settings → Environments**:

- **SSH host**: enter an ID, the host (`user@host` or a host name from `~/.ssh/config`), and optionally a remote folder. Leave the folder blank to start in the remote home directory.
- **Docker container**: enter an ID and an image. The default image is `ubuntu:24.04`.

On the same page you can also **Test** an environment, **Make default**, or **Remove** it.

From the terminal:

```bash
openprogram environments add ssh devbox --target me@devbox --workdir ~/work
```

```bash
openprogram environments add docker sandbox --image python:3.12 --default
```

```bash
openprogram environments list
```

```bash
openprogram environments test devbox
```

`openprogram environments default <id>` sets the default and `openprogram environments rm <id>` removes an entry. `openprogram setup` also has a **Default environment** step.

## SSH requirements

OpenProgram runs the system `ssh` with `BatchMode=yes`, so sign-in must not ask for anything. Use a key that your SSH agent or `~/.ssh/config` already provides. A new host key is accepted the first time and checked after that. Connections are shared for five minutes to keep tool calls fast.

The remote host needs a POSIX shell, `find`, and `grep`; `rg` is used when it is installed.

## Docker requirements

The `docker` command must be on the PATH and the Docker daemon running. Each conversation gets its own long-lived container named `openprogram-<environment>-<conversation>`. The first command starts it, and later commands reuse it, so installed packages persist for that conversation. If the conversation's folders change, the container is recreated. Deleting the conversation removes the container.

## Limits

- Files changed on an SSH host are not covered by a turn's undo. Undo still restores files on this computer.
- In SSH, a file must be read before it is edited. If it changed on the host since the last read, the edit is refused until it is read again.
- The local sandbox applies only to Local. SSH and Docker run with the permissions of the remote account or the container.
- If a conversation's environment is removed, its tools stop with an error. They never fall back to this computer. Add the environment back with the same ID, or start a new chat.
