# Roadmap

Six-week plan. Week 1 is learning, not building: five small experiments,
each mapped to a real system component, done before any `src/` code exists.
Weeks 2-6 build one agent (or layer) at a time, validated standalone before
being wired into the chain.

---

## Step 1: Learning Week

### Goal
Learn five new concepts — async orchestration, idempotency/checkpointing,
graph algorithms, RAG/vector stores, and distributed tracing — by solving a
small, self-contained problem for each in `experiments/`, before writing any
production (`src/`) code.

### Outcome
Five working experiment scripts, each mapped to the system component it
becomes:
- `async_fetch.py` -> Agent 1's parallel parse orchestration
- `idempotent_parser.py` -> the checkpoint/resume strategy
- `dependency_graph.py` -> Agent 1's core
- `rag_chunking.py` -> both indexing paths (ephemeral + permanent stores)
- `tracing.py` -> the observability backbone
- `mini_audit_system.py` -> first draft of the orchestrator, wiring the
  above together end-to-end at small scale

---

## Step 2: Ingress and Job Pipeline

### Goal
Stand up the GitHub App skeleton: webhook handler with HMAC verification,
Postgres job queue with `SKIP LOCKED` claiming and lease-based crash
recovery, and a worker that clones a PR's head commit and posts a
placeholder Check Run.

### Outcome
A deployed App that responds to a real pull request end to end — no
analysis yet, but the whole delivery path proven, including duplicate
webhook deliveries being correctly ignored.

---

## Step 3: Dependency Mapper

### Goal
Build Agent 1: parse a target repo's AST, construct an import/call graph,
detect cycles and coupling hotspots.

### Outcome
A standalone agent that takes a repo path and produces a graph plus a list
of flagged cycles/coupling issues.

---

## Step 4: Pattern Checker

### Goal
Build Agent 2: RAG over the hand-curated `patterns/` library, retrieve
candidate anti-pattern matches, score by confidence, then verify each
candidate against the actual code (not just the retrieval score).

### Outcome
A standalone agent that takes a repo (or its parsed representation) and
returns confidence-scored, code-verified pattern matches.

---

## Step 5: Scalability Analyzer

### Goal
Build Agent 3: estimate bottlenecks from the Dependency Mapper's graph
topology and hotspot data.

### Outcome
A standalone agent that flags likely scalability risk points with a
rationale grounded in the graph.

---

## Step 6: Synthesis Layer

### Goal
Reconcile the three agents' independent outputs: flag disagreements between
them, rank combined findings by severity x confidence.

### Outcome
One ranked report of architectural risk, generated from three independent
analyses plus their points of disagreement.

---

## Step 7: Integration, Tracing, Polish

### Goal
Wire the full chain together with checkpointed/resumable async
orchestration and end-to-end distributed tracing; run it against a real
target repo.

### Outcome
A working tool: point it at a Python repo, get a ranked architectural risk
report back, with a trace of what each agent did and how long it took.

---

## Guiding Principles
- Learn each new concept against a small, real problem before using it in
  production code — the Week 1 rule, but the habit doesn't stop at Week 1
- Validate each agent standalone before wiring it into the chain
- Shipped in 6 weeks beats perfect — hold scope, don't gold-plate
- Every design decision should be one you could defend out loud in an
  interview; if you can't articulate the tradeoff, you don't have it yet
