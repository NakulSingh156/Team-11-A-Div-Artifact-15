"""Executive Decision Support System — Worklet 15 dashboard.

Run with:   streamlit run app.py

Two tabs, one per lab:

    1 · Plan the review   — Lab 1: clarify -> plan -> revise
    2 · Run the pipeline  — Lab 2: typed tools -> KPIs -> brief -> human gate

Every figure is computed live by edss_engine from the department records.
Nothing on any screen is a hardcoded mockup number.
"""

import json

import altair as alt
import pandas as pd
import streamlit as st

import edss_engine as eng
import lab_panels

st.set_page_config(page_title="Executive Decision Support System",
                   page_icon="📊", layout="wide", initial_sidebar_state="expanded")

OK, WARN, BAD = "#1a7f37", "#9a6700", "#b42318"
STATUS_COLOUR = {"on target": OK, "at risk": WARN, "below target": BAD}
STATUS_BG = {"on target": "rgba(26,127,55,.12)", "at risk": "rgba(154,103,0,.12)",
             "below target": "rgba(180,35,24,.12)"}

st.markdown("""
<style>
  .block-container {padding-top: 3.4rem; max-width: 1400px;}
  .edss-title {font-size:1.7rem; font-weight:700; letter-spacing:-.02em; margin:0;}
  .edss-sub {opacity:.68; font-size:.92rem; margin-top:.15rem;}
  .badge {display:inline-block; padding:.22rem .7rem; border-radius:999px;
          font-size:.78rem; font-weight:600;}
  .step {border-left:3px solid rgba(128,128,128,.35); padding:.15rem 0 .15rem .8rem;
         margin-left:.3rem; font-size:.88rem;}
  /* Two-tab bar */
  div[role="radiogroup"] {gap:.2rem; border-bottom:2px solid rgba(128,128,128,.22);}
  div[role="radiogroup"] > label {border:0; background:transparent; margin:0 0 -2px 0;
        border-radius:8px 8px 0 0; padding:.55rem 1.4rem;
        border-bottom:2px solid transparent; opacity:.6; font-weight:500;
        transition:opacity .12s ease, background .12s ease;}
  div[role="radiogroup"] > label:hover {opacity:1; background:rgba(128,128,128,.10);
        cursor:pointer;}
  div[role="radiogroup"] > label > div:first-child {display:none;}
  div[role="radiogroup"] > label:has(input:checked) {opacity:1; font-weight:700;
        color:#3b4fd8; border-bottom:2px solid #3b4fd8; background:rgba(59,79,216,.10);}
</style>
""", unsafe_allow_html=True)


def badge(text, colour, bg):
    return f'<span class="badge" style="color:{colour};background:{bg};">{text}</span>'


def fmt(value, unit):
    return eng.ReportGenerationAgent._fmt(value, unit)


# =============================================================================
# Sidebar — deliberately short. Anything optional is folded away.
# =============================================================================

with st.sidebar:
    st.markdown("### apniLeap AURA Coordinator")
    st.caption("Worklet 15 · Executive Decision Support System")

    run_clicked = st.button("▶  Run pipeline", type="primary", use_container_width=True)
    reviewer = st.text_input("Reviewing authority", "Dr. A. Principal")

    with st.expander("Options"):
        domains = st.multiselect("Domains in scope", eng.DOMAINS, default=eng.DOMAINS)
        latency = st.slider("Simulated source latency (ms per read)", 0, 400, 0, 25,
                            help="Demo aid: adds latency to each connector read so the "
                                 "parallel stage is visibly faster than running the four "
                                 "domain agents one after another. Never affects a figure.")
        if st.button("Reset everything", use_container_width=True):
            for k in ("run", "planner", "assistant"):
                st.session_state.pop(k, None)
            st.rerun()

    if "run" in st.session_state:
        r = st.session_state.run
        st.caption(f"Run `{r.run_id}` · {len(r.trace)} tool calls · "
                   f"{'v' + str(r.version) if r.version else 'draft'}")

if run_clicked:
    eng.SOURCE_LATENCY_SECONDS = latency / 1000.0
    with st.spinner("Access gate → 4 domain agents in parallel → KPI synthesis → "
                    "brief → validation…"):
        st.session_state.run = eng.ExecutiveRun(period=eng.REPORTING_PERIOD,
                                                domains=domains or eng.DOMAINS).execute()
    eng.SOURCE_LATENCY_SECONDS = 0.0

run = st.session_state.get("run")

# =============================================================================
# Header + the two tabs
# =============================================================================

h1, h2 = st.columns([3, 1])
with h1:
    st.markdown('<p class="edss-title">Executive Decision Support System</p>',
                unsafe_allow_html=True)
    st.markdown('<p class="edss-sub">Institution-wide KPIs against NIRF / NAAC and '
                'strategic-plan targets, with drill-down to the source department.</p>',
                unsafe_allow_html=True)
with h2:
    if run is None:
        st.markdown(badge("NO RUN YET", "#6b7280", "rgba(107,114,128,.14)"),
                    unsafe_allow_html=True)
    elif run.approved:
        st.markdown(badge(f"APPROVED v{run.version}", OK, STATUS_BG["on target"]),
                    unsafe_allow_html=True)
    else:
        st.markdown(badge("DRAFT — NOT CIRCULATED", WARN, STATUS_BG["at risk"]),
                    unsafe_allow_html=True)

# One tab per lab — the pipeline flow, left to right.
TABS = ["1 · Agent loop", "2 · Typed tools", "3 · Skills", "4 · Memory",
        "5 · Connector", "6 · Runtime", "7 · Node graph", "8 · Swarm",
        "9 · Grounding", "10 · Resilience", "11 · Factory", "12 · Governance",
        "13 · Specialists", "14 · Capstone"]
tab = st.radio("Tab", TABS, horizontal=True, key="tab", label_visibility="collapsed")
st.caption("All 14 labs · Phase A Foundations (1–6) · Phase B Orchestration (7–8) · "
           "Phase C Applied reliability (9–11) · Phase D Governance & capstone (12–14). "
           "Each tab drives the same code its lab notebook is graded on.")
st.write("")

# =============================================================================
# TAB 1 · Lab 1 — clarify -> plan -> revise
# =============================================================================

if tab == TABS[0]:
    st.caption("Lab 1. Before any KPI is computed, the coordinator turns a vague request "
               "into an executable plan: it asks only for what is genuinely missing, checks "
               "what it is allowed to read, then revises by patching the plan in place.")

    st.session_state.setdefault("plan_request", eng.PLANNER_EXAMPLE_REQUESTS[0])
    st.session_state.setdefault("planner", None)

    q1, q2 = st.columns([4, 1])
    with q1:
        request = st.text_area("Your request", key="plan_request", height=80,
                               label_visibility="collapsed")
    with q2:
        if st.button("▶  Start planning", type="primary", use_container_width=True):
            st.session_state.planner = eng.PlannerSession()
            st.session_state.planner.start(request)
        if st.button("Clear", use_container_width=True):
            st.session_state.planner = None

    planner = st.session_state.planner
    if planner is None:
        st.info("Type a request and press **Start planning**. Try a vague one "
                "(*“Analyze our college performance.”*) and a fully-specified one — the "
                "number of questions changes, because it is driven by what is missing, "
                "not by a script.  \n\nStopping condition, declared before the loop runs: "
                "`goal.plan_locked is True`")
        st.stop()

    m1, m2, m3 = st.columns(3)
    m1.metric("Status", planner.status.replace("_", " "))
    m2.metric("Clarification rounds", planner.rounds)
    m3.metric("Plan revision", f"r{planner.plan.revision}" if planner.plan else "—")

    filled = {k: v for k, v in planner.goal.as_dict().items() if v}
    st.markdown("**Requirements gathered so far** "
                f"({len(filled)} of {len(eng.REQUIRED_SLOTS)} slots filled)")
    st.dataframe(pd.DataFrame([
        {"requirement": k,
         "value": (", ".join(v) if isinstance(v, list) else v) or "— still missing"}
        for k, v in planner.goal.as_dict().items()]),
        use_container_width=True, hide_index=True)

    # ---- waiting on a human ------------------------------------------------
    if planner.status == "awaiting_input":
        st.warning(f"The coordinator needs {len(planner.pending_questions)} thing(s) before "
                   "it will plan. It will not invent them.")
        for i, q in enumerate(planner.pending_questions, 1):
            st.markdown(f"**Q{i}.** {q}")
        with st.form("plan_reply_form", clear_on_submit=True):
            reply = st.text_area("Your reply (answer what you can, in one message)",
                                 key="plan_reply", height=80)
            sent = st.form_submit_button("Send reply", type="primary")
        if sent and reply.strip():
            planner.answer(reply)
            st.rerun()

    elif planner.status == "abandoned":
        st.error(f"**Stopped without a plan.** {planner.log[-1].get('stop_reason', '')}")
        st.caption("This is the graded behaviour: an agent that cannot get its requirements "
                   "refuses to guess them.")

    # ---- the plan ----------------------------------------------------------
    if planner.plan is not None:
        body = planner.plan.body

        if planner.conflicts:
            st.markdown(f"**Conflicts the data-scope tool surfaced ({len(planner.conflicts)})**")
            for c in planner.conflicts:
                st.warning(f"**{c['type']}** · {c['domain']} — {c['detail']}  \n"
                           f"→ {c['required_action']}")

        st.markdown(f"### Execution plan · revision {planner.plan.revision}")
        st.markdown(f"**Objective** — {body['objective']}")
        s1, s2, s3 = st.columns(3)
        s1.markdown(f"**Domains**  \n{', '.join(body['scope']['domains'])}")
        s2.markdown(f"**Period**  \n{body['scope']['period']}")
        s3.markdown(f"**Drill-down**  \n{body['drilldown_policy']}")
        if body.get("brief_length_limit"):
            st.markdown(f"**Length limit** — {body['brief_length_limit']}")

        st.markdown("**Analysis steps** — stable ids are what make the plan patchable")
        st.dataframe(pd.DataFrame(body["analysis_steps"])[["id", "title", "owner_agent"]],
                     use_container_width=True, hide_index=True)

        with st.expander("KPI calculations, evidence requirements, brief structure, "
                         "validation checks, assumptions"):
            st.dataframe(pd.DataFrame(body["kpi_calculations"]),
                         use_container_width=True, hide_index=True)
            for label, key in [("Evidence requirements", "evidence_requirements"),
                               ("Decision brief structure", "brief_structure"),
                               ("Validation checks (hard gate)", "validation_checks"),
                               ("Assumptions and data caveats", "assumptions")]:
                st.markdown(f"**{label}**")
                for x in body.get(key, []):
                    st.markdown(f"- {x}")

        # ---- revise --------------------------------------------------------
        st.markdown("### Revise")
        st.caption("The plan is patched in place. Everything the feedback does not mention "
                   "is provably untouched — the diff below is computed, not claimed.")
        with st.form("plan_feedback_form", clear_on_submit=True):
            fb = st.text_input("What should change?", key="plan_feedback",
                               placeholder="e.g. Remove the Finance domain and make "
                                           "drill-down mandatory for every KPI")
            applied = st.form_submit_button("Apply feedback", type="primary")
        if applied and fb.strip():
            planner.apply_feedback(fb)
            st.rerun()

        if planner.plan.patch_history:
            st.dataframe(pd.DataFrame(planner.plan.patch_history),
                         use_container_width=True, hide_index=True)
            d = planner.diff_last_revision()
            d1, d2, d3 = st.columns(3)
            d1.markdown("**Changed**\n\n" + ("\n".join(f"- `{k}`" for k in d["changed"])
                                             or "_none_"))
            d2.markdown("**Added**\n\n" + ("\n".join(f"- `{k}`" for k in d["added"])
                                           or "_none_"))
            d3.markdown("**Untouched**\n\n" + ("\n".join(f"- `{k}`" for k in d["untouched"])
                                               or "_none_"))
            st.markdown(badge(f"✓ SAME PLAN OBJECT MUTATED — r{planner.plan.revision}, "
                              "never regenerated", OK, STATUS_BG["on target"]),
                        unsafe_allow_html=True)

    with st.expander(f"Iteration log ({len(planner.log)} entries)"):
        st.dataframe(pd.DataFrame([
            {"#": e["iteration"], "planned": e["planned"], "action": e["action"],
             "stopped": e["stopped"], "stop reason": e.get("stop_reason", "")}
            for e in planner.log]), use_container_width=True, hide_index=True)

# =============================================================================
# TAB 2 · Lab 2 — the whole loop: tools -> KPIs -> brief -> human gate
# =============================================================================

if tab == TABS[1]:
    if run is None:
        st.info("Press **Run pipeline** in the sidebar.\n\n"
                "The Coordinator confirms Registrar-authorised read access, runs the four "
                "domain agents **in parallel**, synthesises the institution KPI set, drafts "
                "the decision brief, runs the validation gate, and stops at the human "
                "approval gate. Every figure comes from the typed tool layer built in Lab 2.")
        st.stop()

    brief = run.brief
    sc = pd.DataFrame(brief["scorecard"])
    c = brief["counts"]

    # ---- 1. the loop that just ran ----------------------------------------
    st.markdown("#### The run")
    stages = pd.DataFrame([{"stage": s.name, "mode": s.mode, "status": s.status,
                            "ms": s.elapsed_ms} for s in run.stages])
    st.dataframe(stages, use_container_width=True, hide_index=True,
                 column_config={"ms": st.column_config.NumberColumn("ms", format="%.1f")})
    par = next(s for s in run.stages if s.name.startswith("Parallel"))
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Tool calls", len(run.trace))
    r2.metric("Validation gate", "passed" if run.brief_validation.valid else "BLOCKED")
    r3.metric("Parallel wall time", f"{par.elapsed_ms:.0f} ms")
    r4.metric("If run sequentially", f"{run.serial_ms:.0f} ms",
              delta=f"{run.serial_ms - par.elapsed_ms:+.0f} ms", delta_color="inverse")

    # ---- 2. the KPI scorecard ---------------------------------------------
    st.markdown("#### Institution KPIs against targets")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("KPIs tracked", c["total"])
    k2.metric("Below target", c["below_target"])
    k3.metric("Provisional", c["provisional"],
              help="Unreconciled figures. Labelled everywhere; never shown as actuals.")
    k4.metric("Rounding flags", c["rounding_flags"],
              help="Would read as on-target if rounded. Reported unrounded.")

    table = sc.assign(
        figure=[fmt(v, u) for v, u in zip(sc["value"], sc["unit"])],
        target_shown=[fmt(v, u) for v, u in zip(sc["target"], sc["unit"])],
        flag=[("⚠ provisional " if f != "final" else "")
              + ("⚠ rounding" if w else "") for f, w in
              zip(sc["figure_status"], sc["rounding_warning"])],
    )[["kpi_id", "name", "domain", "figure", "target_shown", "variance", "status",
       "flag", "source_system"]]
    table.columns = ["KPI", "Name", "Domain", "Value", "Target", "Variance", "Status",
                     "Flags", "Source system"]
    st.dataframe(table, use_container_width=True, hide_index=True)

    vdf = sc.assign(gap_pct=lambda d: (d["value"] - d["target"]) / d["target"] * 100,
                    label=lambda d: d["kpi_id"] + "  " + d["name"])
    base = alt.Chart(vdf).encode(
        y=alt.Y("label:N", sort=alt.EncodingSortField("gap_pct", order="ascending"),
                title=None, axis=alt.Axis(labelOverlap=False, labelLimit=240)))
    bars = base.mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("gap_pct:Q", title="variance as % of target"),
        color=alt.Color("status:N",
                        scale=alt.Scale(domain=list(STATUS_COLOUR),
                                        range=list(STATUS_COLOUR.values())),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["kpi_id", "name", "value", "unit", "target", "variance", "status",
                 "source_system"])
    text = base.mark_text(align="right", dx=-6, fontSize=11, color="white").encode(
        x="gap_pct:Q", text=alt.Text("gap_pct:Q", format="+.2f"))
    st.altair_chart((bars + text).properties(height=32 * len(vdf) + 60),
                    use_container_width=True)

    # ---- 3. ask a question -------------------------------------------------
    st.markdown("#### Ask a question")
    st.caption("The Lab 2 router works out which domain and KPI you mean, picks a tool "
               "chain, runs it, and answers only from what the tools returned.")
    if "assistant" not in st.session_state:
        st.session_state.assistant = eng.ExecutiveAssistant()
    assistant = st.session_state.assistant

    st.session_state.setdefault("question_box", "")
    e1, e2, e3 = st.columns(3)
    for col, q in zip((e1, e2, e3), [
            "Which departments are dragging placement down?",
            "How do our citations per faculty compare with peer institutions?",
            "Who should we recruit as Dean of Research next year?"]):
        if col.button(q, key=f"ex_{q[:14]}", use_container_width=True):
            st.session_state.question_box = q

    typed = st.text_input("Your question", key="question_box", label_visibility="collapsed",
                          placeholder="e.g. Are we meeting the pass percentage target?")
    if typed and st.session_state.get("last_answered") != typed:
        st.session_state.last_answered = typed
        ans = assistant.ask(typed)
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Domain", ans.domain or "—")
        a2.metric("KPI", ans.kpi_id or "—")
        a3.metric("Intent", ans.intent or "—")
        a4.metric("Tools called", len(ans.tools_used))
        if not ans.routed:
            st.warning(ans.text)
        else:
            st.success(ans.text)
            st.markdown(" → ".join(f"`{t}`" for t in ans.tools_used))
            if ans.grounded:
                st.markdown(badge("✓ GROUNDED — every figure traces to a tool output",
                                  OK, STATUS_BG["on target"]), unsafe_allow_html=True)

    # ---- 4. drill-down -----------------------------------------------------
    with st.expander("Drill-down evidence — trace any KPI back to its source department"):
        pick = st.selectbox("KPI", [r.kpi_id for r in run.kpi_results],
                            format_func=lambda k: f"{k} — {eng.KPI_DEFINITIONS[k]['name']}")
        r = next(x for x in run.kpi_results if x.kpi_id == pick)
        st.markdown(
            f"""<div class="step"><b>1 · KPI</b> — {r.name} =
            <b>{fmt(r.value, r.compared['unit'])}</b> ({r.status} against
            {fmt(r.compared['target'], r.compared['unit'])}, {r.compared['target_source']})</div>
            <div class="step"><b>2 · Formula</b> — <code>{r.computed['formula']}</code>,
            {', '.join(f'{k} = {v}' for k, v in r.computed['inputs_used'].items())}</div>
            <div class="step"><b>3 · Departments</b> — {r.computed['n_departments']}, below</div>
            <div class="step"><b>4 · Source</b> — {r.computed['source_system']}</div>""",
            unsafe_allow_html=True)
        if r.provisional:
            st.error(f"PROVISIONAL — {r.computed.get('caveat', '')}")
        if r.compared.get("rounding_warning"):
            st.warning(f"Rounding warning — {r.compared['rounding_warning']}")
        ev = pd.DataFrame(r.computed["evidence"])
        show = ev[["dept_code", "dept_name", "numerator", "denominator", "dept_value",
                   "share_of_denominator_pct"]].sort_values("dept_value")
        show.columns = ["Dept", "Department", ev["numerator_field"].iloc[0],
                        ev["denominator_field"].iloc[0] or "—", "Department figure",
                        "Share of denominator %"]
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.caption("Aggregation is over raw counts, never over department percentages — a "
                   "57-student department cannot count the same as a 228-student one.")

    # ---- 5. the decision brief and the human gate --------------------------
    st.markdown("#### Decision brief")
    if run.approved:
        st.success(f"**{brief['status']}** — approved by {brief['approved_by']}, released "
                   "to the Governing Council.")
    else:
        st.warning("**DRAFT — not circulated.** Chapter 15 permits zero consequential "
                   "actions without the Principal / Registrar's approval.")
    for s in brief["executive_summary"]:
        st.markdown(f"- {s}")

    v = run.brief_validation
    st.markdown(badge("VALIDATION GATE PASSED" if v.valid else "GATE BLOCKED",
                      OK if v.valid else BAD,
                      STATUS_BG["on target"] if v.valid else STATUS_BG["below target"]),
                unsafe_allow_html=True)

    with st.expander(f"Options for the {len(brief['findings'])} off-target KPIs "
                     f"({len(brief['options'])} drafted, each with risks and a trade-off)"):
        for kpi_id in dict.fromkeys(o["kpi_id"] for o in brief["options"]):
            opts = [o for o in brief["options"] if o["kpi_id"] == kpi_id]
            st.markdown(f"**{kpi_id} — {opts[0]['kpi_name']}**")
            for o in opts:
                st.markdown(f"- **{o['title']}** · {o['owner']} · {o['timeline']} · "
                            f"{o['indicative_cost']}")
                for risk in o["risks"]:
                    st.markdown(f"    - risk: {risk}")
                st.markdown(f"    - *trade-off: {o['trade_off']}*")

    with st.expander("Validation checks, findings and assumptions"):
        st.dataframe(pd.DataFrame([{"check": n, "result": "pass" if ok else "FAIL",
                                    "evidence": d} for n, ok, d in v.checks]),
                     use_container_width=True, hide_index=True)
        for f in brief["findings"]:
            st.markdown(f"**{f['kpi_id']} — {f['name']}** · {f['statement']}")
            for d in f["drivers"]:
                st.markdown(f"    - {d['dept_code']} ({d['dept_name']}): {d['dept_value']} "
                            f"— {d['numerator']} of {d['denominator']}")
        st.markdown("**Assumptions and data caveats**")
        for a in brief["assumptions"]:
            st.markdown(f"- {a}")

    st.markdown("#### Principal / Registrar gate")
    open_flags = [f for f in run.flags if not f["resolved"]]
    for i, f in enumerate(run.flags):
        fc1, fc2 = st.columns([5, 1])
        fc1.markdown(f"{'✅' if f['resolved'] else '🔺'} **{f['kpi_id']}** — {f['note']}")
        if not f["resolved"] and fc2.button("Resolve", key=f"res{i}"):
            run.resolve_flag(i, reviewer)
            st.rerun()

    g1, g2 = st.columns(2)
    with g1:
        fk = st.selectbox("Flag a KPI for clarification",
                          [r.kpi_id for r in run.kpi_results], key="flagkpi")
        fn = st.text_input("What needs clarifying?", key="flagnote")
        if st.button("Flag", use_container_width=True):
            if fn.strip():
                run.flag_kpi(fk, reviewer, fn.strip())
                st.rerun()
            else:
                st.error("Add a note so the responsible agent knows what to correct.")
    with g2:
        note = st.text_input("Approval note", "Approved for the Governing Council cycle.",
                             key="appnote")
        if st.button("✔  Approve and publish", type="primary", use_container_width=True,
                     disabled=run.approved or bool(open_flags) or not v.valid):
            run.approve(by=reviewer, note=note)
            st.rerun()
        if open_flags:
            st.caption(f"Blocked: {len(open_flags)} KPI(s) still flagged.")
        d1, d2 = st.columns(2)
        d1.download_button("⬇  Brief (.md)", run.to_markdown(),
                           file_name=f"{run.run_id}_brief.md", use_container_width=True)
        d2.download_button("⬇  Run record (.json)", run.to_json(),
                           file_name=f"{run.run_id}_run.json", use_container_width=True)

    # ---- 6. the audit trail ------------------------------------------------
    with st.expander(f"Audit trail — {len(run.trace)} tool calls, {len(run.audit)} "
                     "governance events"):
        st.caption("Every call that produced a figure above, with the reason the agent "
                   "chose it. Nothing reaches a panel without appearing here first.")
        st.dataframe(pd.DataFrame([
            {"#": t["seq"], "agent": t["agent"], "tool": t["tool"], "ok": t["ok"],
             "reason": t["reason"],
             "output": json.dumps(t["output"], default=str)[:120]}
            for t in run.trace]), use_container_width=True, hide_index=True, height=300)
        st.dataframe(pd.DataFrame(run.audit)[["seq", "actor", "action", "detail"]],
                     use_container_width=True, hide_index=True, height=260)


# =============================================================================
# TABS 3-8 · Labs 3-8, each driving the code its notebook is graded on
# =============================================================================

if tab == TABS[2]:
    lab_panels.panel_skills()
elif tab == TABS[3]:
    lab_panels.panel_memory()
elif tab == TABS[4]:
    lab_panels.panel_connector()
elif tab == TABS[5]:
    lab_panels.panel_runtime()
elif tab == TABS[6]:
    lab_panels.panel_graph()
elif tab == TABS[7]:
    lab_panels.panel_swarm()
elif tab == TABS[8]:
    lab_panels.panel_grounding()
elif tab == TABS[9]:
    lab_panels.panel_resilience()
elif tab == TABS[10]:
    lab_panels.panel_factory()
elif tab == TABS[11]:
    lab_panels.panel_governance()
elif tab == TABS[12]:
    lab_panels.panel_specialists()
elif tab == TABS[13]:
    lab_panels.panel_capstone()
