# Evidence base

Every empirical optimization rule in this skill cites sources from this list,
while declared constraint rules remain explicitly non-empirical. Citations are
machine-checked: `scripts/validate_package.py` fails the build if a rule cites
an id that does not resolve here. That check exists because a tool that invents
its own justification is worse than one with no justification at all.

**82 source records**. The original 42-source sweep was collected 2026-07-24;
the nine-source v1.3 extension and 31 round-two publication records were
verified against primary academic pages and official Anthropic documentation
on 2026-07-25. Records distinguish academic evidence from provider contracts
because only official documentation is authoritative for current API and
billing semantics.

All 82 repository source records include a versioned URL or explicitly scoped
living-page snapshot, section locator, verification date, lifecycle state, and
SHA-256 over the exact decompressed response bytes observed during retrieval.
Anthropic's dynamic HTML hashes are point-in-time provenance, not an assertion
that a later refetch will be byte-identical. The historical round-two dossier
was not shipped; those 31 records disclose that gap and bind their primary
publication responses independently.

For eight of these sources, [RESEARCH-BASIS.md](RESEARCH-BASIS.md) goes further: what the
paper actually found, under what conditions, the consideration drawn from it, and what that
consideration does not license. Start there if you want the reasoning rather than the list.

Read `RULES.md` for what each rule does with this evidence, and
`../skill/references/research-digest.md` for the fuller per-source notes.

## Compression & safety-under-compression

| id | source | type | used by |
|---|---|---|---|
| `S-A01` | [LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Mod…](https://arxiv.org/abs/2310.05736) | peer-reviewed | R-21 |
| `S-A02` | [LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via P…](https://arxiv.org/abs/2310.06839) | peer-reviewed | _(context only)_ |
| `S-A03` | [LLMLingua-2: Data Distillation for Efficient and Faithful Task-Agnostic Prompt…](https://arxiv.org/abs/2403.12968) | peer-reviewed | R-21 |
| `S-A04` | [Learning to Compress Prompts with Gist Tokens](https://arxiv.org/abs/2304.08467) | peer-reviewed | R-22 |
| `S-A05` | [500xCompressor: Generalized Prompt Compression for Large Language Models](https://arxiv.org/abs/2408.03094) | peer-reviewed | R-22 |
| `S-A06` | [Prompt Compression for Large Language Models: A Survey](https://arxiv.org/abs/2410.12388) | peer-reviewed | _(context only)_ |
| `S-A07` | [Characterizing Prompt Compression Methods for Long Context Inference](https://arxiv.org/abs/2407.08892) | preprint | R-21 |
| `S-A08` | [Understanding and Improving Information Preservation in Prompt Compression for…](https://arxiv.org/abs/2503.19114) | peer-reviewed | R-21, R-S3 |
| `S-A09` | [When Compression Becomes an Attack Surface: Black-Box Attacks on Prompt-Compre…](https://arxiv.org/abs/2510.22963) | preprint | R-S1 |
| `S-A10` | [Separating Constraint Compliance from Semantic Accuracy: A Novel Benchmark for…](https://arxiv.org/abs/2512.17920) | preprint | R-S1 |
| `S-A11` | [Tokenizer Choice For LLM Training: Negligible or Crucial?](https://aclanthology.org/2024.findings-naacl.247/) | peer-reviewed | R-21 |

## Long context, pruning & RAG

| id | source | type | used by |
|---|---|---|---|
| `S-B01` | [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172) | peer-reviewed-journal | R-12 |
| `S-B02` | [NoLiMa: Long-Context Evaluation Beyond Literal Matching](https://arxiv.org/abs/2502.05167) | conference-paper | R-12 |
| `S-B03` | [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://www.trychroma.com/research/context-rot) | technical-report | R-08 |
| `S-B04` | [Context Length Alone Hurts LLM Performance Despite Perfect Retrieval](https://arxiv.org/abs/2510.05381) | conference-paper | R-12 |
| `S-B05` | [LLMs Get Lost In Multi-Turn Conversation](https://arxiv.org/abs/2505.06120) | arxiv-preprint | R-11, R-23 |
| `S-B06` | [Compressing Context to Enhance Inference Efficiency of Large Language Models (…](https://arxiv.org/abs/2310.06201) | conference-paper | _(context only)_ |
| `S-B07` | [LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via P…](https://arxiv.org/abs/2310.06839) | conference-paper | R-12 |
| `S-B08` | [RECOMP: Improving Retrieval-Augmented LMs with Compression and Selective Augme…](https://arxiv.org/abs/2310.04408) | conference-paper | R-08, R-13 |
| `S-B09` | [The Power of Noise: Redefining Retrieval for RAG Systems](https://arxiv.org/abs/2401.14887) | conference-paper | R-08, R-12, R-13 |
| `S-B10` | [Is Semantic Chunking Worth the Computational Cost?](https://arxiv.org/abs/2410.13070) | conference-paper | R-13 |
| `S-B11` | [LongMemEval](https://arxiv.org/abs/2410.10813) | peer-reviewed | R-11, R-23 |

## Caching, routing & provider pricing

| id | source | type | used by |
|---|---|---|---|
| `S-C01` | [Prompt caching (Anthropic official documentation)](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | provider-doc | R-05, R-32 |
| `S-C02` | [Pricing (Anthropic official pricing page)](https://platform.claude.com/docs/en/about-claude/pricing) | provider-doc | R-05, R-33, R-34 |
| `S-C03` | [Prompt caching (OpenAI official documentation — automatic prompt caching)](https://developers.openai.com/api/docs/guides/prompt-caching) | provider-doc | R-32 |
| `S-C04` | [Pricing (OpenAI official API pricing page)](https://developers.openai.com/api/docs/pricing) | provider-doc | R-34 |
| `S-C05` | [FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving …](https://arxiv.org/abs/2305.05176) | paper | R-15 |
| `S-C06` | [RouteLLM: Learning to Route LLMs with Preference Data](https://arxiv.org/abs/2406.18665) | paper | R-15 |
| `S-C07` | [Prompt Cache: Modular Attention Reuse for Low-Latency Inference](https://arxiv.org/abs/2311.04934) | paper | R-05 |
| `S-C08` | [SGLang: Efficient Execution of Structured Language Model Programs (RadixAttent…](https://arxiv.org/abs/2312.07104) | paper | R-05 |
| `S-C09` | [GPTCache: An Open-Source Semantic Cache for LLM Applications Enabling Faster A…](https://aclanthology.org/2023.nlposs-1.24/) | paper | R-19 |
| `S-C10` | [AutoMix: Automatically Mixing Language Models](https://arxiv.org/abs/2310.12963) | paper | R-15 |
| `S-C11` | [Token counting (Anthropic official documentation)](https://platform.claude.com/docs/en/build-with-claude/token-counting) | provider-doc | _(context only)_ |
| `S-C12` | [Cache diagnostics (Anthropic official documentation)](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics) | provider-doc | R-05 |

## Output control, agent loops & injection

| id | source | type | used by |
|---|---|---|---|
| `S-D01` | [Concise Thoughts: Impact of Output Length on LLM Reasoning and Cost](https://arxiv.org/abs/2407.19825) | preprint | R-06 |
| `S-D02` | [Token-Budget-Aware LLM Reasoning](https://arxiv.org/abs/2412.18547) | preprint | R-06, R-16 |
| `S-D03` | [Chain of Draft: Thinking Faster by Writing Less](https://arxiv.org/abs/2502.18600) | preprint | R-06, R-16 |
| `S-D04` | [Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performan…](https://arxiv.org/abs/2408.02442) | preprint | R-18 |
| `S-D05` | [The Danger of Overthinking: Examining the Reasoning-Action Dilemma in Agentic …](https://arxiv.org/abs/2502.08235) | preprint | R-07, R-16 |
| `S-D06` | [An LLM Compiler for Parallel Function Calling](https://arxiv.org/abs/2312.04511) | peer-reviewed | R-17 |
| `S-D07` | [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | engineering-report | R-20 |
| `S-D08` | [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | engineering-report | R-07, R-20 |
| `S-D09` | [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | engineering-report | R-02, R-08, R-11, R-14, R-20, R-23 |
| `S-D10` | [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) | provider-doc | R-02, R-03, R-04, R-09, R-14 |
| `S-D11` | [Not what you've signed up for: Compromising Real-World LLM-Integrated Applicat…](https://arxiv.org/abs/2302.12173) | preprint | R-S2 |
| `S-D12` | [Design Patterns for Securing LLM Agents against Prompt Injections](https://arxiv.org/abs/2506.08837) | preprint | R-S1, R-S2 |
| `S-D13` | [Context editing (Anthropic official documentation)](https://platform.claude.com/docs/en/build-with-claude/context-editing) | provider-doc | R-11, R-23 |
| `S-D14` | [Compaction (Anthropic official documentation)](https://platform.claude.com/docs/en/build-with-claude/compaction) | provider-doc | R-11 |
| `S-D15` | [Memory tool (Anthropic official documentation)](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) | provider-doc | R-11 |
| `S-D16` | [Agent Skills overview (Anthropic official documentation)](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) | provider-doc | R-03, R-04 |
| `S-D17` | [Skill authoring best practices (Anthropic official documentation)](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) | provider-doc | R-03 |

## Round-two prompt, evaluation, and security research

| id | source | type | used by |
|---|---|---|---|
| `S-R01` | [Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design](https://arxiv.org/abs/2310.11324) | peer-reviewed-conference | R-10, R-24 |
| `S-R02` | [State of What Art? A Call for Multi-Prompt LLM Evaluation](https://aclanthology.org/2024.tacl-1.52/) | peer-reviewed-journal | R-24, R-25 |
| `S-R03` | [The Butterfly Effect of Altering Prompts](https://aclanthology.org/2024.findings-acl.275/) | peer-reviewed-findings | R-24 |
| `S-R04` | [Flaw or Artifact? Rethinking Prompt Sensitivity in Evaluating LLMs](https://arxiv.org/abs/2509.01790) | peer-reviewed-conference | R-25 |
| `S-R05` | [Same Task, More Tokens](https://aclanthology.org/2024.acl-long.818/) | peer-reviewed-conference | R-01 |
| `S-R06` | [Rethinking the Role of Demonstrations](https://aclanthology.org/2022.emnlp-main.759/) | peer-reviewed-conference | R-30 |
| `S-R07` | [What Makes Good In-Context Examples for GPT-3?](https://aclanthology.org/2022.deelio-1.10/) | peer-reviewed-workshop | _(context only)_ |
| `S-R08` | [Many-Shot In-Context Learning](https://arxiv.org/abs/2404.11018) | peer-reviewed-conference | R-30 |
| `S-R09` | [Revisiting Chain-of-Thought Prompting: Zero-shot Can Be Stronger than Few-shot](https://aclanthology.org/2025.findings-emnlp.729/) | peer-reviewed-findings | R-30 |
| `S-R10` | [Towards Compute-Optimal Many-Shot In-Context Learning](https://arxiv.org/abs/2507.16217) | peer-reviewed-conference | R-31 |
| `S-R11` | [Executable Code Actions Elicit Better LLM Agents](https://proceedings.mlr.press/v235/wang24h.html) | peer-reviewed-conference | _(context only)_ |
| `S-R12` | [RedCode: Risky Code Execution and Generation Benchmark for Code Agents](https://arxiv.org/abs/2411.07781) | peer-reviewed-conference | _(context only)_ |
| `S-R13` | [Long-Context LLMs Meet RAG](https://arxiv.org/abs/2410.05983) | peer-reviewed-conference | _(context only)_ |
| `S-R14` | [JSONSchemaBench: A Rigorous Benchmark of Structured Outputs for Language Models](https://arxiv.org/abs/2501.10868) | preprint | _(context only)_ |
| `S-R15` | [Let Me Speak Freely? A Study On The Impact Of Format Restrictions](https://aclanthology.org/2024.emnlp-industry.91/) | peer-reviewed-conference | _(context only)_ |
| `S-R16` | [Learning To Retrieve Prompts for In-Context Learning](https://aclanthology.org/2022.naacl-main.191/) | peer-reviewed-conference | _(context only)_ |
| `S-R17` | [CRANE: Reasoning with constrained LLM generation](https://arxiv.org/abs/2502.09061) | peer-reviewed-conference | _(context only)_ |
| `S-R18` | [Benchmarking Complex Instruction-Following with Multiple Constraints Composition](https://arxiv.org/abs/2407.03978) | peer-reviewed-conference | R-10, R-26, R-27 |
| `S-R19` | [With Little Power Comes Great Responsibility](https://aclanthology.org/2020.emnlp-main.745/) | peer-reviewed-conference | R-28 |
| `S-R20` | [The Hitchhiker's Guide to Testing Statistical Significance in NLP](https://aclanthology.org/P18-1128/) | peer-reviewed-conference | R-28 |
| `S-R21` | [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://proceedings.neurips.cc/paper_files/paper/2023/hash/91f18a1287b398d378ef22505bf41832-Abstract-Datasets_and_Benchmarks.html) | peer-reviewed-conference | R-29 |
| `S-R22` | [Large Language Models are not Fair Evaluators](https://aclanthology.org/2024.acl-long.511/) | peer-reviewed-conference | R-29 |
| `S-R23` | [LLMs instead of Human Judges? A Large Scale Empirical Study across 20 NLP Evaluation Tasks](https://aclanthology.org/2025.acl-short.20/) | peer-reviewed-conference | R-29 |
| `S-R24` | [A Sober Look at Progress in Language Model Reasoning](https://arxiv.org/abs/2504.07086) | peer-reviewed-conference | R-28 |
| `S-R25` | [LLM Evaluators Recognize and Favor Their Own Generations](https://proceedings.neurips.cc/paper_files/paper/2024/hash/7f1f0218e45f5414c79c0679633e47bc-Abstract-Conference.html) | peer-reviewed-conference | R-29 |
| `S-R26` | [On Prompt-Driven Safeguarding for Large Language Models](https://proceedings.mlr.press/v235/zheng24n.html) | peer-reviewed-conference | R-S1 |
| `S-R27` | [The Art of Defending](https://aclanthology.org/2024.findings-acl.776/) | peer-reviewed-findings | R-S1 |
| `S-R28` | [Fine-tuning Aligned Language Models Compromises Safety, Even When Users Do Not Intend To!](https://arxiv.org/abs/2310.03693) | peer-reviewed-conference | R-S1 |
| `S-R29` | [AgentDojo](https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html) | peer-reviewed-conference | R-S2 |
| `S-R30` | [Adaptive Attacks Break Defenses Against Indirect Prompt Injection Attacks on LLM Agents](https://aclanthology.org/2025.findings-naacl.395/) | peer-reviewed-findings | R-S2 |
| `S-R31` | [Formalizing and Benchmarking Prompt Injection Attacks and Defenses](https://www.usenix.org/conference/usenixsecurity24/presentation/liu-yupei) | peer-reviewed-conference | R-S2 |

## How to read a claim in this repository

Numbers carry one of six labels and the labels are enforced, not decorative:

| label | meaning |
|---|---|
| `[measured]` | completed observed usage, bound to a claim-specific `report.json#/claims/<claim-id>` evidence record |
| `[estimated]` | computed via a disclosed approximation (e.g. a tokenizer proxy) |
| `[projected]` | expected from the evidence above, not observed on your target |
| `[cache-dependent]` | realized only on a cache hit — a billing effect, not a token reduction |
| `[behavior-dependent]` | realized only if the assumed path is actually taken |
| `[reported]` | traceable third-party result, bound to a source id rather than target-specific observed usage |

`scripts/validate_report.py` blocks delivery of any report that states a number
without a label, or claims `[measured]` without a valid claim-specific JSON
pointer whose hashes and evidence class satisfy the v2 contract. Version 1.2
ships no live-attestation verifier and therefore rejects every `[measured]`
claim; syntactically valid header flags and hashes do not establish a live run.
