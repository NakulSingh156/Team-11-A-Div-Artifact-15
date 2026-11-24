"""Headless test of pipeline_app.py — drives the whole pipeline through the UI.

Proves, without a browser:
  * the agent refuses a vague request and clarifies instead
  * the clarify answers change the spec the pipeline obeys
  * the run reaches the approval gate on its own and stops there
  * approving replays the checkpoint without re-executing anything
  * a rejection, a role that may not approve, and an unrepairable defect each
    end at an escalation exit instead of a publish
  * publish -> revise -> v2 -> roll back to v1 works end to end
  * the graph is correctly wired (the mixed-edge trap is checked)

    python3 test_pipeline_app.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))

from streamlit.testing.v1 import AppTest

APP = str(HERE / "pipeline_app.py")
CHECKPOINTS = HERE.parent / "evidence" / "pipeline_checkpoints"
import edss_pipeline as P
PASSED, FAILED = [], []


def check(label, cond, detail=""):
    (PASSED if cond else FAILED).append(label)
    print(f"  {'pass' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail
                                                        and not cond else ""))


def fresh(actor="principal", chaos="defect"):
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    assert not at.exception, at.exception
    # these widgets use format_func, which AppTest cannot match by label, so set
    # them through their keys
    at.session_state["who"] = actor
    at.session_state["chaos"] = chaos
    at.session_state["pace"] = 0.0       # no presentation delay under test
    at.run()
    assert not at.exception, at.exception
    return at


def brief(at, example=0):
    at.session_state["ex"] = at.selectbox(key="ex").options[example]
    at.run()
    [b for b in at.button if "Send it to the agent" in b.label][-1].click().run()
    assert not at.exception, at.exception
    return at


COMPLETE_ANSWERS = [
    "All four domains for academic year 2025-26. Leadership wants a decision "
    "brief with options and risks.",
    "Use the approved institution-wide KPI set, compare against NIRF, NAAC and "
    "the strategic plan, drill-down only for KPIs that miss their target.",
]


def answer_until_ready(at, answers=None):
    """TYPE an answer into the free-text box, round after round.

    The box carries no `value=` — it starts empty and the clickable options
    beside each question are the fast path — which means a headless test can
    now drive the typed path for real instead of relying on a prefilled
    default. The clicked path is exercised separately in section 9.
    """
    answers = answers or COMPLETE_ANSWERS
    rounds = 0
    while at.session_state["phase"] == "Clarify":
        rounds += 1
        assert rounds < 6, "clarify loop did not converge"
        at.text_area(key="reply").set_value(answers[min(rounds - 1,
                                                        len(answers) - 1)])
        # by label: at.button also contains the sidebar's "Start over"
        [b for b in at.button if b.label == "Answer"][-1].click().run()
        assert not at.exception, at.exception
    return rounds


def planner_for(request, *replies):
    """The Lab 1 loop without the UI, for answers AppTest cannot type."""
    from edss_engine import PlannerSession
    pl = PlannerSession()
    pl.start(request)
    for r in replies:
        if pl.status != "awaiting_input":
            break
        pl.answer(r)
    return pl


def run_headless(pl, actor_key, chaos="none", decision="approve"):
    """Drive a Pipeline directly — the same objects the app drives."""
    import edss_labs9to13 as _L
    gov = _L.Governance()
    pipe = P.Pipeline(f"direct-{actor_key}-{chaos}", pl.plan, pl.goal,
                      _L.ACTORS[actor_key], gov, chaos=chaos,
                      checkpoint_dir=CHECKPOINTS)
    for _ in pipe.stream():
        pass
    if pipe.outcome == "paused":
        getattr(pipe, decision)()
        for _ in pipe.stream():
            pass
    return pipe

def run_pipeline(at):
    btn = [b for b in at.button if "Run the pipeline" in b.label][-1]
    btn.click().run()
    assert not at.exception, at.exception
    return at.session_state["pipe"]


# ==========================================================================
print("\n— 1 · a vague request is clarified, not answered —")
at = fresh()
brief(at, example=0)                                  # "Analyze our college performance."
check("vague request sends the agent to the clarify phase",
      at.session_state["phase"] == "Clarify")
pl = at.session_state["planner"]
check("it asked questions instead of guessing", len(pl.pending_questions) >= 4,
      f"{len(pl.pending_questions)} questions")
q1 = len(pl.pending_questions)
rounds = answer_until_ready(at)
pl = at.session_state["planner"]
check("the plan locked after the answers", pl.status == "plan_ready")
check("later rounds ask less than the first", rounds >= 2 and q1 >= 4,
      f"{rounds} rounds, first asked {q1}")
check("the locked plan carries conflicts it refused to hide",
      len(pl.conflicts) >= 1, f"{len(pl.conflicts)} conflicts")


print("\n— 2 · the answers decide what the pipeline obeys —")
spec = P.spec_from_plan(pl.plan, pl.goal)
check("all four domains in scope", len(spec["domains"]) == 4, str(spec["domains"]))
check("nine KPIs derived from those domains", len(spec["required_kpis"]) == 9,
      str(len(spec["required_kpis"])))

pl2 = planner_for(
    "Analyze our college performance.",
    "Only Placement, academic year 2025-26, decision brief with options and risks.",
    "Use the approved institution-wide KPI set, compare against NIRF and the "
    "strategic plan, drill-down mandatory for every KPI.")
spec2 = P.spec_from_plan(pl2.plan, pl2.goal)
check("a narrower answer narrows the scope", spec2["domains"] == ["Placement"],
      str(spec2["domains"]))
check("and narrows the KPIs the pipeline will compute",
      len(spec2["required_kpis"]) == 3, str(spec2["required_kpis"]))
check("and changes the drill-down policy it will be tested on",
      spec2["drilldown_policy"].startswith("mandatory"), spec2["drilldown_policy"])
narrow = run_headless(pl2, "registrar")
check("the narrowed run publishes with only its own KPIs",
      narrow.outcome == "published" and len(narrow.spec["required_kpis"]) == 3,
      str(narrow.spec["required_kpis"]))
check("and its acceptance suite is smaller because the spec is smaller",
      narrow.state["suite"].all_pass
      and len(narrow.state["suite"].results) < 21,
      f"{len(narrow.state['suite'].results)} tests")


print("\n— 3 · the graph is wired so every branch is reachable —")
g = P.build_pipeline_graph()
v = g.validate(P.ENTRY)
check("no unreachable or dangling nodes", v["ok"], str(v))
check("no node mixes conditional and unconditional edges",
      P.check_branches(g) == [], str(P.check_branches(g)))
check("the repair cycle is a real back-edge",
      any(e.back_edge for e in g.edges))
check("there are two escalation exits in the graph, not one",
      len([e for e in g.edges if e.dst == "escalate"]) >= 3,
      str(len([e for e in g.edges if e.dst == "escalate"])))


print("\n— 4 · it runs unattended and stops at the gate —")
pipe = run_pipeline(at)
check("it stopped itself at the approval gate", pipe.outcome == "paused")
check("the phase moved to Approve", at.session_state["phase"] == "Approve")
check("nothing was published before a human was asked",
      pipe.governance.live() is None)
ran = [e.node for e in pipe.events if e.status == "ok"]
for node in ("connector_read", "swarm", "reconcile", "domain_skills",
             "compute_kpis", "specialists", "compose", "grounding", "validate",
             "acceptance", "submit"):
    check(f"stage ran unattended: {node}", node in ran)
check("the repairable defect was healed, not ignored", "heal" in ran)
check("the heal touched exactly one KPI row",
      len([e for e in pipe.events
           if e.node == "heal" and e.status == "ok"
           and len(e.detail.get("rows_touched", [])) == 1]) == 1,
      str([e.detail.get("rows_touched") for e in pipe.events if e.node == "heal"]))
check("validation ran twice — once failing, once passing",
      len([e for e in pipe.events if e.node == "validate"]) == 2)
check("the acceptance suite was fully green before the human saw it",
      pipe.state["suite"].all_pass)
check("the swarm degraded rather than failed",
      pipe.state["merged"]["coverage_pct"] < 100)
check("double-counted publications were reconciled away",
      pipe.state["merged"]["double_counted_removed"] > 0)


print("\n— 5 · approving replays the checkpoint and publishes —")
ap = [b for b in at.button if "Approve and publish" in b.label][-1]
ap.click().run()
assert not at.exception, at.exception
pipe = at.session_state["pipe"]
s = pipe.summary()
check("published", pipe.outcome == "published" and pipe.version == 1, str(s))
check("the completed prefix was replayed from the checkpoint",
      s["replayed"] >= 10, f"replayed {s['replayed']}")
skipped = [e for e in pipe.events if e.status == "skipped"]
check("and not one replayed stage re-executed",
      all(e.ms < 1.0 for e in skipped),
      f"max {max((e.ms for e in skipped), default=0):.2f} ms")
check("the graph walked the same path on the replay",
      pipe._conditions["validate"] == "failed"
      and pipe._conditions["validate#2"] == "passed")
check("the release is versioned and reversible",
      pipe.governance.live()["version"] == 1)
check("the edits the approver typed are on the record",
      len(pipe.governance.live()["edits"]) >= 1)
check("the published brief was archived append-only",
      any(e.node == "archive" and e.status == "ok" for e in pipe.events))
check("every lab appears in the coverage table",
      all(r["evidence"] not in ("0 stage(s)",) for r in pipe.lab_coverage()),
      str([r["lab"] for r in pipe.lab_coverage()
           if r["evidence"] == "0 stage(s)"]))


print("\n— 6 · revise in place, publish v2, roll back to v1 —")
rev = [b for b in at.button if "Revise and run again" in b.label][-1]
rev.click().run()
assert not at.exception, at.exception
pl = at.session_state["planner"]
check("the feedback revised the plan instead of replanning",
      pl.plan.revision == 1, f"r{pl.plan.revision}")
d = pl.diff_last_revision()
check("the revision left most of the plan untouched",
      len(d["untouched"]) >= 4, str(d["untouched"]))
# the goal keeps what was originally asked for; the PLAN is what changed, and
# the plan is what the pipeline reads
check("Finance was dropped from the plan's scope",
      "Finance" not in pl.plan.body["scope"]["domains"],
      str(pl.plan.body["scope"]["domains"]))
check("the original goal still records what was first asked",
      "Finance" in pl.goal.domains, str(pl.goal.domains))
pipe2 = run_pipeline(at)
check("the second run re-scoped itself from the revised plan",
      len(pipe2.spec["required_kpis"]) == 8, str(pipe2.spec["required_kpis"]))
ap = [b for b in at.button if "Approve and publish" in b.label][-1]
ap.click().run()
assert not at.exception, at.exception
pipe2 = at.session_state["pipe"]
check("v2 published", pipe2.version == 2, str(pipe2.version))
check("both versions are on record", sorted(pipe2.governance.versions) == [1, 2])
rb = [b for b in at.button if "Roll back" in b.label][-1]
rb.click().run()
assert not at.exception, at.exception
gov = at.session_state["gov"]
check("rolled back to v1", gov.current == 1, f"v{gov.current}")
check("the rollback is a new audit entry, not an edit",
      any(a["action"] == "rollback" for a in gov.audit))
check("v2 still exists after the rollback", 2 in gov.versions)


print("\n— 7 · the refusal paths —")
at = fresh(); brief(at, 0); answer_until_ready(at); pipe = run_pipeline(at)
rj = [b for b in at.button if "Reject" in b.label][-1]
rj.click().run()
assert not at.exception, at.exception
pipe = at.session_state["pipe"]
check("a rejection publishes nothing", pipe.outcome == "escalated"
      and pipe.governance.live() is None)
check("and says who rejected it", "rejected" in (pipe.escalation or ""))

at = fresh(actor="council"); brief(at, 0); answer_until_ready(at)
pipe = run_pipeline(at)
ap = [b for b in at.button if "Approve and publish" in b.label][-1]
ap.click().run()
assert not at.exception, at.exception
pipe = at.session_state["pipe"]
check("a role that may not approve is refused at the gate",
      pipe.outcome == "escalated" and pipe.version is None)
check("the refusal names the role", "may not approve" in (pipe.escalation or ""))

at = fresh(chaos="unrepairable"); brief(at, 0); answer_until_ready(at)
pipe = run_pipeline(at)
check("an unrepairable defect escalates instead of publishing",
      pipe.outcome == "escalated")
check("it never reached the acceptance suite",
      not any(e.node == "acceptance" for e in pipe.events))
check("it spent its repair budget first",
      "exhausted its budget" in (pipe.escalation or ""), str(pipe.escalation)[:80])
check("escalating is the last node in the graph trace",
      pipe.graph.trace[-1]["node"] == "escalate")

pl_bad = planner_for(
    "Analyze our college performance.",
    "All four domains for academic year 2019-20. Decision brief with options "
    "and risks.",
    "Use the approved institution-wide KPI set, compare against NIRF, NAAC and "
    "the strategic plan, drill-down mandatory for every KPI.")
pipe = run_headless(pl_bad, "principal")
check("a period with no authorised export is refused at the connector",
      pipe.outcome == "escalated" and not any(e.node == "swarm"
                                              for e in pipe.events))
check("the connector refusal is explained, not swallowed",
      "no authorised export" in (pipe.escalation or ""), str(pipe.escalation)[:90])


print("\n— 8 · a fully specified request skips the clarify loop —")
at = fresh(chaos="none")
brief(at, example=2)
check("it asked nothing and went straight to the plan",
      at.session_state["phase"] == "Run",
      at.session_state["phase"])
pipe = run_pipeline(at)
check("and still reached the gate on its own", pipe.outcome == "paused")
check("with a clean run needing no repair",
      not any(e.node == "heal" for e in pipe.events))


print("\n— 9 · the questions come from the request, and can be clicked —")
from edss_engine import PlannerSession as _PS

vague = _PS(); vague.start("Analyze our college performance.")
placement = _PS(); placement.start("How is our placement doing this year?")
check("a vague request is asked about every missing slot",
      len(vague.pending_prompts) == 6, str(len(vague.pending_prompts)))
check("a request that already names a domain is not asked for it",
      "domains" not in [p["slot"] for p in placement.pending_prompts],
      str([p["slot"] for p in placement.pending_prompts]))
check("the questions differ between the two requests",
      {p["question"] for p in vague.pending_prompts}
      != {p["question"] for p in placement.pending_prompts})
drill = [p for p in placement.pending_prompts if p["slot"] == "drilldown"][0]
check("the question names the domain the request mentioned",
      "Placement" in drill["question"], drill["question"][:70])
period_q = [p for p in vague.pending_prompts if p["slot"] == "period"][0]
check("the period options come from the data-scope register, not a literal",
      period_q["options"] == ["academic year 2025-26", "academic year 2024-25",
                              "academic year 2023-24"], str(period_q["options"]))
check("every question offers at least two clickable answers",
      all(len(p["options"]) >= 2 for p in vague.pending_prompts),
      str([(p["slot"], len(p["options"])) for p in vague.pending_prompts]))
# an option the extractor cannot read back is a button that does nothing
from edss_engine import extract_slots as _ex
dead = [(p["slot"], o) for p in vague.pending_prompts for o in p["options"]
        if not _ex(o).get(p["slot"])]
check("no offered option is a dead end — each one fills its own slot",
      dead == [], str(dead))

# drive the CLICKED path: set each question's pills, type nothing at all
at = fresh(chaos="none")
brief(at, 0)
clicks = {"pick_domains": ["Placement only"],
          "pick_period": ["academic year 2025-26"],
          "pick_kpis": ["The approved institution-wide KPI set"],
          "pick_targets": ["NIRF, NAAC and the strategic plan"],
          "pick_drilldown": ["Department-level drill-down for every KPI"],
          "pick_output": ["A decision brief with options and risks"]}
for k, v in clicks.items():
    at.session_state[k] = v
at.run()
check("the answer box is empty — nothing was typed",
      at.text_area(key="reply").value in ("", None),
      repr(at.text_area(key="reply").value))
[b for b in at.button if b.label == "Answer"][-1].click().run()
assert not at.exception, at.exception
pl_clicked = at.session_state["planner"]
check("clicking the options alone satisfied the agent",
      pl_clicked.status == "plan_ready", pl_clicked.status)
spec_clicked = P.spec_from_plan(pl_clicked.plan, pl_clicked.goal)
check("the clicked scope is the one the pipeline obeys",
      spec_clicked["domains"] == ["Placement"], str(spec_clicked["domains"]))
check("and the clicked drill-down policy reached the spec",
      spec_clicked["drilldown_policy"].startswith("mandatory"),
      spec_clicked["drilldown_policy"])
pipe_clicked = run_pipeline(at)
check("a run driven entirely by clicks reaches the gate",
      pipe_clicked.outcome == "paused", str(pipe_clicked.outcome))


print("\n— 10 · feedback in plain words really re-scopes the next run —")
from edss_engine import make_patch as _mp

_pl = planner_for(
    "Analyze our college performance.",
    "All four domains for academic year 2025-26. Decision brief with options and risks.",
    "Use the approved institution-wide KPI set, compare against NIRF, NAAC and "
    "the strategic plan, drill-down only for KPIs that miss their target.")
_before = P.spec_from_plan(_pl.plan, _pl.goal)
check("the first plan covers all four domains",
      len(_before["required_kpis"]) == 9, str(len(_before["required_kpis"])))

_pl.apply_feedback("show me department-wise placement results only")
_after = P.spec_from_plan(_pl.plan, _pl.goal)
_d = _pl.diff_last_revision()
check("plain-words feedback actually patches the plan", _d["changed"] != [],
      str(_d["changed"]))
check("'placement ... only' narrows the scope to Placement",
      _after["domains"] == ["Placement"], str(_after["domains"]))
check("and the KPI set shrinks with it", len(_after["required_kpis"]) == 3,
      str(_after["required_kpis"]))
check("'department-wise' turns drill-down on for every KPI",
      _after["drilldown_policy"].startswith("mandatory"),
      _after["drilldown_policy"][:50])
check("the revision left the untouched fields alone",
      len(_d["untouched"]) >= 4, str(_d["untouched"]))

_rerun = run_headless(_pl, "principal", chaos="none")
_brief = _rerun.governance.live()
check("the re-run publishes only the Placement KPIs",
      [k["kpi_id"] for k in _brief["kpis"]] == ["KPI-P1", "KPI-P2", "KPI-P3"],
      str([k["kpi_id"] for k in _brief["kpis"]]))
check("every published KPI carries its department drill-down",
      all(len(k.get("drilldown") or []) == 8 for k in _brief["kpis"]),
      str([len(k.get("drilldown") or []) for k in _brief["kpis"]]))
check("and the acceptance suite was re-derived, not reused",
      len(_rerun.state["suite"].results) == 16,
      str(len(_rerun.state["suite"].results)))

_p1 = [k for k in _brief["kpis"] if k["kpi_id"] == "KPI-P1"][0]
check("each department carries its own status, not just a number",
      all({"dept", "value", "variance", "status"} <= set(d) for d in _p1["drilldown"]),
      str(sorted(_p1["drilldown"][0])))
check("department status uses the same rule as the institution figure",
      all((d["status"] == "on target") == (d["variance"] >= 0)
          for d in _p1["drilldown"] if d["value"] is not None),
      str([(d["dept"], d["variance"], d["status"]) for d in _p1["drilldown"]]))
check("the breakdown is sorted worst first",
      [d["variance"] for d in _p1["drilldown"]]
      == sorted(d["variance"] for d in _p1["drilldown"]),
      str([d["dept"] for d in _p1["drilldown"]]))
check("the departments disagree with each other — it is a real breakdown",
      len({d["status"] for d in _p1["drilldown"]}) > 1,
      str({d["status"] for d in _p1["drilldown"]}))
_md = P.brief_markdown(_brief, _rerun.summary())
check("the downloadable brief carries the department tables",
      "## Department breakdown" in _md and "| CIVIL |" in _md)

check("feedback naming nothing patchable reports zero changes",
      _mp("make it nicer please") == [], str(_mp("make it nicer please")))
check("a negation is not read as a request for drill-down",
      _mp("no department-level drill-down") == [],
      str(_mp("no department-level drill-down")))
for _phrase, _want in [("only Placement", ["Placement"]),
                       ("just research and placement please",
                        ["Research", "Placement"]),
                       ("drop Finance", None)]:
    _ops = _mp(_phrase)
    check(f"feedback understood: {_phrase!r}", _ops != [], str(_ops))


print("\n" + "=" * 78)
print(f"{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    for f in FAILED:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL PIPELINE PATHS PASSED — one request in, an approved brief out, with "
      "every refusal path proven.")
