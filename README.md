# 🛡️ PRD Red Team

**An AI agent that reviews a Product Requirements Document the way a launch review panel would, so problems are found before launch instead of after an incident.**

Nine specialist reviewers attack the PRD in parallel. A moderator removes weak and duplicate findings. A chair makes the launch call, and a deterministic gate makes sure the model can never talk its way past an open blocker.

An AI product management portfolio project: problem framing, agent design, evaluation strategy and a full decision log.

📄 [Product brief](docs/PRODUCT_BRIEF.md) · 🧭 [Decision log](docs/DECISIONS.md) · 📊 [Eval results](evals/RESULTS.md) · 🧪 [Sample PRD with planted defects](examples/sample_prd.md)

<!-- After your first live run: add a screenshot of the HTML report here, e.g. ![Report](docs/assets/report.png) -->

---

## TL;DR

| | |
|---|---|
| **Problem** | PRD reviews happen late, in sequence, and unevenly. Launch-blocking issues (a regulatory rule, a missing rollback plan) surface days before launch, when fixing them is most expensive. |
| **Users** | PMs preparing for launch review (primary), specialist reviewers, launch chairs |
| **Solution** | A multi-agent panel review that produces a verdict, launch conditions and evidence-backed findings, in minutes |
| **What makes it trustworthy** | Every finding quotes the PRD and is verified in code · a judge filters the critics · launch policy is code, not model opinion |
| **How it's measured** | Seeded-defect benchmark. North star: **blocker recall**. Guardrails: precision and hallucinated-quote rate. Single-prompt baseline and ablations built in. |
| **Built with** | Python, Claude (tool use for structured output), Pydantic, Streamlit, GitHub Actions |

---

## The problem

A PRD is usually reviewed by engineering, security, privacy, legal, SRE, QA and design, often days apart and close to launch. Three things go wrong:

1. **Gaps surface late.** Compliance sees the PRD a week before launch and finds the core flow is not allowed.
2. **Depth depends on who is free.** Specialist reviewers are shared across many teams and skim when busy.
3. **Weak writing passes as requirements.** "Fast", "secure", "TBD" and metrics without numbers get through because nobody owns PRD quality end to end.

The PM pays for all three through rework, slipped dates and difficult review meetings.

## Who it's for

| User | Job to be done |
|---|---|
| **PM author** (primary) | "Find the holes before my reviewers do, and tell me how to fix them." |
| **Specialist reviewer** | "Show me the issues in my lane, with evidence, so I can spend my time on judgment." |
| **Launch chair / TPM** | "Is this ready? What has to be true before it ships? Who hasn't signed off?" |

## What you get

For every PRD, a report (Markdown, standalone HTML, or JSON) containing:

- **A verdict:** GO, GO WITH CONDITIONS, or NO-GO, with a 30-second executive summary
- **Launch conditions:** a checklist of concrete, verifiable things that must be true before shipping
- **A scorecard:** 1 to 5 across feasibility, security, privacy and compliance, reliability, testability, AI quality, UX and accessibility, and business case
- **The panel:** each reviewer's one-line take, and whether they would sign off
- **Findings**, every one with the same anatomy:

> **🛑 Blocker · Ananya (Data Protection Officer), Rohan (Compliance & Legal)** · section *6. Data* · L42 · ✓ quote verified
>
> > "stored in our S3 bucket indefinitely so we can use them for model improvement"
>
> **Issue.** Health data is retained forever and reused for a new purpose without specific consent.
>
> **What goes wrong.** *A concrete story of who is harmed and how.*
>
> **Fix.** *A change the PM can write into the PRD this week.*
>
> **Ask the PM.** *The pointed question this reviewer would raise in the meeting.*
>
> <sub>Illustrative example of the format, based on the sample PRD.</sub>

- **Questions to prepare** before the review meeting, grouped by reviewer
- **PRD hygiene checks:** missing sections, vague language, metrics without numbers

## Product principles

1. **Evidence over opinion.** If a finding can't point at the PRD, or clearly at something missing from it, it doesn't count.
2. **Code around the model.** Use the LLM for judgment and deterministic code for everything that can be checked: quotes, policy, hygiene.
3. **Precision is a feature.** A noisy reviewer gets ignored. Fewer, stronger findings beat a long list.
4. **Advisor, not approver.** The tool prepares humans for review. It can block a launch, but a GO means "no blockers found", not "approved".
5. **Measured, not vibed.** Every design choice has a metric that would prove it wrong.

## How it works

```mermaid
flowchart LR
    A[PRD<br/>.md .pdf .docx] --> B[Hygiene linter<br/>(code)]
    A --> C[Understand product<br/>domain, data, geos, regs]
    C --> D{Select<br/>reviewers}
    D --> E1[Staff Eng]
    D --> E2[Security]
    D --> E3[Privacy]
    D --> E4[Compliance]
    D --> E5[SRE]
    D --> E6[QA]
    D --> E7[AI/ML<br/>if AI used]
    D --> E8[UX & a11y]
    D --> E9[GTM/Finance]
    E1 & E2 & E3 & E4 & E5 & E6 & E7 & E8 & E9 --> F[Verify quotes<br/>(code)]
    F --> G[Moderator<br/>judge + dedupe]
    G --> H[Verdict chair]
    B --> H
    H --> I[Launch gate<br/>(code)]
    I --> J[Report<br/>MD / HTML / JSON]
```

| Stage | What it does | Model or code? |
|---|---|---|
| Hygiene linter | Missing sections (rollback, metrics, security), vague words, metrics without numbers, sensitive data with no privacy section, AI with no eval plan | Code |
| Understand product | Extracts domain, users, data types, geographies, dependencies, AI use, payments, likely regulations | Model |
| Reviewer panel | 8 or 9 specialists in parallel, each limited to its lane, with a shared severity rubric | Model |
| Verify quotes | Fuzzy-matches every quote back to the PRD; adds line and section, or flags ⚠ | Code |
| Moderator | Keeps or drops each finding, recalibrates severity, groups duplicates (merging happens in code) | Model |
| Verdict chair | Decision, executive summary, launch conditions, scorecard, top risks | Model |
| Launch gate | Open blocker forces NO-GO; open high prevents a clean GO; overrides are shown in the report | Code |

## Key product decisions

The full reasoning, alternatives and reversal signals are in the **[decision log](docs/DECISIONS.md)**. The short version:

| Decision | Why | What would prove me wrong |
|---|---|---|
| **A panel of specialists**, not one "find all risks" prompt | Narrow mandates force depth and make sign-off attributable | Single-prompt baseline matches panel on blocker recall |
| **Evidence or omission**, verified in code | The fastest way to lose a PM's trust is one hallucinated critique | High unverified-quote rate that the judge rates invalid |
| **A judge after the critics** | Red teams over-report; nobody reads 50 findings | Ablation shows moderator drops real blockers |
| **Deterministic launch gate** | Launch policy must be predictable and auditable | Teams routinely override the gate by hand |
| **Cheap checks first** | Free, offline, and keeps model attention on judgment | Linter noise drowns out expert findings |
| **Four consequence-based severity levels** | Maps directly to launch decisions | Low severity match against ground truth |
| **Output shaped for the review meeting** | Failure stories, fixes and questions turn a report into preparation | PMs don't use the questions or conditions |
| **Ship into existing workflows** (CLI, HTML, CI) | PRD review is an async document step, not a chat | Low repeat usage once the novelty wears off |

## How I measure it

The tool is evaluated on a **seeded-defect benchmark**: a realistic PRD with **15 planted defects (4 of them launch blockers)** across every reviewer's lane. An LLM judge matches the agent's findings to the planted defects and flags invalid findings.

| Metric | Role | Target |
|---|---|---|
| **Blocker recall** | North star: missing a blocker is the costliest failure | ≥ 90% |
| Recall | Overall coverage | ≥ 75% |
| Precision | Guardrail: noise destroys trust | ≥ 80% |
| Unverified-quote rate | Guardrail: deterministic hallucination check, no judge needed | ≤ 5% |
| Severity match | Triage quality | Tracked |
| Tokens and seconds per review | Cost and latency | ≤ 5 min |

Targets are hypotheses set before the first full evaluation (see the [product brief](docs/PRODUCT_BRIEF.md#5-success-metrics)).

**Experiments built into the harness**

```bash
python evals/run_eval.py --runs 3            # the full panel, with run-to-run spread
python evals/run_eval.py --runs 3 --baseline # one generalist prompt, same budget: is the panel worth it?
python evals/run_eval.py --runs 3 --no-moderator   # is the judge earning its cost?
python evals/run_eval.py --model <other-model>     # cost vs quality across models
```

Each run appends a row to **[evals/RESULTS.md](evals/RESULTS.md)**, so experiments build into one comparison table. The harness itself is unit-tested offline so metric bugs can't hide behind API calls.

<!-- Before publishing: run the three experiments above and summarise the headline result here,
     e.g. "The panel caught X of 4 blockers vs Y for the single-prompt baseline, at Z precision." -->

**Known limitations.** One synthetic benchmark, written by the same person who wrote the prompts, risks overfitting, and the judge is itself an LLM. Next: seeded PRDs in other domains (fintech, B2B SaaS) and hand-checking a sample of judge decisions.

## The test case: RefillRx

[`examples/sample_prd.md`](examples/sample_prd.md) is a PRD for **RefillRx**, a WhatsApp-based AI prescription refill assistant for an Indian pharmacy app with 2M users. It reads like a plausible PRD, but it hides problems a real launch review should catch:

- 🛑 Prescription-only (Schedule H/H1) drugs auto-ordered from an LLM-read prescription, with pharmacist review explicitly out of scope
- 🛑 A handwriting misread directly triggers an order, with no confidence threshold or human check
- 🛑 Prescription images kept indefinitely and reused for model training and marketing
- 🛑 Aadhaar numbers collected over WhatsApp and stored in the user profile
- 🔴 Phone number as the only identity, controlling health data and a UPI Autopay mandate of up to Rs 15,000
- 🔴 Recurring debits with no pre-debit notification
- 🔴 Big-bang launch to 2M users: no feature flag, no rollback, a "TBD" dependency, 3 engineers for about 4 weeks
- 🔴 Elderly target users, English only

Full ground truth: [`evals/planted_defects.json`](evals/planted_defects.json).

**Dogfooding.** The tool's own [product brief](docs/PRODUCT_BRIEF.md) passes its hygiene checks with zero issues (`redteam review docs/PRODUCT_BRIEF.md --offline`). Running it the first time surfaced a real linter bug: words *mentioned* in quotes ("avoid words like 'fast'") were being flagged as if they were *used*. That's now fixed and covered by a test.

## Risks and how they're handled

| Risk | Mitigation |
|---|---|
| **Over-trust:** a GO is read as approval | GO says "no blockers found, human sign-off still required"; disclaimer on every report; gate can only make verdicts stricter |
| **Hallucinated findings** | Evidence contract, quote verification, moderator, unverified-quote guardrail metric |
| **Hallucinated legal claims** | Regulations are framed as leads; "counsel to confirm" when uncertain; no invented clause numbers |
| **Prompt injection** inside the PRD | PRD treated as untrusted input in every prompt; policy lives in code the PRD can't influence |
| **Noise and alert fatigue** | Lane discipline, per-reviewer caps, confidence floor, moderator, precision guardrail |
| **One reviewer fails mid-run** | Review completes without it and the report names what's missing |
| **Confidential PRDs** | Nothing stored beyond local report files; teams check provider retention terms before use |

## Roadmap

Prioritised by how much each item increases **real usage**, not feature count.

| Horizon | Item | Why it's here |
|---|---|---|
| **Now** | Run the baseline and ablation experiments; publish results | Validates the two most expensive design choices (D1, D3) |
| **Now** | Two more seeded PRDs (fintech, B2B SaaS) | Reduces benchmark overfitting before tuning prompts further |
| **Next** | Google Docs / Notion / Confluence connectors that post findings as inline comments | Meets PMs where PRDs actually live; biggest adoption lever |
| **Next** | Re-review mode: compare against the last report, show resolved / persisting / new | Turns a one-off review into an iteration loop |
| **Next** | "Risk accepted by owner" state | Lets the gate tell open risks from conscious decisions |
| **Later** | PM rebuttal loop: the PM answers a finding, the reviewer accepts or escalates | Mirrors how review meetings actually resolve issues |
| **Later** | Org memory from past incident postmortems | Reviewers learn what has actually broken at this company |
| **Later** | Domain policy packs (health, payments, lending, kids) | Deeper compliance coverage without bloating the core prompts |

## Takeaways for building AI products

- **Trust is the product.** In a review tool, one fabricated finding costs more than ten missed nitpicks. Most of the design is about earning and keeping trust, not about finding more issues.
- **Wrap the model in code.** The most valuable parts of this agent (quote verification, the launch gate, the linter) contain no AI at all. The model does judgment; code does guarantees.
- **Pick a north star that matches the cost of failure.** Overall recall rewards finding many small issues. Blocker recall rewards finding the ones that matter.
- **Build the eval before tuning the prompts.** Without a baseline and ablations, every prompt change is a guess.

---

## Run it yourself

```bash
git clone <this-repo> prd-redteam && cd prd-redteam
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,docs,dev]"
cp .env.example .env            # add your ANTHROPIC_API_KEY

redteam review examples/sample_prd.md            # full review -> reports/
redteam review examples/sample_prd.md --offline  # hygiene checks only, no API key
streamlit run app.py                             # web UI
pytest                                           # offline test suite, no API key
```

<details>
<summary><b>CLI reference</b></summary>

```
redteam review PRD [--out reports] [--format md,html,json] [--model MODEL]
                   [--personas staff_engineer,security,...] [--persona-file custom.json]
                   [--max-findings 8] [--concurrency 4] [--min-confidence 0.4]
                   [--strict-evidence] [--no-moderator] [--offline] [--fail-on-nogo]
redteam personas
```

| Flag | Effect |
|---|---|
| `--personas` | Run only some reviewers (cheaper, focused) |
| `--persona-file` | Add your own reviewers from JSON; see `examples/custom_personas.json` (adds a Clinical Safety Officer) |
| `--strict-evidence` | Drop findings whose quote isn't in the PRD (default: keep and flag) |
| `--no-moderator` | Skip the judge pass (cheaper, noisier) |
| `--offline` | Hygiene checks only |
| `--fail-on-nogo` | Exit code 2 on NO-GO, for CI |

</details>

<details>
<summary><b>CI: red-team every PRD in a pull request</b></summary>

`.github/workflows/prd-redteam.yml` reviews any changed file under `docs/prd/`, uploads the reports as build artifacts, and fails the check on NO-GO. Add `ANTHROPIC_API_KEY` as a repository secret.

</details>

<details>
<summary><b>Repository map</b></summary>

```
redteam/
  schemas.py     Typed contracts for every stage (Pydantic)
  personas.py    The 9 reviewers, selection logic, custom persona loading
  prompts.py     All prompts in one place, versioned
  llm.py         Claude tool-use wrapper with schema repair; ScriptedLLM for tests
  document.py    PDF/Word/Markdown loading, section splitting, fuzzy quote location
  lint.py        Deterministic hygiene checks
  agent.py       Pipeline, moderation merge, launch gate
  report.py      Markdown / HTML / JSON renderers
  cli.py         `redteam` command
app.py           Streamlit UI
docs/            Product brief and decision log
evals/           Seeded-defect benchmark, harness, results table
examples/        Sample flawed PRD, custom persona example
tests/           Offline tests for the pipeline and the eval harness
```

</details>

## Disclaimer

This tool produces a structured starting point for human review. It does not replace security, legal or clinical sign-off, and its regulatory references are leads to verify with counsel, not legal advice.
