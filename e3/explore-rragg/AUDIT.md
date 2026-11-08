# Audit of the A6 DERIVED lead (offline, zero API calls)

**Date:** 2026-10-24, about 19:00–19:10 IST.

**Inputs (all read-only):**
- E2 CONFIRM data and runs: the ledger with BRIDGE events, the tasks, `answers.jsonl`, the A6 and RR stores, `stats.json`, `log.json` and `render_trace`.
- The pinned local embedder and reranker.

**Script and output:** `audit.py` writes `AUDIT.json`. It covers all 320 DERIVED tasks, including the 89 "gold in header, touched" tasks, and all 401 final A6 summaries across the 32 streams.

**Reproduction check:** the rebuilt RR cosine top-50 plus rerank reproduced E2's served RR list on 320 of 320 tasks.

## Retraction
REPORT.md said that on touched tasks A6's summaries "were built before the deletions and so they still hold the value". **That is wrong.**
- Of the 184 summaries served on the 89 tasks, 179 were recomputed at probe time, after every forget.
- The other 5 were computed in the warm phase. None of their dependencies was ever deleted, so they were never invalidated.
- No served summary has a deleted session in its lineage.

The real mechanism is set out below.

## 1. Provenance
**Gold structure.** Every DERIVED gold is a 2-leaf composition:
- the **ref** leaf: `svc_owner` or `proj_lead`, i.e. who owns or leads the entity;
- the **attr** leaf: `office_city` or `team_name` of that person.

**Gold sources are surviving and present.**
- All leaf evidence sessions survive: 0 of 320 tasks have a deleted support or leaf session.
- Every leaf has a surviving raw chunk that contains its value literal (320 of 320).

**Number of separate surviving sessions needed** (minimum cover of the two leaves):
- 2 sessions for 318 tasks;
- 1 session for 2 tasks;
- 2 sessions for all 89 tasks in the target subset.

**Direct inference statements.** Some sessions also render an *inference statement* of the derived key, such as "X's lead sits in Mumbai". A surviving statement states the gold value directly in:
- 10 of 89 tasks in hdr-gold-touched;
- 54 of 79 in hdr-gold-untouched;
- 15 of 99 in hdr-nogold-touched;
- 34 of 53 in hdr-nogold-untouched.

In 44 of the 89 tasks, the key's inference statement is in a deleted session.

**What deletion does to a task.** Deletion removes the one-hop route: it deletes the inference statement or makes it stale (value_changed in 41 of 89). The task can then be answered only by composing the two leaves.

**Served summaries for the 89 tasks:** 184 in total.
- 179 were computed in the probe phase, after all forgets.
- 5 were computed in the warm phase, with all dependencies surviving.
- In 70 of the 89 tasks, the summary that carries the gold literal has the **attr leaf chunk in its dependencies**. Example: node n09, "Offices: … Ines Chennai (2030-02-04) …". The gold literal comes from the surviving attr fact.

## 2. Residue leak check
**What E2's leak metric checks.** It is the `run_e2.run_stream` integrity gate, which raises on failure. It runs at t_end after the last forget and **before any probe**. It is a structural lineage check:
1. No A6 unit comes from a deleted session.
2. No write-back has a `derived_from` id from a deleted session. This id set is the closure of everything served when the write-back was made.
3. No cached summary has a dependency (input-set unit id) from a deleted session.
4. No RR chunk comes from a deleted session.

It was clean on all 32 streams.

**What it would and wouldn't catch.**
- It would catch any summary or write-back whose recorded input set includes deleted units. `forget()` also cascades: doomed write-backs are removed and caches with doomed dependencies are invalidated.
- It does **not** check summaries created during probes, because it runs before them. Here 650 of 664 served DERIVED summaries were probe-time.
- It does not check **content**. A summary text could carry a value that is absent from its dependencies only if the dependency record were wrong.

**This audit closes both gaps.**
- Across all 401 final A6 summaries (32 streams, every class), lineage, with write-backs resolved recursively, includes a deleted session **0 times**.
- 0 dependencies are missing from the store.
- A literal scan of every ledger value of 3 or more characters found **0** values in any summary text that are absent from that summary's own dependency texts. So nothing in a summary is unexplained by surviving inputs.
- Write-backs: none survive in any final store.

**Result: no residue leak.**

## 3. Where RR loses the gold
For each leaf: is it in RR's cosine top-50, and is it in the served 2000-token context?

| subset | n | ref leaf served by RR | attr leaf in top-50 | attr leaf served by RR | attr cosine rank, median | A6 header has attr leaf |
|---|---|---|---|---|---|---|
| hdr-gold, touched | 89 | 89 | 5 | 5 | 264 | 72 |
| hdr-gold, untouched | 79 | 78 | 3 | 2 | 286 | 59 |
| hdr-nogold, touched | 99 | 97 | 0 | 0 | 311 | 33 |
| hdr-nogold, untouched | 53 | 52 | 1 | 1 | 317 | 18 |

RR almost always retrieves the ref leaf (cosine rank median 2–3). The attr leaf never shares the question's terms: the question names the entity, not the person. So the attr leaf is outside the top-50 in 311 of 320 tasks.

**This is a retrieval effect, not a budget effect.** An attr leaf was in the top-50 but cut by the 2000-token fill in only 1 of 320 tasks.

**Accuracy split by whether a surviving inference statement states the gold:**

| subset | inference states gold? | n | RR | A6 | A6-syn |
|---|---|---|---|---|---|
| hdr-gold, touched | yes | 10 | .900 | .800 | 1.000 |
| hdr-gold, touched | no (composition needed) | 79 | .063 | .481 | .063 |
| hdr-gold, untouched | yes | 54 | .981 | .926 | .944 |
| hdr-gold, untouched | no | 25 | .000 | .520 | .000 |
| hdr-nogold, touched | yes | 15 | .933 | .867 | .867 |
| hdr-nogold, touched | no | 84 | .000 | .012 | .048 |
| hdr-nogold, untouched | yes | 34 | 1.000 | .765 | .853 |
| hdr-nogold, untouched | no | 19 | .053 | .105 | .105 |

## 4. Verdict
Counted on the 50 DERIVED tasks where A6 is right and RR is wrong:

| category | all 50 | of which in hdr-gold-touched (33) |
|---|---|---|
| (a) composition: RR served both leaves and still failed | 1 | 1 |
| (b) retrieval: attr leaf not in RR's top-50 | 49 | 32 |
| (b′) budget: attr leaf in top-50 but not served | 0 | 0 |
| (c) residue of deleted content | 0 | 0 |
| (d) gold-computation bug | 0 | 0 |

Every one of the 50 tasks needs 2 surviving sessions. A surviving inference statement gives the gold directly in only 2 of the 50.

Coverage counts over all 320 tasks: (a) RR had both leaves in 8; (b) the attr leaf was missing from the top-50 in 311; (b′) budget in 1; (c) 0; (d) 0. In the reverse direction, 15 tasks have RR right and A6 wrong. All 15 are tasks where a surviving inference statement states the gold, i.e. one-hop tasks.

**Conclusion: (b), realised through legitimate composition over surviving data.**
- RR's question-conditioned single-shot retrieval cannot reach the second hop.
- A6's query-independent node summary ("latest office or team per person") puts that surviving fact in the header.
- The answerer then composes the two leaves.

**Why it showed up as "touched".** Deletion turned one-hop tasks (the inference statement survives) into two-hop tasks. This also explains RR-agg ≈ RR: a note written from RR's text cannot contain a fact that RR never retrieved.

## 5. Implications
**E2 "no leaks" claim.** It stands, but the paper should state exactly what was checked:
- E2 ran a pre-probe structural lineage check (units, write-backs, summary dependency sets, RR chunks).
- This post hoc audit extends it to all final summaries, including the probe-time ones that E2's gate did not cover, and adds a content-literal scan.
- Both found 0.

Suggested wording: "No deleted session appears in the lineage of any stored or served derived artefact, checked structurally at t_end and, post hoc, for every final summary, including those recomputed at probe time; no summary contains a ledger value absent from its own surviving inputs."

**O2 interpretation.** Unaffected: there is no leak and no gold bug.

**E3 framing.** Before freezing, E3 should frame the DERIVED lead as *query-independent aggregation surfacing second-hop facts* rather than a general deletion advantage. Its fairness arms should include an RR baseline that can reach hop 2.
- RR-k (top-200) would put the attr leaf in the candidate pool for only 23 of the 50 discordant tasks (cosine rank ≤ 200; median 215), and reranking would still have to promote it.
- A two-hop or iterative RR arm (retrieve, extract the entity's person, retrieve again) is the natural fair comparator. Its absence is the main threat to a DERIVED-only E3 claim.
- The RR-agg decision rule's "freeze" outcome should therefore be read as "the lead is not about when aggregation happens". It is not yet evidence that a fair retriever loses.
