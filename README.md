# KnowledgeFlow

> A governance-first, local-first system for personal knowledge work and knowledge management.

[简体中文](README-zh.md)

KnowledgeFlow helps an individual begin with an idea, source, question, research topic, or existing knowledge base: preserve source facts reliably, make material findable, browsable, retrievable, and understandable, then gradually promote only the parts worth stabilizing into trusted knowledge through evidence, human decisions, and constrained execution.

It is not a tool that asks a model to generate a seemingly complete knowledge base, and it does not require a complete taxonomy, schema, ontology, or knowledge graph before work can begin. Models, RAG, wikis, graphs, and local Git are composable tools. The product itself is the governable lifecycle from source facts through working knowledge and proposals to trusted knowledge.

The repository is under active development. The tested capture kernel and selected local administration and inbox scopes are implemented, while the first evidence-linked deep-curation vertical slice is still being formed. The overall product is not production-ready and has not yet proved long-term knowledge-work effectiveness. See the [project status](docs/project-status-项目状态与当前门禁.md) for the exact boundary.

## Why KnowledgeFlow exists

Personal knowledge work often oscillates between two failure modes:

```text
Understand, classify, and model everything before saving it
→ the up-front cost is too high, so ideas and sources are lost before curation

Let a model extract everything and write directly into a knowledge base
→ fast, but opaque source selection and semantic decisions are hard to trust,
  maintain, or roll back
```

KnowledgeFlow does not promise to eliminate understanding and curation with one model call. It turns them into a process that can pause, be reviewed, and continue later:

### The knowledge-curation paradox

High-quality curation requires understanding the material, the user's goals, and the domain context well enough to judge what matters, which claims conflict, and which organization will retain value. Yet people often need a knowledge tool precisely because the material is unfamiliar, too large, or too costly to understand completely up front.

Models can read, compare, and generate candidates at scale, but they do not know what ultimately matters to this user and may omit, compress, misunderstand, or hallucinate. Users own the goal and final judgment, but should not have to perform every mechanical reading, classification, and maintenance step. The problem is therefore not a binary choice between human and model curation; it is how to assign each responsibility to the right actor.

The most dangerous failure is not an extra noisy candidate that is easy to remove. It is a silent omission hidden behind a fluent, apparently complete result. KnowledgeFlow does not promise to eliminate semantic omission. It requires source preservation, visible processing boundaries, evidence for important candidates, and human control of high-impact decisions.

### Resolution: redistribute responsibility

| Actor | Primary responsibility |
|---|---|
| System and models | Perform delegable preservation, segmentation, retrieval, comparison, overview, candidate discovery, evidence organization, conflict checks, and exact change preparation |
| User | Decide the current goal, processing scope, importance, trust, and high-impact structural changes without bearing all mechanical organization work |
| Constrained executor | Deterministically apply, verify, and record precisely approved objects without making new semantic decisions after approval |

This produces a process that may pause, be reviewed, and continue later: first prove what the user submitted; then create useful working knowledge without presenting it as trusted conclusions; expose structures, relationships, and changes as evidence-linked candidates; apply only precisely approved changes; and continue governing additions, conflicts, obsolescence, reorganization, and rollback.

## Core lifecycle

```text
idea / source / question / research topic / existing knowledge base
                              │
               preserve new  │ reuse an existing source
                              ▼
                    T0 source facts
          exact content, stable identity, versions, hashes, intent
                              │
                              ▼
                   T1 working knowledge
       state, indexes, summaries, answers, temporary organization,
                     and candidate relationships
                              │
                              ▼
                   T2 candidates and proposals
          curation maps, evidence, scope, impact, and exact changes
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
           save and finish         prepare exact changes
                                            │
                                    explicit human approval
                                            │
                                  constrained apply and verify
                                            │
                                            ▼
                                    T3 trusted knowledge
                                wiki, stable structures, trusted
                                 relations, checkpoints, rollback
                                            │
                                            └──→ ongoing governance
```

This is not a mandatory pipeline that every task must complete. Preserving a source, answering one evidence-linked question, keeping a curation map, or choosing not to create a knowledge base can all be valid endpoints. A task about an existing source reuses its identity rather than creating another Capture merely to satisfy the diagram.

## Four representative tasks

These are representative user journeys, not four mutually exclusive modules or fixed processing modes. The shared capabilities are reliable capture, working knowledge, evidence binding, candidates and proposals, trusted writing, and ongoing governance.

| User task | What the system should primarily do | Reasonable first result |
|---|---|---|
| Low-friction daily knowledge management | Preserve ideas and short notes, establish minimum source state, and only summarize or group them under a task or a visible, revocable rule | Findable raw material and unobtrusive working knowledge |
| Deep curation of valuable medium or long material | Produce an overall view, chapter or topic structure, claims, disputes, limitations, gaps, and precise evidence locations | A viewable, evidence-linked, editable curation map that may be the endpoint |
| Maintenance of an existing knowledge base | Compare new sources with trusted content, identify additions, duplication, conflicts, staleness, and structural drift, then prepare exact changes | A maintenance proposal that lets the user focus on important differences |
| Large or continuously growing corpora | Preserve sources and processing state, build rebuildable indexes, retrieve evidence by question, and produce local answers | Traceable access that exposes query bias and unprocessed scope |

These are not four unrelated products. A short note may grow into a research topic, research may become a knowledge base, and an existing knowledge base may re-enter the understanding and governance loop as new sources arrive. The paths share invariants such as exact source versions, declared processing scope, evidence location, and source replay, but they need not share the same algorithm, cost, or review depth.

## Two axes that must remain separate

The most common conceptual mistake in KnowledgeFlow is to merge “what kind of artifact is this?” with “how may this particular version be trusted and used?” They are different axes:

| Axis | Question | Examples |
|---|---|---|
| Artifact type | What work does this object perform? | raw material, summary, curation map, wiki page, `SCHEMA.md`, ontology, knowledge graph |
| Governance state | What process has this version passed, and how may it be used? | source fact, working result, pending proposal, approved and verified trusted result, historical version |

The same artifact type may appear in different governance states. A model-generated wiki draft is still working knowledge. A byte-exact wiki change waiting for approval is a proposal. Only after approval, deterministic application, and read-back verification does the page become trusted knowledge. Conversely, accepting a curation map as the result of a task does not turn it into a wiki, ontology, or knowledge graph.

The four trust layers provide the shared boundary:

| Layer | Typical contents | Must not be mistaken for |
|---|---|---|
| T0 source facts | exact content, versions, hashes, provenance, explicit intent | content that is correct, understood, or classified |
| T1 working knowledge | indexes, summaries, outlines, answers, temporary collections, candidate graphs | user-approved knowledge conclusions |
| T2 candidates and proposals | curation maps, Evidence Bundles, routing, structure, and exact change proposals | already executed trusted changes |
| T3 trusted knowledge and governance | approved pages, stable structures, trusted relations, approvals, checkpoints, rollback history | a cache that models, RAG, or mirrors may overwrite |

## How the main artifacts and technologies cooperate

| Artifact or capability | Primary role | Boundary |
|---|---|---|
| Capture / raw | Preserve an exact version of what the user submitted | Proves source facts, not semantic correctness or understanding |
| Curation map | Show what a bounded source set says, where evidence lives, and what disputes, gaps, and organization candidates exist | May be the endpoint; it is not trusted wiki content or a permanent map of an entire corpus |
| Wiki | Explain and maintain topics as durable human-readable pages | Drafts, proposals, and trusted pages remain distinct |
| RAG | Retrieve evidence from an allowed source or knowledge scope and support the current answer | Organizes access and evidence; it does not grant trusted identity |
| KB `SCHEMA.md` | Define valid page, source-reference, link, and navigation conventions | May be minimal and is not automatically a complete domain ontology |
| Ontology | Define concepts, relationships, and constraints that must be reused consistently across content | Introduced for demonstrated reuse or validation value, not as a prerequisite |
| Knowledge graph | Represent, browse, and query concrete entity relationships | May be candidate or trusted; an ordinary link graph is not automatically a knowledge graph |
| SOP | Define who performs which steps, when to pause, approve, verify, and recover | Controls execution; it does not replace product requirements or user decisions |
| Local Git | Provide transparent offline checkpoints for managed knowledge bases | A technical commit is not business approval, backup, or a dependency on GitHub |

Structure matures through real use. A knowledge base may remain a Markdown wiki with ordinary links and search indefinitely. Controlled vocabularies, taxonomies, ontologies, or formal knowledge graphs become worthwhile only when naming consistency, relationship queries, validation, or interoperability create enough benefit to justify their ongoing governance cost.

## Authority, automation, offline use, and accounts

Three permissions remain separate:

1. assign a source to a knowledge base;
2. allow deep semantic processing of the source;
3. approve exact changes to trusted knowledge.

Saving a source does not automatically authorize model summaries, relationship discovery, or indefinite background processing. Deep-processing permission does not authorize changes to the trusted layer. Models may assist reading, comparison, explanation, organization proposals, and diff preparation, but they must not silently change user goals, knowledge-base boundaries, trusted pages, stable structures, deletion scope, or publication state.

Normal Capture Store use does not require GitHub, a GitHub account, or continuous network access. GitHub Actions is only a remote development check. In the first version, once a map is bound to a managed knowledge base, its managed maps, decisions, and later trusted wiki content enter that knowledge base's local Git history. This still requires no remote, account, network, or push.

Semantic features that call an external provider require separate authorization and can be disabled. Without a model key or network, existing Capture data, version history, recovery operations, deterministic evidence, and saved artifacts remain local and usable. External and local models are replaceable semantic adapters, not normative sources for preservation or ordinary local reading.

## Current repository scope

The repository currently contains:

- a single-machine, single-user local text Capture Store;
- four public text operations: create, read, list, and append a new immutable version;
- explicit Store initialization, verification, operational-copy backup, and new-target restore;
- a minimal Tk local inbox using those public operations;
- contracts, mechanical capabilities, and active implementation for an evidence-linked deep-curation vertical slice;
- deterministic tests for identity, integrity, concurrency, crash recovery, migration, and bounded curation transactions.

The project does not yet claim production deployment, high-sensitivity data protection, trusted-wiki writing, general RAG, a formal knowledge graph, multi-device collaboration, or long-term user-value validation. Exact maturity, current completion, and the next authorization belong only in the [project status document](docs/project-status-项目状态与当前门禁.md).

## Quick start for development

KnowledgeFlow currently targets Python 3.13.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e .
```

Open the local inbox after configuring or initializing a test/local Capture Store:

```powershell
.venv\Scripts\knowledgeflow-inbox.exe
```

Run repository checks:

```powershell
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"
.venv\Scripts\python scripts/doc-check.py
```

The machine-facing Capture CLI intentionally uses a framed stdin/stdout protocol rather than an interactive help surface. Use the [operation contract](docs/capture/mvp-0-capture-operations-本地文本捕获操作契约.md) before integrating it. Real data, production paths, external model calls, and trusted writes require the precise authorization described by the current project gate.

## How the documents divide responsibility

- Root README: lets a first-time reader understand the product; it does not maintain current commits or detailed contracts.
- [Master PRD](docs/requirements-and-governance-baseline-需求与治理基线.md): defines the problem, required product outcomes, scope, requirements, and acceptance conditions.
- [Conceptual architecture guide](docs/knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md): explains in detail how T0–T3, schema, SOPs, curation maps, RAG, ontologies, and knowledge graphs fit together.
- [Design authority and conflict register](docs/design-authority-and-conflict-register-设计权威与冲突登记.md): identifies the responsible current document when cross-document claims conflict and records a small set of stable cross-topic rulings.
- [Progressive knowledge-refinement specification](docs/progressive-knowledge-refinement-spec-渐进式知识提炼规范.md): investigates how deeply to process material of different scale and intent, how to account for scope, measure coverage, and choose methods; concrete methods still require evidence.
- [Project status and current gate](docs/project-status-项目状态与当前门禁.md): is the only record of where work stands, what evidence exists, and what may be authorized next.

The full reading order and historical entry points are in `docs/README.md`:

| Looking for | Jump to |
|---|---|
| Documentation map and reading order | [docs/README.md](docs/README.md) |
| Current phase, next gate, and evidence | [project status](docs/project-status-项目状态与当前门禁.md) |
| Product goals and requirements | [Master PRD](docs/requirements-and-governance-baseline-需求与治理基线.md) |
| Topic authority and conflict rulings | [design authority](docs/design-authority-and-conflict-register-设计权威与冲突登记.md) |
| Cross-topic concepts | [conceptual architecture guide](docs/knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md) |
| Store initialization, backup, and restore | [administration contract](docs/capture/capture-store-administration-and-backup-contract-捕获存储管理与备份恢复契约.md) |
| Minimal local inbox | [inbox product specification](docs/capture/local-inbox-product-spec-本地收件箱产品规范.md) |
| Completed Capture implementation evidence | [MVP-0 history](archive/2026-implementation-history/README.md) |
| Completed low-sensitivity pilot evidence | [P0 pilot history](archive/2026-p0-low-sensitivity-pilot/README.md) |
| Historical changes | [CHANGELOG.md](CHANGELOG.md) |

Read the project by selecting documents for the task rather than recursively loading every Markdown file. Research inputs, archived designs, legacy prompts, examples, and evaluation gold are deliberately outside the default implementation context.

## Repository layout

The tree below shows responsibilities, not every file:

```text
knowledge-flow/
├── AGENTS.md
├── README.md
├── README-zh.md
├── pyproject.toml
├── docs/
│   ├── README.md
│   ├── project-status-项目状态与当前门禁.md
│   ├── requirements-and-governance-baseline-需求与治理基线.md
│   ├── design-authority-and-conflict-register-设计权威与冲突登记.md
│   ├── capture/
│   │   └── mvp-0-capture-operations-本地文本捕获操作契约.md
│   └── curation/
│       └── 00-deep-curation-workflow-深入策展流程总览.md
├── src/
│   ├── knowledgeflow_capture/
│   │   └── __init__.py
│   └── knowledgeflow_curation/
│       └── __init__.py
├── tests/
│   └── __init__.py
├── scripts/
│   └── doc-check.py
├── prompts/
│   └── README.md
├── examples/
│   └── curation-map-example.md
└── archive/
    └── 2026-design-history/
        └── README.md
```

## License

[MIT](LICENSE)
