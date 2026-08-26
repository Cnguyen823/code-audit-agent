# code-audit-agent

## Overview
A GitHub App that audits Python repositories for architectural risk. When a
pull request opens, three independent agents analyze the code — a Dependency
Mapper, a Pattern Checker, and a Scalability Analyzer — and a Synthesis layer
reconciles their findings into a ranked GitHub Check Run with file- and
line-level annotations. Portfolio project built to move from backend
engineering into agentic AI work.

## Try It
Not runnable yet. Week 1 is learning, not building — see
[experiments/](experiments/) for the five concept scripts being worked
through before any `src/` code gets written. See
[docs/roadmap.md](docs/roadmap.md) for the full plan.

## Goal
Transition from backend engineering into agentic AI work by building
hands-on, production-shaped experience with:
- Multi-agent system design (independent analysis + synthesis/reconciliation)
- Async orchestration with checkpointed, resumable execution
- Idempotent re-runs
- RAG over two distinct stores (an ephemeral per-codebase index and a
  permanent, hand-curated pattern library)
- Distributed tracing across an agent chain
- Graph algorithms (import/call graph, cycle detection, coupling)

## Tech Stack
- **FastAPI** — webhook ingress; must ack GitHub in <10s, so it only
  verifies and enqueues
- **Postgres** — job queue (`FOR UPDATE SKIP LOCKED`), parse cache, findings.
  One datastore so job state and results commit in one transaction
- **LangGraph** — the agent graph is literally fan-out/fan-in; its
  checkpointer gives workflow-level resume
- **Python `ast` + `ProcessPoolExecutor`** — parsing is CPU-bound and holds
  the GIL, so it needs processes, not an event loop
- **`asyncio`** — for the genuinely IO-bound work: LLM, GitHub, and database
  calls
- **networkx** — import/call graph, cycle detection, centrality-based
  coupling metrics
- **Local code embeddings** (jina-code class) — bulk source never leaves our
  infrastructure
- **numpy** — retrieval is one matmul against ~100 baked pattern vectors;
  code is a query, never an indexed corpus, so there is no vector store
- **Claude** — verification of retrieval candidates and synthesis prose, via
  tool-use schemas for guaranteed output shape
- **OpenTelemetry** — tracing, propagated across the queue boundary via a
  stored `traceparent`
- **Fly.io** — web + worker processes, managed Postgres

Full reasoning for every choice, including what was rejected, is in
[docs/decisions.md](docs/decisions.md).

## MVP Scope
A GitHub App that, on PR open/update, audits the changed files plus their
dependency neighborhood. Three agents run independently:
- **Dependency Mapper** — parses the AST, builds an import/call graph, finds
  cycles and coupling hotspots
- **Pattern Checker** — RAG over a hand-curated anti-pattern library,
  retrieves candidates, then verifies each against the actual code with an
  LLM before it becomes a finding
- **Scalability Analyzer** — estimates bottlenecks from graph topology and
  git churn

A **Synthesis** layer reconciles the three outputs, boosts confidence where
agents independently agree, flags disagreements rather than averaging them
away, and ranks by severity x confidence. Output is a GitHub Check Run with
line-level annotations.

Out of scope for MVP: multi-repo analysis, non-Python languages, a web
dashboard, user-editable patterns, full-repo baseline audits, and billing.

## Current Status
- [x] Architecture and stack decided ([docs/architecture.md](docs/architecture.md),
      [docs/decisions.md](docs/decisions.md))
- [ ] Week 1: learning experiments (`experiments/`) — async, idempotency,
      graph algorithms, RAG/vector stores, tracing
- [ ] Webhook ingress + Postgres job queue
- [ ] Parse layer with content-hash cache
- [ ] Dependency Mapper agent
- [ ] Pattern Checker agent (+ pattern library in `patterns/`)
- [ ] Scalability Analyzer agent
- [ ] Synthesis / reconciliation layer
- [ ] Tracing across the queue boundary
- [ ] Deployed App auditing a real PR end to end

See [docs/roadmap.md](docs/roadmap.md) for the week-by-week plan and
[docs/architecture.md](docs/architecture.md) for system design (in
progress — real design happens after Week 1).
