# Re-checking the AI-made labels (10 of 25)

The 25 real-data precision labels were made by the AI assistant. This sheet picks 10 of them at random
(`random.Random(0)`, fixed so the choice isn't mine) for a human re-check.

**Rule for a "true" item** (the same criterion the labels used): true_drift / true_decision = the comment states an agreed change to what an issue's feature must do (scope, behaviour, limits), made or accepted by someone with standing (maintainer or issue owner). Proposals, volunteering, analysis that asks for a decision, status, code review and bot output are false positives.

**Status (2026-10-18).** A second pass re-read each comment in full and agrees with all 10 labels (one borderline). That
pass was also made by an AI assistant (Claude Code), so it is a consistency check, not an independent one: **0 of 10
have a human verdict yet.** The human verdict lines below are what makes this a re-check.

**How:** open each link, read the comment, and fill in the human verdict line with `agree` or `disagree` (a few words
why if you disagree). Judge the comment yourself first, then compare with the labels.

| | AI label | AI second pass | Human verdict |
|---|---|---|---|
| 1 | false positive (analysis) | agree | |
| 2 | false positive (code_review) | agree | |
| 3 | false positive (analysis) | agree | |
| 4 | false positive (status) | agree | |
| 5 | false positive (code_review) | agree | |
| 6 | false positive (volunteer) | agree | |
| 7 | false positive (code_review) | agree | |
| 8 | false positive (code_review) | agree | |
| 9 | false positive (code_review) | agree | |
| 10 | false positive (code_review) | agree, borderline | |

## 1. [FalkorDB/FalkorDB GH-3070](https://github.com/FalkorDB/FalkorDB/issues/3070#issuecomment-6109406007)

*[Rust] Batched OPTIONAL MATCH emits NULL-fallback rows after matched rows (order differs from input and from C; low)* · comment by **AviAvni** (contributor) on 2026-10-11 · set: `drift_flag`

> Prototype fix and measured cost: needs a decision Reproduced on main @ b033aecc6 (release). There is a second site the issue does not list: the fused Optional Conditional Traverse (cond_traverse.rs, null_pad after the matched batches, in both the mxm path and …

- **AI label:** false positive (analysis). Prototype fix and cost measurement headed 'needs a decision': asks for a decision, makes none.
- **AI second pass:** agree. The issue's author posts a prototype and its measured cost and heads it 'needs a decision'; the closing 'recommended' option is a recommendation, not an agreed change.
- **Human verdict:** 

## 2. [FalkorDB/FalkorDB PR #3125](https://github.com/FalkorDB/FalkorDB/pull/3125#issuecomment-5978254267)

*fix(temporal): reject non-digits in compact date and time strings* · comment by **gkorland** (contributor) on 2026-10-04 · set: `decision_sample`

> Code Review: fix(temporal): reject non-digits in compact date and time strings Summary The fix is right and minimal: both compact branches now reject anything that is not an ASCII digit instead of filtering it out. All valid compact forms still parse (2015, …

- **AI label:** false positive (code_review). Automated-style code review of a PR; 'instead of' describes the diff.
- **AI second pass:** agree. A structured code review of the PR ('Code Review: …', suggestions table); it describes the diff and follow-ups, not a change to the feature.
- **Human verdict:** 

## 3. [excalidraw/excalidraw issue #9123](https://github.com/excalidraw/excalidraw/issues/9123#issuecomment-5647970113)

*Automatically decrease font when text no longer fit rectangle* · comment by **gseilheimer** (no repo role) on 2026-09-12 · set: `decision_sample`

> Worth noting that the mechanism this issue asks for now exists in the codebase — it is just scoped to one element type. 12064 (merged 2026-09-10) introduced exactly this split for the new stickynote element: fontSizeMax on the label is the user's ceiling, …

- **AI label:** false positive (analysis). Points out an existing mechanism elsewhere in the codebase; no decision.
- **AI second pass:** agree. An outside contributor (no repo role) points to a mechanism shipped elsewhere and suggests narrowing the ask; a proposal without standing.
- **Human verdict:** 

## 4. [excalidraw/excalidraw issue #11906](https://github.com/excalidraw/excalidraw/issues/11906#issuecomment-5432065328)

*bug: standalone text elements inside frames not clipped to frame boundary (canvas rendering)* · comment by **JillK83** (no repo role) on 2026-08-26 · set: `decision_sample`

> A fix for this is in review at #11946 by my collaborator Bo. The PR addresses the canvasPadding / fontSize / 2 mismatch in shouldApplyFrameClip that causes the clip decision and the actual painted area to diverge for text elements. A DPR unit correction is …

- **AI label:** false positive (status). Status: a fix is in review in another PR.
- **AI second pass:** agree. Status: a fix is in review in another PR.
- **Human verdict:** 

## 5. [FalkorDB/FalkorDB PR #3155](https://github.com/FalkorDB/FalkorDB/pull/3155#issuecomment-5977958290)

*fix: serialize schema-mutating commands through a single-writer election* · comment by **gkorland** (contributor) on 2026-10-04 · set: `decision_sample`

> Code Review: fix: serialize schema-mutating commands through a single-writer election Summary Moves the per-graph writer election out of cmd_query.c / graphcontext.c into the new graph_write_queue.c, routes GRAPH.CONSTRAINT CREATE/DROP through it as queued …

- **AI label:** false positive (code_review). Code review of a PR.
- **AI second pass:** agree. A code review of the PR, with a critical-issues table.
- **Human verdict:** 

## 6. [excalidraw/excalidraw issue #7016](https://github.com/excalidraw/excalidraw/issues/7016#issuecomment-5382590535)

*Control-z does not work when making an arrow and not yet finished* · comment by **abdoulk30** (no repo role) on 2026-08-22 · set: `decision_sample`

> I'd like to work on this one. Just reproduced it on current master branch and Ctrl+Z does nothing while an arrow is mid-draw (extra waypoint added by mistake), instead of undoing the last point. Will dig into the undo/history handling for in-progress linear …

- **AI label:** false positive (volunteer). 'I'd like to work on this one': volunteer with a repro.
- **AI second pass:** agree. 'I'd like to work on this one': a volunteer with a repro.
- **Human verdict:** 

## 7. [excalidraw/excalidraw PR #11904](https://github.com/excalidraw/excalidraw/pull/11904#issuecomment-5534749674)

*fix(editor): warn instead of error when worker subsetting falls back* · comment by **nessaisling-lab** (no repo role) on 2026-09-04 · set: `decision_sample`

> Thanks — both worth doing, and the second one turned out to be more interesting than it looked. On vi.resetModules(). Agreed, and you are right about the failure mode. subset-main decides whether workers are usable at module scope, so the module has to be …

- **AI label:** false positive (code_review). Author's reply to review ('Agreed') about test code, not product behaviour.
- **AI second pass:** agree. The PR author answering review points about test code (`vi.resetModules`, `expect.any`), not product behaviour.
- **Human verdict:** 

## 8. [FalkorDB/FalkorDB PR #3120](https://github.com/FalkorDB/FalkorDB/pull/3120#issuecomment-5845525082)

*fix(algo): dedupe relTypes in algo.SPpaths/SSpaths config* · comment by **aniruddhaadak80** (contributor) on 2026-09-26 · set: `decision_sample`

> On the suggestion to key the comparison on relationship identities: agreed in principle, and I left it on node ids on purpose. There is no Path.relationships() usage anywhere in tests/ on this branch, so adding it here would be the first use of that client …

- **AI label:** false positive (code_review). Author's reply to review ('agreed in principle') about a test assertion.
- **AI second pass:** agree. The PR author answering a review about a test assertion ('agreed in principle', kept as is).
- **Human verdict:** 

## 9. [FalkorDB/FalkorDB PR #3141](https://github.com/FalkorDB/FalkorDB/pull/3141#issuecomment-5977963446)

*Handle short reads gracefully during RDB decode* · comment by **gkorland** (contributor) on 2026-10-04 · set: `decision_sample`

> Code Review: Handle short reads gracefully during RDB decode Summary Declaring REDISMODULE_OPTIONS_HANDLE_IO_ERRORS and latching a per-load sticky error on SerializerIO is the right design, and the v19 decoder checkpoints are mostly sound. Two paths still …

- **AI label:** false positive (code_review). Code review of a PR.
- **AI second pass:** agree. A code review of the PR, with a critical-issues table.
- **Human verdict:** 

## 10. [excalidraw/excalidraw PR #12161](https://github.com/excalidraw/excalidraw/pull/12161#issuecomment-5994499356)

*fix(editor): Reinforce state and elements restore and import* · comment by **mtolmacs** (collaborator) on 2026-10-05 · set: `decision_sample`

> [P1] Preserve unreadable stored scenes instead of treating them as empty Location: [firebase.ts:118–126](https://github.com/excalidraw/excalidraw/blob/cf98274e50e24b6f1ebcc8ae3b2f842320166f87/excalidraw-app/data/firebase.ts#L118-L126), consumed by …

- **AI label:** false positive (code_review). Review finding on a PR ('instead of treating them as empty').
- **AI second pass:** agree, borderline. A '[P1]' review finding on the PR's own diff, posted by its author (a collaborator). It does ask for different behaviour (keep unreadable scenes), but as a review of the change, not a change to what the issue's feature must do.
- **Human verdict:** 
