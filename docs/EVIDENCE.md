# Evidence base

Every optimization rule in this skill cites sources from this list, and the
citation is machine-checked: `scripts/validate_package.py` fails the build if a
rule cites an id that does not resolve here. That check exists because a tool
that invents its own justification is worse than one with no justification at all.

**42 sources**, collected 2026-07-24. Each was verified against its primary
page (arXiv abstract, DOI, or official provider documentation) — title and first
author confirmed before recording. Nothing here is cited from memory.

For eight of these sources, [RESEARCH-BASIS.md](RESEARCH-BASIS.md) goes further: what the
paper actually found, under what conditions, the consideration drawn from it, and what that
consideration does not license. Start there if you want the reasoning rather than the list.

Read `RULES.md` for what each rule does with this evidence, and
`../skill/references/research-digest.md` for the fuller per-source notes.

## Compression & safety-under-compression

| id | source | type | used by |
|---|---|---|---|
| `S-A01` | [LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Mod…](https://arxiv.org/abs/2310.05736) | peer-reviewed | R-21 |
| `S-A02` | [LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via P…](https://arxiv.org/abs/2310.06839) | peer-reviewed | R-21 |
| `S-A03` | [LLMLingua-2: Data Distillation for Efficient and Faithful Task-Agnostic Prompt…](https://arxiv.org/abs/2403.12968) | peer-reviewed | R-21 |
| `S-A04` | [Learning to Compress Prompts with Gist Tokens](https://arxiv.org/abs/2304.08467) | peer-reviewed | R-22 |  <!-- no-claim -->
| `S-A05` | [500xCompressor: Generalized Prompt Compression for Large Language Models](https://arxiv.org/abs/2408.03094) | peer-reviewed | R-22 |
| `S-A06` | [Prompt Compression for Large Language Models: A Survey](https://arxiv.org/abs/2410.12388) | peer-reviewed | R-21 |
| `S-A07` | [Characterizing Prompt Compression Methods for Long Context Inference](https://arxiv.org/abs/2407.08892) | preprint | R-21 |
| `S-A08` | [Understanding and Improving Information Preservation in Prompt Compression for…](https://arxiv.org/abs/2503.19114) | peer-reviewed | R-21, R-S3 |
| `S-A09` | [When Compression Becomes an Attack Surface: Black-Box Attacks on Prompt-Compre…](https://arxiv.org/abs/2510.22963) | preprint | R-S1 |
| `S-A10` | [Separating Constraint Compliance from Semantic Accuracy: A Novel Benchmark for…](https://arxiv.org/abs/2512.17920) | preprint | R-S1 |

## Long context, pruning & RAG

| id | source | type | used by |
|---|---|---|---|
| `S-B01` | [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172) | peer-reviewed-journal | R-12 |
| `S-B02` | [NoLiMa: Long-Context Evaluation Beyond Literal Matching](https://arxiv.org/abs/2502.05167) | conference-paper | R-12 |
| `S-B03` | [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://www.trychroma.com/research/context-rot) | technical-report | R-08, R-11, R-23 |  <!-- no-claim -->
| `S-B04` | [Context Length Alone Hurts LLM Performance Despite Perfect Retrieval](https://arxiv.org/abs/2510.05381) | conference-paper | R-12 |
| `S-B05` | [LLMs Get Lost In Multi-Turn Conversation](https://arxiv.org/abs/2505.06120) | arxiv-preprint | R-11, R-23 |
| `S-B06` | [Compressing Context to Enhance Inference Efficiency of Large Language Models (…](https://arxiv.org/abs/2310.06201) | conference-paper | _(context only)_ |
| `S-B07` | [LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via P…](https://arxiv.org/abs/2310.06839) | conference-paper | R-12 |
| `S-B08` | [RECOMP: Improving Retrieval-Augmented LMs with Compression and Selective Augme…](https://arxiv.org/abs/2310.04408) | conference-paper | R-08, R-13 |
| `S-B09` | [The Power of Noise: Redefining Retrieval for RAG Systems](https://arxiv.org/abs/2401.14887) | conference-paper | R-08, R-12, R-13 |
| `S-B10` | [Is Semantic Chunking Worth the Computational Cost?](https://arxiv.org/abs/2410.13070) | conference-paper | R-13 |  <!-- no-claim -->

## Caching, routing & provider pricing

| id | source | type | used by |
|---|---|---|---|
| `S-C01` | [Prompt caching (Anthropic official documentation)](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | provider-doc | R-05 |
| `S-C02` | [Pricing (Anthropic official pricing page)](https://platform.claude.com/docs/en/about-claude/pricing) | provider-doc | R-05 |
| `S-C03` | [Prompt caching (OpenAI official documentation — automatic prompt caching)](https://developers.openai.com/api/docs/guides/prompt-caching) | provider-doc | R-05 |
| `S-C04` | [Pricing (OpenAI official API pricing page)](https://developers.openai.com/api/docs/pricing) | provider-doc | R-05 |
| `S-C05` | [FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving …](https://arxiv.org/abs/2305.05176) | paper | R-15 |  <!-- no-claim -->
| `S-C06` | [RouteLLM: Learning to Route LLMs with Preference Data](https://arxiv.org/abs/2406.18665) | paper | R-15 |
| `S-C07` | [Prompt Cache: Modular Attention Reuse for Low-Latency Inference](https://arxiv.org/abs/2311.04934) | paper | R-05 |  <!-- no-claim -->
| `S-C08` | [SGLang: Efficient Execution of Structured Language Model Programs (RadixAttent…](https://arxiv.org/abs/2312.07104) | paper | R-05 |
| `S-C09` | [GPTCache: An Open-Source Semantic Cache for LLM Applications Enabling Faster A…](https://aclanthology.org/2023.nlposs-1.24/) | paper | R-19 |
| `S-C10` | [AutoMix: Automatically Mixing Language Models](https://arxiv.org/abs/2310.12963) | paper | R-15 |

## Output control, agent loops & injection

| id | source | type | used by |
|---|---|---|---|
| `S-D01` | [Concise Thoughts: Impact of Output Length on LLM Reasoning and Cost](https://arxiv.org/abs/2407.19825) | preprint | R-06 |  <!-- no-claim -->
| `S-D02` | [Token-Budget-Aware LLM Reasoning](https://arxiv.org/abs/2412.18547) | preprint | R-06, R-16 |  <!-- no-claim -->
| `S-D03` | [Chain of Draft: Thinking Faster by Writing Less](https://arxiv.org/abs/2502.18600) | preprint | R-06, R-16 |
| `S-D04` | [Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performan…](https://arxiv.org/abs/2408.02442) | preprint | R-18 |
| `S-D05` | [The Danger of Overthinking: Examining the Reasoning-Action Dilemma in Agentic …](https://arxiv.org/abs/2502.08235) | preprint | R-07, R-16 |
| `S-D06` | [An LLM Compiler for Parallel Function Calling](https://arxiv.org/abs/2312.04511) | peer-reviewed | R-17 |
| `S-D07` | [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | engineering-report | R-20 |
| `S-D08` | [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | engineering-report | R-07, R-20, R-S4 |
| `S-D09` | [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | engineering-report | R-01, R-02, R-08, R-10, R-11, R-14, R-20 |
| `S-D10` | [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) | provider-doc | R-01, R-02, R-03, R-04, R-09, R-14 |
| `S-D11` | [Not what you've signed up for: Compromising Real-World LLM-Integrated Applicat…](https://arxiv.org/abs/2302.12173) | preprint | R-S2 |
| `S-D12` | [Design Patterns for Securing LLM Agents against Prompt Injections](https://arxiv.org/abs/2506.08837) | preprint | R-S1, R-S2 |

## How to read a claim in this repository

Numbers carry one of five labels and the labels are enforced, not decorative:

| label | meaning |
|---|---|
| `[measured]` | produced by an identified tool run; must carry a pointer to the data file |
| `[estimated]` | computed via a disclosed approximation (e.g. a tokenizer proxy) |
| `[projected]` | expected from the evidence above, not observed on your target |
| `[cache-dependent]` | realized only on a cache hit — a billing effect, not a token reduction |
| `[behavior-dependent]` | realized only if the assumed path is actually taken |

`scripts/validate_report.py` blocks delivery of any report that states a number
without a label, or claims `[measured]` without pointing at the data.
