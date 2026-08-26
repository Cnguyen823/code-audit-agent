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

1. **Claude writes the code.** Every experiment/component gets implemented
   directly, then explained in depth — what it does, why it's built that
   way, and what the alternatives would have cost.
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
implements each one and explains it in depth; move to the next only once
the user confirms they've got it (rule #2), and before any `src/` code
gets written.
