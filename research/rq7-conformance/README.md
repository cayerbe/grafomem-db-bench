# RQ7 — Conformance instrumentation (the falsifiable core)

W5/W6 two-sided suite run against commercial engines via GMP adapters.
Report the **7a engine-correct** vs **7b engine-as-deployed** split separately:
a 7a PASS with a 7b LEAK is the headline. Extend targets to the adjacent memory
layers (mem0, Zep, MemCP, LangGraph/LlamaIndex stores) — likeliest place to
observe claims-but-leaks in the wild.

Adapters and the cost pairing live in `../../harness/rq9/`.
