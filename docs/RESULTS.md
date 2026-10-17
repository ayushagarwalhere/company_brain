# Results: every measurement, with the command that produced it

The [README](../README.md) summarises these. Raw output is in [`benchmark/results/`](../benchmark/results/), and
[`tests/test_readme_numbers.py`](../tests/test_readme_numbers.py) checks the key numbers here against those files.

## Ablation: switch the graph off, piece by piece

`python -m benchmark.ablation` → [`benchmark/results/ablation.json`](../benchmark/results/ablation.json). Rules extractor, deterministic, no LLM. CI fails if the full graph drops below drift P/R 1.00, or if removing version reasoning stops making drift worse.

| Configuration | Msg→feature P / R | Changes P / R | Drift (requirement) P / R | Stale PRs P / R |
|---|---|---|---|---|
| **Full graph** | 1.00 / 0.92 | 1.00 / 1.00 | **1.00 / 1.00** | **1.00 / 1.00** |
| − thread structure (`REPLY_TO`) | 1.00 / **0.77** | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| − person/time proximity for PRs | 1.00 / 0.92 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| − version reasoning (`SUPERSEDES` / `IMPLEMENTS`) | 1.00 / 0.92 | 1.00 / 1.00 | **0.50** / 1.00 | 1.00 / **0.00** |
| − time-aware IMPLEMENTS fallback | 1.00 / 0.92 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| Ticket IDs only (no threads, proximity or semantic) | 1.00 / **0.33** | 1.00 / **0.50** | 1.00 / **0.00** | 1.00 / **0.00** |

- **Without version reasoning, half the alerts are false and no stale PR is found.** Two changes were written back into their tickets, but nothing knows the tickets caught up. And with no `IMPLEMENTS` edges, PRs #5 and #6 (merged after the decisions) are only "unmatched", not stale.
- **The "half" is 2 of 4 alerts.** The demo has two real drifts, so every ablation number here is a small-n result.
- **With ticket IDs only, both real drifts are missed.** The deciding messages never name a ticket.
- **Person/time proximity and the IMPLEMENTS fallback make no difference here.** The demo never has a PR that implements a chat decision directly. The fallback matters where that happens: in [`tests/test_implements_fallback.py`](../tests/test_implements_fallback.py), and in the qwen3 build below, where it removes qwen3's one false drift.

## Results

Every number comes from the command shown with it. Raw output is in [`benchmark/results/`](../benchmark/results/).
- **Rules** = the rule-based extractor, no LLM.
- **qwen3:8b** = the LLM extractor running a local model through Ollama ([setup](DETAILS.md#setup)).

- **gpt-oss-120b** = OpenAI's open-weight 120B model on Groq's free tier (`reasoning_effort=low`), run on 2026-10-17 for the real-data extraction and the agent Q&A only. The free tier's daily limits didn't allow the full noise run.

Nothing below mixes extractors in one number.

### 1. Synthetic company: resolution and drift

`python -m pipeline.build --extractor heuristic && python -m benchmark.score_resolution` (rules) and `python -m pipeline.build --extractor llm --graph llm_demo && python -m benchmark.score_resolution --graph llm_demo` (qwen3:8b, [result](../benchmark/results/resolution_llm_qwen3-8b.json)).

| Metric (P / R) | Rules | qwen3:8b |
|---|---|---|
| ticket → feature | 1.00 / 1.00 | 0.60 / 1.00 |
| message → feature | 1.00 / 0.92 | 0.59 / **1.00** |
| PR → ticket (incl. PR #7 with no ticket id) | 1.00 / 1.00 | 1.00 / 1.00 |
| requirement changes from chat | 1.00 / 1.00 | 0.67 / 1.00 |
| drift (ticket) | 1.00 / 1.00 | 1.00 / 1.00 |
| drift (requirement) | 1.00 / 1.00 | 1.00 / 1.00 |
| stale PRs / stale docs | 1.00 / 1.00 | 1.00 / **0.50** · 1.00 / 1.00 |

- **The rules score 1.00 because I wrote them while looking at this data.** Treat that as an upper bound.
- **qwen3 finds the paraphrased SLA thread the rules miss** (message → feature R = 1.00).
- **qwen3 groups one-off tickets into 5 extra features**, so the feature-link precision drops.
- **qwen3 makes no IMPLEMENTS judgment of its own.** It reads a "columns" remark (m_exp_07) as a change. The time-aware fallback then links PR #6, which ships those columns, to it. Without the fallback this was a false drift.
- **qwen3 misses PR #5 as stale (stale-PR recall 0.50).** It makes no IMPLEMENTS link from PR #5 to the old BD-103 text, and PR #5 merged after the decision, so the stale-PR rule calls it "unmatched, may implement the new scope". This dropped from 1.00 when that rule was tightened (the rules extractor does make the link). Rebuilt from the committed cache with no live model.

### 2. Graph vs. a relational baseline

`python -m benchmark.sql_baseline` → [`sql_baseline.json`](../benchmark/results/sql_baseline.json). `resolve()` runs once. Its plain-data output goes into an in-memory SQLite database:
- requirements, chat changes and PR → ticket links;
- IMPLEMENTS judgments;
- the supersession pairs computed in Python.

The SQL side never reads the graph. Two SQL variants:
- **`sql_chain`:** drift as an anti-join over the same supersession pairs.
- **`sql_latest`:** no version chain; the "current" requirement is simply the newest per ticket (`ROW_NUMBER()`).

| Dataset | Graph drift found (true / false) | `sql_chain` | `sql_latest` | p50 drift query: graph / `sql_chain` |
|---|---|---|---|---|
| Demo (300 messages) | 2 / 0 | **identical** | identical | 2.1 ms / 0.01 ms |
| Demo + 500 noise messages | 2 / 14 | **identical** | 0 / 5, **misses both** | 4.9 ms / 0.02 ms |
| Stress test (20,800 messages) | 100 / 0 | **identical** | identical | 33 ms / 0.4 ms |

Timings are from the committed run and vary by about ±30% between runs on the same machine.

`sql_chain` also returns the same stale PRs and the same current requirement per ticket on all three datasets.

Lines of query code: Cypher `DRIFT` has 24, against 6 for `sql_chain` and 8 for `sql_latest`. The Cypher query also gathers the evidence (author, previous version, stale PRs, docs), and it runs over the network to FalkorDB, so neither comparison is like-for-like.

**What this means:**
- **Drift detection is a join.** The value is in the version-chain reasoning (`supersession_pairs`, `reflects`), which is application logic, not something only a graph database can do.
- **Without that chain, a relational query falls into the old "latest message wins" trap** under noise.
- **What the graph still gives** (none of this is measured as a speedup here):
  - variable-depth connection questions ("how is liam connected to PR #6?") via `algo.SPpaths`, where SQL needs recursive CTEs;
  - the evidence path returned with every answer;
  - adding a new node or edge type without a schema migration.

### 3. Q&A: graph vs. retrieval

**At scale:** `python -m benchmark.qa_scale` → [`qa_scale.json`](../benchmark/results/qa_scale.json). The stress-test org (200 features, 20,800 messages), rules agent vs. top-k TF-IDF passages returned verbatim, questions generated from ground truth (seed 0).

| | Per-feature (n = 18) | Cross-feature (**n = 3**, F1 over ids named) |
|---|---|---|
| graph (rules agent) | 1.00 · 18/18 | 1.00 · 3/3 |
| retrieval top-25 | 1.00 · 18/18 | 0.15 · 0/3 |
| retrieval top-100 | 1.00 · 18/18 | 0.40 · 1/3 |

- **Per-feature questions are a tie.** Retrieval doesn't degrade at 20k messages here: topic words are unique and the noise is generic.
- **The cross-feature win is n = 3, and partly by construction.** Each answer is 100 ids spread over 200 features, which top-k retrieval can't return, so this mostly shows the limit of top-k, not graph intelligence. A relational query answers these too (section 2).
- **Top-100's 1.00 on "which tickets are stale" is an artifact:** drifted tickets have shorter passages.
- **The router was tuned after seeing these questions.** The third question was a routing miss before the router fix, so this agent result is not held-out.

**Demo Q&A** (15 questions, 300 messages). The grader checks required facts per question with **whole-word** matching (a plain substring test let "sla" match inside "slack"); q11 must also name XLSX. A keyword list still passes, so read the answer lengths too. `python -m benchmark.run --no-llm` → [`latest.json`](../benchmark/results/latest.json) and `python -m benchmark.run` with qwen3:8b configured → [`latest_llm_qwen3-8b.json`](../benchmark/results/latest_llm_qwen3-8b.json).

| System | Mean score | Fully correct | Mean answer length |
|---|---|---|---|
| graph, rules agent (no LLM) | **0.86** | 10/15 | 921 chars |
| retrieval top-3, extractive (no LLM) | 0.52 | 4/15 | 700 chars |
| retrieval top-25, extractive (no LLM) | **0.98** | 14/15 | 4,515 chars |
| graph, **LLM agent (qwen3:8b)** | **0.33** | 4/15 | 308 chars |
| retrieval top-25 → **qwen3:8b** | **0.82** | 11/15 | 241 chars |
| graph, **LLM agent (gpt-oss-120b)** | **0.84** | **11/15** | 395 chars |
| retrieval top-25 → **gpt-oss-120b** | **0.71** | 8/15 | 423 chars |

- **Retrieval wins this benchmark.** The rules agent misses q01 (it reads "ticket" as the export feature and leaves out SLA), q03, q05, q11 and q14. The top-25 dump contains nearly everything, at five times the length.
- **The router was tuned on q03 before this grader existed,** so the rules result is not held-out. The router fixes made after the stricter grading (unknown ids, ticket-scoped answers) left this score unchanged.
- **The qwen3 rows are re-graded from the stored answers;** the model was not re-run.
- **With a strong model the graph agent beats retrieval into the same model** (0.84 vs 0.71) at a similar answer length. `FALKORDB_GRAPH=bench_qa python -m benchmark.run` with the gpt-oss settings, over a rules-built graph → [`latest_llm_openai-gpt-oss-120b.json`](../benchmark/results/latest_llm_openai-gpt-oss-120b.json). It loses q13 and q14 to retrieval. Groq rejected two of its tool calls as malformed (a null feature id); the agent now hands the rejection back to the model and both questions still finished. The first attempt crashed on that, before the fix.
- **The qwen3 agent fails at tool use, not at the data.** It typically makes one call with an invented id (`BD-123`) or a feature name instead of an id, gets nothing back, and answers "I don't know".
- **Retrieval into the same model needs no tool calls, so a small model does better there.**

### 4. Real data: extraction on text I didn't write

[`benchmark/real_data.py`](../benchmark/real_data.py) maps a public repo's issues to tickets, comments to chat and PRs to PRs, then runs the same pipeline. Snapshots are in [`data/real/`](../data/real/). Labels are in [`real_data_labels.json`](../benchmark/real_data_labels.json) and [`real_data_recall_labels.json`](../benchmark/real_data_recall_labels.json).

**Labelled by the AI assistant, not re-checked by me: 0 of 25 precision items and 0 of 60 recall items re-checked.** Please spot-check the URLs.

**Precision sets.** The rules flagged 5 drifts on [FalkorDB/FalkorDB](https://github.com/FalkorDB/FalkorDB), and 2 with the current pipeline. Excalidraw gave 0. I also labelled 20 of the 91 "decision" classifications among 1,575 comments, sampled at random.

**Recall sets,** labelled before running any extractor:
- 30 random issue comments: **0** real decisions;
- 30 comments from recently accepted [golang/go proposals](https://github.com/golang/go/issues?q=label%3AProposal-Accepted): **7** real decisions. This pool is enriched on purpose.

`python -m benchmark.real_data extraction --extractor heuristic|llm`:

| | Rules | qwen3:8b | gpt-oss-120b |
|---|---|---|---|
| The 25 known false positives: still called a change | 25 / 25 | 3 / 25 | **2 / 25** |
| 60-comment sample: precision | 0.17 (1 of 6 flagged) | 0.25 (1 of 4 flagged) | **1.00 (2 of 2 flagged)** |
| 60-comment sample: recall | 0.14 (1 of 7) | 0.14 (1 of 7) | **0.29 (2 of 7)** |

`--extractor llm` with the gpt-oss settings above → [`real_extraction_llm_openai-gpt-oss-120b.json`](../benchmark/results/real_extraction_llm_openai-gpt-oss-120b.json). The first run had 12 rate-limited calls fail (each would have counted as "no change"); the numbers are from a re-run with 0 failed calls.

- **The rules fail** on code review and status (12 of 25), analysis that *asks* for a decision (6) and volunteer proposals (5).
- **qwen3:8b mostly avoids those mistakes**, and the evidence guard discarded 2 of its extractions.
- **gpt-oss-120b flags little, and what it flags is right,** but it still misses 5 of the 7 real decisions.
- **All three miss most of the Go decisions,** which say "accepted" and "the proposal is to…".
- **The LLM prompt names these failure patterns,** so the qwen3 and gpt-oss real-data numbers aren't fully independent.

### 5. Noise: 500 messages that change nothing

`python -m benchmark.noise [--extractor llm]` → [`noise.json`](../benchmark/results/noise.json), [`noise_llm_qwen3-8b.json`](../benchmark/results/noise_llm_qwen3-8b.json). The demo plus 500 injected messages (seed 0):
- 250 real GitHub comments;
- 250 on-topic messages that change nothing (status, review, proposals, questions, customer requests). I wrote these from the real-data failure patterns, so they're deliberately adversarial.

Each configuration adds one change to the previous one. Alerts are split into real drifts found (of 2), alerts caused by noise, and other false alerts from the scenario itself.

| Configuration | Rules: noise read as changes | Rules: alerts (real · noise · other) | qwen3:8b: noise read as changes | qwen3:8b: alerts (real · noise · other) |
|---|---|---|---|---|
| **1. Original:** the latest chat change wins | 59 | 7 (0 · 7 · 0) | 4 | 4 (1 · 0 · 3) |
| **2. + decision rights:** only the ticket's creator or assignee can change it | 17 | 5 (0 · 5 · 0) | 3 | 4 (2 · 1 · 1) |
| **3. + no burial:** chat replaces chat only when judged to | 17 | 16 (**2** · 14 · 0) | 3 | 4 (**2** · 1 · 1) |
| **4. + unverified candidates** (current default) | 17 | 16 (2 · 14 · 0) | 3 | 4 (2 · 1 · 1) |

- **Decision rights alone recovers no drift with rules.** It's a negative result on its own.
- **"No burial" brings both real drifts back with rules,** at the cost of 14 noise-caused alerts.
- **With qwen3:8b, the noise mostly doesn't get through extraction**, so the same pipeline ends with 2 real alerts, 1 from noise and 1 scenario false positive.
- **Unverified candidates:** a change by a non-owner on a *guessed* ticket is kept as `status: 'candidate'` (shown on the dashboard, never drift) instead of dropped.
  - With rules: 14 candidates, all from noise, none from the scenario. No benefit measured on this data.
  - With qwen3: 0 candidates.
- **The rules row moved since the earlier draft.** It used to read 6 → 17 false alerts; it's now 5 → 14 because of the IMPLEMENTS fallback, which links some noise "changes" to PRs merged after them.

**MIN_CONFIDENCE sensitivity**, on configuration 4:

| `MIN_CONFIDENCE` | Rules: alerts (real · noise) | qwen3:8b: alerts (real · noise) |
|---|---|---|
| 0.4 | 16 (2 · 14) | 4 (2 · 1) |
| 0.6 (default) | 16 (2 · 14) | 4 (2 · 1) |
| 0.8 | **0 (0 · 0)** | 4 (2 · 1) |

The rules give every change confidence 0.7, so they pass everything up to 0.7 and nothing at 0.8. qwen3's confidences are all at least 0.8. This threshold doesn't separate signal from noise for either extractor on this data.

### 6. Stress test

`python -m benchmark.scale` → [`scale_200x20000.json`](../benchmark/results/scale_200x20000.json). 200 features, 600 tickets, 200 PRs, 20,800 messages, 100 planted drifts. Local Docker FalkorDB on a laptop:

| Stage | Result |
|---|---|
| Graph size | 22,940 nodes · 27,700 relationships |
| Ingest / resolution | 2.2 s / 3.1 s |
| Drift detection | 100 / 100 found, 0 false positives |
| Drift query: whole graph / one ticket | p50 39 ms / 2.4 ms |
| Connection query (`algo.SPpaths`) | p50 6.1 ms |
| Live monitor, one incoming message | p50 38 ms |

The generator writes clean decision messages, so this measures the graph and the queries at size, not extraction. Resolution and the live path are slower than in the earlier draft (2.0 s, 20 ms): the live monitor now rebuilds the ticket's whole version chain, and resolution runs the IMPLEMENTS fallback.

Problems the stress test caught, each covered by a test or a CI check:
- silent truncation at 10k rows (paged reads);
- a path query that timed out (`algo.SPpaths`);
- label scans (CI fails on any);
- a dense TF-IDF scan (inverted index).

How these work: [`docs/EXPLAIN.md`](EXPLAIN.md).

### 7. Looking for real drift in real repos

The question a judge asks: does it find a real drift in a real repo? `python -m benchmark.real_drift_search --repo FalkorDB/FalkorDB` (gpt-oss-120b) and `--repo excalidraw/excalidraw --standing-only` (gpt-oss-20b, because gpt-oss-120b's daily token cap was used up) → [`real_drift_search_falkordb.json`](../benchmark/results/real_drift_search_falkordb.json), [`real_drift_search_excalidraw.json`](../benchmark/results/real_drift_search_excalidraw.json). Same extractor, prompt and thresholds as everywhere else; nothing was tuned on these comments.

| Repo | Comments searched | Flagged as a decision or change | Real drift after reading each thread |
|---|---|---|---|
| FalkorDB/FalkorDB | 70 (all human issue comments in the snapshot) | 2 | **0** |
| excalidraw/excalidraw | 219 (issue comments by the issue's author, assignee or a maintainer) | 79 | **0** |

- **No confirmed drift in either repo.** Each flag was read against its GitHub thread and linked PRs. The verdicts were written by the AI assistant; each one is in the result files with its reason and links, to check.
- **The two genuine scope decisions it found had already reached the code**, which is exactly the case the product must *not* alert on:
  - FalkorDB [#2876](https://github.com/FalkorDB/FalkorDB/issues/2876#issuecomment-5826403652): a maintainer widens a bug from nodes to nodes *and* relationships; [PR #2964](https://github.com/FalkorDB/FalkorDB/pull/2964), opened the same minute, fixes both.
  - Excalidraw [#10001](https://github.com/excalidraw/excalidraw/pull/10001#issuecomment-5620263663): the maintainer narrows sticky notes to a dedicated element; [PR #12064](https://github.com/excalidraw/excalidraw/pull/12064), which supersedes it, shipped on 2026-09-10.
- **Most flags were closing notes.** Of Excalidraw's 79: 36 were one "closing as superseded" message pasted on 36 PRs, 28 were "Fixed by #N" notes about behaviour that already shipped, 8 other status notes, 5 decisions *not* to change, and 1 agreement with work in progress. FalkorDB's other flag was an outside contributor agreeing with a proposal, which the decision-rights rule keeps as a candidate.
- **The model matters.** gpt-oss-20b flagged 36% of the comments; gpt-oss-120b flagged 3%. Closing notes ("X now does Y") read like requirement changes to the smaller model.
- **What this shows:** in two well-run open-source repos, decisions mostly travel inside their PR, so the decided-but-never-shipped case didn't occur in the sampled weeks. It does not show recall on a team that decides in chat and ships elsewhere; the synthetic company and the live Slack run cover that case.

## Limitations

- **Real-text extraction is the open problem** (Results 4 and 5). The strong hosted LLM run is the missing measurement.
- **The labels are the AI assistant's and are unverified** (0 of 25 re-checked by me). The recall sample has only 7 positives.
- **The graph's advantage is not accuracy.** Given the same facts and chain, SQL matches it (Result 2).
- **Small-model agents fail at tool calling.** Use the rules agent, or retrieval, with qwen3:8b-class models.
- **No burial means more alerts with rules.** Misread messages surface as alerts instead of hiding real drift.
- **Decision rights is coarse.** Unverified candidates keep non-owner changes visible, but here they only caught noise.
- **The Q&A grader is keyword-based** (whole-word), so a list of the right words passes; the router was tuned on the benchmark questions. Cross-feature questions use F1 over named ids, which is stricter.
- **A reversal under rules reports both decisions.** With the rules extractor, chat never supersedes chat, so "change to 100" then "back to 10" leaves two open drifts, the second of them false. An LLM extractor's `replaces()` judgment handles this; the rules don't.
- **Multi-org is selection, not security.** The org comes from a header or `?org=`; one `INGEST_TOKEN` guards writes for every org, and a GitHub signature doesn't cover the org parameter.
- **Same-ticket scope.** A PR on a sibling ticket isn't flagged as stale.
- **Single-version issues.** Each GitHub issue is one version in the real-data run.

## What changed since the first submission draft

- **Dismissals and write-backs now survive a rebuild.** They were deleted by every `resolve()` and every full build.
- **A missed IMPLEMENTS judgment no longer means a false drift.** There's a time-aware fallback, and PRs are labelled as merged before or after the decision.
- **New SQL baseline.** It matches the graph on drift given the same chain, so the headline no longer rests on the 3-question retrieval comparison.
- **The rules router scores intents and sends PR ids to a PR lookup.** The q03 and stress-test misroutes are fixed (and disclosed as tuned).
- **`resolve()` is split into stages.** Outputs are byte-identical on every benchmark; constants and weights live in `config.py`.
- **qwen3:8b measured on the noise set and in LLM-agent Q&A.** The agent result is negative and reported as such.
- **Real Slack run done once:** scope-aware `check_setup`, per-source `--live` and `docs/REAL_RUN.md`, then a live in-thread alert in a real workspace (screenshots above). It found and fixed one bug: Slack code formatting kept in the requirement text.
- **Hygiene:** MIT license, pinned FalkorDB, ruff and mypy in CI, and an ablation that fails CI on regression.
- **One stale-PR rule across the product.** The Q&A answer used to say "PRs that shipped the old version: none" while its own evidence path showed PR #5 implementing the older requirement. PRs merged after the decision that implement the old version are now stale everywhere; only PRs with no link either way are "unmatched".
- **"Days open" no longer grows with the real clock.** On the synthetic company it counts from a fixed reference date in [`data/scenario/config.json`](../data/scenario/config.json) (2026-10-10, the morning after the last message); live builds use today.
- **Dashboard.** Q&A drift answers list one fact per line, with the graph paths behind a toggle; drift cards dropped duplicated text; sections after the hero have their own colour, numbered headers and lit panels. Rules-agent Q&A was unchanged by this.
- **Review fixes (judge-style audit).**
  - The Q&A grader is whole-word, which drops the rules agent from 1.00 to 0.86.
  - README numbers were re-run against the current code: ablation stale PRs, qwen3 stale PRs and SQL timings.
  - The live path no longer undoes write-backs or lets unverified candidates into the version chain.
  - Simulate, write-to-ticket and dismiss need the token when one is set.
  - Failed LLM calls are counted and shown instead of reading as "no change".
  - The router says when an id doesn't exist.
