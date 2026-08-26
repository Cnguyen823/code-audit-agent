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
