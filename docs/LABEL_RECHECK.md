# Re-checking the AI-made labels (10 of 25)

The 25 real-data precision labels were made by the AI assistant. This sheet picks 10 of them at random
(`random.Random(0)`, fixed so the choice isn't mine) for a human re-check.

**Rule for a "true" item** (the same criterion the labels used): true_drift / true_decision = the comment states an agreed change to what an issue's feature must do (scope, behaviour, limits), made or accepted by someone with standing (maintainer or issue owner). Proposals, volunteering, analysis that asks for a decision, status, code review and bot output are false positives.

**How:** open each link, read the comment, and write `agree` or `disagree` in "My verdict", with a few words why
if you disagree. Judge the comment yourself first, then compare with the AI label.

| # | Comment | Set | AI label | AI note | My verdict | Why (if disagree) |
|---|---|---|---|---|---|---|
| 1 | [FalkorDB/FalkorDB GH-3070](https://github.com/FalkorDB/FalkorDB/issues/3070#issuecomment-6109406007) | drift_flag | **false_positive** (analysis) | Prototype fix and cost measurement headed 'needs a decision': asks for a decision, makes none. |  |  |
| 2 | [FalkorDB/FalkorDB PR #3125](https://github.com/FalkorDB/FalkorDB/pull/3125#issuecomment-5978254267) | decision_sample | **false_positive** (code_review) | Automated-style code review of a PR; 'instead of' describes the diff. |  |  |
| 3 | [excalidraw/excalidraw issue #9123](https://github.com/excalidraw/excalidraw/issues/9123#issuecomment-5647970113) | decision_sample | **false_positive** (analysis) | Points out an existing mechanism elsewhere in the codebase; no decision. |  |  |
| 4 | [excalidraw/excalidraw issue #11906](https://github.com/excalidraw/excalidraw/issues/11906#issuecomment-5432065328) | decision_sample | **false_positive** (status) | Status: a fix is in review in another PR. |  |  |
| 5 | [FalkorDB/FalkorDB PR #3155](https://github.com/FalkorDB/FalkorDB/pull/3155#issuecomment-5977958290) | decision_sample | **false_positive** (code_review) | Code review of a PR. |  |  |
| 6 | [excalidraw/excalidraw issue #7016](https://github.com/excalidraw/excalidraw/issues/7016#issuecomment-5382590535) | decision_sample | **false_positive** (volunteer) | 'I'd like to work on this one': volunteer with a repro. |  |  |
| 7 | [excalidraw/excalidraw PR #11904](https://github.com/excalidraw/excalidraw/pull/11904#issuecomment-5534749674) | decision_sample | **false_positive** (code_review) | Author's reply to review ('Agreed') about test code, not product behaviour. |  |  |
| 8 | [FalkorDB/FalkorDB PR #3120](https://github.com/FalkorDB/FalkorDB/pull/3120#issuecomment-5845525082) | decision_sample | **false_positive** (code_review) | Author's reply to review ('agreed in principle') about a test assertion. |  |  |
| 9 | [FalkorDB/FalkorDB PR #3141](https://github.com/FalkorDB/FalkorDB/pull/3141#issuecomment-5977963446) | decision_sample | **false_positive** (code_review) | Code review of a PR. |  |  |
| 10 | [excalidraw/excalidraw PR #12161](https://github.com/excalidraw/excalidraw/pull/12161#issuecomment-5994499356) | decision_sample | **false_positive** (code_review) | Review finding on a PR ('instead of treating them as empty'). |  |  |
