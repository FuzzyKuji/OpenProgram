# Installing programs

`openprogram programs install` adds a program package to OpenProgram from a
local directory, a git URL or a GitHub `owner/repo`. Installed programs appear
under **Abilities → Programs → Applications** as a folder named by its
directory, with the Agent entries it registers inside. A release bundles no programs of its
own: every program you use beyond the built-in tools and applications is one
you installed this way.

New clones go to your Programs directory, `~/.openprogram/programs/<name>/`
(`~/.openprogram-<profile>/programs/<name>/` under a named profile).
Checkouts that earlier installers cloned into the source tree
(`openprogram/programs/packages/` or `openprogram/programs/applications/`)
move into the Programs directory the first time the worker starts on a newer
version, keeping their names and their recorded sources.

> **Where the agent reads this:** this file is the canonical procedure.
> When a user asks to install a program the agent doesn't have, follow
> the steps below — they're written to be executed step by step.

## TL;DR

```bash
openprogram programs install https://github.com/<owner>/<repo>   # git URL
openprogram programs install <owner>/<repo>                      # GitHub shorthand
openprogram programs install ~/work/my-program                   # local directory
openprogram programs install file:///path/to/checkout            # local git source

openprogram programs list                          # every Program with its state
openprogram programs install <source> --upgrade    # pull the latest commits
openprogram programs uninstall <name>              # set a clone aside in .removed/

# The running worker picks the clone up; a fresh process loads it at start.
```

These commands need a mutable environment: a source-development checkout or a
CLI/server installation. The packaged desktop runtime is immutable and refuses
`programs install` and `programs uninstall`.

---

# Part 1 — Installing programs

## What a source can be

| Source | What happens |
|---|---|
| A git URL (`https://`, `ssh://`, `git@`, `file://`) | Shallow-cloned into `~/.openprogram/programs/<name>/`, then inspected (below). |
| GitHub `owner/repo` | Expanded to `https://github.com/owner/repo` and cloned the same way. |
| A local application directory (`application.json`) | Recorded in the catalog and loaded from where it is; nothing is copied. |
| A local package repository (`__init__.py` and `.git`) | Cloned into the Programs directory like a git URL. Commit it first; a directory that is not a Git repository is refused. |
| A package already in `~/.openprogram/programs/` | Nothing to install; `openprogram programs check <directory>` makes it callable. |

## What the clone becomes

After cloning, OpenProgram inspects the checkout and records it by what it
holds. A repository can hold more than one of these.

1. **Package** — an `__init__.py` at the clone's root. The clone is named
   after the repository as a valid import name (`My-Tools` → `my_tools`). It
   loads as one of your packages while its checkout is clean and committed;
   see [Workflow automation](workflows/README.md#self-programming-workflows) for `PROGRAM_ENTRIES` and
   `openprogram programs check`.
2. **Application** — an `application.json` in the clone. The application is
   recorded in the catalog (see [Applications](applications.md)). `--trust`
   authorizes a reviewed Python backend to run, and `--replace` accepts a
   changed digest for one already recorded.
3. **Harness** — a `<package>/agentics/__init__.py` inside the clone (see
   Part 2). OpenProgram installs the harness's own declared dependencies from
   its `pyproject.toml`/`setup.py` (preferred) or `requirements.txt`, then
   records the directory as an owner-approved source. On the next scan the
   registry imports only recorded `<package>.agentics` packages, and their
   `PROGRAM_ENTRIES` appear in chat, on the Programs page and in
   `openprogram programs run`.

A clone that is none of these is reported, and nothing loads from it; it
never breaks the load of other programs.

Guard rails: for an existing **dev symlink** of the same name, `install`
verifies the harness contract and records the link without modifying its
target. It refuses a same-named directory that is not a git clone.
`uninstall` on a symlink moves only the link into `.removed/`, never the
checkout it points to.

## Upgrade and uninstall

```bash
openprogram programs install <source> --upgrade   # git pull --ff-only, re-resolve deps
openprogram programs uninstall <name>             # a directory name or an application id
```

`uninstall` with a directory name moves the clone out of
`~/.openprogram/programs/` into `~/.openprogram/programs/.removed/`, where it
can be restored by hand; it is never deleted. With an application id it
unregisters the application and keeps its data, so a compatible reinstall
restores it.

<details>
<summary>Manual equivalent (mirror / no GitHub access)</summary>

```bash
git clone <repo-url> /path/to/Program-Name
openprogram programs install file:///path/to/Program-Name
```

The install command clones the source into the Programs directory and
records it; auto-discovery loads only recorded directories that satisfy the
contract.

</details>

## Developer setup (work on a program you're writing)

Install from your working checkout, then add it as a remote of the clone:

```bash
openprogram programs install file:///path/to/your/Program-Checkout
cd ~/.openprogram/programs/Program-Checkout && git remote add work /path/to/your/Program-Checkout
```

The install is a clone of your checkout; pull your commits into it
(`git pull work main`) and they take effect on the next restart.

## Verify an install

```bash
openprogram programs list          # every Program, harnesses included, with its state
openprogram programs list --json   # the same rows as JSON
```

To see why a present-but-broken harness didn't load:

```bash
OPENPROGRAM_DEBUG_REGISTRY=1 openprogram programs list
```
(Windows PowerShell: `$env:OPENPROGRAM_DEBUG_REGISTRY=1; openprogram programs list`)

Then use it — the program's functions are callable like any built-in
(in chat, or `openprogram programs run <fn> -a key=value`).

## Platform notes

- **Supported CLI/server release hosts are macOS, Linux, and Windows x86_64/arm64.**
  Windows Desktop is supported on both architectures. Sandboxed command
  execution on Windows uses optional WSL2 plus bubblewrap.
- **These Program commands require a mutable environment.** They work in a
  source-development checkout and may be used by a CLI release only when its
  release notes explicitly support Program mutation. Packaged desktop builds
  refuse the mutation commands until Programs have isolated external
  environments.
- **No symlinks are required** in a supported mutable environment: the
  installer records a real checkout in the Programs directory.
- **A program can still be platform-specific in its own code** (e.g. a
  desktop-automation harness may only implement macOS / Linux backends).
  Whether installation and every function run on a supported host depends on
  the program's declared dependencies and platform support; check its README.
- **Encoding / paths:** OpenProgram's own tooling is UTF-8 and
  `os.path`-based throughout; a well-behaved program should be too.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Harness functions don't appear after restart | Folder doesn't match the contract — confirm `<pkg>/agentics/__init__.py` exists and exports `PROGRAM_ENTRIES`. Run with `OPENPROGRAM_DEBUG_REGISTRY=1`. |
| `[!] … neither a package (__init__.py), an application (application.json) nor a harness` at install | The repository holds none of the three shapes, so nothing loads from it. |
| `ModuleNotFoundError` for the harness's own deps | Installing its declared dependencies failed — rerun `openprogram programs install <source> --upgrade` and inspect its error. |
| Imports inside the harness fail (`from <pkg>.x import y`) | The package dir isn't named like the import root, or a missing `__init__.py`. The package folder name must equal the import name. |
| An existing dev symlink does not load | Run `openprogram programs install <git-source>` once to verify and record it; the installer does not modify the linked checkout. |
| A program fails to install or run on Windows | Check the program's README and dependency markers. The OpenProgram CLI/server is supported, but an individual program may still provide only macOS/Linux backends. |

---

# Part 2 — Writing your own installable harness

Any repo that satisfies one layout contract becomes a one-command
install for every OpenProgram user.

## The contract

```
<Harness-Name>/                      ← the repo (any name)
├── pyproject.toml                   ← declares the harness's OWN deps only
└── <package>/                       ← an importable package (ascii name)
    ├── __init__.py                  ← kept dependency-light
    └── agentics/
        └── __init__.py              ← exposes PROGRAM_ENTRIES = [...]
```

The registration entry point is the **`agentics` sub-package** — at
startup OpenProgram imports `<package>.agentics` and registers the
callables its `PROGRAM_ENTRIES` lists. The harness root may also vendor
other packages — discovery finds the one with an `agentics/` sub-package
and puts the harness root on `sys.path`, so the harness's own absolute
imports (`from <package>.foo import bar`) resolve.

## Minimal working template

```python
# <package>/agentics/__init__.py
from openprogram import Agent


class ExampleAgent(Agent):
    method_options = {
        'my_tool': {'tool': True},
    }

    def my_tool(self, text: str = "") -> str:
        "One line: what this does (shown in catalogs)."
        return text.upper()


_example_agent = ExampleAgent()
my_tool = _example_agent.my_tool

PROGRAM_ENTRIES = [my_tool]
```

```python
# <package>/__init__.py
"""My harness — keep this import-light (see hard rule 2)."""
```

```toml
# pyproject.toml
[project]
name = "my-harness"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []          # the harness's own deps — NEVER openprogram
```

That's a complete installable harness.

## Two hard rules

1. **Never declare `openprogram` as a dependency** (in `pyproject.toml`
   *or* `requirements.txt`). The harness runs inside an existing
   OpenProgram install; a declared `openprogram @ git+…` would make pip
   re-install the host from git, clobbering the user's local (often
   editable) install.
2. **Keep the top-level `<package>/__init__.py` dependency-light, and
   guard heavy imports in `agentics/__init__.py`.** Discovery imports
   `<package>.agentics` on every startup, including on machines that
   haven't installed your optional/heavy deps — a top-level import of
   cv2/torch/etc. would break the whole registry load. Lazy-import heavy
   modules inside function bodies, and guard the entry import:

   ```python
   # agentics/__init__.py — deps-less machines must not break the load
   try:
       from my_package.main import my_tool
       PROGRAM_ENTRIES = [my_tool]
   except ImportError:
       PROGRAM_ENTRIES = []
   ```

## Test locally before publishing

The install command accepts a `file://` source, so the full user flow is
testable against your local checkout:

```bash
cd /path/to/My-Harness && git add -A && git commit -m wip
openprogram programs install file:///path/to/My-Harness
openprogram programs list             # should list My-Harness under Harnesses
OPENPROGRAM_DEBUG_REGISTRY=1 openprogram programs list   # functions present?
openprogram programs run my_tool -a text=hello           # smoke test
openprogram programs uninstall My-Harness                # set it aside
```

Checklist before you publish:

- [ ] `<package>/agentics/__init__.py` exposes `PROGRAM_ENTRIES`
- [ ] no `openprogram` in pyproject/requirements (hard rule 1)
- [ ] `python -c "import <package>.agentics"` succeeds in a bare venv
      with only OpenProgram installed (hard rule 2)
- [ ] `file://` install round-trip above passes

## Publish

Push to GitHub. Users install with:

```bash
openprogram programs install <owner>/<Harness-Name>
```

Nothing to register anywhere — the repo URL *is* the distribution.
