# Concept Reference

The mechanisms behind the decisions in [decisions.md](decisions.md) —
written to be re-read, not read once. Definitions are the easy part; what
follows is why each thing had to be the way it is.

Personal notes go in [learning.md](learning.md), in your own words. This
file is the reference; that one is the test of whether it stuck.

---

## One pull request, start to finish

Every mechanism below appears somewhere along this path. Read this first;
the rest of the file zooms in on the parts that are hard to get right.

```
GitHub: PR opened or updated
  -> Webhook handler       verify signature, insert job, return 202
                           must answer in <10s, so no audit here
  -> jobs table            UNIQUE(installation, repo, head_sha)
                           traceparent stored on the row
  -> Worker claims         FOR UPDATE SKIP LOCKED, lease + heartbeat
                           traceparent read back, spans rejoin the trace
  -> Clone at head_sha     JWT -> 1-hour installation token, scratch disk
  -> Parse changed files   ProcessPoolExecutor (CPU work, not the loop)
                           sha256(bytes) cache: 5 changed -> 495 reused
  -> fan out
       Dependency Mapper   graph, cycles, coupling
       Pattern Checker     retrieve -> verify   <- the RAG lives here
       Scalability         topology + git churn
     fan in
  -> Synthesis             merge, boost, flag disagreement, rank
                           severity x confidence in plain Python
  -> GitHub Check Run      summary + line annotations
```

**1. Someone pushes code.** A developer updates a PR; GitHub notices.

**2. GitHub knocks.** It POSTs a webhook: "PR #42 changed, new commit is
`abc123`." First thing you do is check the signature — GitHub signs every
webhook with a shared secret, and without that check anyone who finds your
URL can make your workers clone and audit arbitrary repos on your budget.

**3. Write it down, say "got it" immediately.** Insert a row, return `202`,
done in milliseconds. You don't audit here: GitHub wants an answer in ten
seconds and an audit takes minutes. The unique constraint makes a
redelivered webhook a no-op rather than a second audit. You also stash a
`traceparent` — the thread connecting this moment to a worker minutes away.

**4. A worker picks it up.** Workers poll with `SKIP LOCKED`, so each grabs
a different row instead of piling onto one. Claiming and marking `running`
happen in one transaction, so two workers can never hold the same job. A
lease heartbeat means a dead worker's job gets reclaimed.

**5. Get the code.** Sign a JWT with the app's private key, exchange it for
an installation token, shallow-clone that exact commit to scratch disk.
Tokens are minted on demand and expire — you store a key, never a standing
credential to anyone's repository.

**6. Parse.** Hash each file's bytes. Seen it? Reuse the stored facts. New?
Parse it, in a process pool rather than on the event loop, because parsing
is CPU work and asyncio doesn't make CPU work faster. What gets stored is
derived facts, never source.

**7. Three agents run at once.** They never read each other's output, which
is precisely what makes their later agreement evidence rather than echo.
Inside the Pattern Checker: chunk on syntax boundaries, embed a chunk
locally, compare against ~100 baked pattern vectors in one matmul, discard
the chunk's vector, keep the top few as candidates, check the verdict cache,
and send survivors to Claude with the real code for a yes/no plus confidence
plus line range. Only verified matches become findings.

**8. Synthesis reconciles.** Merge findings on the same lines. Independent
agreement raises confidence. Disagreement is shown, not averaged. Ranking
is plain Python; the model writes the explanation but never the score.

**9. Post a Check Run** with annotations pinned to specific lines.

**10. Clean up.** Delete the clone. The embeddings were local variables.

### What survives, and what doesn't

| Persisted in Postgres | Destroyed with the job |
|---|---|
| Job row — status, lease, trace context | The cloned repository |
| Parse facts — imports, definitions, call edges | Chunk embeddings (never written anywhere) |
| Verification verdicts, keyed by pattern + chunk hash | Raw source (never entered the database) |
| Findings — file, line, severity, confidence | |

### If it dies halfway through

The lease goes stale and another worker reclaims the job. LangGraph resumes
at the last finished agent. The parse cache skips files already parsed. The
verdict cache skips candidates already verified. A resumed job is mostly
cache hits — which is the whole point of keying caches on content hashes
rather than filenames.

---

## The cascade: one constraint decided the stack

Nobody compared databases. A single number in GitHub's documentation
determined the shape of the whole system.

GitHub expects a webhook response in roughly ten seconds. An audit takes
minutes. Both cannot be true inside one request handler, so the handler
*cannot do the work* — it validates, records a job, and returns.

That's the first domino:

```
must answer in <10s
  -> handler can't audit inline
  -> a worker process does the work
  -> two processes must agree on which jobs exist
  -> shared state across containers
  -> a database server, not a file
```

SQLite is a library, not a server — code compiled into your process that
reads a file on disk. Two containers with the same path `/data/app.db` have
two unrelated files on two unrelated filesystems. The worker would not see
anything the web process wrote. Not slow: invisible.

Postgres is a separate process speaking a network protocol, so any number
of processes on any number of machines share one source of truth.

Worth carrying into interviews: this is how most infrastructure decisions
actually get made. Not by comparing feature matrices, but by a product
constraint eliminating options until one remains.

---

## Idempotency

An operation is **idempotent** when doing it more than once has the same
effect as doing it once.

```python
x = 5        # idempotent    — run it 100 times, x is 5
x = x + 1    # not idempotent — run it 100 times, x is +100
```

An elevator button is idempotent. Charging a credit card is not, which is
why every payment API demands an idempotency key.

**Dedupe** is narrower — one *technique* for achieving idempotency:
recognize you've seen this before, skip it. Already built once in
`receipt-expense-agent`, hashing image bytes so a re-uploaded receipt
didn't create a second row or spend a second API call.

### Exactly-once is a myth

    at-least-once delivery + idempotent processing = effectively-once

Exactly-once delivery isn't merely hard, it's impossible over an unreliable
network. A worker that finishes an audit and dies before marking the job
done leaves no way to tell from outside whether the work happened. So
nobody builds exactly-once delivery — they accept duplicates and make
duplicates harmless.

Two things will genuinely happen in production, and neither is an edge case:

- **GitHub redelivers webhooks.** Miss the ten-second window once and the
  same event arrives twice. Unprotected: two audits of one commit, double
  the LLM spend, two conflicting check runs.
- **Workers die mid-job.** A deploy, an OOM kill, a machine going away —
  400 files into 500.

### Three layers, three granularities

| Layer | Key | Prevents | Invalidated when |
|---|---|---|---|
| Delivery | `(installation, repo, head_sha)` unique constraint | Two audits of one commit | A new commit is pushed |
| Workflow | LangGraph checkpoint, per node | Re-running finished agents after a crash | The commit under audit changes |
| File | `sha256(file_bytes)` parse cache | Re-parsing unchanged files | That one file's bytes change |

The file layer is what makes re-runs *cheap* rather than merely correct: a
PR touching 5 files in a 500-file repo reuses 495 cached parses.

### Scoping the parse cache — a security decision, not a performance one

Content addressing tempts you toward a *global* cache: identical bytes
parse identically no matter who owns them, so two customers vendoring the
same library could share one parse. Don't.

**A cache hit is observable.** With a shared cache, an attacker puts bytes
they suspect are proprietary to another company into their own repo, runs
an audit, and watches the timing. Fast means somebody else already has
those exact bytes. This is the known cross-user deduplication side channel,
documented against cloud storage that dedups uploads globally. The signal
is noisier here, so severity is modest — but the mitigation is one column,
so there's no version of this tradeoff worth taking.

The duller reason matters too: parse facts carry function, class, and
import names lifted from customer source. When someone uninstalls and asks
you to delete everything of theirs, "which rows are yours" has to have an
answer, and a shared row three tenants depend on doesn't.

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

`installation_id` is the tenancy boundary — one org or user. Sharing
*within* an installation is fine and useful: a company with thirty repos
vendoring the same internal library parses it once.

**No repo id, no file path — deliberately.** Same bytes, same facts,
wherever they sit. A moved or renamed file is a cache hit rather than a
miss, which matters because refactors that relocate files would otherwise
invalidate everything. (Same trick as hashing receipt bytes instead of
filenames, and it pays off harder here.)

That requires splitting the work in two:

- **Cached, path-independent** — what a file *declares*: imported names,
  definitions, call targets.
- **Not cached, path-dependent** — *resolving* those names onto real
  modules. `from . import helpers` means different things at different
  locations, so resolution happens fresh at graph assembly. It's cheap:
  dictionary lookups over facts already in hand.

### Four different hashes, four different jobs

Hashing shows up all over this design, and the four uses are easy to
collapse into one another. They aren't the same mechanism:

| Hash | Where it comes from | Question it answers | If you drop it |
|---|---|---|---|
| `head_sha` | GitHub hands it to you | "Already audited this commit?" | Redelivered webhooks cause duplicate audits |
| `sha256(file_bytes)` | Computed per file | "Already parsed this file?" | Every re-run re-parses all 500 files |
| `(pattern_id, chunk_hash)` | Computed per chunk | "Already asked the LLM about this code against this pattern?" | You pay repeatedly for identical verification calls |
| Image tag | The build pipeline | "Which pattern library judged this?" | Findings stop being reproducible |

Different scopes: per-commit, per-file, per-chunk-per-pattern, per-release.

The third one lives in the retrieval path and is the most valuable, since
LLM verification is the dominant cost in the system. Note what it stores:
a pattern id, a hash, a verdict, a confidence, and a line range —
**verdicts, not embeddings and not source**. Nothing reconstructible back
into the customer's code, which is exactly why it can safely persist when
an embedding index could not.

**A unique constraint beats check-then-insert.** If you `SELECT` to see
whether a job exists and then `INSERT`, two concurrent handlers can both
pass the check before either inserts — producing exactly the duplicate you
were preventing. The constraint has no such window, and no application bug
can route around it.

**Cache invalidation trap.** Parse results are valid only for the exact
bytes that produced them *and* the exact parser version that read them.
Change the parser and every cached entry is silently stale. The cache key
needs a parser-version component; forgetting it produces wrong answers that
look completely normal.

---

## The queue is a table

The `audits` table *is* the queue:

```sql
SELECT * FROM audits
 WHERE status = 'queued'
   AND lease_expires_at < now()
 ORDER BY created_at
 FOR UPDATE SKIP LOCKED
 LIMIT 1;
```

Ordinarily `FOR UPDATE` makes a second transaction *block* until the first
commits. Build a queue that way with ten workers and nine wait on the same
row, wake one at a time, and find it already taken — a lock convoy, ten
workers delivering one worker's throughput.

`SKIP LOCKED` inverts it: a locked row is treated as though it doesn't
exist, so the query moves to the next candidate. Ten workers claim ten
distinct jobs with no coordination.

**Claiming is one transaction.** Selecting the row and marking it `running`
happen atomically. There is no window where a job is claimed but unmarked —
precisely the window where a naive `SELECT` then `UPDATE` hands one job to
two workers.

**The lease makes crashes survivable.** A running worker pushes
`lease_expires_at` forward as a heartbeat. If it dies, the heartbeat stops,
the lease goes stale, and `lease_expires_at < now()` makes the row
claimable again. That's the visibility-timeout pattern managed queues
charge for, in one timestamp column.

---

## Execution model: asyncio won't speed up parsing

`async` does not mean parallel. It means a function can *pause itself* at
an `await` and hand control back to an event loop, which uses the gap to
run something else. The win comes entirely from overlapping *waiting*.

Reading a file off disk is waiting. Parsing it into an AST is not — it's
CPU work holding the GIL. Ten `gather`ed parses interleave their file reads
and then queue up single-file for the actual parsing.

```
asyncio, 4 CPU-bound parses:   [A][B][C][D]        total 4T
ProcessPool, 4 parses:         [A]
                               [B]
                               [C]
                               [D]                 total T
```

So the split is by workload, not preference:

- **`ProcessPoolExecutor`** for read + parse — real parallelism across
  cores, which is what CPU-bound work needs.
- **`asyncio`** for everything that genuinely waits: LLM calls, GitHub API
  calls, database queries. Dozens of concurrent verification calls is where
  an event loop shines.

**Process pool gotcha.** Data crossing a process boundary is pickled and
copied. Send a *file path* to the pool and let the worker read and parse
it; sending parsed syntax trees back and forth costs more than the parse
saved. Misjudging this is the classic way to make a process pool slower
than a plain loop.

---

## What RAG actually is

Three words. **Retrieval** — look something up. **Augmented** — paste it
into the prompt. **Generation** — the model answers using it.

That's the whole definition. Vectors, embeddings, and databases appear
nowhere in it. They're implementation choices for the first word.

The classic example, a chatbot over company docs:

| | |
|---|---|
| Knowledge base | the docs |
| Query | "how do I request PTO?" |
| Retrieve | find docs matching the question |
| Augment | paste them into the prompt |
| Generate | model answers |

This project, same shape:

| | |
|---|---|
| Knowledge base | the pattern library — anti-patterns *we* wrote |
| Query | one chunk of the customer's code |
| Retrieve | find which patterns resemble this chunk |
| Augment | paste the pattern + the code into the prompt |
| Generate | model returns a verdict and a line range |

### This is a policy, not a technical impossibility

Worth being precise about, because it's a natural follow-up: nothing
stops an `INSERT` into a `pgvector` column right where a chunk gets
embedded. That vector exists, in memory, at that moment — the line would
run fine. The real safeguard is narrower: **no such table exists in the
schema**, so persisting requires someone to deliberately add a table and a
write path — a reviewable architectural change, not an accidental stray
write.

The argument for not adding it: nothing in this system ever queries "find
code similar to this code," so persisting would take on tenant-scoped
exposure of partially-invertible source for a feature nobody uses. (Also
considered and rejected: caching embeddings just to skip re-embedding
unchanged chunks, the same way parse facts are cached. Not worth it — local
embedding is cheap relative to the LLM verification call that's already
cached, so the performance win is small against an unchanged privacy cost.)

### Code is a query, not a corpus

The thing to hold onto: **there is one knowledge base here, not two.**

The pattern library is the corpus — the only thing ever looked *up*. The
customer's code is a stream of *queries*. Each chunk asks "am I any of
these anti-patterns?", gets scored against the pattern matrix, and its
embedding is discarded.

Nothing searches code against code, so there is nothing to index. The
privacy property falls out for free: chunk embeddings are never persisted,
not because a policy forbids it, but because no code path exists that
would. That's stronger than a retention rule — a rule can be forgotten, a
missing code path cannot.

You'd only need a searchable code index for features that compare code to
code: "this anti-pattern also appears in 12 other files," or pulling
related code in as verification context. Both useful, both post-MVP.

### "Fixed" describes the rulebook, not the matching method

Every pattern has its own vector — the build step embeds each `.md` file
separately, so `god-object` and `circular-imports` are different rows in
the same matrix. "Fixed" means the *set* of patterns doesn't change during
an audit, not that matching against them is exact.

The reason similarity search exists at all, given that the patterns are
known in advance: most of these concepts aren't reducible to a
deterministic check. "Flag files over 500 lines" needs no vector — it's
`len(lines) > 500`. "God object" isn't like that. It's not one method-count
threshold; some 40-method classes are fine, some 8-method ones are the
problem, and telling them apart is a contextual judgment, not a formula.

So the two stages do genuinely different jobs, neither of which exists
because the library is editable:

- **Similarity — the wide, cheap net.** "Does this chunk resemble the
  description at all?" Deliberately loose; missing a real candidate here
  costs more than passing along a few bad ones.
- **LLM verification — the actual judgment.** Claude reads the pattern's
  written definition and the real code and decides in context — the part
  a vector could never do, only narrow down to.

### Where the pattern vectors actually live

Three forms, three places:

| Stage | Location | Form |
|---|---|---|
| Source of truth | `patterns/*.md` in git | Hand-written markdown |
| Build time | Inside the container image | Compiled `patterns.npz` |
| Runtime | Worker process memory | numpy array, loaded at boot |

The `.md` files are what you edit; nothing at runtime ever reads them. A
Dockerfile step embeds them all and saves **two** arrays — `vectors`
(~100 x 768) and `ids` (pattern slugs, same row order). The matrix alone
is useless: the ids are what turn row 42 back into `god-object`.

At worker startup the file loads once, ~300KB resident, reused for every
audit that container handles. No per-audit load, no query, no connection.

**The silent-failure trap.** Stored vectors came from one specific model
version. If a worker embeds chunks with a *different* model, the query
vector lives in a different space and similarity returns pure noise — and
nothing raises. So the model id is stored alongside the vectors and the
worker refuses to boot on a mismatch. Fail loudly at startup rather than
quietly for months.

**Adding a pattern:** commit the `.md`, CI rebuilds the image (re-embedding
everything), deploy, workers restart. That's the version-locking that keeps
findings reproducible from an image tag. The image is big because of the
*embedding model* (hundreds of MB), not the patterns (300KB).

### "No vector database" never meant "no vectors"

Easy to conflate, because the words overlap. Two separate things were
rejected, and neither was the vectors themselves:

| Thing | Present? |
|---|---|
| Vectors / embeddings | **Yes** — every pattern and every chunk becomes one |
| A vector *database* (Qdrant, Chroma, pgvector) | No — a numpy array in RAM does the job at ~100 patterns |
| A persistent *index* of the customer's code | No — chunk vectors are used once, then discarded |

Retrieval *is* comparing a chunk's vector to a pattern's vector — remove
that and there's no retrieval step left. What got rejected was the
*infrastructure* (a database service to hold vectors) and the
*persistence* (writing the customer's vectors down anywhere), not the
technique. "Vector database" and "vector index" both carry "vector" as a
modifier on the part that was actually cut.

### Why no vector database

Finding a name in a list: with 10 names you read the list; with 10 million
you need an index. The index isn't *better*, it's better **at scale** — at
10 names, building it costs more than reading.

The entire retrieval step:

```python
scores = patterns @ chunk_vec      # compare against every pattern
top = np.argsort(-scores)[:k]      # keep the best k
```

Measured, at 100 patterns x 768 dimensions:

```
knowledge base: 300 KB (fits in CPU cache)
one chunk vs all 100 patterns:     7.5 microseconds
5,000 chunks vs all 100 patterns:  4.0 ms   (one matmul)
```

That's *exhaustive* search, skipping nothing. A vector database exists to
provide an approximate index (so you can skip comparisons), persistence,
metadata filtering, concurrent access, and sharding. At this size none of
those are needed — and a network round-trip to a vector service would cost
more than the 4ms of work it was meant to save.

Still RAG: retrieve, augment, generate. All three steps present. The
database was never part of the definition.

---

## Retrieval: similarity finds candidates, verification finds bugs

Vector similarity answers "does this resemble the god-object entry." It
does not answer "is this a god object." Shipping similarity scores directly
as findings produces false positives at a rate that teaches developers to
ignore the tool — and an ignored tool has no value regardless of recall.

```
AST chunks -> embed -> similarity vs pattern matrix -> ~40 candidates
           -> LLM verify (pattern + real code, tool schema) -> 6 findings
```

Chunking uses the syntax tree rather than line counts. The parse layer
already produced an AST, so chunks cut on natural boundaries — one function
or class each — and a retrieved chunk is always semantically complete.
Fixed-size chunking would routinely split a function in half and destroy
the thing being matched.

Verdicts are cached on `(pattern_id, chunk_hash)`: identical code checked
against an identical pattern cannot produce a different answer, so it
should not cost a second call.

### The inspector analogy

A home inspector arrives at your house carrying a **codebook** — the list
of what counts as a violation. Same book at every house, the inspector's
own property, small, kept permanently. What they do *not* carry is a
searchable archive of your house. They walk through it, check what they see
against the codebook, write findings, and leave.

The codebook is the pattern library. Your house is the code being audited.
The inspector looks things up in the codebook; the house is what generates
the questions.

**Why the codebook isn't in a shared database.** March: the tool flags
`billing/invoice.py` as a god object. September: a developer asks why. You
check out the commit; the code is right there, unchanged. But if the
pattern library lived in a database that's been edited forty times since,
the "god object" entry now has different symptoms and a different
threshold. You have the house and the report, but not the rule it was
judged against — the finding is unreproducible. Baking patterns into the
image staples the exact edition to the report.

Note this argument has nothing to do with privacy. The pattern library is
*our* data. The reason is reproducibility: patterns are code, versioned
with the release that reasons about them.

**Why nothing about the house is kept.** A customer's security team asks
what you retain. If chunk embeddings were indexed and stored, the honest
answer is *"vector embeddings of every function in your codebase"* — and
the follow-up is "can those be reversed?", to which the answer is
*partially, yes*. Saying "we didn't keep your source, only the embeddings"
is like saying "I didn't keep photos of your house, only a precise 3D
scan." Not the reassurance it sounds like.

Because code is only ever a query, the real answer is simply: *"nothing but
findings — a file path, a line number, and a verdict."*

| | Pattern library | The code being audited |
|---|---|---|
| Role | The corpus — the thing looked up | The queries — one per chunk |
| Whose data | Ours, hand-written | The customer's source |
| Lifetime | Permanent, versioned in git | Discarded as the scan proceeds |
| Size | ~100 entries | Thousands of chunks |
| Storage | Matrix baked into the image | Not stored at all |
| Deciding reason | It's *code*, not data — a database lets the library version drift from the release | Nothing searches code against code, so there is nothing to index |

**Two separate arguments, easily conflated.** "So we don't hold people's
source code" explains why *the code* isn't stored. It says nothing about
why the pattern library — our own data — also skips a vector database.
That one is about reproducibility, and it's the half most people miss.

---

## Tracing: a trace that stops at the queue isn't distributed

A trace is a tree of spans linked by IDs. Inside one process the SDK
threads that context implicitly — call a function and its span finds its
parent automatically.

But the webhook handler returns `202` and exits. Minutes later a different
process on a different machine claims the job. There is no in-memory link.
Instrument both sides naively and you get two unrelated traces — and *how
long from PR opened to check posted* becomes unanswerable.

The fix is to serialize the context and carry it through the queue as data.
W3C defines a `traceparent`:

```
00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
│  │                                │                └─ flags
│  │                                └─ parent span id
│  └─ trace id
└─ version
```

Injected into the job row at enqueue, extracted when the worker claims it,
so the worker's span is a child of the webhook's. The queue wait becomes a
measurable gap rather than a blind spot.

This matters beyond tidiness: the p99 latency problem will eventually be
queue depth, not agent speed. Without propagation you'd stare at fast
worker traces wondering why users say the tool is slow.

---

## Questions this project invites

**"You built a RAG system but didn't use a vector database."**
There's one corpus — the pattern library, ~100 hand-written entries.
Customer code is a stream of queries against it, never an indexed corpus,
so most of what a vector DB provides has nothing to act on. Exhaustive
search over the library is one matmul: ~8 microseconds per chunk, 4ms for a
whole repo, 300KB resident. An ANN index would add a network hop to skip
work that doesn't need skipping. The library also stays out of a database
for a second reason: patterns are code, versioned with the release, so a
finding stays reproducible from a commit SHA. Name where the ANN threshold
sits (~10k vectors) and what would move you past it.
*Trap: answering only the privacy half. That explains why code isn't
stored; it says nothing about the library, which is our own data.*

**"Why Postgres as a queue instead of Redis?"**
Job state, lease, trace context, and findings commit in one transaction. A
separate broker introduces the dual-write problem — queue and database can
disagree about whether a job ran. `SKIP LOCKED` makes it a correct queue,
not a hand-rolled approximation. Honest limit: Redis wins on throughput,
but audits are minutes long so the queue sees single-digit ops/sec.

**"How do you know an audit ran exactly once?"**
You don't, and can't. At-least-once delivery plus idempotent processing
gives effectively-once. Three layers, each with a different key and
different invalidation. A unique constraint beats check-then-insert under
concurrency.

**"Your agents disagree. What does the report say?"**
Disagreement is surfaced, not averaged away — it's information about
confidence. Independent agreement raises confidence precisely because the
agents don't read each other. Ranking arithmetic is deterministic Python;
the LLM writes prose, never the score, because "why was this ranked first"
needs an answer that doesn't vary per run.

**"What's the weakest part of this design?"**
The Scalability Analyzer — heuristics over graph metrics with no
verification step to ground it. And the call graph is approximate: Python
resolves calls dynamically, so static analysis misses real edges and
invents plausible ones. Findings are tagged by which graph produced them,
and call-graph findings carry a confidence ceiling. Naming a real weakness
with a mitigation reads stronger than claiming there isn't one.
