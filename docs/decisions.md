# Engineering Decisions

Running log of engineering decisions made during development of
code-audit-agent. Each entry records what was considered, what was chosen,
why, and what it costs.

---

## 1. Deployment Shape: GitHub App

### Options Considered
- CLI + CI tool (pip-installable, runs on the developer's machine)
- GitHub App (webhook-driven, posts Check Runs on PRs)
- Hosted multi-tenant SaaS (accounts, dashboard, billing)

### Chosen
GitHub App.

### Reasoning
The PR review loop is where an architectural audit actually changes
behavior. A report you have to remember to run is a report nobody runs; a
check that appears on the PR is one people read. The App shape also forces
the interesting engineering — async job processing, idempotent webhook
handling, distributed tracing across a queue boundary — which is precisely
the production experience this project exists to build.

### Tradeoffs
Roughly double the surface area of a CLI: a public HTTPS endpoint, secret
management, a queue, workers, and uptime ownership. Most of that addition
is infrastructure rather than agent work. Mitigated by keeping the audit
engine a pure library (`audit(repo_path, changed_files, config) -> Report`)
that knows nothing about GitHub or queues — the App is a caller, not the
architecture.

---

## 2. Execution Model: ProcessPool for Parsing, asyncio for IO

### Options Considered
- `asyncio` for everything
- `ProcessPoolExecutor` for everything
- Split: processes for CPU-bound parsing, asyncio for IO-bound calls

### Chosen
Split — `ProcessPoolExecutor` for read+parse, `asyncio` for LLM, GitHub,
and database calls.

### Reasoning
`asyncio` provides concurrency, not parallelism. It overlaps *waiting*,
which is why it wins on IO. AST parsing does no waiting — it is CPU work
holding the GIL, so N concurrent parses on an event loop run one at a time.
Meanwhile the LLM verification calls are pure IO and benefit enormously
from being concurrent. Each workload gets the mechanism built for it.

### Tradeoffs
Two concurrency models in one codebase, which is more to reason about than
either alone. Process pools also carry real costs: worker startup, and
pickling data across the process boundary — so the unit of work sent to a
process must be a file path (cheap to send) rather than a parsed tree
(expensive). Getting this backwards is the classic way to make a process
pool slower than a plain loop.

---

## 3. Job Queue: Postgres FOR UPDATE SKIP LOCKED

### Options Considered
- Redis + arq
- Redis + Celery
- Postgres `FOR UPDATE SKIP LOCKED`

### Chosen
Postgres as the queue.

### Reasoning
The job's state, its lease, its trace context, and its findings all want to
live in one transaction. With a separate broker, the queue and the database
can disagree about whether a job ran — the classic dual-write problem, and
it shows up as duplicate audits or silently dropped ones. `SKIP LOCKED`
makes Postgres a correct queue: a row locked by one worker is passed over
rather than waited on, so N workers claim N distinct jobs with no
coordination. One less service to run, monitor, and pay for.

### Tradeoffs
Postgres will not match Redis throughput at high volume, and queue depth
becomes database load. Irrelevant at this scale — audits are minutes long,
so the queue sees single-digit operations per second — but it is the reason
to revisit if volume grows by orders of magnitude. Also gives up Celery's
mature scheduling and retry ecosystem, which has to be hand-rolled here
(lease expiry, attempt counting, backoff).

---

## 4. Idempotency: Content Hashing at Two Levels

### Options Considered
- No dedup — process every webhook delivery
- Dedup on GitHub's webhook delivery GUID
- Dedup on `(installation_id, repo_id, head_sha)` + per-file content hash

### Chosen
Both levels: a unique constraint on the commit for job creation, and
SHA-256 file content hashes keying a parse cache.

### Reasoning
GitHub redelivers webhooks on timeout or failure, so duplicate deliveries
are normal operation, not an edge case. Deduping on the delivery GUID would
prevent double-processing one delivery but still allow two audits of the
same commit. The correct unit of work is the commit.

The file-level hash is what makes re-runs cheap rather than merely correct:
a PR touching 5 files in a 500-file repo reuses 495 cached parses, and a
crashed worker resumes at file granularity instead of restarting. This is
the same pattern used in `receipt-expense-agent` — hash the content, check
before spending the expensive call — applied to source files instead of
receipt images.

### Tradeoffs
Cache invalidation is now a real concern: parse facts are valid only for
the exact file bytes that produced them, and any change to the *parser*
invalidates every cached entry. That requires a parser-version column in
the cache key, which is easy to forget and produces subtly stale results
when forgotten.

---

## 5. Pattern Library: Baked Embeddings, No Vector Database

### Options Considered
- Dedicated vector database (Qdrant, Chroma)
- `pgvector` in the Postgres already being run
- Precomputed embedding matrix baked into the container image, brute-force
  cosine similarity in numpy

### Chosen
Baked matrix, brute-force similarity.

### Reasoning
The decisive argument is not size, it is that **the pattern library is
code, not data**. The `.md` entries are hand-written and versioned in git
alongside the analyzer that reasons about them. If they live in Postgres,
every new pattern becomes a data migration and the library version drifts
out of sync with the deployed release — meaning findings stop being
reproducible from a commit SHA. Baking embeddings at image build time
version-locks patterns to the code that uses them.

Size reinforces it: retrieval over ~100 vectors is one matrix multiply,
microseconds, with no index to build and no service to run. An ANN index
earns its complexity somewhere north of 10k vectors.

### Tradeoffs
Adding a pattern requires a rebuild and redeploy rather than a database
write — correct for a hand-curated library, wrong if patterns ever become
user-editable at runtime. That change would force a move to `pgvector`.
Also means no vector database appears in this project, which some resume
screens look for; the reasoning above is the answer to that question in an
interview.

---

## 6. No Codebase Index At All — Code Is a Query, Not a Corpus

### Options Considered
- `pgvector` with a `run_id`, cleaned up after each job
- Persistent embedded store on the worker's disk
- In-process ephemeral index (LanceDB), discarded with the job
- No index whatsoever — embed each chunk, score it, discard the vector

### Chosen
No index. Chunk embeddings are transient values inside the retrieval call.

### Reasoning
There is exactly one retrieval corpus in this system: the pattern library.
The customer's code is never a corpus — it's a stream of queries against
that library. Each chunk asks "which of my ~100 patterns do I resemble,"
gets scored, and is discarded. An index exists to be *searched repeatedly*;
nothing here ever searches code against code, so there is no reader for a
persisted index of it.

No `code_vectors` table exists in the schema, either. Persisting an
embedding isn't one accidental line away — it requires someone to
deliberately design a table and a write path, which is a visible,
reviewable architectural change, not a stray write a bad PR slips in.
That's a narrower and more honest safeguard than "impossible": nothing
stops an `INSERT` at the point a chunk is embedded, there's simply no
reason to add one.

Not persisting also happens to be the right privacy posture, as a
consequence rather than the primary driver: embeddings are partially
invertible, so a stored index would amount to a retained copy of
proprietary source. The honest answer to a security review becomes "we
retain nothing but findings," not a retention schedule to defend.

### Tradeoffs
Rules out, for now, any feature that searches code against code: "this
anti-pattern also appears in 12 other files," or pulling related code in as
extra verification context. Both are genuinely useful and both are
post-MVP; adding either means deliberately adding a table and reopening the
retention question honestly, not discovering the capability was there all
along.

Also considered and rejected: caching embeddings by content hash purely for
performance, the same way parse facts are cached, to skip re-embedding
unchanged chunks on a re-run. Not worth it — local embedding is cheap
relative to the LLM verification call that's already cached, so the
performance win is small against a privacy cost that doesn't change. A
resumed job re-embeds what it re-embeds; that cost was already accepted
under decision 4, where the parse cache — not an embedding cache — is what
makes resume cheap.

---

## 7. Embeddings: Local Code-Tuned Model

### Options Considered
- Hosted embedding API (Voyage `voyage-code-3`, OpenAI
  `text-embedding-3-small`)
- Local code-tuned model on the worker
  (`jina-embeddings-v2-base-code` or similar)

### Chosen
Local model running on the worker.

### Reasoning
Embedding is the bulk-data step — every chunk of every analyzed file goes
through it. Routing that through a third party means transmitting
essentially the whole codebase to an external subprocessor, which is the
single hardest objection a security-conscious customer will raise. Running
locally keeps bulk source inside our own infrastructure and reduces the
subprocessor list to one (Claude), used only for small targeted snippets at
the verification step. Marginal cost per audit also drops to compute.

### Tradeoffs
Larger container images and slower cold starts, since model weights ship
with the worker. Retrieval quality is somewhat below the best hosted
code-embedding models. Both are acceptable because stage 1 only needs to
produce *candidates* — the LLM verification stage is what determines
whether a finding is real, so recall matters more than precision at the
retrieval step.

---

## 8. Retrieve-Then-Verify Instead of Retrieval-Only

### Options Considered
- Report high-similarity retrieval matches directly as findings
- Two-stage: retrieve candidates, then verify each against the actual code
  with an LLM

### Chosen
Two-stage retrieve-then-verify.

### Reasoning
Vector similarity answers "does this resemble the god-object entry," not
"is this a god object." Shipping similarity scores as findings produces
false positives at a rate that trains developers to ignore the tool — and
an ignored tool has no value regardless of its recall. The verification
call sends the pattern definition plus the real code to Claude and gets
back a structured verdict, confidence, and cited line range through a
tool-use schema. Only verified matches become findings.

### Tradeoffs
An LLM call per candidate makes verification the dominant cost and latency
term. Bounded by capping candidates per chunk and caching verdicts on
`(pattern_id, chunk_hash)` — identical code checked against an identical
pattern cannot yield a different answer, so it should not cost a second
call.

---

## 9. Orchestration: LangGraph Plus a Separate File-Level Cache

### Options Considered
- Hand-rolled asyncio orchestration with custom state and resume
- LangGraph
- Temporal (durable execution)

### Chosen
LangGraph for the agent graph, plus an independent content-hash parse cache.

### Reasoning
The system's shape — fan out to three independent agents, fan in to
synthesis — is literally a graph, and LangGraph expresses that directly
instead of requiring hand-written coordination. Its checkpointer handles
workflow-level resume: if the process dies, the run restarts from the last
completed node.

But node-level granularity is too coarse for parsing. If Agent 1 dies after
400 of 500 files, the checkpointer only knows "Agent 1 did not finish" and
re-parses all 500. So parse progress lives in its own table, keyed by
content hash. Two checkpoint layers with different granularity and
different invalidation rules: the workflow checkpoint is invalid when the
commit changes, a file's cache entry is invalid only when that file's bytes
change.

### Tradeoffs
Framework abstraction to learn and occasionally fight, versus roughly 200
lines of asyncio that would be fully understood. Temporal would be
genuinely better at durable execution — surviving machine death and deploys,
with automatic retries — but requires running a server and adopting a
deterministic-workflow model, a sixth new concept in a project already
carrying five.

---

## 10. Deterministic Ranking, LLM Explanation

### Options Considered
- Ask the LLM to rank and order all findings
- Compute `severity x confidence` in Python, use the LLM only for prose

### Chosen
Deterministic scoring; LLM writes the explanation.

### Reasoning
Ranking must be reproducible and auditable. A customer asking "why was this
finding ranked first" deserves an answer that does not vary between runs,
and LLM arithmetic over a list of findings is neither stable nor
inspectable. The model is good at explaining *why* a risk matters in
context, which is where it is used.

### Tradeoffs
Requires hand-designing a severity scale and a confidence model, then
tuning both against real findings on real repositories. Thresholds set
before seeing real output would be guesses — this stays deliberately
unresolved until there is evidence to tune against.

---

## 11. Pattern Library: Fixed Rulebook, Not Auto-Discovery

### Options Considered
- Fixed, hand-written pattern library (retrieve-then-verify against it)
- Unsupervised discovery: cluster/flag recurring code shapes the library
  doesn't already name, with no pre-written definition required

### Chosen
Fixed rulebook for the MVP. Discovery logged as a deferred, separate idea
(see `docs/architecture.md`, "Deliberately Deferred: Pattern Discovery").

### Reasoning
These are different systems, not two settings of one system. Discovery is
unsupervised anomaly detection over code structure; the current design is
retrieval against known, hand-authored definitions. The two-stage
retrieve-then-verify design — the reason this system's findings are
trustworthy rather than noisy — depends entirely on there being a written
definition to verify a candidate against. Discovery has no such anchor: it
would need to argue "this is anomalous" without one, which is a
categorically weaker and harder-to-trust claim, and "anomalous" is not the
same as "bad" — telling those apart is exactly the judgment a hand-written
pattern currently encodes. Discovery also needs volume to establish what's
"normal" for a codebase, which argues for a scheduled, whole-repo job, not
a per-PR check — a different execution model, not just a different agent.

### Tradeoffs
The system can never flag a real problem nobody has already named and
written up. That's a genuine capability gap versus what was originally
imagined, and it's accepted rather than hidden: fixed-rulebook matching is
buildable in 6 weeks, verifiable, explainable to a developer, and RAG-shaped
in the way this project exists to practice. Discovery remains a legitimate
v2 direction — outlined in architecture.md, not abandoned — once there's a
volume of audits to mine for recurring verification failures.

---

## 12. Hosting: Fly.io

### Options Considered
- Fly.io / Railway
- AWS (ECS Fargate + RDS)
- Defer the decision

### Chosen
Fly.io, with managed Postgres.

### Reasoning
A web process and a worker process from one repository, Postgres as an
add-on, minimal configuration. The infrastructure is not what this project
is demonstrating, so it should consume as little attention as possible
while still being genuinely deployed. Deferring was rejected because the
first deploy would then land under time pressure at the end.

### Tradeoffs
Less enterprise-standard than AWS, and less control over networking and IAM.
Migration cost is low, since the application is containerized and depends
only on Postgres and object storage — both available anywhere.
