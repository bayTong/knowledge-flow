[English](README.md) · [中文文档](README-zh.md)

# KnowledgeFlow

<!-- knowledgeflow-doc-status tests=305 capture_tests=290 script_tests=15 next_gate=P0B -->

> A general-purpose, adaptive, governance-first personal knowledge-work system: start from
> material, a question, or a vague intent; let the system do most knowledge labor while evidence,
> trust layers, and reversible approval control high-impact changes.

> **Current status (2026-09-29):** the project is migrating from the legacy direct-initialization/curated-write workflow to a governed flow: local durable capture → human routing → proposal → exact approval → reversible write. R1.2/R1.3 clarify that users may start from material, a question, a research topic, an existing KB, or a vague intent; tasks over existing knowledge reuse source identities, `capture-only` does not authorize deep semantic processing, and the three Processing Profiles remain Draft candidates. These changes do not alter Capture v1. The single-machine, single-user MVP-0 text capture kernel has completed C0–C8: 41 directed local acceptance tests and two complete 305-test runs passed; evidence commit `63f3a3d` was pushed and its [exact-commit Windows CI](https://github.com/bayTong/knowledge-flow/actions/runs/36544619016) passed. That limited scope is `Implemented`; the overall project is not `Effective` or production-ready. The [P0 production initialization and minimal inbox dogfood plan](docs/p0-production-dogfood-plan-P0生产初始化与最小收件箱试用方案.md) has completed P0A.1 review and is now `Approved Design`, with the primary journey, minimal P0B scope, privacy/deletion disclosure, pending-state mapping, client idempotency, and separate exact P0D authorization fixed. The next gate is separate authorization for P0B-min; approving the plan did not authorize P0B–P0V, production initialization, or interface implementation. No production configuration or Store was created; Processing Profile defaults, the Source Ledger physical contract, and retrieval remain Draft. See the [`C8 acceptance report`](docs/mvp-0-capture-c8-acceptance-report-C8总验收报告.md) and [`design authority and conflict register`](docs/design-authority-and-conflict-register-设计权威与冲突登记.md). Legacy SOP-002 and its write prompt are suspended.

| Looking for | Jump to |
|------------|---------|
| The core problem this project solves | [The Curation Paradox](#the-curation-paradox) |
| Full pipeline walkthrough | [The Pipeline](#the-pipeline) |
| Why it's designed this way — hard constraints, two-stage, three-layer defense | [Key Design Decisions](#key-design-decisions) |
| What files are in this repo | [Project Structure](#project-structure) |
| How to get started | [Quick Start](#quick-start) |
| Real-world usage data | [In Practice](#in-practice) |
| Design philosophy | [Philosophy](#philosophy) |
| Documentation hub and numbered reading order | [`docs/README.md`](docs/README.md) |
| Master product requirements document (sole L0 PRD) | [`docs/requirements-and-governance-baseline-需求与治理基线.md`](docs/requirements-and-governance-baseline-需求与治理基线.md) |
| Current design authority and conflicts | [`docs/design-authority-and-conflict-register-设计权威与冲突登记.md`](docs/design-authority-and-conflict-register-设计权威与冲突登记.md) |
| Cross-topic conceptual architecture guide | [`docs/knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md`](docs/knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md) |
| Current MVP-0 coding execution plan | [`docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md`](docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) |
| C8 local final acceptance report | [`docs/mvp-0-capture-c8-acceptance-report-C8总验收报告.md`](docs/mvp-0-capture-c8-acceptance-report-C8总验收报告.md) |
| P0 production initialization and minimal inbox dogfood plan | [`docs/p0-production-dogfood-plan-P0生产初始化与最小收件箱试用方案.md`](docs/p0-production-dogfood-plan-P0生产初始化与最小收件箱试用方案.md) |
| Version and stage changelog | [`CHANGELOG.md`](CHANGELOG.md) |

---

## The Curation Paradox

Two premises, each reasonable on its own, but together they form a paradox:

**Premise 1**: High-quality knowledge curation demands domain judgment. You need to distinguish core concepts from minor details, recognize when two different-sounding ideas refer to the same thing, identify which entities in a source are worth extracting as domain-relevant versus peripheral or low-relevance, and determine which pieces of knowledge should be linked — and how. These judgments can only be made by someone who actually understands the domain.

**Premise 2**: People adopt knowledge management tools precisely because they don't yet know the domain. The goal is to learn faster, more intuitively, and more easily from unfamiliar material — building structured knowledge or enabling a range of interactive capabilities. This process depends heavily on AI for analysis and reasoning.

The paradox: **the responsibility for curation lies with the human (only you know your goals and context), yet the human lacks the domain knowledge required to curate; meanwhile, the entity with knowledge-processing capability (the LLM) lacks the context to judge what matters to you, and its risks — extraction omissions, hallucinations — cannot be ignored.** Two independently valid premises point to a contradiction — who should curate?

Most AI knowledge tools resolve this by **ignoring Premise 2** — they let the LLM curate directly. The LLM reads the source, decides what's worth a page, writes summaries, assigns tags, builds links. This is fast and frictionless, but it has an unfixable defect: **LLM omissions are far harder to repair than LLM noise.** If the LLM over-extracts (noise), you delete the extra pages in seconds. If the LLM misses a critical concept, you never know it was skipped — because there's no curation map, no intermediate artifact between the raw source and the finished wiki. The reasoning is entirely inside the LLM's black box.

KnowledgeFlow takes a different position — **redistribute responsibility and make the limits explicit, rather than assume semantic completeness**:

- **The system performs most knowledge labor** — it may assist research, summarize, cluster, discover entities and relationships, organize evidence, compare structures, and prepare exact diffs; formal candidates stay source-bound, uncertainty is explicit, and suggestions remain isolated from facts
- **You control intent and high-impact judgment** — low-risk mechanical work may run automatically; reversible derived results may be generated within the current task or a visible, scoped, revocable rule; ordinary trusted changes may be reviewed as bounded batches, and high-impact scope or structure changes require exact approval; a ledger keeps processed, deferred, and failed boundaries visible
- **A restricted writer performs the target-state write** — the replacement SOP-002 will process only precisely approved changes under SCHEMA, transaction, and rollback constraints. It has not been redesigned yet; the legacy write prompt must not be run

The trusted-promotion pipeline aims to **reduce manual work while preserving auditability, evidence binding, and controlled promotion**. The system does not promise one-pass semantic zero omission; it promises preserved sources, visible processing state, traceable candidates, and approved objects before trusted writes. Q&A, learning, or temporary research may remain clearly labeled derived/candidate output instead of being forced into a wiki.

---

## The Core Problem

Following from the paradox above, the specific failures of existing tools can be precisely located:

**The issue is not only LLM capability — it is a mismatch between role and verification boundary.** LLMs are useful for large-scale candidate generation, structured extraction, and evidence organization, but can still omit, compress, or misread long material. Putting them directly in the trusted curator's seat amplifies two failure modes:

- **Omissions**: The LLM decides a concept isn't important enough and skips it. Without reading the original source, you'll never know what was left out
- **Over-simplification**: The LLM produces a wiki page that reads well, but you can't tell whether it represents everything the source contained or just the subset the LLM chose to include. You lose a sense of control — the output looks reasonable, but you have no measure of the gap between source and product

KnowledgeFlow's design goal is therefore not "a better curation algorithm" or a zero-omission promise — it's **pulling trusted judgment back to the human side, reducing silent omission through deterministic segmentation, processing ledgers, evidence binding, and layered paths, then measuring semantic recall with gold-set experiments.**

---

## The Pipeline

This diagram describes promotion from source material into trusted knowledge; it is not mandatory for every knowledge task. Unrouted capture, question-first work, and research exploration may produce useful derived/candidate results before any target KB exists.

```
Raw Source
    │
    ▼
┌──────────────────────────────────┐
│  Phase 1: Profile-based processing │
│                                    │
│  · Captures raw material + SHA256 │
│  · Deterministic segmentation +   │
│    Source Ledger                  │
│  · `full-map` / `hierarchical-map`│
│    / `retrieval-first`            │
│  · Summaries, candidates, and     │
│    Evidence Bundles               │
│  · Zero wiki pages created        │  ← Hard constraint
│                                    │
│  Output: Ledger, overview/map,    │
│  Evidence Bundles, and candidates │
└──────────────────┬───────────────┘
                   │
                   ▼
         ═══ RISK-TIERED REVIEW ═══
         · Batch: approve / edit / return / defer
         · Precisely approve high-impact scope or structure changes
         · Request more sources or adjust organization proposals
                   │
                   ▼
┌──────────────────────────────────┐
│  Phase 2: Trusted write           │
│  (replacement SOP-002; not built) │
│                                    │
│  · Only processes human-confirmed │
│    entries from the curation map  │
│  · Deduplication against existing │
│    wiki pages (full-text search)  │
│  · Decision tree: create / append │
│    / mark contradiction / skip    │
│  · Writes wiki pages constrained  │
│    by SCHEMA + 8 universal rules  │
│  · Self-verification (8 checks)   │
│                                    │
│  Output: wiki pages + updated     │
│  index + log + change report      │
└──────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Hard Constraints, Not Guidelines

The rough reader operates under 7 hard constraints (C1–C7), five of which are prohibitions marked ☒:

| Constraint | Type | Why |
|------|:---:|------|
| C1: Never create wiki pages | ☒ | The rough reader produces curation maps, not finished artifacts |
| C2: Every extraction must cite its source location | ☒ | Traceability = verifiability = correctability |
| C3: Uncertainty must be explicitly marked | ☒ | The core value of the rough reader over direct curation |
| C4: Agent suggestions must be structurally separated from facts | ☒ | Prevents suggestion contamination of the factual layer |
| C5: Never silently discard; defer or layer only with an explicit state | ☒ | Processing gaps must not look complete |
| C6: Deterministically segment long sources and keep a processing ledger | ☑ | Make processed, deferred, and failed boundaries visible |
| C7: Implicit relationships can be extracted but must be flagged as "speculative" + confidence ≤ medium | ☑ | Speculation must never masquerade as certainty |

The mechanically auditable guarantees are preservation, segmentation, status, and evidence binding. Semantic recall still requires gold-set comparison and controlled experiments; item counts or coverage reports alone cannot prove it.

### 2. Trusted Promotion with a Risk-Tiered Audit Surface

Derived processing and trusted writing are **separate stages** with a review checkpoint proportionate to risk. A curation map, Evidence Bundle, or exact diff can be the audit surface. The system first performs bulk reading, evidence binding, and change preparation; the user then reviews a bounded batch or the high-impact differences instead of manually curating every item.

This separation mitigates the curation paradox: even without prior domain knowledge, the user can first receive sourced explanations and candidate structures. Only when results are about to change trusted knowledge does the flow pause for review of key evidence and impact; the user may continue researching, return the whole batch, or defer it without designing the complete structure up front.

### 3. Three-Layer Defense System

| Layer | SOP | Scope | Trigger |
|------|-----|------|------|
| Target-state increment check | Replacement SOP-002 (pending redesign) | Format and transaction correctness of approved changes | Every trusted write |
| Cumulative scan | SOP-003 full lint (9 items) | Structural health of entire KB | Weekly or manual |
| Ripple-effect check | SOP-004 SCHEMA consistency | Impact of SCHEMA changes on all pages | After any SCHEMA modification |

The layers don't overlap — each checks what the others don't, and they form a safety net where missed errors at one layer are caught at the next.

---

## Project Structure

```
knowledge-flow/
├── README.md                         English README
├── README-zh.md                      Chinese README（中文文档）
├── CHANGELOG.md                      Version history
├── LICENSE                           MIT
├── pyproject.toml                    Capture-kernel package and pinned runtime dependency
├── src/
│   └── knowledgeflow_capture/
│       ├── __init__.py               C0/C3/C4C package identity and public capture/read surface
│       ├── errors.py                 C1/C3A/C4A public errors and write/read results
│       ├── models.py                 C1/C3A/C4A hash and write/read request values
│       ├── ids.py                    C1 UUIDv7 and typed prefixes
│       ├── hashing.py                C1/C3A four-hash and idempotency-digest primitives
│       ├── codec.py                  C1/C3A/C4A restricted YAML and Envelope/Event/Projection schemas
│       ├── config.py                 C2A local-config contract and canonical emission
│       ├── paths.py                  C2A Windows path-safety policy
│       ├── manifest.py               C2A Capture Store identity contract
│       ├── locking.py                C2B/C3B Windows initialization and Store write locks
│       ├── durability.py             C2B/C3B durable commit and bounded UTF-8 streaming
│       ├── store.py                  C2B–C6B recovery, staging, and version-chain primitives
│       ├── operations.py             C3–C6C four governed text operations and migration binding checks
│       ├── cli.py                    C7A/C7B restricted CLI framing, spools, production dispatch, and entry
│       ├── recovery.py               C6B explicit derived-state rebuild operation
│       └── migration.py              C6C explicit copy-verify-switch Store migration
├── tests/
│   ├── capture/
│   │   ├── fixtures/                 Ten C1–C4A JSON/YAML/body golden files
│   │   ├── unit/                     C0–C7V unit and platform tests
│   │   ├── integration/              C2B–C7V transaction, read, CLI, rebuild, migration, boundary, and concurrency tests
│   │   └── fault/                    C2B/C6A process-crash recovery tests (290 capture tests total)
│   └── scripts/
│       ├── test_doc_check.py          8 deterministic document-guard regressions
│       └── test_maintenance_scripts.py  7 maintenance-script regressions
├── docs/
│   ├── README.md                    Sole documentation hub and numbered reading order
│   ├── requirements-and-governance-baseline-需求与治理基线.md      Master product requirements document (sole L0 PRD)
│   ├── design-authority-and-conflict-register-设计权威与冲突登记.md  Current topic authority and conflict rulings
│   ├── knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md  Non-normative cross-topic concept map
│   ├── mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md       Completed C0–C8 batches and authorization record
│   ├── mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md  Implemented choices and test matrix
│   ├── mvp-0-capture-c8-acceptance-report-C8总验收报告.md          C8 local evidence, limits, and status recommendation
│   ├── p0-production-dogfood-plan-P0生产初始化与最小收件箱试用方案.md  Approved P0 plan and staged authorization boundaries
│   ├── c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md      Completed C3 decisions pending D2 archive review
│   ├── capture-and-routing-spec-捕获与路由规范.md                  Capture and manual-routing design
│   ├── capture-envelope-v1-捕获信封数据契约与原子保存事务.md      Capture identity and transaction contract
│   ├── mvp-0-capture-operations-本地文本捕获操作契约.md           Four text-operation contract
│   ├── sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md   Provisional KB design
│   ├── progressive-knowledge-refinement-spec-渐进式知识提炼规范.md  Approved governance red lines + Draft methods
│   └── research/
│       └── README.md                Non-authoritative research-input index
├── prompts/                          LLM-agnostic prompt templates（提示词模板）
│   ├── README.md                    Template usage guide
│   ├── sop-001-modeA.md             Default: single-pass extraction (sections 1-9)
│   ├── sop-001-modeA-auditor.md     Default: independent coverage auditor (section 10)
│   ├── sop-001-modeA-fast.md        Optional fast path (self-check coverage)
│   ├── sop-001-modeB-pass1-entities-claims.md  Mode B Pass 1: entities + claims
│   ├── sop-001-modeBC-pass2-relationships.md   Shared B/C: relationships
│   ├── sop-001-modeBC-assembler.md             Shared B/C: assembler + coverage report
│   ├── sop-001-modeC-pass1-entities.md         Mode C Pass 1: entities only
│   ├── sop-001-modeC-pass3-claims.md           Mode C Pass 3: claims only
│   ├── sop-002-curator.md           Legacy SOP-002 write prompt (suspended)
│   ├── sop-003-lint.md              SOP-003 health scan
│   └── extraction-interface.md      Extraction interface + coverage report spec
├── scripts/                          Reference implementation (Python, zero deps)
│   ├── README.md                    Usage, Windows notes, SOP-003 mapping
│   ├── doc-check.py                 Git-aware deterministic document guard
│   ├── lint.py                      SOP-003 lint scanner
│   ├── link-validator.py            Wikilink validator
│   └── index-generator.py           index.md generator
├── templates/
│   └── SCHEMA-template.md           Reusable knowledge base constitution template
├── examples/
│   ├── curation-map-example.md      Historical 25K-line curation-map example (raw source absent)
│   └── wiki-page-example.md         Resulting wiki page after curation
└── archive/
    ├── 2026-design-history/
    │   └── README.md                  Index for nine archived plans, vision, and SOP files
    └── v1.0/
        ├── README.md                  v1.0 limitations overview
        └── sop-v1-original.md        v1.0 original SOP
```

---

## Quick Start

The single-machine, single-user MVP-0 text capture kernel passed local C8 acceptance and exact-commit remote CI, and its limited scope is `Implemented`. Production initialization still requires separate authorization, so there is no production-ready complete flow yet. The next order is:

1. Follow the [design authority and conflict register](docs/design-authority-and-conflict-register-设计权威与冲突登记.md).
2. Read the [implementation choices and test matrix](docs/mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md), [coding execution plan](docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md), and [C8 local acceptance report](docs/mvp-0-capture-c8-acceptance-report-C8总验收报告.md) together for the current implementation and evidence boundary.
3. The direction governance red lines are approved, but the three Processing Profiles, Source Ledger, Evidence Bundles, automatic routing, and semantic-recall evaluation methods remain Draft; they do not authorize RAG or candidate-graph implementation.
4. The [P0 production initialization and minimal inbox dogfood plan](docs/p0-production-dogfood-plan-P0生产初始化与最小收件箱试用方案.md) has completed P0A.1 review and is `Approved Design`. The next permissible action is a separate request for P0B-min; P0B is not yet authorized, and production initialization and interface implementation still require later explicit authorization.
5. After P0V, establish representative-journey and local retrieval/Evidence Bundle experiment baselines before deciding on manual routing, SOP-000A, the SOP-001 redesign, candidate graphs, or the unreviewed GBrain mirror. Enable trusted wiki writes only after SOP-000B and the replacement SOP-002 define exact approval, transactions, and rollback.

The existing `prompts/sop-001-*` files remain useful as `full-map` or layered-processing experiment material; outputs belong under `proposals/curation-maps/` or another explicitly unreviewed derived layer, and the workflow stops after human review. Do not run the legacy [`prompts/sop-002-curator.md`](prompts/sop-002-curator.md) against a real knowledge base. The SOP-003 lint tools remain usable for existing Markdown KBs.

### Installed capture CLI

`knowledgeflow-capture` is a **machine-protocol entry point** for local adapters, not an interactive shell command. The installed package exposes exactly four commands:

```text
knowledgeflow-capture capture_text [--config <absolute local Windows path>]
knowledgeflow-capture append_capture_version [--config <absolute local Windows path>]
knowledgeflow-capture get_capture [--config <absolute local Windows path>]
knowledgeflow-capture list_captures [--config <absolute local Windows path>]
```

stdin must contain one single-line UTF-8 JSON header, LF or CRLF, exactly `body_length_bytes` raw body bytes, and EOF. Read/list requests require a zero-length body. With exit 0 or 2, stdout uses the same single-line header + LF + exact body + EOF framing; exit 70 means stdout may be incomplete and must be discarded in full. The entry point deliberately has no `--help`, `--version`, Store initialization, recovery, migration, routing, or test-policy switch, and invoking it never auto-creates a production configuration or Store. See [implementation matrix §3.7](docs/mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md#37-c7-v1-受限-cli-契约) and [four-operation contract §7A](docs/mvp-0-capture-operations-本地文本捕获操作契约.md#7a-c7-受限-cli-适配映射) for the exact fields, frames, exit codes, and safety boundaries.

---

## In Practice

> The methodology was informed by work across four cross-domain knowledge bases. Repository-verifiable evidence currently consists of one historical 25K-line curation-map example and one derived wiki-page example in [`examples/`](examples/); the raw source is not included, so these files are illustrative rather than reproducible validation evidence.

---

## Philosophy

Knowledge bases degrade in two ways: **drift** (pages become outdated) and **fragmentation** (the same concept gets scattered across multiple pages). Most tools address drift with periodic cleanup; few address fragmentation at all.

KnowledgeFlow addresses both through **constitutional constraints** (SCHEMA.md as the single source of truth for structure rules) and **defense-in-depth** (format checks at write time, structural scans at lint time, ripple-effect checks on SCHEMA changes). The system is designed so that the most dangerous failure modes — duplicate pages, broken links, orphaned entities, SCHEMA-page inconsistency — are caught automatically, not by human vigilance.

---

## License

MIT
