# PRD Red Team: Product Brief

**Author:** Nithya · **Status:** v0.1 built, evaluation in progress · **Type:** portfolio project

> This is the PRD for the tool itself. It is run through the tool's own hygiene checks on every change (see [Dogfooding](#dogfooding)).

## 1. Problem

Launch reviews find problems late. A PRD is typically written by one PM, then reviewed in sequence by engineering, security, privacy, legal, SRE, QA and design, often days apart and often close to launch. Three things go wrong:

- **Gaps surface late.** The compliance reviewer sees the PRD a week before launch and finds that the core flow is not allowed. Rework at that stage is expensive and launches slip.
- **Reviews are uneven.** Depth depends on who is available. Busy reviewers skim; specialist reviewers are a bottleneck shared across many teams.
- **Weak writing passes as requirements.** "Fast", "secure", "TBD" and metrics without numbers get through because nobody owns PRD quality as a whole.

The PM is the person who pays for this, through rework, slipped dates, and difficult review meetings.

## 2. Users

| User | Job to be done | What they need from the tool |
|---|---|---|
| **PM author** (primary) | "Help me find the holes before my reviewers do." | Specific findings with fixes, before the review meeting |
| **Specialist reviewers** (engineering, security, privacy, legal) | "Let me spend my time on judgment, not on spotting the obvious." | A pre-filtered list in their own lane, with evidence |
| **Launch chair / TPM** | "Tell me if this is ready and what has to be true before it ships." | A clear verdict, launch conditions, and who has not signed off |

## 3. Goals

1. Surface launch-blocking issues **before** the first human review.
2. Give every PRD a consistent, multi-discipline review, regardless of reviewer availability.
3. Make every finding verifiable and directly actionable.

## 4. Non-goals

- Replacing human sign-off or giving legal advice (see [D12](DECISIONS.md#d12-advisor-not-approver)).
- Writing or rewriting the PRD for the PM.
- Reviewing code, designs or architecture documents (possible later, not v1).

## 5. Success metrics

Targets are initial hypotheses, set before the first full evaluation, and will be revised against the baseline.

| Metric | Type | Target | Measured by |
|---|---|---|---|
| Blocker recall on seeded benchmark | North star | ≥ 90% | `evals/run_eval.py` |
| Recall on seeded benchmark | Input | ≥ 75% | `evals/run_eval.py` |
| Precision (findings judged valid) | Guardrail | ≥ 80% | `evals/run_eval.py` |
| Unverified-quote rate | Guardrail | ≤ 5% | Deterministic check in pipeline |
| Panel beats single-prompt baseline on blocker recall | Validation of [D1](DECISIONS.md#d1-a-panel-of-specialists-not-one-find-all-risks-prompt) | ≥ 20 points | `--baseline` ablation |
| Time per review | Guardrail | ≤ 5 minutes | Run stats in every report |

**In production (future):** share of launch-blocking issues first raised by the tool rather than by a human reviewer, and reviewer-rated usefulness of findings.

## 6. Requirements

- **R1.** Accept PRDs as Markdown, text, PDF or Word.
- **R2.** Review with a panel of specialist personas, each limited to its own lane, selected according to product context.
- **R3.** Every finding includes severity, verbatim evidence or an omission flag, a failure scenario, a fix and a question for the PM.
- **R4.** Verify every quoted piece of evidence against the PRD in code and show the result.
- **R5.** Remove invalid and duplicate findings before showing them.
- **R6.** Produce a verdict (GO, GO WITH CONDITIONS, NO-GO) with launch conditions and a scorecard.
- **R7.** Enforce launch policy deterministically: open blockers mean NO-GO.
- **R8.** Run hygiene checks offline with no API key.
- **R9.** Output Markdown, HTML and JSON, and support a CI gate.
- **R10.** Let teams add their own reviewers without code changes.

## 7. Non-functional requirements

- **Latency:** a full review completes in ≤ 5 minutes for a PRD of up to 20 pages.
- **Reliability:** if one reviewer call fails, the review still completes and the report names the missing reviewer.
- **Reproducibility:** prompts are versioned (`PROMPT_VERSION`) and recorded in every report's run stats.
- **Cost visibility:** token usage is recorded in every report.

## 8. Security and privacy

- PRDs often contain confidential plans. The tool sends the PRD only to the configured model provider; it stores nothing beyond the report files it writes locally.
- The API key is read from the environment or a local `.env` file that is git-ignored.
- The PRD is treated as untrusted input to protect against prompt injection (see [D11](DECISIONS.md#d11-the-prd-is-untrusted-input)).
- Onboarding checklist item: teams with strict data rules confirm their model provider's data retention terms before first use.

## 9. Rollout plan

1. **Now:** offline evaluation on the seeded benchmark; run baseline and ablations.
2. **Pilot:** 3 to 5 PMs run it on real PRDs before their review meeting; collect reviewer ratings on each finding.
3. **Team default:** enable the CI workflow for teams that keep PRDs in a repository.

## 10. Rollback and kill switch

The tool is advisory, so rollback is simple: disable the CI workflow, or remove `--fail-on-nogo` to keep reports without blocking merges. Prompt changes are versioned, so a bad prompt version can be reverted in git.

## 11. Monitoring

Every report records the model, prompt version, call count, tokens, time and any failed reviewers. Eval results accumulate in `evals/RESULTS.md`, so regressions between prompt or model versions are visible.

## 12. Dependencies

- Anthropic API (model calls) via the official Python SDK.
- Optional: `pypdf` and `python-docx` for PDF and Word input, Streamlit for the web UI.

## 13. Risks and open questions

| Risk | Mitigation |
|---|---|
| Over-trust: teams treat GO as approval | GO is worded as "no blockers found"; disclaimer on every report ([D12](DECISIONS.md#d12-advisor-not-approver)) |
| Noise causes reviewers to ignore the tool | Moderator pass, precision guardrail, severity rubric |
| Hallucinated regulatory claims | Evidence contract, "counsel to confirm", no invented clause numbers |
| Benchmark overfitting (one synthetic PRD) | Add seeded PRDs in other domains; hand-check the judge |
| Cost at scale | Persona subsets, offline mode, cost tracked per report |

**Open questions**
- Do we record accepted risks, so the gate can distinguish "open" from "consciously accepted"?
- What is the right re-review experience when the PM revises the PRD?

## Dogfooding

```bash
redteam review docs/PRODUCT_BRIEF.md --offline
```

This brief is checked by the tool's own hygiene linter. The current result is recorded in the README.
