"""edss_pipeline — Worklet 15 as ONE autonomous end-to-end pipeline.

The lab-by-lab dashboard shows each lab in isolation. This module is the other
view: a single agentic run that takes a free-text executive request and returns
an approved, published, reversible decision brief.

The human is asked for exactly three things:

    1. the request                      (intake)
    2. answers to whatever the agent     (Lab 1 clarify loop — it refuses to guess)
       says it is missing
    3. an approval decision              (Lab 12 gate — role-checked)

Everything between those three points is automatic.

How the labs compose here:

    Lab 1   produces the locked plan, and the plan DERIVES the spec that the rest
            of the pipeline obeys — so the answers you type genuinely change what
            runs, not just what is printed.
    Lab 6   is the executor. Every stage goes through Runtime.perform(), so each
            one is budget-checked, audited and checkpointed, and the approval
            pause is the same mechanism as crash recovery.
    Lab 7   is the control flow. The stage order, the heal -> re-validate cycle
            and the approve/reject branch are edges in a real graph, validated
            for reachability before anything runs.
    Labs 2,3,4,5,8,9,10,11,12,13 are the stages themselves.
    Lab 14  is this file: nothing here invents capability, it only wires.
"""

import copy
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from edss_core import DOMAINS, KPI_DEFINITIONS, REPORTING_PERIOD, ToolRouter
import edss_stack as L345
import edss_labs678 as L678
import edss_labs9to13 as L913
from edss_capstone import capstone_build


# ==========================================================================
# the plan -> spec bridge  (Lab 1 output becomes the contract for Labs 2-13)
# ==========================================================================

def spec_from_plan(plan, goal) -> Dict[str, Any]:
    """Turn the locked Lab 1 plan into the Lab 11 spec the pipeline is judged on.

    This is the join that makes the run agentic rather than scripted: the domains
    and the drill-down policy the user agreed to in the clarify loop decide which
    KPIs are computed and which acceptance tests are derived.
    """
    # Read the PLAN, not the goal. A feedback round revises the plan in place —
    # plan.body["scope"]["domains"] and plan.body["drilldown_policy"] change,
    # while the original goal still holds what was first asked for. The plan is
    # the authority, so a revision really does re-scope the next run.
    body = plan.body
    scope = body.get("scope", {})
    domains = list(scope.get("domains") or goal.domains or DOMAINS)
    period = scope.get("period") or goal.period
    spec = copy.deepcopy(L913.SPEC)
    spec["spec_id"] = f"PLAN-{period.replace(' ', '-')}-r{plan.revision}"
    spec["period"] = period
    spec["domains"] = domains
    spec["required_kpis"] = [k for k, d in KPI_DEFINITIONS.items()
                             if d["domain"] in domains]
    spec["drilldown_policy"] = (body.get("drilldown_policy") or goal.drilldown
                                or "mandatory for every KPI")
    if isinstance(body.get("brief_structure"), list):
        spec["brief_sections"] = list(body["brief_structure"])
    spec["target_sets"] = list(goal.targets)
    return spec


# ==========================================================================
# what a stage reports back to the UI
# ==========================================================================

@dataclass
class Event:
    """One pipeline stage, as the UI shows it."""
    seq: int
    node: str
    lab: str
    title: str
    status: str                       # ok | skipped | paused | failed | escalated
    headline: str                     # the one line a reader needs
    detail: Dict[str, Any] = field(default_factory=dict)
    ms: float = 0.0
    budget: str = ""
    visit: int = 1                    # 2+ when a back-edge brought us here again


STAGE_META = {
    "plan_locked":    ("Lab 1",  "Locked plan accepted"),
    "recall":         ("Lab 4",  "Recall prior context"),
    "connector_read": ("Lab 5",  "Read data through the governed connector"),
    "swarm":          ("Lab 8",  "Department agents, in parallel"),
    "reconcile":      ("Lab 8",  "Reconcile conflicting claims"),
    "domain_skills":  ("Lab 3",  "Reusable skill reviews each domain"),
    "compute_kpis":   ("Lab 2",  "Typed tools compute every KPI"),
    "specialists":    ("Lab 13", "Domain packs draft the options"),
    "compose":        ("Lab 14", "Compose the draft brief"),
    "grounding":      ("Lab 9",  "Ground every claim in a source"),
    "validate":       ("Lab 10", "Validate against the constraints"),
    "heal":           ("Lab 10", "Diagnose and repair, minimally"),
    "acceptance":     ("Lab 11", "Acceptance suite derived from the spec"),
    "submit":         ("Lab 11", "Gate: route to a human"),
    "approval":       ("Lab 12", "Human approval (role-checked)"),
    "publish":        ("Lab 12", "Publish, version, audit"),
    "archive":        ("Lab 4",  "Archive the release, append-only"),
    "escalate":       ("Lab 10", "Escalate to a human"),
}


# ==========================================================================
# Lab 7 — the pipeline graph
# ==========================================================================

def build_pipeline_graph() -> L678.Graph:
    """The whole run as an explicit graph: one linear spine, one repair cycle,
    one approve/reject branch, two escalation exits."""
    g = L678.Graph("worklet15-pipeline", max_steps=60)

    for name, (lab, title) in STAGE_META.items():
        kind = {"approval": "gate", "submit": "gate", "publish": "publish",
                "escalate": "terminal"}.get(name, "work")
        g.add_node(L678.Node(name, kind, f"{lab} · {title}", fn=lambda s: s))

    # the straight-through spine. connector_read and validate are left out of it
    # because they BRANCH, and Graph.successors() treats an unconditional edge as
    # matching every condition — so a node must not mix the two kinds.
    spine = ["plan_locked", "recall", "swarm", "reconcile",
             "domain_skills", "compute_kpis", "specialists", "compose",
             "grounding", "validate"]
    for src, dst in zip(spine, spine[1:]):
        if src == "recall":
            continue                                  # recall -> connector_read below
        g.add_edge(src, dst)
    g.add_edge("recall", "connector_read")

    # the connector is allowed to refuse — that exit is an edge in the graph, not
    # a try/except buried somewhere downstream
    g.add_edge("connector_read", "swarm", condition="ok")
    g.add_edge("connector_read", "escalate", condition="no_data")

    g.add_edge("validate", "acceptance", condition="passed")
    g.add_edge("validate", "heal", condition="failed")
    g.add_edge("heal", "validate", condition="repaired", back_edge=True)
    g.add_edge("heal", "escalate", condition="unrepairable")

    g.add_edge("acceptance", "submit", condition="green")
    g.add_edge("acceptance", "escalate", condition="red")

    g.add_edge("submit", "approval")
    g.add_edge("approval", "publish", condition="approved")
    g.add_edge("approval", "escalate", condition="rejected")

    g.add_edge("publish", "archive")

    g.set_router("connector_read", lambda s: s.get("_route_connector_read", "ok"))
    g.set_router("validate", lambda s: s.get("_route_validate", "passed"))
    g.set_router("heal", lambda s: s.get("_route_heal", "repaired"))
    g.set_router("acceptance", lambda s: s.get("_route_acceptance", "green"))
    g.set_router("approval", lambda s: s.get("_route_approval", "approved"))
    return g


def check_branches(g: L678.Graph) -> List[str]:
    """A wiring check Lab 7's own validate() does not make.

    Graph.successors() matches an unconditional edge against EVERY condition and
    returns the first hit, so a node carrying both an unconditional edge and a
    conditional one would silently always take the unconditional one and the
    branch would be dead. This run found that bug; this keeps it found.
    """
    problems = []
    for name in g.nodes:
        out = [e for e in g.edges if e.src == name]
        kinds = {e.condition is None for e in out}
        if len(kinds) > 1:
            problems.append(
                f"'{name}' mixes {len([e for e in out if e.condition is None])} "
                f"unconditional edge(s) with "
                f"{len([e for e in out if e.condition])} conditional one(s); the "
                f"conditional branches are unreachable")
        labels = [e.condition for e in out if e.condition]
        if len(labels) != len(set(labels)):
            problems.append(f"'{name}' has duplicate condition labels: {labels}")
        if labels and name not in g.routers:
            problems.append(f"'{name}' branches but has no router")
    return problems


ENTRY = "plan_locked"


# ==========================================================================
# the pipeline
# ==========================================================================

class Paused(Exception):
    """The run stopped at a gate and is waiting for a named human."""


class Pipeline:
    """One request, start to finish.

    Drives the Lab 7 graph one node at a time so a UI can sit inside the loop,
    exactly as PlannerSession does for the Lab 1 loop. Each node is executed by
    the Lab 6 Runtime, which is what makes the run bounded, audited, resumable
    and pausable.
    """

    def __init__(self, run_id: str, plan, goal, approver: L913.Actor,
                 governance: L913.Governance,
                 checkpoint_dir: Path = Path("pipeline_checkpoints"),
                 budget: Optional[L678.Budget] = None,
                 chaos: str = "defect",
                 edits: Optional[List[str]] = None):
        self.run_id = run_id
        self.plan, self.goal = plan, goal
        self.spec = spec_from_plan(plan, goal)
        self.approver = approver
        self.governance = governance
        self.edits = list(edits or [])
        # what the run has to cope with:
        #   none          — clean data, validation passes first time
        #   defect        — a KPI loses its source; Lab 10 repairs it
        #   unrepairable  — an unapproved KPI row; Lab 10 spends its budget and
        #                   escalates instead of publishing
        if chaos not in ("none", "defect", "unrepairable"):
            raise ValueError(f"chaos must be none|defect|unrepairable, got {chaos!r}")
        self.chaos = chaos
        self.inject_defect = chaos == "defect"

        self.runtime = L678.Runtime(
            run_id,
            budget or L678.Budget(max_actions=40, max_connector_calls=80,
                                  max_seconds=120.0),
            L678.CheckpointStore(Path(checkpoint_dir)))
        self.graph = build_pipeline_graph()
        check = self.graph.validate(ENTRY)
        if not check["ok"]:
            raise L678.GraphError(f"pipeline graph will not run: {check}")
        branch_problems = check_branches(self.graph)
        if branch_problems:
            raise L678.GraphError(f"pipeline graph is mis-wired: {branch_problems}")
        self.graph_check = {**check, "branch_check": "clean"}

        self.state: Dict[str, Any] = {}
        self.events: List[Event] = []
        self.visits: Dict[str, int] = {}
        # the branch taken on each action's first execution. A replay reads these
        # back instead of re-running the routers, so resuming walks the exact
        # same path rather than a plausible one.
        self._conditions: Dict[str, Optional[str]] = {}
        self.decision: Optional[str] = None     # set by the UI at the approval gate
        self.artifact: Optional[Dict[str, Any]] = None
        self.version: Optional[int] = None
        self.outcome: Optional[str] = None      # published | escalated | paused
        self.escalation: Optional[str] = None
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.wall_ms = 0.0
        self._t0 = time.perf_counter()

    # ---- the stage bodies ------------------------------------------------
    # Each returns (headline, detail). None of them creates capability; they
    # call the lab layers.

    def _s_plan_locked(self, rt):
        p = self.plan.body
        return (f"plan r{self.plan.revision} locked · {len(p['analysis_steps'])} steps · "
                f"{len(self.spec['required_kpis'])} KPIs in scope "
                f"({', '.join(self.spec['domains'])})",
                {"objective": p["objective"],
                 "spec_id": self.spec["spec_id"],
                 "domains": self.spec["domains"],
                 "required_kpis": self.spec["required_kpis"],
                 "drilldown_policy": self.spec["drilldown_policy"],
                 "targets": self.spec.get("target_sets", []),
                 "assumptions_carried": p["assumptions"]})

    def _s_recall(self, rt):
        snaps = L345.retrieve_by_tags(L345.archive, ["kpi-snapshot"], "any")
        hits = L345.index.query("recruiter outreach to lift placement", k=2,
                                record_type="decision_brief")
        rt.state.retrieved = snaps
        rt.state.note("prior_decisions", [h["record_id"] for h in hits])
        prior = hits[0] if hits else None
        return (f"{len(snaps)} baseline snapshot(s); nearest prior decision "
                f"{prior['record_id']} (similarity {prior['similarity']:.3f})"
                if prior else f"{len(snaps)} baseline snapshot(s); no prior decision",
                {"archive_records": len(L345.archive),
                 "baselines": [s["record_id"] for s in snaps],
                 "nearest_prior": [{"record_id": h["record_id"],
                                    "similarity": round(h["similarity"], 3)}
                                   for h in hits],
                 "why": "so the brief does not re-propose an action that was already "
                        "tried, and so this year's figures have something to move from"})

    def _s_connector_read(self, rt):
        try:
            res = rt.client.read("department_reports", period=self.spec["period"])
        except L345.MCPError as exc:
            self.state["_route_connector_read"] = "no_data"
            self.escalation = (f"the connector has no authorised export for "
                               f"{self.spec['period']!r} ({exc}). The agent will not "
                               f"substitute another period's data.")
            return (f"REFUSED — no export on disk for {self.spec['period']!r}",
                    {"error": str(exc),
                     "available": REPORTING_PERIOD,
                     "why": "the connector refuses rather than silently reading a "
                            "different period"})
        self.state["_route_connector_read"] = "ok"
        self.state["rows"] = res["rows"]
        return (f"{res['row_count']} department rows via {res['source_system']} "
                f"(token: coordinator scope)",
                {"resource": "department_reports", "backend": res.get("rows_source", "—"),
                 "system_of_record": res["source_system"],
                 "row_count": res["row_count"],
                 "connector_calls_so_far": rt.connector_calls})

    def _s_swarm(self, rt):
        L678.reset_swarm_state()
        sw = L678.Swarm(L678.department_agent, max_retries=2, backoff_s=0.02)
        calls_before = len(L345.server.log)
        t0 = time.perf_counter()
        results = sw.run(L678.UNITS)
        wall = (time.perf_counter() - t0) * 1000
        calls = len(L345.server.log) - calls_before
        serial = sum(r.ms for r in results.values())
        ok = [u for u, r in results.items() if r.ok]
        bad = [u for u, r in results.items() if not r.ok]
        rows = sum(r.data.get("rows_fetched", 0) for r in results.values() if r.ok)
        self.state["swarm"] = results
        return (f"{len(ok)}/{len(results)} department agents succeeded in "
                f"{wall:.0f} ms (serial would be {serial:.0f} ms, "
                f"{serial / wall:.1f}x) · {rows} fact rows via {calls} connector "
                f"calls · failed: {bad or 'none'}",
                {"per_agent": [{"unit": u, "ok": r.ok, "attempts": r.attempts,
                                "ms": round(r.ms, 1),
                                "rows_fetched": r.data.get("rows_fetched", 0)
                                if r.ok else 0,
                                "domains": r.data.get("domains_fetched", [])
                                if r.ok else [],
                                "error": r.error or ""}
                               for u, r in results.items()],
                 "wall_ms": round(wall, 1), "serial_ms": round(serial, 1),
                 "connector_calls": calls,
                 "fact_rows_fetched": rows,
                 "token_held_by_agents": "tok-department-agent "
                                         "(scope: read:department-detail only)",
                 "why": "each agent pulls its OWN department's rows through the "
                        "connector with a single-scope token, so one department "
                        "system being down degrades coverage rather than failing "
                        "the run — and no agent can read anything but its own data"})

    def _s_reconcile(self, rt):
        merged = L678.merge(self.state["swarm"])
        self.state["merged"] = merged
        return (f"coverage {merged['coverage_pct']}% · publications "
                f"{merged['publications_naive_sum']} claimed -> "
                f"{merged['publications_reconciled']} after removing "
                f"{merged['double_counted_removed']} double-counted",
                {**{k: v for k, v in merged.items() if k != "rows"},
                 "why": "parallel agents each counted joint publications; a naive sum "
                        "would overstate research output"})

    def _s_domain_skills(self, rt):
        router = ToolRouter(agent=f"pipeline:{self.run_id}")
        reviews = {}
        for d in self.spec["domains"]:
            reviews[d] = rt.skills["review_domain"].run(router, domain=d,
                                                        period=REPORTING_PERIOD)
        self.state["reviews"] = reviews
        off = sum(len(r["off_target"]) for r in reviews.values())
        return (f"one skill, {len(reviews)} domain(s), {off} KPIs off target, "
                f"{len(router.trace)} typed tool calls through one router",
                {**{d: {"headline": r["headline"], "off_target": r["off_target"],
                        "provisional": r["provisional"]}
                    for d, r in reviews.items()},
                 "why": "the same review_domain skill served every domain; nothing "
                        "was re-implemented per domain"})

    def _s_compute_kpis(self, rt):
        rows = self.state["rows"]
        computed = []
        for kpi_id in self.spec["required_kpis"]:
            c = L913.compute_kpi(kpi_id, rows)
            t = L913.compare_to_target(kpi_id, c["value"])
            computed.append({"kpi_id": kpi_id, "name": c["name"],
                             "value": c["value"], "unit": c["unit"],
                             "target": t["target"], "status": t["status"],
                             "figure_status": c["figure_status"],
                             "source_system": c["source_system"],
                             "rounding_warning": t["rounding_warning"]})
        self.state["computed"] = computed
        off = [k["kpi_id"] for k in computed if k["status"] != "on target"]
        prov = [k["kpi_id"] for k in computed if k["figure_status"] != "final"]
        flags = [k["kpi_id"] for k in computed if k["rounding_warning"]]
        return (f"{len(computed)} KPIs computed in Python · {len(off)} off target · "
                f"{len(prov)} provisional · {len(flags)} rounding flag(s)",
                {"kpis": computed, "off_target": off, "provisional": prov,
                 "rounding_flagged": flags,
                 "why": "the model chose which tool to call; every number came from "
                        "code, so each one is reproducible"})

    def _s_specialists(self, rt):
        items = [i for i in L913.work_items()
                 if i.kpi_id in self.spec["required_kpis"]]
        drafted, rejected = [], []
        for item in items:
            sp = L913.REGISTRY[item.domain]
            out = sp.check(sp.generate(item))
            if out.valid:
                drafted.append({"kpi_id": item.kpi_id, "specialist": sp.name,
                                "headline": out.headline,
                                "options": [o["title"] for o in out.options]})
            else:
                rejected.append({"kpi_id": item.kpi_id, "specialist": sp.name,
                                 "violations": out.violations})
        self.state["specialist_items"] = items
        return (f"{len(drafted)} off-target KPIs drafted by "
                f"{len({d['specialist'] for d in drafted})} domain pack(s); "
                f"{len(rejected)} rejected by their own scheme",
                {"drafted": drafted, "rejected_by_own_check": rejected,
                 "why": "each pack validates its own output against its domain's "
                        "scheme and units, so a generic draft cannot pass"})

    def _s_compose(self, rt):
        artifact = capstone_build(self.spec, self.state["rows"], L913.REGISTRY,
                                  inject_defect=self.inject_defect)
        if self.chaos == "unrepairable":
            # a row for a KPI that is not in the approved register: it fails the
            # source constraint, and no repair exists because there is no approved
            # definition to repair it from
            artifact["kpis"].append(
                {"kpi_id": "KPI-X9", "name": "Unapproved metric", "value": 42.0,
                 "value_shown": "42.00", "unit": "%", "target": 50.0,
                 "status": "below target", "source_system": "",
                 "figure_status": "final", "caveat": "", "rounding_warning": None,
                 "drilldown": [], "departments": []})
        self.artifact = artifact
        rt.state.draft = artifact
        return (f"draft assembled: {len(artifact['kpis'])} KPIs, "
                f"{len(artifact['options'])} options, "
                f"{len(artifact['sections'])} sections, status "
                f"{artifact['status']}"
                + {"none": "",
                   "defect": " · a data defect was injected on purpose",
                   "unrepairable": " · an UNREPAIRABLE row was injected on purpose"
                   }[self.chaos],
                {"spec_id": artifact["spec_id"],
                 "sections": list(artifact["sections"]),
                 "assumptions": artifact["assumptions"],
                 "chaos": self.chaos,
                 "why": "Lab 11's suite looks for 'drilldown' and Lab 12's redactor "
                        "looks for 'departments'; integration reconciles the two "
                        "names here rather than editing either lab"})

    def _s_grounding(self, rt):
        cands = [L913.Candidate(f"K-{k['kpi_id']}", "finding", k["name"],
                                {"kpi_id": k["kpi_id"]})
                 for k in self.artifact["kpis"]]
        for c in cands:
            c.evidence = L913.research(c)
            c.accepted = c.evidence.in_scope
        kept = [c for c in cands if c.accepted]
        dropped = [c.cid for c in cands if not c.accepted]
        self.state["grounded"] = kept
        return (f"{len(kept)}/{len(cands)} claims carry an in-scope source, locator "
                f"and value · {len(dropped)} dropped",
                {"evidence": [{"claim": c.text,
                               "source": c.evidence.source,
                               "locator": c.evidence.locator,
                               "value": str(c.evidence.value)} for c in kept],
                 "dropped": dropped,
                 "in_scope_sources": sorted(L913.IN_SCOPE_SOURCES),
                 "why": "a claim with no authorised source is removed, not softened"})

    def _s_validate(self, rt):
        report = L913.validate(self.artifact)
        self.state["_route_validate"] = "passed" if report.passed else "failed"
        self.state["last_report"] = report
        if report.passed:
            return (f"all {len(L913.CONSTRAINTS)} constraints satisfied", {})
        return (f"FAILED: {report.summary()}",
                {"failing": report.failing,
                 "diagnosis": L913.diagnose(report),
                 "why": "validation names the constraint AND the row, so the repair "
                        "can be targeted instead of regenerating the brief"})

    def _s_heal(self, rt):
        before = copy.deepcopy(self.artifact)
        try:
            healed = L913.heal(self.artifact, budget=L913.RETRY_BUDGET)
        except L913.Escalation as exc:
            self.state["_route_heal"] = "unrepairable"
            self.escalation = (f"self-repair exhausted its budget of "
                               f"{L913.RETRY_BUDGET} attempts: {exc}")
            return (f"UNREPAIRABLE after {L913.RETRY_BUDGET} attempts — escalating",
                    {"detail": str(exc),
                     "why": "knowing when to stop and hand over is a feature"})
        self.state["_route_heal"] = "repaired"      # follow the back-edge
        touched = [k["kpi_id"] for k, b in zip(self.artifact["kpis"], before["kpis"])
                   if k != b]
        return (f"repaired in {healed['attempts']} attempt(s) · "
                f"{len(touched)} of {len(self.artifact['kpis'])} KPI rows touched "
                f"({', '.join(touched) or 'none'})",
                {"log": healed["log"], "rows_touched": touched,
                 "why": "a surgical repair, not a regeneration — everything that was "
                        "already correct is left byte-identical"})

    def _s_acceptance(self, rt):
        report = L913.acceptance_suite(self.artifact, self.spec)
        self.state["suite"] = report
        green = sum(r["passed"] for r in report.results)
        self.state["_route_acceptance"] = "green" if report.all_pass else "red"
        if not report.all_pass:
            self.escalation = (f"{len(report.failures)} of {len(report.results)} "
                               f"derived acceptance tests are red; the brief will not "
                               f"be sent to a human.")
        return (f"{green}/{len(report.results)} tests derived from the spec are green",
                {"results": report.results,
                 "failures": report.failures,
                 "derived_from": sorted({r["derived_from"] for r in report.results}),
                 "why": "the tests are generated from the spec you approved in the "
                        "clarify loop, so changing the spec changes the suite"})

    def _s_submit(self, rt):
        sub = L913.submit_for_review(self.artifact, self.state["suite"],
                                     str(self.approver))
        return (f"submitted to {sub['submitted_to']} with "
                f"{sub['tests_passed']} green tests",
                {**sub, "why": "submit_for_review is the only path to a human, and it "
                               "refuses anything that is not fully green"})

    def _s_approval(self, rt):
        """Reached only once a named human has been recorded on the Lab 6 gate."""
        if self.decision == "reject":
            self.state["_route_approval"] = "rejected"
            self.escalation = (f"{self.approver} rejected the draft; nothing was "
                               f"published.")
            return (f"REJECTED by {self.approver}", {"decision": "reject"})
        if not self.approver.role.can_approve:
            self.state["_route_approval"] = "rejected"
            self.escalation = (f"{self.approver} holds a role that may not approve an "
                               f"executive brief.")
            return (f"DENIED — {self.approver.role.name} may not approve",
                    {"role": self.approver.role.name, "can_approve": False})
        self.state["_route_approval"] = "approved"
        view = L913.view_for(self.approver, self.artifact)
        return (f"approved by {self.approver} · "
                f"{len(view['redactions'])} redaction(s) in this reader's view",
                {"granted_by": rt.approvals.get("approval"),
                 "redactions": view["redactions"],
                 "edits_requested": self.edits,
                 "why": "the gate is role-checked, and what the reader sees is "
                        "redacted for their access level"})

    def _s_publish(self, rt):
        self.artifact["status"] = "draft"
        self.version = self.governance.approve_and_publish(
            self.approver, self.artifact, edits=self.edits)
        return (f"published v{self.version} by {self.approver} · "
                f"{len(self.governance.audit)} governance audit entries · "
                f"rollback available",
                {"version": self.version,
                 "versions_on_record": sorted(self.governance.versions),
                 "audit": self.governance.audit[-4:],
                 "why": "every release is versioned and reversible, and the audit log "
                        "is append-only — a rollback is a new entry, never an edit"})

    def _s_archive(self, rt):
        # The archive refuses to overwrite, by design. After a "Start over" the
        # version counter restarts at v1, so the same id can come round again —
        # a seconds-resolution suffix was not enough, because two runs really
        # can land inside the same second. Keep stepping until the id is free.
        base = f"BRIEF-{self.spec['period'].replace(' ', '-')}-v{self.version}"
        rid, n = base, 1
        while rid in L345.archive:
            rid = f"{base}-{datetime.now(timezone.utc).strftime('%H%M%S')}-{n}"
            n += 1
        live = self.governance.live()
        L345.archive.put(rid, {
            "type": "decision_brief", "tags": ["decision_brief", "published"],
            "period": self.spec["period"], "version": self.version,
            "approved_by": live["approved_by"],
            "summary": f"{len(live['kpis'])} KPIs, "
                       f"{sum(1 for k in live['kpis'] if k['status'] != 'on target')} "
                       f"off target",
            "kpis": [{"kpi_id": k["kpi_id"], "value": k["value"],
                      "status": k["status"]} for k in live["kpis"]]})
        self.outcome = "published"
        return (f"archived as {rid} · the archive now holds "
                f"{len(L345.archive)} records and cannot be edited",
                {"record_id": rid, "archive_size": len(L345.archive),
                 "why": "this release becomes next run's prior context, which is what "
                        "the recall stage reads"})

    def _s_escalate(self, rt):
        self.outcome = "escalated"
        return (self.escalation or "escalated to a human",
                {"reason": self.escalation,
                 "audit_entries": len(rt.audit),
                 "why": "the run stops with a diagnosis instead of shipping something "
                        "it cannot stand behind"})

    # ---- the traversal ---------------------------------------------------

    def _body(self, node: str):
        return getattr(self, f"_s_{node}")

    def stream(self, on_start=None) -> Iterator[Event]:
        """Walk the Lab 7 graph, executing each node through the Lab 6 runtime.

        This is Graph.run()'s loop in generator form so a UI can render each
        stage as it lands and so the approval gate can stop the world. Yields an
        Event per stage; stops when the graph reaches a terminal node or a gate
        needs a human.

        `on_start(node, lab, title, visit)` is called just BEFORE a stage is
        executed, so a UI can say what is about to happen while it happens. It
        changes nothing about the run — a caller that passes nothing gets the
        same sequence of events.
        """
        current, steps = ENTRY, 0
        # Reset per call: a replay must regenerate the SAME action names as the
        # first pass, or Runtime.perform() would treat each one as new work.
        self.visits = {}
        # On a resume, replay the completed prefix: Runtime.perform() returns the
        # cached result and re-runs nothing, so the graph lands exactly where it
        # stopped.
        while current is not None:
            steps += 1
            if steps > self.graph.max_steps:
                raise L678.GraphError(
                    f"cycle budget of {self.graph.max_steps} steps exhausted at "
                    f"'{current}' — a back-edge is not converging")

            self.visits[current] = self.visits.get(current, 0) + 1
            visit = self.visits[current]
            lab, title = STAGE_META[current]
            action_name = current if visit == 1 else f"{current}#{visit}"
            already = action_name in self.runtime.completed

            action = L678.Action(
                name=action_name, kind=self.graph.nodes[current].kind,
                description=f"{lab} · {title}",
                fn=lambda rt, _n=current: self._body(_n)(rt),
                requires_approval=(current == "approval"),
                depends_on=[])

            if on_start is not None:
                on_start(current, lab, title, visit)

            t0 = time.perf_counter()
            try:
                headline, detail = self.runtime.perform(action)
            except L678.ApprovalRequired:
                self.outcome = "paused"
                self.visits[current] -= 1            # this visit did not happen
                ev = Event(len(self.events) + 1, current, lab, title, "paused",
                           f"waiting for a named human — {self.approver} must "
                           f"approve or reject",
                           {"gate": action_name, "actor": str(self.approver),
                            "can_approve": self.approver.role.can_approve,
                            "why": "the runtime blocks the action rather than "
                                   "trusting the caller to stop"},
                           0.0, self._budget(), visit)
                self.events.append(ev)
                yield ev
                return
            except L678.BudgetExceeded as exc:
                self.outcome = "escalated"
                self.escalation = f"budget exceeded: {exc}"
                ev = Event(len(self.events) + 1, current, lab, title, "failed",
                           f"BUDGET EXCEEDED — {exc}", {"why": "a bounded run stops "
                           "itself rather than spending without limit"},
                           0.0, self._budget(), visit)
                self.events.append(ev)
                yield ev
                return

            ms = (time.perf_counter() - t0) * 1000
            status = "skipped" if already else (
                "escalated" if current == "escalate" else "ok")
            ev = Event(len(self.events) + 1, current, lab, title, status,
                       headline, detail, ms, self._budget(), visit)
            self.events.append(ev)
            yield ev

            if already and action_name in self._conditions:
                condition = self._conditions[action_name]      # replay the real path
            else:
                condition = (self.graph.routers[current](self.state)
                             if current in self.graph.routers else None)
                self._conditions[action_name] = condition
            self.graph._log(current, self.graph.nodes[current].kind, headline[:80],
                            ms, condition)
            nxt = self.graph.successors(current, condition)
            current = nxt[0] if nxt else None

        self.wall_ms = (time.perf_counter() - self._t0) * 1000
        if self.outcome is None:
            self.outcome = "finished"

    # ---- gate control ----------------------------------------------------

    def approve(self, by: Optional[str] = None) -> None:
        """Record the named human on the Lab 6 gate, then stream() will proceed."""
        self.decision = "approve"
        gate = "approval" if "approval" not in self.runtime.approvals else "approval"
        self.runtime.approve(gate, by=by or str(self.approver))

    def reject(self, by: Optional[str] = None) -> None:
        self.decision = "reject"
        self.runtime.approve("approval", by=by or str(self.approver))

    def rollback(self, actor: L913.Actor, to_version: int) -> int:
        return self.governance.rollback(actor, to_version)

    # ---- reporting -------------------------------------------------------

    def _budget(self) -> str:
        rt = self.runtime
        return rt.budget.report(len(rt.completed), rt.connector_calls, rt.elapsed)

    def lab_coverage(self) -> List[Dict[str, Any]]:
        """Which labs this run actually exercised — read off the events, not a list."""
        fired = {}
        for ev in self.events:
            if ev.status in ("ok", "escalated"):
                fired.setdefault(ev.lab, []).append(ev.node)
        rows = []
        for lab, note in [
            ("Lab 1", "clarify loop → locked plan → spec"),
            ("Lab 2", "typed tools computed every figure"),
            ("Lab 3", "one reusable skill across the domains in scope"),
            ("Lab 4", "recall before, archive after"),
            ("Lab 5", "the only door to data, scope-checked"),
            ("Lab 6", "executed, budgeted, audited, checkpointed every stage"),
            ("Lab 7", "the stage order, the repair cycle and the branch"),
            ("Lab 8", "parallel department agents + reconciliation"),
            ("Lab 9", "evidence for every claim"),
            ("Lab 10", "validate → diagnose → heal → escalate"),
            ("Lab 11", "spec-derived acceptance suite gated the human"),
            ("Lab 12", "role-checked approval, versioning, rollback, audit"),
            ("Lab 13", "domain packs drafted the options"),
            ("Lab 14", "this pipeline — wiring only, no new capability"),
        ]:
            if lab == "Lab 6":
                rows.append({"lab": lab, "where": "runtime (all stages)",
                             "note": note,
                             "evidence": f"{len(self.runtime.completed)} actions, "
                                         f"{len(self.runtime.audit)} audit entries"})
            elif lab == "Lab 7":
                rows.append({"lab": lab, "where": "graph (all stages)", "note": note,
                             "evidence": f"{len(self.graph.nodes)} nodes, "
                                         f"{len(self.graph.edges)} edges, "
                                         f"{len(self.graph.trace)} steps walked"})
            else:
                rows.append({"lab": lab, "where": ", ".join(fired.get(lab, [])) or "—",
                             "note": note,
                             "evidence": f"{len(fired.get(lab, []))} stage(s)"})
        return rows

    def summary(self) -> Dict[str, Any]:
        suite = self.state.get("suite")
        heal_events = [e for e in self.events
                       if e.node == "heal" and e.status == "ok"]
        return {"run_id": self.run_id, "outcome": self.outcome,
                "version": self.version,
                "stages": len([e for e in self.events if e.status != "skipped"]),
                "replayed": len([e for e in self.events if e.status == "skipped"]),
                "graph_steps": len(self.graph.trace),
                # time the AGENT spent, summed from the stages. Not elapsed
                # wall time, which would include the display pacing and however
                # long the human took at the approval gate.
                "wall_ms": round(sum(e.ms for e in self.events), 1),
                "elapsed_ms": round(self.wall_ms or
                                    (time.perf_counter() - self._t0) * 1000, 1),
                "tests_green": sum(r["passed"] for r in suite.results) if suite else 0,
                "tests_total": len(suite.results) if suite else 0,
                "heal_rounds": len(heal_events),
                "audit_entries": len(self.runtime.audit),
                "budget": self._budget(),
                "domains": self.spec["domains"],
                "kpis": len(self.spec["required_kpis"]),
                "escalation": self.escalation}


# ==========================================================================
# the graph, rendered for the UI
# ==========================================================================

_SHAPE = {"work": ("box", "#e8eef7", "#1f3b63"),
          "gate": ("hexagon", "#fdf0d5", "#8a5a00"),
          "publish": ("box", "#e3f3e6", "#1d5c2a"),
          "terminal": ("octagon", "#fbe4e4", "#8a1c1c")}


def render_dot(pipeline: "Pipeline", current: Optional[str] = None) -> str:
    """The pipeline graph as DOT, shaded by what has actually run."""
    done = {e.node for e in pipeline.events if e.status in ("ok", "skipped")}
    lines = ["digraph pipeline {", '  rankdir=TB;', '  bgcolor="transparent";',
             '  node [fontname="Helvetica", fontsize=9, style="filled,rounded"];',
             '  edge [fontname="Helvetica", fontsize=8, color="#8795a8"];']
    for name, node in pipeline.graph.nodes.items():
        shape, fill, pen = _SHAPE.get(node.kind, _SHAPE["work"])
        lab, title = STAGE_META[name]
        if name == current:
            fill, pen = "#fff3bf", "#b07a00"
        elif name not in done:
            fill, pen = "#f4f5f7", "#b6bcc6"
        lines.append(f'  "{name}" [shape={shape}, fillcolor="{fill}", '
                     f'color="{pen}", label="{lab}\\n{title}"];')
    for e in pipeline.graph.edges:
        attrs = []
        if e.condition:
            attrs.append(f'label="{e.condition}"')
        if e.back_edge:
            attrs.append('style=dashed, color="#b07a00", constraint=false')
        lines.append(f'  "{e.src}" -> "{e.dst}"'
                     + (f' [{", ".join(attrs)}];' if attrs else ";"))
    lines.append("}")
    return "\n".join(lines)


# ==========================================================================
# markdown export of the published brief
# ==========================================================================

def brief_markdown(brief: Dict[str, Any], summary: Dict[str, Any]) -> str:
    out = [f"# Executive decision brief — {brief['period']}", "",
           f"**Version** v{brief['version']} · **Approved by** {brief['approved_by']} "
           f"· **Approved at** {brief['approved_at']}", "",
           f"**Spec** `{brief['spec_id']}` · **Run** `{summary['run_id']}` · "
           f"{summary['stages']} stages in {summary['wall_ms']:.0f} ms · "
           f"{summary['tests_green']}/{summary['tests_total']} acceptance tests green",
           "", "## KPI scorecard", "",
           "| KPI | Value | Target | Status | Source |", "|---|---|---|---|---|"]
    for k in brief["kpis"]:
        out.append(f"| {k['name']} | {k['value_shown']} {k['unit']} | "
                   f"{k['target']} | {k['status']} | {k['source_system']} |")
    detailed = [k for k in brief["kpis"] if k.get("drilldown")]
    if detailed:
        out += ["", "## Department breakdown", "",
                "Each department measured against the same target as the "
                "institution figure, worst first.", ""]
        for k in detailed:
            out += [f"### {k['name']} — target {k['target']}{k['unit']}", "",
                    "| Department | Value | vs target | Status |",
                    "|---|---|---|---|"]
            for d in k["drilldown"]:
                if d.get("value") is None:
                    out.append(f"| {d['dept']} | — | — | no data |")
                    continue
                v = d.get("variance")
                gap = "—" if v is None else f"{'+' if v > 0 else ''}{v:.2f}"
                out.append(f"| {d['dept']} | {d['value']} {k['unit']} | {gap} | "
                           f"{d['status']} |")
            out.append("")
    out += ["", "## Options", ""]
    for o in brief["options"]:
        out.append(f"- **{o['title']}** ({o['kpi_id']}, {o['specialist']})")
        for r in o.get("risks", []):
            out.append(f"  - risk: {r}")
        if o.get("trade_off"):
            out.append(f"  - trade-off: {o['trade_off']}")
    out += ["", "## Assumptions", ""]
    out += [f"- {a}" for a in brief["assumptions"]]
    if brief.get("edits"):
        out += ["", "## Edits applied at approval", ""]
        out += [f"- {e}" for e in brief["edits"]]
    return "\n".join(out)
