"""Smoke test: drive the Streamlit app headlessly and assert nothing throws.

Covers every interactive path, including the governance rule that a flagged KPI
must block approval.
"""
from streamlit.testing.v1 import AppTest


def show(at, label):
    if at.exception:
        for e in at.exception:
            print(f"  !! {label}: {e.type}: {e.value}")
            trace = e.stack_trace
            print(trace[-1500:] if isinstance(trace, str) else "".join(trace or [])[-1500:])
        raise SystemExit(1)
    print(f"  ok  {label}")


TAB_PLAN = "1 · Agent loop"
TAB_RUN = "2 · Typed tools"


def goto(at, tab):
    at.session_state["tab"] = tab
    at.run()
    show(at, f"tab '{tab.split(chr(183))[0].strip()}' renders")


at = AppTest.from_file("app.py", default_timeout=180)
at.run()
show(at, "initial load (no run yet)")

[b for b in at.sidebar.button if "Run pipeline" in b.label][0].click().run()
show(at, "after Run pipeline")
run = at.session_state["run"]
print(f"      run {run.run_id}  KPIs {len(run.kpi_results)}  tool calls {len(run.trace)}  "
      f"validation {run.brief_validation.valid}")

# --- both tabs render -------------------------------------------------------
ALL_TABS = ["1 · Agent loop", "2 · Typed tools", "3 · Skills", "4 · Memory",
            "5 · Connector", "6 · Runtime", "7 · Node graph", "8 · Swarm",
            "9 · Grounding", "10 · Resilience", "11 · Factory", "12 · Governance",
            "13 · Specialists", "14 · Capstone"]
for t in ALL_TABS:
    goto(at, t)

# --- Lab 1 planner: clarify -> plan -> revise -------------------------------
goto(at, TAB_PLAN)
at.session_state["plan_request"] = "Analyze our college performance."
at.run()
[b for b in at.button if "Start planning" in b.label][-1].click().run()
show(at, "planner started on a vague request")
pl = at.session_state["planner"]
print(f"      round 1: status={pl.status} questions={len(pl.pending_questions)}")
assert pl.status == "awaiting_input" and len(pl.pending_questions) >= 2, \
    "a vague request must trigger at least two clarifying questions"

[t for t in at.text_area if t.key == "plan_reply"][-1].set_value(
    "All four domains for academic year 2025-26. Leadership wants a decision brief with "
    "options and risks.")
[b for b in at.button if b.label == "Send reply"][-1].click().run()
show(at, "planner after reply 1")
pl = at.session_state["planner"]
print(f"      round 2: status={pl.status} questions={len(pl.pending_questions)}")
assert len(pl.pending_questions) < 6, "answered slots must not be asked again"

[t for t in at.text_area if t.key == "plan_reply"][-1].set_value(
    "Use the approved institution-wide KPI set, compare against NIRF, NAAC and the "
    "strategic plan, drill-down only for KPIs that miss their target.")
[b for b in at.button if b.label == "Send reply"][-1].click().run()
show(at, "planner after reply 2")
pl = at.session_state["planner"]
assert pl.status == "plan_ready" and pl.plan is not None
plan_id = id(pl.plan)
print(f"      plan locked: {len(pl.plan.body['analysis_steps'])} steps, "
      f"{len(pl.conflicts)} conflicts surfaced")
assert pl.conflicts, "the Finance period/provisional conflicts must be caught"

[t for t in at.text_input if t.key == "plan_feedback"][-1].set_value(
    "Remove the Finance domain and make drill-down mandatory for every KPI.")
[b for b in at.button if "Apply feedback" in b.label][-1].click().run()
show(at, "planner after revision 1")
[t for t in at.text_input if t.key == "plan_feedback"][-1].set_value(
    "Keep the brief to two pages and add year-on-year trend context.")
[b for b in at.button if "Apply feedback" in b.label][-1].click().run()
show(at, "planner after revision 2")
pl = at.session_state["planner"]
assert pl.plan.revision == 2, "two revision rounds expected"
assert id(pl.plan) == plan_id, "revise() must MUTATE the plan, not regenerate it"
d = pl.diff_last_revision()
assert "objective" in d["untouched"] and "kpi_calculations" in d["untouched"], d
print(f"      revisions: r{pl.plan.revision} on the SAME object (id stable)")
print(f"      round 2 left untouched: {d['untouched'][:4]}…")
print("  ok  Lab 1 loop: asks only what is missing, mutates rather than regenerates")

# --- the Ask panel ----------------------------------------------------------
goto(at, TAB_RUN)
at.session_state["question_box"] = "Which departments are dragging placement down?"
at.run()
show(at, "after asking a routed question")
a = at.session_state["assistant"].history[-1]
print(f"      routed: domain={a.domain} kpi={a.kpi_id} intent={a.intent} "
      f"tools={len(a.tools_used)} grounded={a.grounded}")
assert (a.kpi_id, a.intent, a.grounded) == ("KPI-P1", "drilldown", True)

at.session_state["question_box"] = "Who should we appoint as Dean next year?"
at.run()
show(at, "after an out-of-scope question")
a = at.session_state["assistant"].history[-1]
assert not a.routed and not a.tools_used
print(f"      declined correctly with {len(a.tools_used)} tool calls")

# --- the governance gate ----------------------------------------------------
goto(at, TAB_RUN)
at.text_input(key="flagnote").set_value("Confirm the EEE placement count with the Cell.")
[b for b in at.button if b.label == "Flag"][-1].click().run()
show(at, "after flagging a KPI")
run = at.session_state["run"]
print(f"      flags open: {sum(not f['resolved'] for f in run.flags)}")
assert [b for b in at.button if "Approve and publish" in b.label][0].disabled
print("  ok  approval correctly BLOCKED while a KPI is flagged")

[b for b in at.button if b.label == "Resolve"][0].click().run()
show(at, "after resolving the flag")
approve = [b for b in at.button if "Approve and publish" in b.label][0]
assert not approve.disabled
approve.click().run()
show(at, "after approval")
run = at.session_state["run"]
print(f"      {run.brief['status']} by {run.brief['approved_by']}  "
      f"published {len(run.published)}  audit {len(run.audit)}")
assert run.approved and run.version == 1

# --- the panel selection must survive the approval rerun --------------------
assert at.session_state["tab"] == TAB_RUN, "tab selection was lost on rerun"
print("  ok  tab selection survived the approval rerun")


# --- Labs 3-8: every tab's demo must actually run, not just render ----------
goto(at, "3 · Skills")
[b for b in at.button if b.label == "Run skill"][-1].click().run()
show(at, "Lab 3 — review_domain skill runs from the UI")
[b for b in at.button if b.label == "Send it"][-1].click().run()
show(at, "Lab 3 — an invalid call is refused by the schema")

goto(at, "4 · Memory")
show(at, "Lab 4 — tag + similarity retrieval and the YoY trend render")

goto(at, "5 · Connector")
at.selectbox(key="mcp_tok").set_value("tok-intern")
at.selectbox(key="mcp_res").set_value("department_reports")
[b for b in at.button if b.label == "Call"][-1].click().run()
show(at, "Lab 5 — a token without the scope is refused")
at.radio(key="mcp_swap").set_value("sqlite")
at.run()
show(at, "Lab 5 — the source swaps file -> sqlite")

goto(at, "6 · Runtime")
[b for b in at.button if "Run (a backend fails" in b.label][-1].click().run()
show(at, "Lab 6 — the run crashes and checkpoints")
before = at.session_state["rt_first"]["completed"]
[b for b in at.button if "Resume" in b.label][-1].click().run()
show(at, "Lab 6 — the run resumes from the checkpoint")
r6 = at.session_state["rt_resumed"]
assert len(r6["completed"]) == 7, "the resumed run must finish all 7 actions"
assert not [x for x in r6["fresh"] if x in r6["restored"]], "completed work was repeated"
print(f"      crashed after {len(before)} actions; resumed, skipped {len(r6['skipped'])}, "
      f"finished {len(r6['completed'])}/7")

goto(at, "7 · Node graph")
[b for b in at.button if "Run the graph" in b.label][-1].click().run()
show(at, "Lab 7 — the graph runs and the back-edge fires")
g7 = at.session_state["g_result"]
assert g7["regen"] == 1 and g7["validation"]["passed"]
print(f"      {len(g7['trace'])} steps, back-edge fired {g7['regen']}x, validation passed")

goto(at, "8 · Swarm")
[b for b in at.button if "Run the swarm" in b.label][-1].click().run()
show(at, "Lab 8 — the swarm runs, retries, and merges")
s8 = at.session_state["sw"]
assert s8["merged"]["double_counted_removed"] == 3
assert s8["merged"]["coverage_pct"] == 87.5
print(f"      coverage {s8['merged']['coverage_pct']}%, "
      f"{s8['merged']['double_counted_removed']} double-counts removed, "
      f"{s8['wall']:.0f}ms parallel vs {s8['serial']:.0f}ms serial")


# --- Labs 9-14 --------------------------------------------------------------
goto(at, "9 · Grounding")
[b for b in at.button if "Ground it" in b.label][-1].click().run()
show(at, "Lab 9  — a claim is grounded or rejected")

goto(at, "10 · Resilience")
[b for b in at.button if "Inject and heal" in b.label][-1].click().run()
show(at, "Lab 10 — a fault is injected, diagnosed and healed")
[b for b in at.button if "Inject an UNREPAIRABLE" in b.label][-1].click().run()
show(at, "Lab 10 — an unrepairable fault escalates")

goto(at, "11 · Factory")
[b for b in at.button if "Build and run the suite" in b.label][-1].click().run()
show(at, "Lab 11 — the derived suite judges a build")
rep = at.session_state["f11_report"]
assert not at.session_state["f11_pass"], "the naive build must fail the suite"
assert "REFUSED" in at.session_state["f11_gate"], "the gate must refuse a red build"
print(f"      naive build: {sum(r['passed'] for r in rep)}/{len(rep)} green, gate refused")

goto(at, "12 · Governance")
[b for b in at.button if "Approve and publish" in b.label][-1].click().run()
show(at, "Lab 12 — approval is permission-controlled")

goto(at, "13 · Specialists")
[b for b in at.button if "Generate with the owning pack" in b.label][-1].click().run()
show(at, "Lab 13 — the owning pack drafts the options")
[b for b in at.button if "Compare generic vs specialist" in b.label][-1].click().run()
show(at, "Lab 13 — generic vs specialist on the Finance KPI")

goto(at, "14 · Capstone")
[b for b in at.button if "Run request" in b.label][-1].click().run()
show(at, "Lab 14 — request to approved brief, end to end")
cap = at.session_state["cap_result"]
assert cap["version"] == 1 and cap["suite_pass"] == cap["suite_total"]
assert cap["heal"] >= 1, "the injected defect must have been healed in-flight"
print(f"      capstone: {len(cap['stages'])} stages, v{cap['version']}, "
      f"{cap['suite_pass']}/{cap['suite_total']} tests green, "
      f"{cap['heal']} defect(s) healed, {cap['ms']:.0f} ms")

print("\nALL UI PATHS PASSED — 14 tabs, one per lab, each driving the code its "
      "notebook is graded on.")
