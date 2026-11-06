# Evaluation

This layer is intended to support a future paper. This document outlines its evaluation: how to distinguish contributions from published work, which experiments, baselines and metrics to use, and how to release the dataset.

## 1. Reframing the contributions

The original PRL was an **unpublished internal design**. Removing its YAML/14-intent/CapabilityManifest is not a contribution: reviewers cannot verify a comparison they cannot access. PRL therefore becomes design motivation in the appendix, not a baseline. Reframe contributions around three distinctions from published work:

| Contribution | Description | What prior work lacks |
|---|---|---|
| **C1** git-as-truth event sourcing + replay-as-policy-test | Decisions are a pure fold over the event stream; historical replay tests policies offline (`replay.md`) | Claude Code hooks / AgentSpec intercept immediately, without event sourcing or offline replay tests |
| **C2** Framework-enforced interruption budgets + dismiss-triggered circuit-breaker feedback | The framework enforces budgets and circuit breakers, automatically incorporating acceptance feedback (`execution-model.md` §5) | Hooks are open-loop: no post-interception feedback or self-muting |
| **C3** Lazy L2 inference written back as derived events | Infer semantic state on demand and write results into the event stream for deterministic replay (`events-and-state.md` §4) | Other systems lack a mechanism in which inference becomes recorded data that reproduces the result |

**The two channels (synchronous gate / asynchronous observer) are not a contribution.** They follow existing patterns such as K8s admission webhooks versus controllers, or servlet filters versus event listeners; a systems reviewer can immediately reject their novelty. Present them as a **design decision, explicitly compared with admission webhooks**. Their value comes from agent-specific evidence: measured 10ms p99, critical fail-closed incident analysis, and gates applying through subagent bypass. These are evidence, not novelty claims.

## 2. Related work that must be addressed

| Work | Relationship |
|---|---|
| Claude Code hooks `PreToolUse` (allow/ask/deny) | An external observer sees the gate lane as a reimplementation; the gate-only baseline must compare against it |
| AgentSpec (arXiv 2503.18666) and related runtime enforcement | Covers gate semantics; lacks C1/C2 |
| Horvitz 1999 mixed-initiative and interruption-cost literature | Principled predecessors to interruption budgets and acceptance feedback; compare breaker thresholds with expected utility of interruption |
| ProactiveBench (arXiv 2410.12361) | Existing proactive evaluation with annotations of whether events warrant intervention; the paper must use it, extend it, or justify why it does not apply |
| Levels-of-automation literature | Relates to the removed 0–8 ladder; explain why autonomy levels are outside our contribution |

## 3. Experimental design

Two weeks of N=1 personal use is anecdotal, not an experiment. The author both writes policies and serves as the subject, introducing Hawthorne effects and circular reasoning; 20–50 events have no statistical significance. Replace this with:

1. **Large-scale replay:** map public agent trajectories (thousands from SWE-bench / SWE-agent / OpenHands) into the Event schema and replay them. Use **at least two annotators** for would-have-fired decisions; report **precision and Cohen's kappa**.
2. **Recall:** independently annotate should-have-fired examples to estimate recall. A would-have-fired report structurally cannot expose false negatives (`replay.md` §5), so recall requires a separate set.
3. **Human deployment:** n=8–12 developers for 1–2 weeks each instead of N=1 personal use. Derive the required session count for statistical power from the expected event rate.

## 4. Required baselines

| Baseline | Description | Why it matters |
|---|---|---|
| **prompt-only** | Put the three policy intents directly in the system prompt, e.g. “Remind me before completion if tests have not run,” with zero runtime cost | **The most consequential comparison:** if acceptance is similar, the rationale for the runtime layer fails. Establish what runtime interception, state and budgets provide that prompts cannot |
| **no-proactive** | Disable this layer | Lower bound |
| **gate-only** | Retain only the gate lane, approximately a Claude Code hooks reimplementation | Isolate the added contribution of observers and feedback |

Do not use the original full PRL pipeline as a baseline: it was never implemented, and forced comparison would be a straw man.

## 5. Metrics

**Primary metrics measure outcomes**, not accept/dismiss:

- TestGapWatcher: the proportion of triggered modules that **actually gain tests**, and their subsequent actual bug rate.
- UnvalidatedCompletionNudge: the proportion of accepted suggestions that **actually reveal regressions**.

Accept/dismiss mixes confounders: a dismissal may mean incorrect advice, bad timing, prior knowledge or automatic dismissal during focused work. **Treat it as an auxiliary signal.** Provide **sensitivity analysis** for breaker thresholds: muting and missed-intervention curves for N∈{2,3,5}. Explain in related work why a simple counter is used instead of expected utility; lack of calibrated cold-start data is a defensible reason.

## 6. Supporting evaluations addressing our own critique

We criticize PRL for assuming state-inference quality is solved; we cannot simply move that assumption down one layer. Therefore:

- **Evaluate L1/L2 inference separately:** create 100–200 annotated examples each for path-prefix → touched_modules (error-prone in monorepos), claimed_completion and similar tasks; **report accuracy separately**.
- **Decompose error attribution:** when policy precision is poor, distinguish **state errors from decision errors**. Otherwise it is impossible to tell whether `evaluate` logic or state inference is wrong.
- **Ablations required for a systems paper:** remove the breaker; remove dual channels (all synchronous or all asynchronous); remove L2 and retain only L1. Measure precision loss and added latency for each. The additional X seconds of turn latency caused by putting observer checks in the synchronous path directly supports the dual-channel design decision.
- **L2 cost accounting:** dollars and latency for at most two inferences per turn, compared with prompt-only costs.

## 7. Dataset release

Make public-trajectory replay and its annotations a **dataset contribution**: opportunity taxonomy, at least two annotators, fire/no-fire cases and a should-have-fired set. Apply the redaction schema before release (`threat-model.md` §5: events contain secrets/private code, so raw payloads must not be published directly). Release augmented-mode L2 caches and model fingerprints with the dataset, enabling reproduction of the annotation set rather than the inference process (`replay.md` §3).
