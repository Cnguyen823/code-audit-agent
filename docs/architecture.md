# Architecture

A GitHub App that audits Python repositories for architectural risk. It
receives a webhook when a pull request opens or updates, runs three
independent analysis agents over the code, reconciles their findings, and
posts a GitHub Check Run with file- and line-level annotations.

## System Flow

```
GitHub PR event
  -> webhook handler (FastAPI): verify HMAC, enqueue, return 202 in <10s
  -> jobs table (Postgres, FOR UPDATE SKIP LOCKED)
  -> worker claims job, clones repo at head_sha
  -> file discovery + parse (ProcessPoolExecutor, content-hash cached)
  -> LangGraph run:
         fan out -> Dependency Mapper
                 -> Pattern Checker
                 -> Scalability Analyzer
         fan in  -> Synthesis
  -> ranked Report
  -> GitHub Check Run + annotations
```

The three agents run concurrently and share only the parsed representation
produced upstream of them. They do not read each other's output — that
independence is what makes their agreement (or disagreement) meaningful
signal at the synthesis step.

## Components

### Webhook Handler (ingress)

FastAPI endpoint receiving `pull_request` events (`opened`, `synchronize`)
and `check_run` re-request events. Three jobs, in order: verify the
`X-Hub-Signature-256` HMAC against the webhook secret, insert a job row,
return `202`. Nothing else — GitHub expects a response in roughly ten
seconds and an audit takes minutes, so the handler must never do work
inline.

Authentication to GitHub is the standard App flow: sign a JWT with the
App's private key, exchange it for an installation access token (1-hour
TTL), use that token to clone and to post results. The private key lives in
platform secrets, never in the image or the repo.

### Job Queue (Postgres, SKIP LOCKED)

The `audits` table is the queue. Workers claim with:

```sql
SELECT * FROM audits
 WHERE status = 'queued' AND lease_expires_at < now()
 ORDER BY created_at
 FOR UPDATE SKIP LOCKED
 LIMIT 1;
```

`SKIP LOCKED` is what makes this a real queue rather than a lock
convoy: a row already locked by another worker is passed over instead of
waited on, so N workers claim N distinct jobs with no coordination.

Using Postgres rather than Redis is deliberate. The job's state, its lease,
its trace context, and its resulting findings are all things we want in one
transaction — a separate broker would mean two systems that can disagree
about whether a job ran.

**Idempotency at the queue boundary:** GitHub redelivers webhooks on
timeout or failure, so the same PR event can arrive several times. A unique
constraint on `(installation_id, repo_id, head_sha)` makes a duplicate
delivery a no-op insert rather than a duplicate audit. The unit of work is
a commit, not a delivery.

**Crash recovery:** a claimed job carries a lease (`lease_expires_at`)
that the worker heartbeats while running. A worker that dies stops
heartbeating, its lease expires, and the row becomes claimable again. This
is the visibility-timeout pattern, implemented in one column.

### Parse Layer

File discovery walks the repo, honors `.gitignore`, and applies configured
excludes (vendored code, migrations, tests).

**Execution model — this is the load-bearing detail.** `asyncio` does not
parallelize AST parsing. Parsing is CPU-bound and holds the GIL, so N
concurrent `ast.parse` calls on an event loop serialize. The split:

- **`ProcessPoolExecutor`** for read + parse. Real parallelism across
  cores, which is what a CPU-bound workload needs.
- **`asyncio`** for everything genuinely IO-bound: LLM API calls, GitHub
  API calls, Postgres queries. This is where concurrency actually pays.

Getting this backwards produces a system that looks concurrent and runs at
single-core speed.

**Parse cache and idempotent re-runs.** Each file's SHA-256 content hash
keys a Postgres row holding its derived facts (imports, definitions, call
edges) as JSONB:

```sql
CREATE TABLE parse_cache (
    installation_id  bigint      NOT NULL,
    content_hash     bytea       NOT NULL,  -- sha256 of the file's bytes
    parser_version   text        NOT NULL,  -- invalidates on parser change
    facts            jsonb       NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (installation_id, content_hash, parser_version)
);
```

**Scoped per installation, deliberately.** Content addressing would permit
a global cache — identical bytes parse identically regardless of owner, so
two customers vendoring the same library could share one parse. That is a
cross-tenant leak: a cache hit is observable through timing, so a shared
cache lets one customer test whether specific proprietary bytes exist in
someone else's repository. This is the known cross-user deduplication
side channel. Practical exploitability here is modest given the noise, but
the mitigation is one column, so there is no tradeoff worth making. The
scoping also makes deletion-on-uninstall answerable, which a globally
shared row would not be.

**Not keyed by repo or path.** The same bytes yield the same facts wherever
they sit, so a moved or renamed file is a cache hit rather than a miss —
which matters because refactors that relocate files would otherwise
invalidate everything. This requires splitting the work: what a file
*declares* (imported names, definitions, call targets) is path-independent
and cached; *resolving* those names onto modules is path-dependent —
`from . import helpers` differs by location — and is recomputed at graph
assembly, where it costs dictionary lookups over facts already in hand.

Consequences:

- A PR touching 5 files in a 500-file repo reuses 495 cached parses.
- A crashed run resumes at file-level granularity, not from zero.
- Re-running the same commit is genuinely idempotent — same input hash,
  same stored facts, same findings.

The cache stores *derived facts*, never raw source. That keeps the durable
footprint of customer code as small as the analysis allows.

### Agent 1 — Dependency Mapper

Builds a `networkx.DiGraph` from the parsed facts and reports structural
risk:

- **Cycles** via `simple_cycles` / strongly connected components. Import
  cycles are the highest-confidence finding in the whole system — they're
  purely structural, with no interpretation required.
- **Coupling** via fan-in / fan-out and betweenness centrality. High
  betweenness marks modules that everything routes through.
- **Instability** (Martin's metric): `I = Ce / (Ca + Ce)`. Flags modules
  that are both heavily depended upon and themselves volatile.

**Known limitation, stated up front:** the *import* graph is reliable; the
*call* graph is approximate. Python resolves calls dynamically —
`getattr`, decorators, duck typing, runtime registration — so a purely
static call graph will miss real edges and invent plausible ones. Findings
are therefore tagged with which graph produced them, and call-graph
findings carry a confidence ceiling that import-graph findings don't.

### Agent 2 — Pattern Checker

Two-stage retrieve-then-verify RAG over the hand-curated `patterns/`
library.

**Chunking uses the AST, not line counts.** Because the parse layer already
produced a syntax tree, chunks are cut on natural boundaries — one function
or class per chunk — so a retrieved chunk is always a semantically complete
unit. Fixed-size chunking would routinely split a function across two
chunks and destroy the thing being matched on.

**There is exactly one retrieval corpus: the pattern library.** The
customer's code is not a corpus — it is a stream of *queries*. Each chunk
asks "am I any of these anti-patterns?", gets compared against the pattern
matrix, and its embedding is discarded. Nothing about the customer's code
is ever indexed or stored, because nothing ever searches code against code.

**Where the pattern vectors live.** Three forms, three places:

| Stage | Location | Form |
|---|---|---|
| Source of truth | `patterns/*.md` in git | Hand-written markdown |
| Build time | Inside the container image | Compiled `patterns.npz` |
| Runtime | Worker process memory | numpy array, loaded at boot |

A Dockerfile step (`RUN python -m src.patterns.build`) reads every pattern
file, embeds it with the local model, and saves two arrays: `vectors`
(shape ~100 x 768, float32) and `ids` (pattern slugs in matching row
order). The matrix alone is useless — the id array is what turns row 42
back into `god-object`.

At worker startup the `.npz` is loaded once, ~300KB resident, and reused
for every audit that container handles. No per-audit load, no query, no
connection.

**Embedding-space compatibility is a hard startup check.** The stored
vectors came from one specific model version. If a worker embeds chunks
with a different model, the query vector lives in a different space and
cosine similarity returns numbers that are pure noise — with no error
raised. The model identifier is therefore stored in the `.npz` and the
worker refuses to boot on a mismatch. Failing loudly at startup beats
failing silently for months.

Adding a pattern means: commit the `.md`, CI rebuilds the image
(re-embedding all patterns), deploy, workers restart with the new matrix.
That is the version-locking that keeps findings reproducible from an image
tag. Note the image is large because of the *embedding model* (hundreds of
MB), not the patterns (300KB).

**Stage 1 (retrieve):** embed each chunk locally, score it against the
in-memory pattern matrix, keep top-k candidates. Exhaustive comparison
against all ~100 patterns is a single matrix multiply — roughly 8
microseconds per chunk, ~4ms for a 5,000-chunk repository. No index, no
service, no network hop. Similarity alone is a weak signal anyway: it says
"this looks like the god-object entry," not "this *is* one."

**Stage 2 (verify):** each candidate goes to Claude with the pattern
definition and the actual code, and comes back through a tool-use schema
with a verdict, a confidence, and a cited line range. Only verified matches
become findings.

The second stage is the entire point. Retrieval-only pattern matching
produces false positives at a rate that makes the tool ignorable, and a
tool developers ignore has no value regardless of its recall.

**Cost control:** verification results are cached on
`(pattern_id, chunk_hash)`. Identical code checked against the same pattern
cannot produce a different verdict, so it should not produce a second API
call.

### Agent 3 — Scalability Analyzer

Estimates bottlenecks from graph topology plus git churn. High-fan-in nodes
are change amplifiers; cycles can't be scaled or tested independently; deep
dependency chains lengthen critical paths. Cross-referencing with commit
frequency finds the genuinely dangerous quadrant: files that change often
*and* are heavily depended upon.

This is the fuzziest of the three, and it's labeled that way. Its findings
are heuristics over graph metrics with LLM interpretation layered on, and
they carry lower baseline confidence than Agent 1's structural facts.

### Synthesis

Reconciles three independent finding sets:

1. **Merge** findings that refer to the same code location.
2. **Boost** confidence where multiple agents independently flag the same
   module — independent agreement is real evidence.
3. **Flag disagreement** explicitly rather than averaging it away. If the
   Dependency Mapper calls a module tightly coupled and the Scalability
   Analyzer calls it fine, that tension is shown to the reviewer.
4. **Rank** by `severity x confidence`.

**The ranking arithmetic is deterministic Python, not an LLM call.** The
LLM writes the explanation; it does not compute the score. Scoring must be
reproducible and auditable — a customer asking "why was this ranked first"
deserves an answer that doesn't vary between runs.

### Observability

OpenTelemetry SDK, exported over OTLP. Auto-instrumentation for FastAPI and
the database driver; manual spans per agent, per LLM call, and per parse
batch.

**The genuinely distributed part is crossing the queue.** A trace that
starts in the webhook handler ends when the handler returns `202` — the
worker picks up the job in a different process, minutes later, with no
in-memory link. So the W3C `traceparent` is stored on the job row at enqueue
and restored as the parent context when the worker claims it. Without that,
you get two unrelated traces and no way to answer "how long from PR opened
to check posted."

Backend is swappable by construction (OTLP): Jaeger locally, a hosted
backend in production. LLM-specific concerns — token counts, cost per audit
— are span attributes, with a dedicated LLM observability tool as a later
addition rather than a launch dependency.

### Data Handling

- Repo clones are shallow, single-commit, to ephemeral disk, deleted when
  the job ends.
- Postgres holds job metadata, derived parse facts, and findings — not raw
  source.
- Chunk embeddings exist only as transient values inside the retrieval
  call and are never indexed, written to disk, or stored in a database.
  This falls out of the design rather than being enforced by policy:
  because code is only ever a query and never a corpus, there is no code
  path that would persist it. Which is convenient, since embeddings are
  partially invertible — a stored index would amount to a retained copy of
  customer source.
- Every table carries `installation_id`, and every query is scoped by it.
  Tenant isolation is a security boundary, not a filtering convenience.

## Deliberately Deferred: Pattern Discovery

The Pattern Checker matches against a *fixed, hand-written* library — it
can only flag anti-patterns someone already decided to write down, never a
recurring shape of problem nobody named yet. That's the correct scope for
this system (see decision 12), but the other thing — auto-discovering new
anti-pattern candidates from a codebase's own structure — is a real,
different, harder project, not an extension of this one:

- No fixed definition to verify a candidate against, so the two-stage
  retrieve-then-verify design (the source of this system's precision)
  doesn't apply. It would need to justify "this is anomalous" without a
  written anchor, which is a much weaker, harder-to-trust claim.
- "Anomalous" isn't "bad." A cluster of similar files might be a genuine
  problem, or just how this team writes handlers. Separating those is
  exactly the judgment currently encoded by hand in a pattern file.
- Needs volume to establish what's "normal" for a given codebase — a
  single PR's diff usually isn't enough signal. This shape of analysis
  belongs on a schedule, over a whole repo, not per-PR.
- It's closer to the Scalability Analyzer (heuristics over graph shape, no
  pre-written definition, lower confidence by design) than to the Pattern
  Checker — a fourth capability, not a variant of the second agent.

If this gets built later: cluster chunks that get flagged as *candidates*
by retrieval but fail LLM verification repeatedly across many audits over
time — those are exactly the shapes the current pattern library doesn't
yet name, and a human reviewing the cluster (not the model unsupervised)
decides whether it's worth writing up as a real pattern.

## Future Scaling Considerations

- **`rustworkx` instead of `networkx`** if graph construction dominates on
  large monorepos — same algorithms, Rust-backed.
- **A searchable codebase index**, if features arrive that search code
  against code — "this same anti-pattern appears in 12 other files," or
  pulling related code in as extra verification context. That is the point
  at which an embedded store like LanceDB would earn its place; the current
  design needs none, because code is only ever a query.
- **ANN index for the pattern library**, if it ever grows past roughly 10k
  entries or becomes user-editable at runtime. Neither is close.
- **Full-repo baseline audits** as a separate, lower-priority job class —
  PR-scoped audits are small because they only index changed files plus
  their dependency neighborhood.
- **Incremental graph updates** rather than full reconstruction per audit.
- **Per-installation rate limits and spend caps.** LLM verification is the
  dominant marginal cost; an unbounded installation is an unbounded bill.
- **Temporal** if orchestration outgrows LangGraph checkpoints plus a lease
  column — genuinely better durable execution, at the cost of a server to
  run and a programming model to learn.
- **Multi-language support** via tree-sitter, which would replace the
  Python-specific `ast` layer while leaving the graph, RAG, and synthesis
  layers intact.

## Open Questions

- Severity thresholds for failing a check run vs. reporting neutral —
  needs real findings on real repos before it can be tuned honestly.
- Whether the Scalability Analyzer earns its place in the MVP, or whether
  two strong agents beat three where one is mostly heuristic.
- How to handle monorepos where a PR's dependency neighborhood is
  effectively the whole repo.
