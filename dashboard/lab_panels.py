"""Dashboard panels for Labs 3-8.

Each panel drives the SAME code the lab notebooks are graded on — imported from
edss_stack (Labs 3-5) and edss_labs678 (Labs 6-8), not reimplemented here.
"""

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import edss_core as core
import edss_stack as stack
import edss_labs678 as labs
import edss_labs9to13 as l913
import edss_capstone as cap

OK, WARN, BAD = "#1a7f37", "#9a6700", "#b42318"
BG = {"ok": "rgba(26,127,55,.12)", "warn": "rgba(154,103,0,.12)",
      "bad": "rgba(180,35,24,.12)"}


def badge(text, colour, bg):
    return f'<span class="badge" style="color:{colour};background:{bg};">{text}</span>'


# =============================================================================
# Lab 3 · Skills
# =============================================================================

def panel_skills():
    st.caption("Lab 3 — a skill is a reusable capability package: instructions, "
               "constraints, typed input/output schemas and a declared tool surface, all "
               "enforced at call time. The case is an input, never a branch in the code.")

    st.markdown("#### The skill registry")
    for name, sk in stack.SKILL_REGISTRY.items():
        with st.expander(f"`{name}` — {sk.description}"):
            c1, c2 = st.columns(2)
            c1.markdown("**Inputs**")
            c1.json({k: v.get("type") for k, v in
                     sk.input_schema.get("properties", {}).items()})
            c1.caption(f"required: {sk.input_schema.get('required', [])}")
            c2.markdown("**Outputs**")
            c2.json({k: v.get("type") for k, v in
                     sk.output_schema.get("properties", {}).items()})
            st.markdown(f"**Tools it may call:** "
                        f"`{sk.tools if sk.tools else 'none — pure, calls no tool'}`")
            st.markdown("**Instructions**")
            st.code(sk.instructions, language=None)
            st.markdown("**Constraints**")
            for c in sk.constraints:
                st.markdown(f"- {c}")

    st.markdown("#### Run `review_domain` — the same skill, any case")
    c1, c2, c3 = st.columns([2, 2, 1])
    domain = c1.selectbox("Domain", core.DOMAINS, key="sk_domain")
    category = c2.selectbox("Department subset", ["all", "circuit", "core"], key="sk_cat")
    c3.write(""); c3.write("")
    go = c3.button("Run skill", type="primary", use_container_width=True)

    if go:
        router = core.ToolRouter(agent="dashboard:lab3")
        kwargs = {"domain": domain, "period": core.REPORTING_PERIOD}
        if category != "all":
            kwargs["category"] = category
        out = stack.SKILL_REGISTRY["review_domain"].run(router, **kwargs)
        st.success(out["headline"])
        df = pd.DataFrame([{"KPI": k["kpi_id"], "Name": k["name"],
                            "Value": round(k["value"], 2), "Unit": k["unit"],
                            "Target": k["target"], "Status": k["status"],
                            "Source": k["source_system"]} for k in out["kpis"]])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(router.trace)} tool calls, all inside the skill's declared "
                   f"surface: {sorted({e['tool'] for e in router.trace})}")

    st.markdown("#### The contract is enforced, not documented")
    bad_case = st.selectbox("Try an invalid call", [
        "domain='Sustainability'  (not in the enum)",
        "period missing  (required field)",
        "period=2025  (wrong type)",
        "sort_by='value'  (field the skill does not accept)",
        "format_document template='poster'  (not in the enum)"], key="sk_bad")
    if st.button("Send it", key="sk_bad_btn"):
        router = core.ToolRouter(agent="dashboard:lab3-bad")
        calls = {
            0: lambda: stack.SKILL_REGISTRY["review_domain"].run(
                router, domain="Sustainability", period=core.REPORTING_PERIOD),
            1: lambda: stack.SKILL_REGISTRY["review_domain"].run(router, domain="Academic"),
            2: lambda: stack.SKILL_REGISTRY["review_domain"].run(
                router, domain="Academic", period=2025),
            3: lambda: stack.SKILL_REGISTRY["review_domain"].run(
                router, domain="Academic", period=core.REPORTING_PERIOD, sort_by="value"),
            4: lambda: stack.SKILL_REGISTRY["format_document"].run(
                router, title="x", sections=[], template="poster"),
        }
        idx = ["domain='Sus", "period missin", "period=2025", "sort_by=", "format_doc"]
        i = next(n for n, p in enumerate(idx) if bad_case.startswith(p))
        try:
            calls[i]()
            st.error("NOT REFUSED — the contract did not hold")
        except stack.SkillContractError as exc:
            st.warning(f"**Refused before the skill body ran** — {exc}")


# =============================================================================
# Lab 4 · Memory & retrieval
# =============================================================================

def panel_memory():
    st.caption("Lab 4 — short-term run state versus a long-term, append-only archive. "
               "Retrieval by tag (precise) and by TF-IDF similarity (fuzzy), so the "
               "coordinator can ask 'is this getting worse?' and 'have we tried this "
               "before?'")

    briefs = [r for r in stack.archive.all() if r["type"] == "decision_brief"]
    snaps = [r for r in stack.archive.all() if r["type"] == "kpi_snapshot"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Archive records", len(stack.archive))
    m2.metric("Past decision briefs", len(briefs))
    m3.metric("Index vocabulary", f"{len(stack.index.idf)} terms")

    with st.expander("What is in the archive"):
        st.dataframe(pd.DataFrame([{"id": r["record_id"], "type": r["type"],
                                    "period": r["period"], "title": r["title"],
                                    "tags": ", ".join(r["tags"])}
                                   for r in stack.archive.all()]),
                     use_container_width=True, hide_index=True)

    st.markdown("#### Retrieve")
    q = st.text_input("Describe what you are working on",
                      "Placement is below target and the core branches are dragging it down",
                      key="mem_q")
    tag_choices = sorted({t for r in stack.archive.all() for t in r["tags"]})
    tags = st.multiselect("Filter by tag (optional)", tag_choices, key="mem_tags")

    if q.strip():
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**By tag** — exact")
            hits = stack.retrieve_by_tags(stack.archive, tags or ["placement"], "any",
                                          "decision_brief")
            st.dataframe(pd.DataFrame([{"id": h["record_id"], "matched": ", ".join(h["matched_tags"]),
                                        "score": h["tag_score"]} for h in hits])
                         if hits else pd.DataFrame([{"id": "— no record carries that tag"}]),
                         use_container_width=True, hide_index=True)
        with c2:
            st.markdown("**By similarity** — fuzzy")
            sim = stack.index.query(q, k=4, record_type="decision_brief")
            st.dataframe(pd.DataFrame([{"id": h["record_id"], "similarity": h["similarity"],
                                        "title": h["title"][:38]} for h in sim]),
                         use_container_width=True, hide_index=True)
        top = sim[0]
        if top["similarity"] > 0.2:
            st.info(f"**Closest prior case — {top['record_id']} ({top['period']})**  \n"
                    f"{top['summary']}  \n\n**Outcome:** {top['outcome']}")

    st.markdown("#### No-repeat check")
    st.caption("Before the brief proposes an option, ask the archive whether the Council "
               "has already tried it.")
    proposal = st.text_input("Proposed option",
                             "Approve a recruiter outreach budget to lift placement in "
                             "the core branches", key="mem_prop")
    if proposal.strip():
        prior = stack.index.query(proposal, k=1, record_type="decision_brief")[0]
        if prior["similarity"] >= 0.20:
            st.warning(f"**Already tried in {prior['period']}** (similarity "
                       f"{prior['similarity']:.3f}) — {prior['decisions'][0]}  \n"
                       f"Outcome: {prior['outcome']}")
        else:
            st.success(f"No close prior decision (closest {prior['similarity']:.3f}) — "
                       f"this is a genuinely new proposal.")

    st.markdown("#### Why the archive exists — year-on-year trend")
    router = core.ToolRouter(agent="dashboard:lab4")
    rows = stack.Connector(router).read("department reports", reason="trend",
                                        period=core.REPORTING_PERIOD)["rows"]
    s23 = stack.archive.get("KPI-SNAPSHOT-2023-24")["values"]
    s24 = stack.archive.get("KPI-SNAPSHOT-2024-25")["values"]
    trend = []
    for kpi_id, d in core.KPI_DEFINITIONS.items():
        now = core.compute_kpi(kpi_id, rows)["value"]
        cmp_ = core.compare_to_target(kpi_id, now)
        trend.append({"KPI": kpi_id, "Name": d["name"], "2023-24": s23[kpi_id],
                      "2024-25": s24[kpi_id], "2025-26": round(now, 2),
                      "YoY": round(now - s24[kpi_id], 2), "Target": cmp_["target"],
                      "Direction": "improving" if now > s24[kpi_id] else "declining"})
    tdf = pd.DataFrame(trend)
    st.dataframe(tdf, use_container_width=True, hide_index=True)
    declining = tdf[tdf["Direction"] == "declining"]
    if not declining.empty:
        r = declining.iloc[0]
        st.error(f"**{r['KPI']} — {r['Name']} is below target AND declining** "
                 f"({r['2023-24']} → {r['2024-25']} → {r['2025-26']}, {r['YoY']:+.2f} YoY). "
                 f"Read against the archived 2023-24 decision the cause is visible: the "
                 f"approved recruiter-outreach drive lifted placement percentage, and the "
                 f"wider recruiter pool pays less. This finding exists only because the "
                 f"decision and the baseline were both archived.")


# =============================================================================
# Lab 5 · MCP-style connector
# =============================================================================

def panel_connector():
    st.caption("Lab 5 — one typed connector over a CSV file, a real SQLite database and a "
               "mock HTTP API. Scoped tokens, one envelope, one error vocabulary, one "
               "audit log. No agent touches a source directly.")

    man = stack.server.describe()
    st.markdown("#### Capability manifest — what a client can discover without calling")
    st.dataframe(pd.DataFrame([{"resource": r["name"], "served by": r["served_by"],
                                "scope required": r["required_scope"],
                                "params": ", ".join(r["params"]),
                                "returns": r["returns"]} for r in man["resources"]]),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Tokens and scopes")
    st.dataframe(pd.DataFrame([{"token": t, "holder": r["holder"],
                                "scopes": ", ".join(sorted(r["scopes"]))}
                               for t, r in stack.server.tokens.items()]),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Try a call")
    c1, c2, c3 = st.columns([2, 2, 1])
    tok = c1.selectbox("Call as", list(stack.server.tokens),
                       format_func=lambda t: stack.server.tokens[t]["holder"], key="mcp_tok")
    res = c2.selectbox("Resource", list(stack.server.resources) + ["student_medical_records"],
                       key="mcp_res")
    c3.write(""); c3.write("")
    if c3.button("Call", type="primary", use_container_width=True):
        params = {"department_reports": {"period": core.REPORTING_PERIOD},
                  "kpi_definitions": {"kpi_ids": ["KPI-P1"]},
                  "external_benchmark": {"kpi_id": "KPI-P1"}}.get(res, {})
        try:
            out = stack.server.call(tok, res, **params)
            st.success(f"**Allowed** — served by `{out['served_by']}`")
            st.json(stack._summarise(out["data"]) if hasattr(stack, "_summarise")
                    else {"keys": list(out["data"])[:8]})
        except stack.MCPError as exc:
            st.warning(f"**{exc.code}** — {exc.message}")

    st.markdown("#### Swap the source — the acceptance test")
    st.caption("`department_reports` can be served by the CSV file or the SQLite table. "
               "The agent function is never edited; two lines change inside the connector.")
    current = stack.server.resources["department_reports"].backend
    choice = st.radio("Serve department_reports from", ["file:csv", "sqlite"],
                      index=0 if current == "file:csv" else 1, horizontal=True, key="mcp_swap")
    if choice != current:
        stack.server.resources["department_reports"].handler = (
            stack.file_backend.department_reports if choice == "file:csv"
            else stack.sqlite_backend.department_reports)
        stack.server.resources["department_reports"].backend = choice
        st.rerun()

    client = stack.MCPClient(stack.server, "tok-coordinator")
    reports = client.read("department_reports", period=core.REPORTING_PERIOD)
    figures = []
    for kpi_id in ["KPI-P1", "KPI-R2", "KPI-A1"]:
        v = core.compute_kpi(kpi_id, reports["rows"])
        figures.append({"KPI": kpi_id, "Value": v["value"],
                        "Rows read from": reports["source_system"]})
    st.dataframe(pd.DataFrame(figures), use_container_width=True, hide_index=True)
    st.info(f"Backend now: **{choice}** · rows provenance: *{reports['source_system']}* — "
            f"switch the radio and watch the figures stay identical while the provenance "
            f"string changes.")

    with st.expander(f"Connector audit log — {len(stack.server.log)} calls"):
        st.dataframe(pd.DataFrame([{"#": e["seq"], "holder": e["holder"],
                                    "resource": e["resource"],
                                    "backend": e.get("served_by", "—"),
                                    "ok": e["ok"], "error": e["error_code"] or ""}
                                   for e in stack.server.log]),
                     use_container_width=True, hide_index=True, height=280)


# =============================================================================
# Lab 6 · Runtime
# =============================================================================

def panel_runtime():
    st.caption("Lab 6 — the runtime the loop runs inside: budgets, an audit log of every "
               "action with inputs and outputs, approval gates, and checkpoint/resume so a "
               "crashed run does not start over.")

    st.session_state.setdefault("rt_store",
                                labs.CheckpointStore(Path(tempfile.gettempdir()) /
                                                     "edss_dashboard_checkpoints"))
    store = st.session_state.rt_store

    st.markdown("#### The run plan")
    st.dataframe(pd.DataFrame([{"action": a.name, "kind": a.kind,
                                "gate": "yes" if a.requires_approval else "-",
                                "depends on": ", ".join(a.depends_on) or "-",
                                "description": a.description} for a in labs.PLAN]),
                 use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    max_actions = c1.slider("Action budget", 1, 10, 10, key="rt_actions")
    if c2.button("▶ Run (a backend fails mid-run)", type="primary",
                 use_container_width=True):
        labs.reset_runtime_fault()
        if store.exists("DASH"):
            store.path("DASH").unlink()
        rt = labs.Runtime("DASH", labs.Budget(max_actions=max_actions), store)
        crashed = None
        for a in labs.PLAN:
            try:
                rt.perform(a)
            except Exception as exc:
                crashed = f"{type(exc).__name__}: {exc}"
                break
        st.session_state.rt_first = {"completed": list(rt.completed), "crashed": crashed,
                                     "audit": list(rt.audit)}
        st.session_state.pop("rt_resumed", None)
    if c3.button("⟲ Resume from checkpoint", use_container_width=True,
                 disabled="rt_first" not in st.session_state):
        rt2 = labs.Runtime.resume("DASH", labs.Budget(max_actions=10), store)
        before = list(rt2.completed)
        skipped, fresh = [], []
        for a in labs.PLAN:
            n = len(rt2.completed)
            try:
                rt2.perform(a)
            except labs.ApprovalRequired:
                break
            (skipped if len(rt2.completed) == n else fresh).append(a.name)
        rt2.approve("human_gate", by="Dr. A. Principal")
        for a in labs.PLAN:
            if a.name not in rt2.completed:
                rt2.perform(a)
                fresh.append(a.name)
        st.session_state.rt_resumed = {"restored": before, "skipped": skipped,
                                       "fresh": fresh, "completed": list(rt2.completed),
                                       "audit": list(rt2.audit)}

    first = st.session_state.get("rt_first")
    if first:
        st.error(f"**Crashed** — {first['crashed']}")
        st.markdown(f"Completed before the crash: `{first['completed']}` · "
                    f"checkpoint written to disk ({store.path('DASH').stat().st_size:,} bytes)")
    res = st.session_state.get("rt_resumed")
    if res:
        st.success(f"**Resumed and finished** — {len(res['completed'])}/{len(labs.PLAN)} "
                   f"actions complete")
        a, b, c = st.columns(3)
        a.metric("Restored from disk", len(res["restored"]))
        b.metric("Skipped (already done)", len(res["skipped"]))
        c.metric("Re-executed needlessly", len([x for x in res["fresh"]
                                                if x in res["restored"]]))
        st.markdown(f"Skipped: `{res['skipped']}` · newly executed: `{res['fresh']}`")
        with st.expander(f"Audit log — {len(res['audit'])} entries"):
            st.dataframe(pd.DataFrame([{"#": e["seq"], "action": e["action"],
                                        "kind": e["kind"], "status": e["status"],
                                        "ms": e["ms"], "error": e["error"] or ""}
                                       for e in res["audit"]]),
                         use_container_width=True, hide_index=True, height=320)


# =============================================================================
# Lab 7 · Node graph
# =============================================================================

def _dot(graph) -> str:
    colour = {"coordinator": "#1f3864", "agent": "#9dc3e6", "join": "#9dc3e6",
              "validation": "#b42318", "gate": "#9a6700", "publish": "#1a7f37"}
    font = {"coordinator": "white", "validation": "white", "gate": "white",
            "publish": "white", "agent": "black", "join": "black"}
    out = ['digraph G {', '  rankdir=TB;', '  bgcolor="transparent";',
           '  node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=10];',
           '  edge [fontname="Helvetica" fontsize=9];']
    for n in graph.nodes.values():
        out.append(f'  {n.name} [label="{n.label}" fillcolor="{colour[n.kind]}" '
                   f'fontcolor="{font[n.kind]}"];')
    for e in graph.edges:
        style = 'style=dashed color="#b42318" penwidth=2' if e.back_edge else 'color="#888888"'
        label = f' label="{e.condition}"' if e.condition else ""
        out.append(f'  {e.src} -> {e.dst} [{style}{label}];')
    out.append("}")
    return "\n".join(out)


def panel_graph():
    st.caption("Lab 7 — the pipeline as an explicit graph. The edges are data, so the "
               "wiring can be drawn, statically checked for unreachable nodes, and can "
               "carry a back-edge that returns control on a validation failure.")

    g = labs.g
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Nodes", len(g.nodes))
    m2.metric("Edges", len(g.edges))
    m3.metric("Back-edges", sum(1 for e in g.edges if e.back_edge))
    m4.metric("Conditional edges", sum(1 for e in g.edges if e.condition))

    st.graphviz_chart(_dot(g), use_container_width=True)
    st.caption("Navy = coordinator · light blue = agents · red = validation gate · "
               "amber = human gate · green = governed publish · dashed red = back-edge")

    check = g.validate("coordinator")
    st.markdown(badge("STATIC CHECK PASSED" if check["ok"] else "GRAPH WILL NOT RUN",
                      OK if check["ok"] else BAD, BG["ok"] if check["ok"] else BG["bad"]),
                unsafe_allow_html=True)
    st.caption(f"unreachable: {check['unreachable'] or 'none'} · dangling: "
               f"{check['dangling'] or 'none'} · terminal: {check['terminal_nodes']}")

    st.markdown("#### Run it")
    st.caption("The report node deliberately omits one KPI's source system on its first "
               "pass — exactly what the validation gate exists to catch.")
    if st.button("▶ Run the graph", type="primary", key="g_run"):
        labs.reset_graph_state()
        state = g.run("coordinator")
        st.session_state.g_result = {"trace": list(g.trace),
                                     "regen": labs.REGEN["count"],
                                     "validation": state["validation"],
                                     "published": state.get("published")}

    r = st.session_state.get("g_result")
    if r:
        df = pd.DataFrame([{"step": e["step"], "node": e["node"], "kind": e["kind"],
                            "condition": e["condition_taken"] or "-",
                            "ms": e["ms"], "note": e["note"]} for e in r["trace"]])
        st.dataframe(df, use_container_width=True, hide_index=True)
        visits = df["node"].value_counts().to_dict()
        c1, c2, c3 = st.columns(3)
        c1.metric("Steps", len(r["trace"]))
        c2.metric("Back-edge fired", r["regen"])
        c3.metric("Domain agents re-run", visits.get("domain_agents", 0) - 1)
        st.success(f"Validation passed on the second pass; published "
                   f"{r['published']}. `report_agent` ran "
                   f"{visits.get('report_agent', 0)}× and `validation` "
                   f"{visits.get('validation', 0)}× — but `domain_agents` and "
                   f"`kpi_agent` ran exactly once. Only the failing stage was redone.")


# =============================================================================
# Lab 8 · Parallel swarm
# =============================================================================

def panel_swarm():
    st.caption("Lab 8 — one agent per department, run in parallel, then merged. What makes "
               "it a swarm rather than a loop is everything that happens when parallel work "
               "goes wrong: retry, partial coverage, and two agents claiming the same item.")

    st.markdown("#### The units, and the faults injected on purpose")
    st.dataframe(pd.DataFrame([{
        "dept": u, "claims": len(labs.PUBLICATION_IDS[u]),
        "joint papers": ", ".join(p for p in labs.PUBLICATION_IDS[u] if p in labs.JOINT) or "-",
        "fault": ("flaky — fails once then recovers" if u == "CHEM"
                  else "DEAD — never responds" if u == "CIVIL" else "-")}
        for u in labs.UNITS]), use_container_width=True, hide_index=True)

    if st.button("▶ Run the swarm", type="primary", key="sw_run"):
        labs.reset_swarm_state()
        sw = labs.Swarm(labs.department_agent, max_retries=2, backoff_s=0.05)
        res = sw.run(labs.UNITS)
        st.session_state.sw = {
            "results": {u: {"ok": r.ok, "attempts": r.attempts, "ms": round(r.ms, 1),
                            "error": r.error,
                            "claimed": (r.data or {}).get("publication_count_claimed")}
                        for u, r in res.items()},
            "merged": labs.merge(res), "wall": sw.wall_ms, "serial": sw.serial_ms,
            "retry_log": list(sw.log)}

    s = st.session_state.get("sw")
    if not s:
        st.info("Press **Run the swarm**. Eight agents dispatch at once; CHEM recovers on "
                "retry, CIVIL never does.")
        return

    m = s["merged"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Agents", len(s["results"]))
    c2.metric("Succeeded", sum(1 for r in s["results"].values() if r["ok"]))
    c3.metric("Parallel wall time", f"{s['wall']:.0f} ms")
    c4.metric("If run one by one", f"{s['serial']:.0f} ms",
              delta=f"{s['serial'] - s['wall']:+.0f} ms", delta_color="inverse")

    st.dataframe(pd.DataFrame([{"dept": u, "ok": r["ok"], "attempts": r["attempts"],
                                "ms": r["ms"], "claimed": r["claimed"],
                                "error": r["error"] or ""}
                               for u, r in s["results"].items()]),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Coverage")
    if m["complete"]:
        st.success(f"All {len(s['results'])} departments reported.")
    else:
        st.error(f"**{m['coverage_pct']}% coverage** — {m['missing_departments']} did not "
                 f"report. A figure built on this cannot be published as institution-wide.")
        st.caption(f"What it may say instead: “Publications per faculty (PARTIAL — "
                   f"{len(m['reporting_departments'])} of {len(s['results'])} departments, "
                   f"{', '.join(m['missing_departments'])} not reporting): "
                   f"{m['kpis']['publications_per_faculty_reconciled']:.4f}”")

    st.markdown("#### Conflict resolution — merge identities, not counts")
    st.dataframe(pd.DataFrame([{"publication": p, "claimed by": ", ".join(u)}
                               for p, u in m["contested_publications"].items()]),
                 use_container_width=True, hide_index=True)
    a, b, c = st.columns(3)
    a.metric("Summed as counts", m["publications_naive_sum"])
    b.metric("Merged as identities", m["publications_reconciled"])
    c.metric("Double-counts removed", m["double_counted_removed"])
    st.info(f"Publications per faculty: **{m['kpis']['publications_per_faculty_naive']:.4f}** "
            f"if you sum the claims, **{m['kpis']['publications_per_faculty_reconciled']:.4f}** "
            f"once identities are merged. Chapter 15's Research guardrail — *never "
            f"double-count a cross-department collaboration* — enforced in the merge rather "
            f"than trusted to the departments.")

    with st.expander(f"Retry log — {len(s['retry_log'])} failed attempts"):
        st.dataframe(pd.DataFrame(s["retry_log"]), use_container_width=True,
                     hide_index=True)


# =============================================================================
# Lab 9 · Deep research — grounding
# =============================================================================

def panel_grounding():
    st.caption("Lab 9 — a claim is worthless until it is tied to a real, in-scope "
               "source. research() may FAIL, and a candidate with no source is "
               "rejected, not kept with a caveat.")

    st.markdown("#### The four in-scope sources")
    st.dataframe(pd.DataFrame([{"source": k, "what it is": v}
                               for k, v in l913.IN_SCOPE_SOURCES.items()]),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Screen a claim")
    st.caption("Pick one of the candidates the Report Generation Agent wants to put in "
               "the brief. Three of the eight rest on nothing.")
    labels = {f"{c.cid} — {c.text[:62]}": c for c in l913.CANDIDATES}
    pick = st.selectbox("Candidate", list(labels), key="g9_pick")
    c = labels[pick]
    if st.button("Ground it", type="primary", key="g9_run"):
        ev = l913.research(c)
        if ev.in_scope:
            st.success(f"**GROUNDED** — {ev.source}")
            st.markdown(f"- **locator:** `{ev.locator}`\n- **value:** `{ev.value}`\n"
                        f"- **why:** {ev.reason}")
        else:
            st.error(f"**REJECTED** — {ev.reason}")
            st.caption("It is not kept with a caveat. The brief simply does not get "
                       "to say it.")

    st.markdown("#### The evidence table")
    rows = []
    for cand in l913.CANDIDATES:
        ev = l913.research(cand)
        # the value column mixes floats, ints and text, so render it as str —
        # otherwise Arrow tries to coerce the whole column to double
        rows.append({"id": cand.cid, "kind": cand.kind, "in scope": ev.in_scope,
                     "source": ev.source or "—",
                     "value": "—" if ev.value is None else str(ev.value)[:40],
                     "locator/reason": ev.locator or ev.reason})
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    ok, bad = int(df["in scope"].sum()), int((~df["in scope"]).sum())
    a, b = st.columns(2)
    a.metric("Grounded", ok)
    b.metric("Rejected", bad)
    st.info("Every rejected claim *reads* like a finding — a causal story with no "
            "source, a KPI that does not exist, a field no department reports. That is "
            "why grounding has to be structural rather than a matter of care.")


# =============================================================================
# Lab 10 · Ops resilience — validate, diagnose, heal
# =============================================================================

def panel_resilience():
    st.caption("Lab 10 — when a check fails, work out WHICH constraint broke, on WHICH "
               "part, and repair only that. Rebuilding everything churns good work.")

    st.markdown("#### The constraints")
    st.dataframe(pd.DataFrame([{"constraint": c.cid, "scope": c.scope, "rule": c.text,
                                "what a failure means": c.diagnosis}
                               for c in l913.CONSTRAINTS]),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Inject a fault and watch it heal")
    FAULTS = {
        "A KPI row loses its source citation": l913.inject_missing_source,
        "The assumptions block is truncated": l913.inject_dropped_assumptions,
        "An option loses its risks and trade-off": l913.inject_option_without_risks,
        "The provisional figure loses its caveat": l913.inject_unlabelled_provisional,
        "91.85 is displayed as 92, hiding a miss": l913.inject_rounding_cover_up,
    }
    choice = st.selectbox("Fault to inject", list(FAULTS), key="r10_fault")
    if st.button("Inject and heal", type="primary", key="r10_run"):
        brief = l913.build_brief(l913.ROWS)
        import copy as _c
        what = FAULTS[choice](brief)
        broken = _c.deepcopy(brief)
        pre = l913.validate(brief)
        healed = l913.heal(brief)
        touched = [k["kpi_id"] for k, kb in zip(brief["kpis"], broken["kpis"]) if k != kb]
        untouched = sum(1 for k, kb in zip(brief["kpis"], broken["kpis"]) if k == kb)

        st.warning(f"**injected** — {what}")
        st.error("**detected** — " +
                 ", ".join(f"{f['constraint']} @ {f['where']}" for f in pre.failing))
        st.markdown(f"**diagnosis** — {l913.diagnose(pre)[0]}")
        st.success(f"**healed** in {healed['attempts']} attempt(s); "
                   f"all {len(l913.CONSTRAINTS)} constraints now satisfied")
        m1, m2, m3 = st.columns(3)
        m1.metric("KPI rows repaired", len(touched))
        m2.metric("KPI rows untouched", untouched)
        m3.metric("Retry budget used", f"{healed['attempts']}/{l913.RETRY_BUDGET}")
        st.caption(f"Repaired: {touched or 'a brief-level section'}. That is the pitfall "
                   f"being guarded — rebuilding the brief would have churned "
                   f"{untouched} good rows to fix one.")

    st.markdown("#### When repair is impossible")
    if st.button("Inject an UNREPAIRABLE fault", key="r10_esc"):
        broken = l913.build_brief(l913.ROWS)
        broken["kpis"].append({"kpi_id": "KPI-X9", "name": "Unapproved metric",
                               "value": 42.0, "value_shown": "42.00", "unit": "%",
                               "target": 50.0, "status": "below target",
                               "source_system": "", "figure_status": "final",
                               "caveat": "", "rounding_warning": None})
        try:
            l913.heal(broken)
            st.error("the loop claimed success on an unrepairable fault")
        except l913.Escalation as exc:
            last = json.loads(str(exc))
            st.error(f"**ESCALATED** after {l913.RETRY_BUDGET} attempts — "
                     f"{last['failing']}")
            st.caption("It did not publish, did not loop forever, and did not quietly "
                       "drop the row. It spent its budget and handed the problem to a "
                       "human with the failing constraint named.")


# =============================================================================
# Lab 11 · SDLC factory — the plan is the spec
# =============================================================================

def panel_factory():
    st.caption("Lab 11 — the locked plan becomes a build specification, and the "
               "acceptance suite is DERIVED from it. Change the spec and the tests "
               "change themselves.")

    import copy as _c
    st.session_state.setdefault("f11_spec", _c.deepcopy(l913.SPEC))
    spec = st.session_state.f11_spec

    st.markdown("#### The spec")
    c1, c2 = st.columns(2)
    with c1:
        kpis = st.multiselect("required_kpis", list(core.KPI_DEFINITIONS),
                              default=spec["required_kpis"], key="f11_kpis")
        domains = st.multiselect("domains", core.DOMAINS, default=spec["domains"],
                                 key="f11_domains")
    with c2:
        extra = st.text_input("add a brief section", "", key="f11_sec",
                              placeholder="e.g. Council cover note")
        mandatory = st.checkbox("drill-down mandatory for every KPI",
                                value=spec["drilldown_policy"].startswith("mandatory"),
                                key="f11_dd")

    spec["required_kpis"] = kpis or spec["required_kpis"]
    spec["domains"] = domains or spec["domains"]
    spec["drilldown_policy"] = ("mandatory for every KPI" if mandatory
                                else "only for KPIs that miss their target")
    sections = list(l913.SPEC["brief_sections"])
    if extra.strip() and extra.strip() not in sections:
        sections.insert(0, extra.strip())
    spec["brief_sections"] = sections

    suite = l913.derive_suite(spec)
    from collections import Counter as _C
    st.markdown(f"#### The suite — **{len(suite)} tests**, none written by hand")
    st.dataframe(pd.DataFrame([{"spec field": k, "tests it generated": v}
                               for k, v in _C(t.derived_from for t in suite).items()]),
                 use_container_width=True, hide_index=True)
    st.caption("Add a KPI or a section above and watch this table change — no test is "
               "edited anywhere.")

    st.markdown("#### Build and judge")
    complete = st.radio("Build quality", ["naive first pass", "complete build"],
                        horizontal=True, key="f11_quality")
    if st.button("▶ Build and run the suite", type="primary", key="f11_run"):
        artifact = l913.build(spec, complete=(complete == "complete build"))
        report = l913.acceptance_suite(artifact, spec)
        st.session_state.f11_report = report.results
        st.session_state.f11_pass = report.all_pass
        try:
            l913.submit_for_review(artifact, report, "Principal / Registrar")
            st.session_state.f11_gate = "SUBMITTED to the Principal / Registrar"
        except l913.AcceptanceGateError as exc:
            st.session_state.f11_gate = f"REFUSED — {exc}"

    if "f11_report" in st.session_state:
        res = st.session_state.f11_report
        df = pd.DataFrame(res)[["tid", "derived_from", "passed", "detail"]]
        st.dataframe(df, use_container_width=True, hide_index=True, height=300)
        a, b = st.columns(2)
        a.metric("Tests green", f"{sum(r['passed'] for r in res)}/{len(res)}")
        b.metric("all_pass", str(st.session_state.f11_pass))
        if st.session_state.f11_pass:
            st.success(st.session_state.f11_gate)
        else:
            st.error(st.session_state.f11_gate)
            st.caption("The human never sees this build. The acceptance suite, not the "
                       "author, decides what is ready for review.")


# =============================================================================
# Lab 12 · Safety & governance
# =============================================================================

def panel_governance():
    st.caption("Lab 12 — permission is what an actor may DO; confidentiality is what an "
               "actor may SEE. Both are enforced, and every release is versioned and "
               "reversible.")

    st.markdown("#### Roles")
    st.dataframe(pd.DataFrame([{"role": r.name, "view": r.can_view, "edit": r.can_edit,
                                "approve": r.can_approve, "rollback": r.can_rollback,
                                "dept detail": r.sees_department_detail,
                                "provisional": r.sees_provisional}
                               for r in l913.ROLES.values()]),
                 use_container_width=True, hide_index=True)

    if "g12" not in st.session_state:
        st.session_state.g12 = l913.Governance()
        st.session_state.g12_draft = l913.make_brief()
    gov = st.session_state.g12

    st.markdown("#### Try to approve")
    who = st.selectbox("Acting as", list(l913.ACTORS),
                       format_func=lambda k: str(l913.ACTORS[k]), key="g12_who")
    if st.button("Approve and publish", type="primary", key="g12_approve"):
        draft = l913.make_brief()
        try:
            v = gov.approve_and_publish(l913.ACTORS[who], draft,
                                        edits=["Tightened the summary."])
            st.success(f"Published **v{v}** — {l913.ACTORS[who]}")
        except (l913.PermissionError_, l913.StateError) as exc:
            st.warning(f"**DENIED** — {exc}")

    if gov.versions:
        st.markdown("#### Releases")
        st.dataframe(pd.DataFrame([{"version": n, "approved by": r["approved_by"],
                                    "at": r["approved_at"],
                                    "live": "← LIVE" if n == gov.current else ""}
                                   for n, r in gov.versions.items()]),
                     use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        to_v = c1.selectbox("Roll back to", list(gov.versions), key="g12_v")
        if c2.button("⟲ Roll back", key="g12_rb"):
            try:
                gov.rollback(l913.ACTORS[who], to_v)
                st.success(f"current → v{to_v} (v{max(gov.versions)} stays on record)")
            except (l913.PermissionError_, l913.StateError) as exc:
                st.warning(f"**DENIED** — {exc}")

    st.markdown("#### Confidentiality — the same brief, rendered per reader")
    reader = st.selectbox("Rendered for", list(l913.ACTORS),
                          index=list(l913.ACTORS).index("council"),
                          format_func=lambda k: str(l913.ACTORS[k]), key="g12_reader")
    view = l913.view_for(l913.ACTORS[reader], st.session_state.g12_draft)
    a, b = st.columns(2)
    a.metric("KPIs visible", f"{len(view['kpis'])} of "
                             f"{len(st.session_state.g12_draft['kpis'])}")
    b.metric("Redactions", len(view["redactions"]))
    if view["redactions"]:
        st.warning("Withheld: " + ", ".join(view["redactions"]))
        st.caption("Every redaction is declared, so a reader is never misled about "
                   "completeness.")
    else:
        st.success("This reader sees the full document.")

    with st.expander(f"Governance audit — {len(gov.audit)} entries"):
        if gov.audit:
            st.dataframe(pd.DataFrame(gov.audit)[["seq", "actor", "action", "detail",
                                                  "allowed"]],
                         use_container_width=True, hide_index=True)


# =============================================================================
# Lab 13 · Domain specialists
# =============================================================================

def panel_specialists():
    st.caption("Lab 13 — the four domains are not interchangeable. Each pack brings its "
               "own vocabulary, its own option templates and, critically, its own "
               "CHECKABLE SCHEME.")

    st.markdown("#### The packs")
    st.dataframe(pd.DataFrame([{"domain": d, "pack": sp.name,
                                "vocabulary": ", ".join(sp.vocabulary[:4]),
                                "required scheme": ", ".join(sp.required_scheme)}
                               for d, sp in l913.REGISTRY.items()]),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Route a work item to its specialist")
    items = {f"{i.kpi_id} — {i.name} ({i.domain})": i for i in l913.ITEMS}
    pick = st.selectbox("Off-target KPI", list(items), key="s13_item")
    item = items[pick]
    if st.button("Generate with the owning pack", type="primary", key="s13_run"):
        sp = l913.REGISTRY[item.domain]
        out = sp.check(sp.generate(item))
        st.success(out.headline)
        for o in out.options:
            st.markdown(f"**{o['title']}**  \n"
                        f"owner {o['owner']} · {o['timeline']}  \n"
                        f"*measure of success:* {o['measure_of_success']}")
            for r in o["risks"]:
                st.markdown(f"- risk: {r}")
            st.info(f"trade-off — {o['trade_off']}")
        st.markdown("**Checkable scheme**")
        st.json(out.scheme_fields)
        st.markdown(badge("✓ PASSES ITS OWN SCHEME" if out.valid
                          else f"✗ {out.violations}",
                          OK if out.valid else BAD,
                          BG["ok"] if out.valid else BG["bad"]),
                    unsafe_allow_html=True)

    st.markdown("#### Why a generic agent is not enough")
    if st.button("Compare generic vs specialist on the Finance KPI", key="s13_cmp"):
        import copy as _c
        fin = next(i for i in l913.ITEMS if i.domain == "Finance")
        sp = l913.REGISTRY["Finance"]
        special = sp.check(sp.generate(fin))

        class _Generic(l913.Specialist):
            domain, name = "generic", "Generic generation agent"
            vocabulary, required_scheme = ["target", "improve"], []
            def generate(self, it):
                return l913.SpecialistOutput(
                    it.kpi_id, self.name,
                    f"{it.name} is below target and should be improved.",
                    [{"title": f"Improve {it.name}", "owner": "TBD", "timeline": "TBD",
                      "risks": ["Unspecified."], "trade_off": "Unspecified.",
                      "measure_of_success": "Improvement."}], {})

        gen = _Generic().check(_Generic().generate(fin))
        gen_under_finance = sp.check(_c.deepcopy(gen))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Generic agent**")
            st.write(gen.headline)
            st.json(gen.scheme_fields or {})
            st.error(f"Judged by the Finance pack: {len(gen_under_finance.violations)} "
                     f"violations")
            for v in gen_under_finance.violations:
                st.caption(f"• {v}")
        with c2:
            st.markdown("**Finance specialist**")
            st.write(special.headline)
            st.json(special.scheme_fields)
            st.success("action_permitted = False — the only option it will draft is "
                       "to defer, because the figure is unreconciled.")


# =============================================================================
# Lab 14 · Capstone — the whole system, end to end
# =============================================================================

def panel_capstone():
    st.caption("Lab 14 — integrate, don't rewrite. Every capability below is imported "
               "from the layer its lab built; this panel only wires and runs.")

    if "cap_system" not in st.session_state:
        st.session_state.cap_system = cap.deploy()
    system = st.session_state.cap_system

    st.markdown("#### The deployed system")
    st.dataframe(pd.DataFrame([{"lab": k, "wired in": v}
                               for k, v in cap.wiring_summary(system).items()]),
                 use_container_width=True, hide_index=True)
    st.caption("Lines of new capability written in the capstone: 0.")

    st.markdown("#### Run the whole thing")
    st.code(cap.REQUEST, language=None)
    if st.button("▶  Run request → approved brief", type="primary", key="cap_run"):
        st.session_state.cap_system = cap.deploy()     # fresh governance each run
        system = st.session_state.cap_system
        res = cap.run(system, cap.REQUEST, l913.ACTORS["principal"])
        st.session_state.cap_result = {
            "stages": res["stages"], "ms": res["ms"], "version": res["version"],
            "artifact": res["artifact"],
            "suite_total": len(res["suite"].results),
            "suite_pass": sum(r["passed"] for r in res["suite"].results),
            "heal": res["heal"]["attempts"],
            "merged": res["merged"], "grounded": len(res["grounded"]),
            "metrics": list(system.metrics), "audit": list(system.audit)}

    r = st.session_state.get("cap_result")
    if not r:
        st.info("Press run. Eleven stages: connector → swarm → skills → memory → "
                "specialists → grounding → validate → heal → acceptance suite → gate "
                "→ approve & publish.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stages", len(r["stages"]))
    m2.metric("Wall time", f"{r['ms']:.0f} ms")
    m3.metric("Acceptance tests", f"{r['suite_pass']}/{r['suite_total']}")
    m4.metric("Defects healed", r["heal"])

    st.markdown("##### Stage timeline")
    st.dataframe(pd.DataFrame(r["stages"]), use_container_width=True, hide_index=True)

    live = r["artifact"]
    st.success(f"**{live['status'].upper()} v{live['version']}** — approved by "
               f"{live['approved_by']} at {live['approved_at']}")

    st.markdown("##### The approved brief")
    st.dataframe(pd.DataFrame([{"KPI": k["kpi_id"], "name": k["name"],
                                "value": k["value_shown"], "target": k["target"],
                                "status": k["status"],
                                "flag": "PROVISIONAL" if k["figure_status"] != "final"
                                        else "", "source": k["source_system"]}
                               for k in live["kpis"]]),
                 use_container_width=True, hide_index=True)

    with st.expander(f"Options — {len(live['options'])} drafted by "
                     f"{len({o['specialist'] for o in live['options']})} domain packs"):
        for o in live["options"]:
            st.markdown(f"**{o['kpi_id']} · {o['title']}**  \n"
                        f"{o['specialist']} · owner {o['owner']} · {o['timeline']}  \n"
                        f"*measure:* {o['measure_of_success']}  \n"
                        f"*trade-off:* {o['trade_off']}")

    st.markdown("##### The same release, for the Governing Council")
    council = l913.view_for(l913.ACTORS["council"], live)
    a, b = st.columns(2)
    a.metric("KPIs visible", f"{len(council['kpis'])} of {len(live['kpis'])}")
    b.metric("Redactions", len(council["redactions"]))
    st.warning("Withheld: " + ", ".join(council["redactions"]))

    with st.expander("Metrics and audit"):
        st.dataframe(pd.DataFrame(r["metrics"]), use_container_width=True,
                     hide_index=True)
        st.dataframe(pd.DataFrame(r["audit"]), use_container_width=True,
                     hide_index=True)
