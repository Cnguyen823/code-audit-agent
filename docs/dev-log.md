# Development Log

Daily diary: what got worked on, where it fought back, how it actually got
resolved, how long it took, what would change next time. Dated entries,
newest at the bottom, separated by `---`. Honest, not polished — dead ends
included, that's the point.

---

## 2026-08-26

Session one. No production code today — this was almost entirely project
setup and architecture, and that turned out to be the right call rather
than a delay, since two real design mistakes got caught before either one
was built on top of.

Scaffolded the repo: README, docs structure, `experiments/`, `patterns/`,
`tests/`, `src/`.

Process correction, worth recording plainly: Claude wrote and ran an
`async_fetch.py` experiment during this session, without walking through it
with me first. Today was scoped as planning and architecture only — no
code yet — and it should have stayed that way regardless of which mode
we're in for who types the code. Removed the file. First real code, on
whichever day that starts, gets reviewed together before it counts as
done, not narrated after the fact.

Original plan had me writing all the code myself with Claude coaching from
the side — quiz-before-phase, small adapted snippets, no full
implementations. Reversed that almost immediately: I wanted depth of
understanding over hands-on-keyboard practice, so the working agreement
flipped to Claude implementing and explaining in depth, checking my
understanding before moving on. Recorded in the project's own `CLAUDE.md`
so it doesn't quietly drift back.

Then the real work: decided this becomes a GitHub App (not a CLI or a
hosted SaaS) — the PR-review loop is where an audit tool actually changes
behavior, and the ten-second webhook deadline that decision forces turned
out to determine almost everything downstream. Worked through the whole
cascade out loud: can't audit inline -> needs a worker -> needs shared
state -> rules out SQLite -> Postgres becomes the job queue via
`FOR UPDATE SKIP LOCKED`, LangGraph orchestrates the three agents with a
separate content-hash cache for file-level resume, local embeddings keep
bulk source off third-party servers, Fly.io hosts it.

Two real mistakes surfaced and got fixed before any of it was built:

**The codebase index.** Original spec called for "RAG over two separate
stores — an ephemeral codebase index plus the permanent pattern library."
Claude designed straight to that without questioning it, and it took me
asking the same question a few different ways before either of us could
cleanly explain why an index of the customer's code needed to exist at
all — the actual question that broke it open: *what queries this thing?*
Nothing does. The Pattern Checker only ever asks "does this chunk resemble
one of ~100 fixed patterns" — that's a query against the pattern library,
not a lookup in a corpus of code. Pulled the index entirely. Better outcome
than the original design: the privacy story got *stronger* by having no
reader, not just a policy against writing.

Root cause, worth remembering: that "two stores" spec came from a project
prompt Claude itself had generated in an earlier session, which I then
pasted back in as the starting spec for this one. A guess hardened into a
written requirement, came back as input, got treated as a given. Logged in
`tasks/lessons.md` — test what a spec asks for before designing around it,
especially one Claude wrote for itself.

**Overclaiming the safeguard.** Claude said at one point that persisting a
chunk's embedding was structurally impossible — "no code path exists that
would." Not true. An `INSERT` at the embedding call site would run fine;
the actual safeguard is narrower — no `code_vectors` table exists in the
schema, so persisting requires someone to deliberately add one, which is a
reviewable change rather than an accidental line. Caught when asked
directly why the already-embedded vector couldn't just go into the
Postgres that's already running. Correct answer held up; the framing
around it didn't, and got fixed in `docs/decisions.md` rather than left
standing.

Had Claude write up all of it: `docs/architecture.md` (full system design, including
the pattern-discovery idea I deliberately deferred rather than dropped —
auto-discovering *new* anti-patterns is a real but much harder unsupervised
problem, not a variant of the fixed-rulebook retrieval this MVP does),
`docs/decisions.md` (twelve entries, options/chosen/reasoning/tradeoffs),
and `docs/concepts.md` as a standalone teaching reference — the mechanism
behind each decision, a full request walkthrough, and the interview
questions this project invites, since half the value of building this is
being able to defend it out loud.

What I'd do differently: question the spec's own premises before
designing to them, not after struggling to explain the result. The
"what queries this?" test would have caught the codebase index on day one
instead of three corrections in.

Next: Week 1 experiments proper, starting tomorrow — `async_fetch.py`
first, walked through together as it's written, not created and explained
after the fact.

---

## 2026-09-08

Session two, and the first real code of the project: `experiments/async_fetch.py`.
Built it in three steps, together, each one reviewed as it happened
instead of explained afterward — the thing session one's mistake was
about, and this time it actually held.

Started with a plain sync version — fetch 20 fake files one at a time,
just `time.sleep` standing in for GitHub latency. About 6.3 seconds. Not
interesting on its own, just a real number to compare against instead of
guessing.

Then the async version, no limits: same 20 fetches, about half a second.
The point wasn't the speedup, it was understanding why it happened —
`asyncio.sleep` lets the program go do something else while it waits,
and `gather` is what actually runs a bunch of those waits at once. On
their own, neither one buys you anything, which is an easy thing to miss
if you're skimming the code instead of thinking about it. Also worked out
why this trick does nothing for CPU-heavy work instead of waiting —
there's only one thread, and it can only switch tasks at the exact points
where something says "go ahead and wait," so CPU work just hogs it start
to finish either way.

Last, a bounded version using a semaphore, capping how many fetches run
at once. Tried a few different caps and watched the time move between
the two extremes from before.

The real roadblock today wasn't the code, it was figuring out what should
actually decide that cap. First instinct was "base it on how many files
are in the PR" — which is backwards. That number should come from
something GitHub itself enforces (their own rate limits), not from
whatever happens to be in front of you at the time. Took a few tries to
land, but it clicked into a rule worth keeping: for any hardcoded number,
ask what actually enforces it and what breaks if you ignore it. If there's
no real answer, you're not looking at a real constraint yet.

The other roadblock was more about how we work than the code: partway
through, I got asked a question, kept talking through it instead of
giving a clear yes, and the semaphore code got written anyway. Fair catch
— fixed it going forward. From here on, describe the edit first and wait
for an actual go-ahead before making it, every time, not just for the big
stuff.

Stopped before handling what happens when a fetch fails — `gather`
doesn't clean that up nicely on its own — rather than cramming a fourth
idea into an already full day. That's next, then on to
`idempotent_parser.py`.
