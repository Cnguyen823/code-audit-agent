# Experiments

Small, self-contained scripts, one per new concept, each solving a
scaled-down version of a problem the real system will hit later. Written by
hand before any `src/` code exists. Each maps to a real component:

| Script | Concept | Becomes |
|---|---|---|
| `async_fetch.py` | async orchestration | Agent 1's parallel parse orchestration |
| `idempotent_parser.py` | idempotency / checkpointing | the checkpoint/resume strategy |
| `dependency_graph.py` | graph algorithms | Agent 1's core |
| `rag_chunking.py` | RAG / vector stores | both indexing paths (ephemeral + permanent) |
| `tracing.py` | distributed tracing | the observability backbone |
| `mini_audit_system.py` | integration | first draft of the orchestrator |

Work through these one at a time, in order — each one is small enough to
finish in isolation before it has to compose with the others in
`mini_audit_system.py`.
