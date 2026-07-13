[English](README.md) · [中文文档](README-zh.md)

# KnowledgeFlow

> Solving the curation paradox — a two-stage pipeline that separates LLM-powered
> exhaustive extraction from human semantic curation, with an auditable curation map
> as the interface between them.

| Looking for | Jump to |
|------------|---------|
| The core problem this project solves | [The Curation Paradox](#the-curation-paradox) |
| Full pipeline walkthrough | [The Pipeline](#the-pipeline) |
| Why it's designed this way — hard constraints, two-stage, three-layer defense | [Key Design Decisions](#key-design-decisions) |
| What files are in this repo | [Project Structure](#project-structure) |
| How to get started | [Quick Start](#quick-start) |
| Real-world usage data | [In Practice](#in-practice) |
| Design philosophy | [Philosophy](#philosophy) |
| Full SOP specification | [`docs/sop-v2-full.md`](docs/sop-v2-full.md) |
| Build plan & roadmap | [`docs/build-plan.md`](docs/build-plan.md) |
| Strategic vision | [`docs/second-brain-vision.md`](docs/second-brain-vision.md) |
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
- **LLM executes constrained writes** — the curation phase (SOP-002) only processes entries you've confirmed, operating under SCHEMA rules for deduplication, conflict resolution, and formatting

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
│  Phase 2: Curation (策展入库)     │
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

The rough reader operates under 7 hard constraints (C1–C7), four of which are prohibitions marked ☒:

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
| Increment check | SOP-002 self-verification | Format-level correctness of new pages | Every curation |
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
├── docs/
│   ├── sop-v2-full.md               Core deliverable (SOP-000 through SOP-006 + appendices)
│   ├── build-plan.md                Build plan & roadmap（外置第二大脑建设规划）
│   └── second-brain-vision.md       Strategic vision（战略愿景）
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
│   ├── sop-002-curator.md           SOP-002 curation & ingestion
│   ├── sop-003-lint.md              SOP-003 health scan
│   └── extraction-interface.md      Extraction interface + coverage report spec
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

**Minimum path to a working knowledge base:**

1. **Define your domain** — one or two intersecting knowledge areas.
2. **Copy `templates/SCHEMA-template.md`** to `schema/SCHEMA.md` in your knowledge base directory and fill in the placeholders.
3. **Feed your first source** to an LLM using the default template `prompts/sop-001-modeA.md` — this produces a 9-section curation map in a single LLM call. Then run `prompts/sop-001-modeA-auditor.md` for the independent coverage report (section 10). See `prompts/README.md` for all extraction modes.
4. **Review the curation map** — mark entries as "ingest," "ignore," or "need more sources." Adjust SCHEMA if the rough reader suggested changes.
5. **Tell the LLM to execute SOP-002** using `prompts/sop-002-curator.md` — it will create wiki pages from only the entries you confirmed.
6. **Run SOP-003 lint** using `prompts/sop-003-lint.md` to verify structural integrity.

Full specification: [`docs/sop-v2-full.md`](docs/sop-v2-full.md). Prompt templates: [`prompts/`](prompts/).

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
