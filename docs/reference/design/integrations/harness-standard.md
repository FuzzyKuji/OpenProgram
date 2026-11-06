# Harness Standard — how an agentic program plugs into OpenProgram

> This document is the contract every **harness** (a self-contained agentic
> program shipped as its own repo) satisfies, so that cloning it into
> OpenProgram's `agentics/` folder makes it **auto-detected and usable with
> no host edits**. OpenProgram bundles no harnesses; every harness,
> whoever writes it, follows the same rules.
> Related: [`../installing-programs.md`](../../../capabilities/installing-programs.md)
> (install procedure), `openprogram/programs/_host/registry.py` (the loader),
> `openprogram/programs/_host/sources.py` (the owner-recorded sources).

## 0. The one rule that matters

**A harness is anything installed into `~/.openprogram/programs/`
that exposes its functions through `<pkg>/agentics/__init__.py`.** The host
walks that folder on startup (and, with hot-reload, whenever it changes),
finds the inner package, imports `<pkg>.agentics`, and the
Agent method executions self-register. Nothing else is required and
no host file is edited.

```
<Harness-Repo>/                    ← what you git clone into agentics/
└── <pkg>/                         ← importable package; folder name == import name
    ├── __init__.py                ← marks it a package (may re-export niceties)
    └── agentics/
        └── __init__.py            ← THE ENTRY POINT — exposes PROGRAM_ENTRIES
```

If a cloned folder doesn't match this shape, the host **silently ignores
it** (a non-harness folder must never break the load). So "auto-detect"
== "matches this contract".

## 1. The entry point: `<pkg>/agentics/__init__.py`

Must define `PROGRAM_ENTRIES` — a list of `Agent` method-decorated
callables. Importing this module fires the decorators, which register the
functions into the shared tool registry. The list is also the harness's
declared public surface.

**Required pattern — degrade gracefully, never crash the host:**

```python
# <pkg>/agentics/__init__.py
"""Entry point for the Foo harness."""
try:
    from .foo_agent import foo_agent, foo_helper
    PROGRAM_ENTRIES = [foo_agent, foo_helper]
except Exception:          # missing optional dep, unsupported platform, …
    # The host imports this module during discovery. If the harness can't
    # load on this machine (a heavy dep isn't installed, this OS has no
    # backend, …), expose NOTHING rather than raising — "can run → listed,
    # can't → skipped", per the discovery contract. The host logs the
    # cause under OPENPROGRAM_DEBUG_REGISTRY=1.
    PROGRAM_ENTRIES = []
```

Rules:
- `PROGRAM_ENTRIES` **must always be defined** (even if `[]`).
- The `try/except` is **mandatory** — a harness that can't run on this
  machine must yield `[]`, not propagate an `ImportError`. This is what
  makes "clone anything in, the ones that can run light up, the rest stay
  dark" work.
- Don't do heavy work at import time (no model downloads, no network, no
  GUI grab). Import must be cheap and side-effect-free beyond registration.

## 2. The package: `<pkg>/`

- **Folder name == import name.** `paper_harness/` is imported as
  `paper_harness`. The host puts the harness root on `sys.path` so the
  harness's own absolute imports (`from paper_harness.x import y`) resolve.
  A hyphenated *repo* folder (`Paper-Harness/`) is fine — the host
  finds the inner ascii-identifier package inside it.
- May vendor sibling packages (e.g. a `third_party/` package alongside
  `paper_harness/`). The host picks the **one** package that has
  an `agentics/` sub-package as the entry; vendored siblings are ignored
  by discovery and just ride along on `sys.path`.

## 3. Configuration — the unified convention

Harnesses differ wildly in what they configure (one: providers +
work dir; another: a vault path). The
**standard is the mechanism, not the parameters**:

1. **Per-call parameters first.** Anything that varies per invocation is a
   function argument with a sane default:
   ```python
   from openprogram import Agent

   class HarnessAgent(Agent):
       method_options = {"foo_agent": {"tool": True, "name": "foo_agent"}}

       def foo_agent(self, task: str, max_steps: int = 15) -> dict:
           ...
   ```
2. **The runtime comes from the host, never constructed.** A harness
   method runs on the Runtime of the call that reaches it — the host's —
   and makes model requests with `llm()` / `agent()`; it declares no
   `runtime` parameter. A second model (a reviewer, say) is a second Agent
   instance configured where the run starts. Harnesses **must not** build their own provider /
   read `ANTHROPIC_API_KEY` themselves for the in-host path — provider
   selection and auth belong to the host. (A harness MAY keep a
   standalone CLI that calls `create_runtime(...)` for use outside the
   host; that's separate from the in-host entry point.)
3. **Environment variables for machine-level settings**, namespaced with
   the harness's prefix, documented in the README:
   ```
   WAH_VAULT          # Wiki: vault root
   ```
4. **No config files required to start.** A harness must work with zero
   config (sensible defaults); config is opt-in override, never a setup
   gate. No mandatory wizard / first-run prompt.
5. **State / scratch goes under the host state dir**, not a hand-rolled
   home path. Use `openprogram.state.paths.get_state_dir()` (→ `~/.openprogram/`)
   as the base; **never hardcode `~/.agentic/...`** (that path is retired).
   A per-harness subdir is the convention:
   `get_state_dir() / "harnesses" / "<pkg>"`.

## 4. Dependencies

- **Do NOT declare `openprogram` as a git dependency.** The host is the
  thing importing the harness, so it's already installed. A
  `openprogram @ git+https://...` line in the harness's `pyproject.toml`
  causes `pip install <harness>` to re-fetch and possibly downgrade the
  host. List openprogram only as a documented *assumption* ("install into
  an environment that already has openprogram"), not a hard dep.
- **Declare the harness's own third-party deps** (torch, Jinja2, …) in its
  `pyproject.toml` / `requirements.txt`. Installing those is the
  **harness's** install step (run when the user installs the harness),
  not OpenProgram's concern — the host never auto-installs harness deps.
- **Heavy / native deps go behind an extra** so a light clone stays light:
  ```toml
  [project.optional-dependencies]
  ocr = ["easyocr"]
  ```
- The graceful-degrade `try/except` in §1 is what lets a harness be
  *cloned* before its deps are installed without breaking the host — it
  just stays dark until the deps are present.

## 5. Platform support

- A harness MAY be platform-specific in its own code (a harness that drives
  the desktop has macOS / Linux backends that differ, and Windows may be
  unimplemented). That's allowed.
- **Express "unsupported here" as `PROGRAM_ENTRIES = []`**, via the §1
  `try/except` or an explicit `platform.system()` check — never as an
  uncaught `NotImplementedError` at import. Install/registration always
  succeeds; whether a function is *listed* reflects whether it can run on
  this OS.
- Detect backends at runtime (`shutil.which`, `importlib.util.find_spec`),
  don't assume. Document the per-OS setup in the harness README.

## 6. Discovery & hot-reload (host side — what a harness can rely on)

- **Startup:** the host imports every matching folder under `agentics/`.
- **Hot-reload:** the host watches `agentics/` and, when a new folder
  appears, runs the same discovery on it and broadcasts a
  `programs:changed` event so the web UI lists the new harness without a
  restart. A harness needs to do nothing special — just satisfy §1.
- **No built-in list:** the host names no harness. Every harness is
  installed from a directory, a git URL or GitHub `owner/repo` with
  `openprogram programs install`, and discovery treats them all alike.

## 7. Conformance checklist (for a harness author)

- [ ] Repo clones into `agentics/<Repo-Name>/`; inside is a package
      `<pkg>/` whose folder name equals its import name.
- [ ] `<pkg>/agentics/__init__.py` defines `PROGRAM_ENTRIES = [...]`.
- [ ] That module wraps its imports in `try/except` → `[]` on failure.
- [ ] Import is cheap: no network / model-download / GUI grab at import.
- [ ] LLM access via an injected `runtime` parameter, not self-built.
- [ ] No required config file / wizard; works at zero-config defaults.
- [ ] State under `get_state_dir()`, never `~/.agentic` or another
      hardcoded home path.
- [ ] `openprogram` is NOT a git dependency in `pyproject.toml`.
- [ ] Own third-party deps declared; heavy/native ones behind an extra.
- [ ] Platform-unsupported → `PROGRAM_ENTRIES = []`, not a crash.

## Appendix: Implementation Status

Known harnesses that do not yet fully conform to this standard, and
their remaining gaps:

| Harness | Conformance | Gap to close |
|---|---|---|
| **Wiki** | closest | `agentics/__init__.py`, `PROGRAM_ENTRIES`, and the `try/except` are all present. The default vault path still uses the retired `~/.agentic/memory/wiki` and belongs under `get_state_dir()`. |

It still declares `openprogram @ git+…` as a dependency, which §4
rules out.
