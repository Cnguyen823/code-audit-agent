# Lessons

Patterns worth not repeating, captured after corrections. Working file for
Claude — see the note in `docs/learning.md` for how this differs from the
project's own documentation.

---

## 1. Test the premises in a spec, don't implement them

**What happened.** The project spec listed "RAG over two separate stores
(ephemeral codebase index + permanent pattern library)" under "the hard
parts." I designed the architecture around that requirement without
checking whether it held. It didn't: nothing in the system ever searches
code against code, so the index had no reader. It survived several rounds
of explanation — including two attempts to justify it as "two opposite
corpora" — before a direct question from the user exposed that there was
nothing to justify.

**Why it survived.** Indexing a codebase is genuinely correct for a large
class of code tools (Cursor, Sourcegraph) where the repo is the corpus and
the user's question is the query. This system runs the other direction:
code is the query, the pattern library is the corpus. Same domain, opposite
data flow, and the pattern-match was strong enough to override inspection.

**Compounding factor.** The spec was itself generated in an earlier Claude
session. A guess hardened into a written requirement, came back as input,
and got treated as a given. Documents you produced returning as
specifications deserve *more* scrutiny, not less.

**The rule.** For any proposed store, index, cache, or queue, name the
reader before designing it in: *what queries this, and with what?* If the
query can't be stated in one sentence, the component doesn't belong yet.
Applies equally to requirements handed down in a spec — a spec is an input
to the design, not a substitute for it.

**Tell.** Needing more than one attempt to explain why a component exists
is evidence about the component, not about the explanation. When a
justification keeps needing to be rephrased, check whether it's justifying
something that shouldn't be there.

---

## 2. Answer the question that was asked, not the adjacent one

**What happened.** Asked in an interview drill why the project uses no
vector database, the user answered "so we don't hold people's source code."
Correct reasoning, wrong question — that explains why *customer code* isn't
stored, not why the *pattern library* (our own data) skips a vector store.

**The rule.** Before answering, pin down which decision is being asked
about. Two adjacent decisions with different justifications are the
easiest place to give a confident, well-reasoned, wrong-question answer —
and the follow-up is unanswerable once you've committed to it.

*(Kept here as a coaching note: this one is the user's pattern to watch,
recorded because the same failure mode applies to me.)*
