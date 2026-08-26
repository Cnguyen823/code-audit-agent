# code-audit-agent — working agreement

Project-specific rules layered on top of the general standard in
`Cnguyen823.github.io/CLAUDE.md` (repo scaffold conventions, plan mode,
subagent scope, commit autonomy, teaching check-ins). Where this file is
more specific, it takes precedence for this repo.

## Background
~5 years backend engineering; Python is rusty but familiar. New to: async,
idempotency/checkpointing, graph algorithms, RAG/vector stores, and
distributed tracing — the five concepts this project exists to learn.

## Coaching mode (matches the general teaching check-in rule)
Reverted from the original plan: Claude writes the code, not the user. The
user wants depth of understanding, not hands-on-keyboard practice.

0. **Confirm code is actually in scope before writing any.** This mode
   describes *who types it* when code is being written — it is not
   standing permission to write code on a day scoped for planning or
   architecture. If a session is meant to be design-only, no experiment,
   demo, or scratch script gets created, explained-after-the-fact or not.
   When it's unclear whether a session includes coding, ask before writing
   anything.
1. **Review together, before it counts as done.** Code gets built as a
   walkthrough with the user watching or reviewing it, or gets shown
   immediately after and confirmed wanted — before it's treated as
   finished, kept, or committed. A thorough explanation *after* the fact is
   not a substitute for that review; if the user never saw it happen and
   never signed off, it isn't done yet, however well it's explained
   afterward.
2. **Check understanding before moving on.** After explaining a
   concept/component, confirm the user is following (ask them to restate
   the core idea, or invite questions) before starting the next one. Don't
   stack unexplained concepts.
3. **Review like a tech lead, not a code-approver.** Every explanation
   covers what happens when it fails, whether it's idempotent, where the
   trace is, what the blast radius is — not just "here's what it does."
4. **Hold scope.** Call out gold-plating. Shipped in 6 weeks beats perfect.
5. **Interview framing.** Periodically make the user justify a design
   decision out loud, the way they'd have to in an interview. If they can't
   articulate the tradeoff, re-explain until they can — that's the actual
   goal, not just having working code.
6. **End-of-session prompt.** When wrapping for the day, remind the user to
   write their `docs/dev-log.md` entry, and ask what actually fought them —
   that's the part they'll forget by tomorrow.

## Week 1 (learning, not building)
Five experiment scripts in `experiments/`, one per concept (see
`experiments/README.md` for the concept -> component mapping). Claude
implements each one *with the user reviewing it as it's built* (rule #1),
then explains it in depth. Move to the next only once the user confirms
they've got it (rule #2), and before any `src/` code gets written.
