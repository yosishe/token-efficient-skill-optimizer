# Research basis — considerations taken, not commandments issued

[EVIDENCE.md](EVIDENCE.md) lists all 42 sources and which rule cites each one. This file answers
the question that list cannot: **what did the paper actually find, in what setting, and what
consideration did we take from it?**

## How to read this

Each entry is written as *"this paper found X under conditions Y, so we took consideration Z."*
None of them is written as *"research proves you should always do Z."* That distinction is the
whole point, and it is why every entry carries a **what this does not license** line.

A few things worth saying plainly before the list:

- **These papers are evidence about mechanisms, not permission slips.** They establish that
  context length degrades retrieval, that near-miss content is harmful, that compressors drop
  entities. They do not establish that any particular edit to *your* skill is a good idea.
- **Numbers reported below are the papers' own**, quoted as their findings. They are not
  measurements of this tool and never carry a `[measured]` label, which in this repository means
  "we ran it and here is the data file." Where one carries `[projected]`, that marks the
  figure as the paper's own result whose transfer to your setting is exactly what is unproven.
- **Where we used part of a paper and refused another part, it says so.** One entry below does
  exactly that.
- **One of the most-used sources is not peer-reviewed**, and is published by a company that sells
  retrieval infrastructure. That is disclosed in its entry rather than left for someone to
  discover.

---

## 1. Length is not free, even when everything fits

**Rules shaped:** R-08, R-11, R-23

**Paper:** Hong, Troynikov & Huber, *Context Rot: How Increasing Input Tokens Impacts LLM
Performance*, Chroma technical report, 2025 — [link](https://www.trychroma.com/research/context-rot) · `S-B03`

**What it found.** 18 models across 4 families (Claude, GPT, Gemini, Qwen) on extended
needle-in-a-haystack tasks varying needle–question similarity, distractor count, and haystack
structure. Performance degrades **non-uniformly** with input length *even on trivially simple
tasks*. Degradation accelerates when the needle and question are semantically dissimilar, and
**even a single distractor** measurably reduces performance. Counter-intuitively, models did
better on *shuffled* haystacks than on logically structured ones.

**The consideration we took.** "It fits in the context window" is not a reason to leave something
there. The relevant question is not whether content fits but whether its presence degrades the
task — which means position and distractor-density matter independently of token count. This is
why the tool reports context structure rather than only a total, and why R-11 keeps critical
content out of mid-context positions.

**What this does not license.** It does not license aggressive deletion. The paper measures
retrieval-style tasks; it says nothing about whether a given instruction in your skill is a
distractor or a load-bearing constraint. Nothing here justifies removing text on length grounds
alone.

**Disclosure.** This is a **vendor-adjacent technical report, not peer-reviewed** — Chroma sells
retrieval infrastructure, and a finding that "more context hurts" is commercially convenient for
them. Methodology, code, and tasks are published, which mitigates the conflict without erasing it.
It is used because the direction replicates across four independent model families, which is
harder to explain by vendor incentive than by mechanism. It is cited by 3 rules.

**A larger disclosure, which this one led to.** An earlier draft of this file called Context Rot
"the single most-cited source in the registry." That was wrong, and checking it surfaced something
more worth knowing: the two most-cited sources are not papers at all. They are
`S-D09` *Effective context engineering for AI agents* (7 rules) and `S-D10` *Equipping agents for
the real world with Agent Skills* (6 rules) — both **Anthropic engineering reports**, classified in
the catalog as `anecdotal` evidence.

So the honest shape of this evidence base is: **the peer-reviewed literature supplies the
mechanisms, and provider engineering documentation supplies the most rule-level guidance.** That is
a real limitation, not a footnote. Provider documentation describes how one vendor's system behaves
and is written by people with an interest in it being adopted. It earns its weight here because
this tool targets that vendor's skill format specifically — but a reader should know that the most
load-bearing sources in the registry are not academic.

## 2. Models commit early and do not recover

**Rules shaped:** R-11, R-23

**Paper:** Laban, Hayashi, Zhou & Neville, *LLMs Get Lost In Multi-Turn Conversation*, arXiv
preprint, 2025 — [link](https://arxiv.org/abs/2505.06120) · `S-B05`

**What it found.** Over 200,000 simulated conversations comparing single-turn versus multi-turn
delivery of *the same* instructions, across six generation tasks. Every model tested performed
significantly worse when the instruction arrived in pieces — an average drop the authors report
at **39%** — and the decomposition attributes it mostly to unreliability rather than lost
aptitude. In the authors' phrasing, when a model takes a wrong turn it does not recover.

**The consideration we took.** A skill that states its instruction completely and up front is
structurally advantaged over one that reveals it progressively through the conversation. This
sharpens what progressive disclosure means here: move *reference material* off the trigger path,
never the *instruction itself*. Splitting an instruction across a read boundary is not the same
operation as moving an example.

**What this does not license.** The study uses LLM-simulated users, not organic conversations, and
it is a preprint. The 39% is an average across tasks with real spread. It supports a design
preference, not a quantitative promise about your workload.

## 3. Near-misses hurt more than junk

**Rules shaped:** R-08, R-12, R-13

**Paper:** Cuconasu et al., *The Power of Noise: Redefining Retrieval for RAG Systems*,
SIGIR 2024 — [link](https://arxiv.org/abs/2401.14887) · `S-B09`

**What it found.** Controlled injection experiments varying the type, count, and position of
documents in a RAG prompt. Documents that are **related but not actually relevant** — precisely
what similarity ranking surfaces first — measurably harm answer accuracy. The authors' broader
conclusion is that retriever "relevance" is not aligned with what helps the generator.

**The consideration we took.** When pruning context, rank removal candidates by *near-miss
similarity*, not by "least relevant." The content most likely to be quietly hurting is the content
that looks most like it belongs. This shaped how R-12 and R-13 order what they propose cutting.

**What we deliberately did not take.** The same paper reports that adding *random* irrelevant
documents can improve accuracy by up to 35%. **No rule builds on this.** A later SIGIR follow-up
("The Powerless Noise: How Experimental Settings Shape the Reported Power of Noise") reports the
effect is setting-dependent, and the mechanism is unexplained. Using half a paper and refusing the
other half is the honest response to a result that has not held up.

**What this does not license.** 2024-era open models on NQ-style QA. The direction is credible and
consistent with entry 1; the magnitude should not be carried into a different setting.

## 4. Compression that scores well can still drop the facts

**Rules shaped:** R-21, R-S3

**Paper:** Łajewska et al., *Understanding and Improving Information Preservation in Prompt
Compression for LLMs*, Findings of EMNLP 2025 — [link](https://arxiv.org/abs/2503.19114) · `S-A08`

**What it found.** A holistic evaluation scoring compression on three axes — downstream task
performance, grounding in the input, and information preservation such as entity retention. Some
state-of-the-art compressors **fail to preserve key details**, capping performance on complex
tasks. Controlling compression granularity recovered up to +23% downstream performance and
**2.7× more entities preserved**.

**The consideration we took.** This is the paper that made R-S3 a safety-tier rule rather than a
quality nicety. A compressed artifact that still passes its task check can have silently lost
specifics — names, identifiers, conditions — and a task-level score will not reveal it. So
compression is gated on *detail retention*, checked separately, not on task performance alone.

**What this does not license.** The recovery result is demonstrated on one soft-prompting method,
and the abstract does not name which compressors fail or by how much per task. It justifies the
existence of a preservation check; it does not tell you the safe compression ratio for your text.

## 5. If you must compress, compress unevenly

**Rules shaped:** R-21

**Paper:** Jiang et al., *LLMLingua: Compressing Prompts for Accelerated Inference of Large
Language Models*, EMNLP 2023 — [link](https://arxiv.org/abs/2310.05736) · `S-A01`

**What it found.** Coarse-to-fine, perplexity-guided token dropping reaches high compression while
maintaining semantic integrity — the authors report up to **20×** — but only when a budget
controller allocates compression **unequally**, protecting instructions and questions while
compressing demonstrations harder.

**The consideration we took.** Uniform compression is the wrong default. Instructions, safety
text, and output contracts are protected classes; examples and demonstrations are where a budget
should be spent first. That asymmetry is built into how R-21 proposes changes, and it is the
reason this tool never applies one ratio across a whole artifact.

**What this does not license.** The 20× figure comes with a compressor LM aligned to the target
model's distribution, evaluated against 2023-era GPT-3.5-class targets, and the abstract does not
quantify the loss at that ratio. It is evidence for *unequal allocation as a principle*, not a
target ratio for anyone to aim at.

## 6. Output budgets work, and a naive cap is the failure mode

**Rules shaped:** R-06, R-16

**Paper:** Han et al., *Token-Budget-Aware LLM Reasoning*, arXiv preprint, 2024–25 —  <!-- no-claim -->
[link](https://arxiv.org/abs/2412.18547) · `S-D02`

**What it found.** Controlled budget-injection experiments. Current LLM reasoning is
"unnecessarily lengthy," and a well-chosen prompt-level token budget compresses it substantially
with only slight performance loss. Critically, **budget choice matters** — too-small budgets break
compression effectiveness rather than degrading gracefully.

**The consideration we took.** Output tokens are the expensive side of most workloads, and an
explicit budget beats vague instructions like "be concise." But the budget has to be adaptive to
task difficulty. A single global cap is not the conservative choice — it is the documented failure
mode, and R-06 is written to avoid exactly that.

**What this does not license.** Preprint, verified at abstract level, with no exact percentages
published there. Optimal budgets are model- and task-specific, and estimating a budget itself costs
tokens.

## 7. Unbounded deliberation is a defect signal

**Rules shaped:** R-07, R-16

**Paper:** Cuadron et al., *The Danger of Overthinking: Examining the Reasoning-Action Dilemma in
Agentic Tasks*, arXiv preprint, 2025 — [link](https://arxiv.org/abs/2502.08235) · `S-D05`

**What it found.** Across 4,018 trajectories, higher "overthinking" scores correlate inversely
with task performance; reasoning models overthink more than non-reasoning models. Selecting the
lower-overthinking solution improved performance by roughly **30%** `[projected]` while cutting
compute cost **43%** `[projected]`.

**The consideration we took.** In an agent loop, a long deliberation trace is a signal that
something is wrong, not evidence of thoroughness. This is why R-07 treats a loop with no
termination condition as a finding — "keep searching until you have found everything" is a defect,
not diligence — and why the tool prefers acting and tool-calling over extended reasoning chains.

**What this does not license.** The score-to-performance link is **correlational**. The 30%/43%
result comes from *post-hoc selection among existing solutions*, not from training or prompting
models to think less — so it does not establish that forcing shorter reasoning produces the same
gain. Single domain (software engineering), and the pattern is strongest in reasoning-tuned models.
It supports adding a stop condition; it does not support cutting reasoning generally.

## 8. Injection resistance has to be structural

**Rules shaped:** R-S1, R-S2

**Paper:** Beurer-Kellner et al., *Design Patterns for Securing LLM Agents against Prompt
Injections*, arXiv preprint, 2025 (Invariant Labs / ETH Zürich / Google / Microsoft and others) —
[link](https://arxiv.org/abs/2506.08837) · `S-D12`

**What it found.** An architectural argument with case studies rather than a benchmark: security
against injection should come from **structural constraints on agent design** — once an agent
ingests untrusted input, its subsequent actions must be restricted — rather than from model-level
filtering. Each pattern trades some generality for resistance that is provable within its threat
model.

**The consideration we took.** This is the most load-bearing consideration in the whole tool,
because this tool's entire job is to *read other people's instruction files*. So: the target
artifact is untrusted data, always. Nothing inside an inspected skill can direct the optimizer's
behavior, request a tool call, or influence what gets reported. Instructions found inside a target
are quoted as findings, never followed. That is a structural rule, not a filter, and it is why
R-S1 and R-S2 sit in the safety tier where no profile can disable them.

**What this does not license.** No benchmark numbers; the contribution is design patterns, and
"provable resistance" holds only within each pattern's stated threat model. The patterns also cost
capability — a constrained agent can do less. We accepted that trade explicitly for this tool
because the alternative is a program that reads adversarial text and can act on it.

---

## What this evidence base cannot do

Stated here because the list above reads more confidently than the underlying evidence warrants:

- **Most of these findings are marked `partial` on cross-model generalization** in the source
  catalog. Directions replicate; magnitudes do not.
- **Four of the eight are preprints**, verified at abstract level against their primary pages.
  Where a claim exists only in a paper's body, this document does not repeat it.
- **One is a vendor-adjacent technical report**, disclosed in entry 1.
- **None of them was run on your skill.** They describe mechanisms in controlled settings. Whether
  a mechanism applies to your artifact is an empirical question about your artifact.

That last point is the reason this tool ships a measurement harness and a frozen evaluation
protocol rather than a table of promised percentages. The research earns a rule the right to be
*considered*. Only a measurement earns it the right to be *applied*.
