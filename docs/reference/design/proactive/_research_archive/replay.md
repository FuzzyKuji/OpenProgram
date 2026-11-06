# Replay as policy testing

## 1. Why replay is a testing framework

A policy's `evaluate(event, state)` is a pure function; `state` is a pure fold of `events.jsonl` (see `events-and-state.md` §4). Both inputs come from the persisted event stream, so **replaying historical events through a policy tests it on real workloads** without mocks or a running agent.

```
openprogram proactive replay --policy TestGapWatcher --sessions <ids|all>
```

Two complementary uses:

- **Engineering**: every new policy **must** be replayed before activation to inspect how often it would have fired in historical sessions and which events it matched. This exposes poor precision offline instead of discovering it only after deployment (the failure pattern associated with Clippy).
- **Paper**: the would-have-fired report supplies samples for manual precision annotation (see `evaluation.md`).

The replay tool should be ready **before** the decision engine: evaluation precedes functionality (`overview.md` §5).

## 2. The determinism problem: a new policy's first historical replay

Replay promises determinism and therefore testability. One case is inherently non-deterministic and must be handled explicitly:

> The L2 inference required by a new policy **never occurred** in the historical session: its `state.inferred` derived event is absent from that session's `events.jsonl` (`events-and-state.md` §4).

Replaying a policy that has already run is deterministic because it reads historical derived events directly. However, a central use case is running a new policy on history for the first time, when L2 does not exist. Provide two explicit modes:

| Mode | Permitted state | Determinism | Purpose |
|---|---|---|---|
| **strict** | L0/L1 and persisted `state.inferred` only | Fully deterministic, bit-for-bit reproducible | Regression testing of L0/L1 policies; reproducible quantitative paper results |
| **augmented** | strict plus **newly computed L2** | See §3 | First evaluation of a new L2-dependent policy, such as UnvalidatedCompletionNudge |

Among the three MVP policies, DangerousCommandGuard and the L1 part of TestGapWatcher use strict mode. UnvalidatedCompletionNudge and TestGapWatcher's completion-signal detection use augmented mode.

## 3. Reproducibility in augmented mode

Computing missing L2 requires calling an LLM and is inherently non-deterministic because of sampling and model-version drift. Constrain this to reproducible evaluation inputs:

- Fix `model + version + temperature=0`.
- **Persist a cache** of the newly computed L2 inferences and publish the `model fingerprint` with the report.
- Reproduction means **reproducing the annotation set**, not repeating the inference process. Others use the published cache and fingerprint to obtain exactly the same L2 values and reproduce reported precision without calling a model that may have changed.
- A **second replay** of the same policy on the same session **is deterministic**, because it reads the cache.

Additional boundary for Prepare policies: replay **stops at would-have-prepared** because the reviewer subagent cannot be rerun deterministically. TestGapWatcher's actual user-visible step — Notify only after prepared confidence exceeds the threshold — **cannot be verified through replay**. Its Notify precision requires online A/B evaluation and must be labeled “Notify precision: online-only” in the report.

## 4. Three replay details that must be correct

**Simulated cooldown feedback**: a new policy has no action history when replaying historical events, so its `cooldown` records, derived from events indicating an action occurred, are empty. Ignoring its own cooldown reports every match, distorting would-have-fired counts and precision. The replay engine must **feed simulated would-fire decisions back as virtual cooldown events**, suppressing subsequent matches as they would be suppressed in production.

**Clock injection**: for temporal logic such as `cooldown_s`, a 15-minute cooldown, or a task-segment budget, replay's “now” must be **the event's `ts`**, not wall-clock time. A policy therefore **must not call `time.time()`**. The framework injects a clock driven by the current event's `ts` into `evaluate`. Computing cooldown for a historical 2024 session using the current time in 2026 would be incorrect.

**Branch-aware folding**: a session is a git DAG that supports rewind and branching, whereas `events.jsonl` is linear. Replay must **reconstruct** the DAG path from the current node to the root using `node_id` and then fold it (`events-and-state.md` §5), rather than following file order. Otherwise, branches discarded by rewind are incorrectly treated as a continuous history, corrupting state and invalidating would-have-fired reports. Exception: interruption budgets such as cooldowns and circuit breakers are declared global across branches.

## 5. A structural limitation for recall

A would-have-fired report lists only where a policy would fire. It **cannot structurally reveal false negatives**: places where it should have fired but did not. Precision can therefore be derived directly from replay, but **recall cannot**. Recall requires a separately annotated should-have-fired sample set, with humans marking historical moments where a notification should have occurred; see `evaluation.md`. The replay report itself makes no recall claim.

## 6. Report output structure

```
replay-report {
  policy: "TestGapWatcher"
  mode: "augmented"                      # strict | augmented
  model_fingerprint: "claude-…@2026-06"  # augmented only
  sessions_scanned: 214
  events_scanned: 51_320
  fired: 38
  per_session: [
    { session_id, node_path: [...],      # DAG path used for folding
      fires: [
        { event_ref, state_snapshot_ref, # Inspect triggering context after redaction; see threat-model.md
          action: "Prepare→Notify",
          cooldown_suppressed: false,    # Whether simulated cooldown suppressed it
          notes: "Notify precision: online-only" }
      ] }
  ]
  invariant_checks: { loop_free: pass, breaker_exempt: pass, ... }   # See invariants.md §5
}
```

Every fire includes `event_ref` and `state_snapshot_ref`, enabling annotators to judge whether it should have fired (precision annotation). The report also executes the four invariants (`invariants.md`) as assertions: replay evaluates policy quality and checks framework invariants.
