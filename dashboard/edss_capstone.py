"""edss_capstone — Lab 14: deploy() and system.run(), importable.

Wires the four engine layers into one System and runs a request end to end.
Written so the dashboard drives exactly the code the Lab 14 notebook is graded on.
"""

import copy
import json
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from edss_core import (DOMAINS, KPI_DEFINITIONS, REPORTING_PERIOD, ToolRouter,
                       TOOL_SCHEMAS, department_breakdown)
import edss_stack as L345
import edss_labs678 as L678
import edss_labs9to13 as L913


# ==========================================================================
# deploy()
# ==========================================================================

#              governance, specialists


@dataclass
class System:
    """Every lab's deliverable, in one object."""
    connector: Any                 # Lab 5
    skills: Dict[str, Any]         # Lab 3
    memory: Any                    # Lab 4
    runtime_cls: Any               # Lab 6
    graph: Any                     # Lab 7
    swarm_worker: Any              # Lab 8
    research: Any                  # Lab 9
    validate: Any                  # Lab 10
    heal: Any                      # Lab 10
    derive_suite: Any              # Lab 11
    acceptance_suite: Any          # Lab 11
    governance: Any                # Lab 12
    specialists: Dict[str, Any]    # Lab 13
    audit: List[Dict[str, Any]] = field(default_factory=list)
    metrics: List[Dict[str, Any]] = field(default_factory=list)

    def log(self, lab: str, stage: str, detail: str):
        self.audit.append({"seq": len(self.audit) + 1, "lab": lab, "stage": stage,
                           "detail": detail,
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def deploy() -> System:
    """Wire the eight phases together. No new capability is created here."""
    return System(
        connector=L345.coordinator_client,
        skills=L345.SKILL_REGISTRY,
        memory=L345.archive,
        runtime_cls=L678.Runtime,
        graph=L678.g,
        swarm_worker=L678.department_agent,
        research=L913.research,
        validate=L913.validate,
        heal=L913.heal,
        derive_suite=L913.derive_suite,
        acceptance_suite=L913.acceptance_suite,
        governance=L913.Governance(),
        specialists=L913.REGISTRY,
    )


# ==========================================================================
# system.run(request)
# ==========================================================================

CAPSTONE_SPEC = copy.deepcopy(L913.SPEC)
CAPSTONE_SPEC["spec_id"] = "PLAN-CAPSTONE-2025-26"
CAPSTONE_SPEC["domains"] = list(DOMAINS)                 # all four, incl. Finance
CAPSTONE_SPEC["required_kpis"] = list(KPI_DEFINITIONS)   # all nine

REQUEST = ("Prepare the executive decision brief on institution performance for "
           "academic year 2025-26, against NIRF, NAAC and the strategic plan, with "
           "department-level drill-down and options for every KPI that misses target.")


def capstone_build(spec, rows, specialists, inject_defect=False):
    """Compose ONE artifact that both the Lab 10 constraints and the Lab 11
    acceptance suite can judge. This is wiring, not new capability."""
    kpis = []
    for kpi_id in spec["required_kpis"]:
        c = L913.compute_kpi(kpi_id, rows)
        t = L913.compare_to_target(kpi_id, c["value"])
        src = c["source_system"]
        shown = f"{c['value']:.2f}"
        if inject_defect and kpi_id == "KPI-R2":
            src = ""                                     # Lab 10 will catch this
        kpis.append({"kpi_id": kpi_id, "name": c["name"], "value": c["value"],
                     "value_shown": shown, "unit": c["unit"], "target": t["target"],
                     "status": t["status"], "source_system": src,
                     "figure_status": c["figure_status"], "caveat": c.get("caveat", ""),
                     "rounding_warning": t["rounding_warning"],
                     # Lab 11's suite looks for 'drilldown'; Lab 12's redactor
                     # looks for 'departments'. The two labs named the same thing
                     # differently — integration is where that surfaces, and the
                     # capstone reconciles it rather than editing either lab.
                     "drilldown": department_breakdown(kpi_id, c["evidence"]),
                     "departments": department_breakdown(kpi_id, c["evidence"])})

    # Lab 13: the specialist that owns each domain drafts the options
    options = []
    for item in L913.work_items():
        if item.kpi_id not in spec["required_kpis"]:
            continue
        sp = specialists[item.domain]
        out = sp.check(sp.generate(item))
        if not out.valid:
            continue
        for o in out.options:
            options.append({**o, "kpi_id": item.kpi_id, "specialist": sp.name})

    return {"spec_id": spec["spec_id"], "period": spec["period"], "kpis": kpis,
            "sections": {s: "…" for s in spec["brief_sections"]},
            "options": options,
            "assumptions": ["Analysis covers academic year 2025-26 only.",
                            "Only Registrar-authorised read access was used.",
                            "KPI definitions and targets are the approved set.",
                            "Institution figures aggregate raw counts, never a mean "
                            "of department percentages."],
            "status": "DRAFT"}


def run(system: System, request: str, actor) -> Dict[str, Any]:
    t0 = time.perf_counter()
    stages = []

    def stage(lab, name, detail):
        stages.append({"stage": len(stages) + 1, "lab": lab, "name": name,
                       "detail": detail})
        system.log(lab, name, detail)
        print(f"  [{len(stages):>2}] {lab:<8} {name:<30} {detail}")

    print("=" * 100)
    print(f"REQUEST: {textwrap.fill(request, 86, subsequent_indent='         ')}")
    print("=" * 100)

    # 1 — Lab 5: the governed door
    reports = system.connector.read("department_reports", period=REPORTING_PERIOD)
    rows = reports["rows"]
    stage("Lab 5", "connector read", f"{reports['row_count']} rows via "
                                     f"{reports['source_system']}")

    # 2 — Lab 8: the swarm, in parallel, with its merge
    L678.reset_swarm_state()
    sw = L678.Swarm(system.swarm_worker, max_retries=2, backoff_s=0.02)
    swarm_results = sw.run(L678.UNITS)
    merged = L678.merge(swarm_results)
    stage("Lab 8", "parallel swarm + merge",
          f"{sum(1 for r in swarm_results.values() if r.ok)}/{len(swarm_results)} "
          f"agents, {merged['double_counted_removed']} double-counts removed, "
          f"coverage {merged['coverage_pct']}%")

    # 3 — Lab 3: skills review each domain
    skill_router = ToolRouter(agent="capstone")
    reviews = {d: system.skills["review_domain"].run(skill_router, domain=d,
                                                     period=REPORTING_PERIOD)
               for d in DOMAINS}
    stage("Lab 3", "domain skills",
          f"{len(reviews)} domains reviewed, "
          f"{sum(len(r['off_target']) for r in reviews.values())} KPIs off target")

    # 4 — Lab 4: the baseline and the no-repeat check
    snaps = L345.retrieve_by_tags(system.memory, ["kpi-snapshot"], "any")
    prior = L345.index.query("recruiter outreach to lift placement", k=1,
                             record_type="decision_brief")[0]
    stage("Lab 4", "memory + no-repeat",
          f"{len(snaps)} baselines; closest prior decision {prior['record_id']} "
          f"(sim {prior['similarity']:.3f})")

    # 5 — Lab 13 + wiring: build the artifact (with a defect injected)
    artifact = capstone_build(CAPSTONE_SPEC, rows, system.specialists,
                              inject_defect=True)
    stage("Lab 13", "specialists drafted options",
          f"{len(artifact['options'])} options from "
          f"{len({o['specialist'] for o in artifact['options']})} domain packs")

    # 6 — Lab 9: ground every claim
    cands = [L913.Candidate(f"K-{k['kpi_id']}", "finding", k["name"],
                            {"kpi_id": k["kpi_id"]}) for k in artifact["kpis"]]
    for c in cands:
        c.evidence = system.research(c)
        c.accepted = c.evidence.in_scope
    grounded = [c for c in cands if c.accepted]
    stage("Lab 9", "grounding", f"{len(grounded)}/{len(cands)} claims carry an "
                                f"in-scope source, locator and value")

    # 7 — Lab 10: validate, diagnose, heal
    pre = system.validate(artifact)
    stage("Lab 10", "validation (pre-heal)",
          f"passed={pre.passed}; failing "
          f"{[f['constraint'] + '@' + f['where'] for f in pre.failing]}")
    healed = system.heal(artifact)
    stage("Lab 10", "self-heal",
          f"{healed['attempts']} attempt(s); now passed={healed['report'].passed}")

    # 8 — Lab 11: the derived acceptance suite gates the human
    suite_report = system.acceptance_suite(artifact, CAPSTONE_SPEC)
    stage("Lab 11", "acceptance suite",
          f"{sum(r['passed'] for r in suite_report.results)}/"
          f"{len(suite_report.results)} derived tests green")
    submission = L913.submit_for_review(artifact, suite_report, str(actor))
    stage("Lab 11", "gate -> human", f"submitted to {submission['submitted_to']}")

    # 9 — Lab 12: approve, version, publish
    artifact["status"] = "draft"
    version = system.governance.approve_and_publish(
        actor, artifact, edits=["Lead with the average-package decline."])
    stage("Lab 12", "approved + published",
          f"v{version} by {actor.name}; "
          f"{len(system.governance.audit)} governance audit entries")

    elapsed = (time.perf_counter() - t0) * 1000
    system.metrics.append({"request": request[:60], "version": version,
                           "ms": round(elapsed, 1), "stages": len(stages),
                           "tests_green": len(suite_report.results),
                           "heal_attempts": healed["attempts"]})
    return {"artifact": system.governance.live(), "stages": stages,
            "suite": suite_report, "heal": healed, "merged": merged,
            "reviews": reviews, "grounded": grounded, "version": version,
            "ms": elapsed}


def wiring_summary(system: "System") -> Dict[str, str]:
    """What each lab contributes, for the dashboard's deployment panel."""
    return {
        "Lab 1  coordinator loop": "clarify -> plan -> revise",
        "Lab 2  typed tools": f"{len(TOOL_SCHEMAS)} tools behind one router",
        "Lab 3  skills": f"{len(system.skills)} reusable skills",
        "Lab 4  memory": f"{len(system.memory)} archive records",
        "Lab 5  connector": f"{len(L345.server.resources)} resources, "
                            f"{len(L345.server.tokens)} scoped tokens",
        "Lab 6  runtime": "budgets, audit, gates, checkpoint/resume",
        "Lab 7  node graph": f"{len(system.graph.nodes)} nodes, "
                             f"{len(system.graph.edges)} edges",
        "Lab 8  swarm": f"{len(L678.UNITS)} department agents + merge",
        "Lab 9  grounding": f"{len(L913.IN_SCOPE_SOURCES)} in-scope sources",
        "Lab 10 self-healing": f"{len(L913.CONSTRAINTS)} constraints, "
                               f"budget {L913.RETRY_BUDGET}",
        "Lab 11 factory": f"{len(system.derive_suite(L913.SPEC))} derived tests",
        "Lab 12 governance": f"{len(L913.ROLES)} roles, versioned + reversible",
        "Lab 13 specialists": f"{len(system.specialists)} domain packs",
    }
