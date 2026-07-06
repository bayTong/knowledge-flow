# KnowledgeFlow

> A structured SOP system for LLM-assisted personal knowledge base management —
> from raw source to curated wiki, with a human-in-the-loop audit pipeline.

---

## The Core Problem

LLM-assisted knowledge management tools face a fundamental tension:

- **High-quality curation demands domain judgment** — you need to know what matters before you can organize it.
- **Users adopt knowledge management tools precisely because they don't yet know the domain** — if you already understood the field, you wouldn't need a structured knowledge base.

Most AI knowledge tools resolve this by letting the LLM **both** extract and curate. The LLM decides what's a "core concept" vs. a "minor detail," which pages to create, and how to organize them. This is fast and frictionless — but the LLM is making semantic judgments about what matters **to you**, without knowing your goals, your context, or your evolving understanding of the field.

**KnowledgeFlow takes a different position**: the LLM does exhaustive mechanical extraction (what it's good at), and you do semantic curation at checkpoints (what requires human judgment). The pipeline enforces this separation through hard constraints — not guidelines, but prohibitions the LLM cannot violate.

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
│  Output: Reading Map (阅读地图)    │
│  A structured, auditable artifact │
│  with 9 sections                  │
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
│    entries from the reading map   │
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
| C1: Never create wiki pages | ☒ | The rough reader produces reading maps, not finished artifacts |
| C2: Every extraction must cite its source location | ☒ | Traceability = verifiability = correctability |
| C3: Uncertainty must be explicitly marked | ☒ | The core value of the rough reader over direct curation |
| C4: Agent suggestions must be structurally separated from facts | ☒ | Prevents suggestion contamination of the factual layer |
| C5: Never filter by importance — extract everything | ☒ | Agent omissions are harder to fix than agent noise |
| C6: Ultra-long sources must list "sections not yet read" | ☑ | Transparency about coverage boundaries |
| C7: Implicit relationships can be extracted but must be flagged as "speculative" + confidence ≤ medium | ☑ | Speculation must never masquerade as certainty |

Telling an LLM "you should try to do X" gets diluted. Telling it "you must never do Y" creates an auditable compliance checkpoint.

### 2. Two-Stage Pipeline with a Human Audit Surface

Extraction and curation are **separate SOPs** with a mandatory human review checkpoint between them. The reading map is the audit surface — a structured artifact you can reason about before any permanent changes are made to your knowledge base.

This separation solves the "paradox of curation": you don't yet know the domain, so you can't judge extraction quality on the fly. The reading map gives you a pause point — you review it, mark what matters, and then the LLM executes constrained writes.

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
├── README.md
├── docs/
│   └── sop-v2-full.md          ← Full SOP specification (v2.0, 6 SOPs + appendices)
├── templates/
│   └── SCHEMA-template.md      ← Reusable SCHEMA template (7 minimum chapters)
├── examples/
│   ├── reading-map-example.md  ← Real reading map from 25K-line technical dialogue
│   └── wiki-page-example.md    ← Resulting wiki page after curation
└── .gitignore
```

---

## Quick Start

**Minimum path to a working knowledge base:**

1. **Define your domain** — one or two intersecting knowledge areas.
2. **Copy `templates/SCHEMA-template.md`** to `schema/SCHEMA.md` in your knowledge base directory and fill in the placeholders.
3. **Feed your first source** to an LLM, instructing it to execute SOP-001 (the rough reader). It will produce a reading map — no wiki pages yet.
4. **Review the reading map** — mark entries as "ingest," "ignore," or "need more sources." Adjust SCHEMA if the rough reader suggested changes.
5. **Tell the LLM to execute SOP-002** — it will create wiki pages from only the entries you confirmed.
6. **Run SOP-003 lint** to verify structural integrity.

The full specification is at [`docs/sop-v2-full.md`](docs/sop-v2-full.md).

---

## In Practice

The SOP system has been used to manage 4 knowledge bases covering:
- LLM agent architecture and internals
- LLM application development (RAG, agents, knowledge graphs, retrieval)
- Knowledge base curation toolchain design
- Cross-domain knowledge synthesis

The reading map example in this repository was produced from a 25K-line technical dialogue on LLM application development — demonstrating the rough reader's ability to handle ultra-long, multi-topic source material with transparent coverage boundaries.

---

## Philosophy

Knowledge bases degrade in two ways: **drift** (pages become outdated) and **fragmentation** (the same concept gets scattered across multiple pages). Most tools address drift with periodic cleanup; few address fragmentation at all.

KnowledgeFlow addresses both through **constitutional constraints** (SCHEMA.md as the single source of truth for structure rules) and **defense-in-depth** (format checks at write time, structural scans at lint time, ripple-effect checks on SCHEMA changes). The system is designed so that the most dangerous failure modes — duplicate pages, broken links, orphaned entities, SCHEMA-page inconsistency — are caught automatically, not by human vigilance.

---

## License

MIT
