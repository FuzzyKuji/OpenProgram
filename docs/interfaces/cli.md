<span id="cli"></span>
# Use the CLI

Call OpenProgram from scripts or other programs and get one reply per command.

## One-shot

```bash
openprogram --print "Summarize what the python files in this directory do"
```

Sends the prompt, prints the reply, exits. It does not enter the TUI. The conversation is written to the session store and can be revisited or continued later in the Web UI or TUI.

When a worker is running for the profile (the desktop App, `openprogram worker start` or a foreground `openprogram web`), the turn runs on that worker, exactly like a message typed in the Web UI: the agent has the App's built-in browser, the channel bridges and the session's settings, and the turn appears live in the Web UI session it belongs to. If the agent asks a follow-up question, the command prints it on stderr and reads the answer from the terminal; without a terminal (a pipeline, a cron job) the question goes unanswered and the turn continues. Ctrl-C cancels the execution on the worker. An error on the worker prints to stderr and the command exits 1. A worker restart during the turn (a refresh, a promote) does not end it: the command reconnects to the worker that comes back, follows the same turn to its end and prints its reply; if no worker returns within three minutes, or the turn was interrupted meanwhile, the command says so and the Web UI session shows where it stopped.

Without a worker the turn runs in this process with the CLI's own runtime, which has no browser or channels. Set `OPENPROGRAM_PRINT_IN_PROCESS=1` to force the in-process turn even while a worker is running.

Note: `--print` only accepts the string in its argument; it does not read stdin. To put file contents into the prompt, use shell substitution:

```bash
openprogram --print "Review this code: $(cat main.py)"
```

## Resuming a specific session

```bash
openprogram sessions list                 # find the session id
openprogram --resume <session-id> --print "Given last time's conclusion, what is the next step"
```

`--resume` takes effect together with `--print`. For interactive resumption, pick the session with `/resume` inside the TUI instead (the flag is currently ignored when launching the interactive TUI); see [Terminal TUI](tui.md).

## Isolated environments

```bash
openprogram --profile ci --print "..."
```

`--profile <name>` switches config, sessions, and credentials wholesale to `~/.openprogram-<name>/`, keeping script environments from polluting your daily one. It can also be set via the `OPENPROGRAM_PROFILE` environment variable.

## Other scripting entry points

All non-chat subcommands can be scripted directly, most supporting `--json` output, for example:

```bash
openprogram sessions list
openprogram providers list --json
openprogram providers discover --json
openprogram status
openprogram programs run <name> --arg key=value   # run one agentic program
```

See `openprogram -h` for the full command list; each subcommand has its own `-h`.
