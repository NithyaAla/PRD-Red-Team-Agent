"""Streamlit UI.   streamlit run app.py"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import streamlit as st

from redteam import AnthropicLLM, RedTeamAgent, RedTeamConfig, load_prd
from redteam.personas import DEFAULT_PERSONAS
from redteam.report import DECISION_LABEL, to_html, to_json, to_markdown

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

st.set_page_config(page_title="PRD Red Team", page_icon="🛡️", layout="wide")
st.title("🛡️ PRD Red Team")
st.caption("A panel of AI reviewers tears down your PRD before launch: engineering, security, privacy, compliance, SRE, QA, AI, design and business.")

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Anthropic API key", type="password", value=os.getenv("ANTHROPIC_API_KEY", ""))
    model = st.text_input("Model", value=os.getenv("REDTEAM_MODEL", "claude-sonnet-5-5"))
    chosen = st.multiselect(
        "Reviewers (empty = auto-select)",
        options=[p.key for p in DEFAULT_PERSONAS],
        format_func=lambda k: next(p.name for p in DEFAULT_PERSONAS if p.key == k),
    )
    max_findings = st.slider("Max findings per reviewer", 3, 12, 8)
    strict = st.checkbox("Drop findings whose quote is not in the PRD", value=False)
    offline = st.checkbox("Offline (hygiene checks only)", value=False)

source = st.radio("PRD source", ["Upload a file", "Use the sample PRD (RefillRx)"], horizontal=True)
prd_path: Path | None = None
if source == "Upload a file":
    uploaded = st.file_uploader("Upload a PRD", type=["md", "txt", "pdf", "docx"])
    if uploaded:
        tmp = Path(tempfile.mkdtemp()) / uploaded.name
        tmp.write_bytes(uploaded.getvalue())
        prd_path = tmp
else:
    prd_path = Path(__file__).parent / "examples" / "sample_prd.md"

if prd_path:
    doc = load_prd(prd_path)
    with st.expander(f"PRD: {doc.title}", expanded=False):
        st.markdown(doc.text)

    if st.button("Run red team", type="primary"):
        if not offline and not api_key:
            st.error("Add an API key in the sidebar, or tick Offline.")
            st.stop()
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        log = st.status("Red-teaming…", expanded=True)
        llm = None if offline else AnthropicLLM(model=model)
        agent = RedTeamAgent(
            llm,
            RedTeamConfig(personas=chosen or None, max_findings_per_persona=max_findings, drop_unverified_quotes=strict),
            progress=lambda m: log.write(m),
        )
        # Keep the result across reruns so filters and checkboxes don't trigger a new (paid) review.
        st.session_state["report"] = asyncio.run(agent.run(doc))
        st.session_state["stem"] = Path(prd_path).stem
        log.update(label="Done", state="complete", expanded=False)

if "report" in st.session_state:
    report = st.session_state["report"]

    v = report.verdict
    c = report.counts()
    colour = {"GO": "green", "GO_WITH_CONDITIONS": "orange", "NO_GO": "red"}[v.decision]
    st.markdown(f"## Verdict: :{colour}[{DECISION_LABEL[v.decision]}]")
    if report.gate_override:
        st.warning(report.gate_override)
    cols = st.columns(5)
    for col, (label, n) in zip(cols, [("Blocker", c["blocker"]), ("High", c["high"]), ("Medium", c["medium"]), ("Low", c["low"]), ("Hygiene", len(report.lint_findings))]):
        col.metric(label, n)
    st.write(v.executive_summary)

    t1, t2, t3, t4 = st.tabs(["Findings", "Launch conditions & scorecard", "Panel", "Hygiene"])
    with t1:
        sev_filter = st.multiselect("Severity", ["blocker", "high", "medium", "low"], default=["blocker", "high", "medium", "low"])
        for f in [f for f in report.findings if f.severity in sev_filter]:
            with st.expander(f"{f.id} · [{f.severity.upper()}] {f.title}  ({', '.join(f.personas)})"):
                if f.evidence:
                    st.markdown(f"> {f.evidence}")
                    st.caption({True: "✓ quote verified in PRD", False: "⚠ quote not found in PRD", None: ""}[f.evidence_verified]
                               + (f" · line {f.line}" if f.line else ""))
                st.markdown(f"**Issue.** {f.issue}\n\n**What goes wrong.** {f.failure_scenario}\n\n**Fix.** {f.recommendation}\n\n**Ask the PM.** {f.question_for_pm}")
                if f.moderator_note:
                    st.caption(f"Moderator: {f.moderator_note}")
    with t2:
        for cond in v.launch_conditions:
            st.checkbox(cond, key=cond)
        st.dataframe([{"Dimension": s.dimension, "Score": s.score, "Note": s.note} for s in v.scorecard], use_container_width=True)
    with t3:
        for name, take in report.persona_takes.items():
            st.markdown(f"**{name}** {'✅' if report.persona_signoffs.get(name) else '❌'}  \n{take}")
    with t4:
        st.dataframe([{"ID": f.id, "Severity": f.severity, "Issue": f.title, "Detail": f.issue} for f in report.lint_findings], use_container_width=True)

    stem = st.session_state.get("stem", "prd")
    d1, d2, d3 = st.columns(3)
    d1.download_button("Download Markdown", to_markdown(report), f"{stem}_redteam.md")
    d2.download_button("Download HTML", to_html(report), f"{stem}_redteam.html")
    d3.download_button("Download JSON", to_json(report), f"{stem}_redteam.json")
