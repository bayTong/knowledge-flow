[English](README.md) · [中文文档](README-zh.md)

# KnowledgeFlow

> Solving the curation paradox — a two-stage pipeline that separates LLM-powered
> exhaustive extraction from human semantic curation, with an auditable curation map
> as the interface between them.

> **Current status (2026-09-02):** the project is migrating from the legacy direct-initialization/curated-write workflow to a governed flow: local durable capture → human routing → proposal → exact approval → reversible write. The MVP-0 technical design and coding plan are approved. C0 project scaffolding and C1 deterministic primitives are complete with 30 passing tests, but the four capture operations and production store do not exist yet. See the [`design authority and conflict register`](docs/design-authority-and-conflict-register-设计权威与冲突登记.md). Legacy SOP-002 and its write prompt are suspended.

| Looking for | Jump to |
|------------|---------|
| The core problem this project solves | [The Curation Paradox](#the-curation-paradox) |
| Full pipeline walkthrough | [The Pipeline](#the-pipeline) |
| Why it's designed this way — hard constraints, two-stage, three-layer defense | [Key Design Decisions](#key-design-decisions) |
| What files are in this repo | [Project Structure](#project-structure) |
| How to get started | [Quick Start](#quick-start) |
| Real-world usage data | [In Practice](#in-practice) |
| Design philosophy | [Philosophy](#philosophy) |
| Current design authority & conflicts | [`docs/design-authority-and-conflict-register-设计权威与冲突登记.md`](docs/design-authority-and-conflict-register-设计权威与冲突登记.md) |
| Capture & routing design | [`docs/capture-and-routing-spec-捕获与路由规范.md`](docs/capture-and-routing-spec-捕获与路由规范.md) |
| MVP-0 coding execution plan | [`docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md`](docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) |
| Legacy SOP reference (partially superseded) | [`docs/sop-v2-full.md`](docs/sop-v2-full.md) |
| Build plan & roadmap | [`docs/build-plan.md`](docs/build-plan.md) |
| Strategic vision | [`docs/second-brain-vision.md`](docs/second-brain-vision.md) |
| Audit findings & fix checklist | [`docs/improvement-action-plan.md`](docs/improvement-action-plan.md) |
| v1.0 → v2.0 changelog | [`CHANGELOG.md`](CHANGELOG.md) |
| v1.0 archive | [`archive/v1.0/`](archive/v1.0/) |

---

## The Curation Paradox

Two premises, each reasonable on its own, but together they form a paradox:

**Premise 1**: High-quality knowledge curation demands domain judgment. You need to distinguish core concepts from minor details, recognize when two different-sounding ideas refer to the same thing, identify which entities in a source are worth extracting as domain-relevant versus peripheral or low-relevance, and determine which pieces of knowledge should be linked — and how. These judgments can only be made by someone who actually understands the domain.

**Premise 2**: People adopt knowledge management tools precisely because they don't yet know the domain. The goal is to learn faster, more intuitively, and more easily from unfamiliar material — building structured knowledge or enabling a range of interactive capabilities. This process depends heavily on AI for analysis and reasoning.

The paradox: **the responsibility for curation lies with the human (only you know your goals and context), yet the human lacks the domain knowledge required to curate; meanwhile, the entity with knowledge-processing capability (the LLM) lacks the context to judge what matters to you, and its risks — extraction omissions, hallucinations — cannot be ignored.** Two independently valid premises point to a contradiction — who should curate?

Most AI knowledge tools resolve this by **ignoring Premise 2** — they let the LLM curate directly. The LLM reads the source, decides what's worth a page, writes summaries, assigns tags, builds links. This is fast and frictionless, but it has an unfixable defect: **LLM omissions are far harder to repair than LLM noise.** If the LLM over-extracts (noise), you delete the extra pages in seconds. If the LLM misses a critical concept, you never know it was skipped — because there's no curation map, no intermediate artifact between the raw source and the finished wiki. The reasoning is entirely inside the LLM's black box.

KnowledgeFlow takes a different position — **redistribute responsibility rather than make the LLM smarter**:

- **LLM handles exhaustive extraction** — no filtering, no importance judgment (hard constraint C5). Every extraction is anchored to a source location (C2), uncertainty is explicitly marked (C3), and agent suggestions are structurally isolated from facts (C4). The output is a structured curation map
- **You handle semantic judgment** — mark each entry in the curation map as "ingest," "ignore," or "need more sources." You don't need to trust the LLM's judgment; you only need to verify that it extracted everything (verifiable through section-by-section coverage and source citations)
- **A restricted writer performs the target-state write** — the replacement SOP-002 will process only precisely approved changes under SCHEMA, transaction, and rollback constraints. It has not been redesigned yet; the legacy write prompt must not be run

The two-stage pipeline isn't primarily about efficiency — it's about **auditability**.

---

## The Core Problem

Following from the paradox above, the specific failures of existing tools can be precisely located:

**The issue isn't insufficient LLM capability — it's a misallocation of roles.** When the LLM is placed in the curator's seat, its strength (exhaustive scanning — not missing anything) is sidelined, and its weakness (judging what matters to you) is pushed to the frontline. Two failure modes dominate:

- **Omissions**: The LLM decides a concept isn't important enough and skips it. Without reading the original source, you'll never know what was left out
- **Over-simplification**: The LLM produces a wiki page that reads well, but you can't tell whether it represents everything the source contained or just the subset the LLM chose to include. You lose a sense of control — the output looks reasonable, but you have no measure of the gap between source and product

KnowledgeFlow's design goal is therefore not "a better curation algorithm" — it's **pulling judgment authority back to the human side, demoting the LLM from curator to extraction tool, and proving that in this role, the LLM can perform more reliably and thoroughly than a human would.**

---

## The Pipeline

```
Raw Source
    │
    ▼
┌──────────────────────────────────┐
│  Phase 1: Rough Reader (粗读器)   │
│                                    │
│  · Captures raw material + SHA256 │
│  · Exhaustive annotation — every  │
│    entity, concept, relationship, │
│    and factual claim, anchored to │
│    exact source locations          │
│  · Uncertainty classification     │
│    (5 categories, not binary)     │
│  · Gap analysis + SCHEMA proposals│
│  · Zero wiki pages created        │  ← Hard constraint
│                                    │
│  Output: Curation Map (策展地图)   │
│  A structured, auditable artifact │
│  with 10 sections (incl. coverage) │
└──────────────────┬───────────────┘
                   │
                   ▼
         ═══ HUMAN REVIEW ═══
         · Mark entries: "ingest" / "ignore" / "need more sources"
         · Adjust SCHEMA proposals
         · Resolve uncertainty flags
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
| C5: Never filter by importance — extract everything | ☒ | Agent omissions are harder to fix than agent noise |
| C6: Ultra-long sources must list "sections not yet read" | ☑ | Transparency about coverage boundaries |
| C7: Implicit relationships can be extracted but must be flagged as "speculative" + confidence ≤ medium | ☑ | Speculation must never masquerade as certainty |

Telling an LLM "you should try to do X" gets diluted. Telling it "you must never do Y" creates an auditable compliance checkpoint.

### 2. Two-Stage Pipeline with a Human Audit Surface

Extraction and curation are **separate SOPs** with a mandatory human review checkpoint between them. The curation map is the audit surface — a structured artifact you can reason about before any permanent changes are made to your knowledge base.

This separation solves the "paradox of curation": you don't yet know the domain, so you can't judge extraction quality on the fly. The curation map gives you a pause point — you review it, mark what matters, and then the LLM executes constrained writes.

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
│       ├── __init__.py               C0 package identity
│       ├── errors.py                 C1 public errors, internal causes, commit states
│       ├── models.py                 C1 hash and request value objects
│       ├── ids.py                    C1 UUIDv7 and typed prefixes
│       ├── hashing.py                C1 four-hash primitives
│       └── codec.py                  C1 restricted YAML and Envelope v1 schema
├── tests/
│   └── capture/
│       ├── fixtures/                 C1 JSON/YAML golden files
│       └── unit/                     30 automated C0–C1 tests
├── docs/
│   ├── sop-v2-full.md               Legacy SOP collection (partly superseded)
│   ├── build-plan.md                Build plan & roadmap（外置第二大脑建设规划）
│   ├── second-brain-vision.md       Strategic vision（战略愿景）
│   ├── curation-paradox.md          The curation paradox argument
│   ├── design-authority-and-conflict-register-设计权威与冲突登记.md  Current topic authority and conflict rulings
│   ├── requirements-and-governance-baseline-需求与治理基线.md      Approved requirements and governance
│   ├── sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md   Provisional KB design
│   ├── capture-and-routing-spec-捕获与路由规范.md                  Capture and manual routing design
│   ├── capture-envelope-v1-捕获信封数据契约与原子保存事务.md      Capture identity and transaction contract
│   ├── mvp-0-capture-operations-本地文本捕获操作契约.md           Approved capture root and text-operation design
│   ├── mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md  Approved implementation choices and test matrix
│   ├── mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md       Approved coding batches and authorization gates
│   ├── adaptive-extraction-plan.md  Adaptive extraction tiers design
│   ├── improvement-action-plan.md   Evaluation findings & fix checklist（评估整改清单）
│   ├── gbrain-integration-plan.md   GBrain engine integration plan（GBrain 集成方案）
│   └── qq-qa-bot-plan.md            QQ Q&A bot plan（QQ 问答机器人方案）
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
│   ├── lint.py                      SOP-003 lint scanner
│   ├── link-validator.py            Wikilink validator
│   └── index-generator.py           index.md generator
├── templates/
│   └── SCHEMA-template.md           Reusable knowledge base constitution template
├── examples/
│   ├── curation-map-example.md      Curation map from a 25K-line technical dialogue
│   └── wiki-page-example.md         Resulting wiki page after curation
└── archive/
    └── v1.0/                         v1.0 historical archive
        ├── README.md                  v1.0 limitations overview
        └── sop-v1-original.md        v1.0 original SOP
```

---

## Quick Start

The complete capture MVP is not implemented yet. Only the tested deterministic foundation exists, so there is no honest “ready-to-run” save path for the governed architecture. The implementation order is:

1. Follow the [design authority and conflict register](docs/design-authority-and-conflict-register-设计权威与冲突登记.md).
2. The [MVP-0 implementation choices and test matrix](docs/mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md) and [coding execution plan](docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) are approved, and C0–C1 are complete. Explicitly authorize C2 before implementing configuration, paths, the manifest, and test-only temporary Store initialization.
3. Complete the local text-capture path batch by batch through C8, then add manual routing, SOP-000A, and the unreviewed GBrain mirror.
4. Enable trusted wiki writes only after SOP-000B and the replacement SOP-002 define exact approval, transactions, and rollback.

The existing `prompts/sop-001-*` files remain useful for studying curation-map extraction and coverage auditing, but outputs now belong under `proposals/curation-maps/` and the workflow stops after human review. Do not run the legacy [`prompts/sop-002-curator.md`](prompts/sop-002-curator.md) against a real knowledge base. The SOP-003 lint tools remain usable for existing Markdown KBs.

---

## In Practice

> Battle-tested across 4 cross-domain knowledge bases covering LLM architecture, application development, and curation toolchain design — the [`examples/`](examples/) directory contains a complete curation map and curated output from one 25K-line dialogue.

---

## Philosophy

Knowledge bases degrade in two ways: **drift** (pages become outdated) and **fragmentation** (the same concept gets scattered across multiple pages). Most tools address drift with periodic cleanup; few address fragmentation at all.

KnowledgeFlow addresses both through **constitutional constraints** (SCHEMA.md as the single source of truth for structure rules) and **defense-in-depth** (format checks at write time, structural scans at lint time, ripple-effect checks on SCHEMA changes). The system is designed so that the most dangerous failure modes — duplicate pages, broken links, orphaned entities, SCHEMA-page inconsistency — are caught automatically, not by human vigilance.

---

## License

MIT
