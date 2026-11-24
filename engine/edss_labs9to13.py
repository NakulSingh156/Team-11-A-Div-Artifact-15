"""edss_labs9to13 — the Labs 9-13 machinery, importable.

    Lab 9   Evidence / research()        grounding, in-scope sources, rejection
    Lab 10  Constraint / validate / heal self-healing with targeted repair
    Lab 11  derive_suite / acceptance    the plan as spec, tests derived from it
    Lab 12  Roles / Governance           approval, confidentiality, versions, rollback
    Lab 13  Specialist / REGISTRY        four domain packs with checkable schemes

Extracted verbatim from the lab notebooks so the capstone WIRES these together
rather than reimplementing them.
"""

import copy
import json
import re
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from edss_core import (DOMAINS, KPI_DEFINITIONS, REPORTING_PERIOD, ToolRouter,
                       compute_kpi, compare_to_target, department_breakdown)
from edss_stack import coordinator_client, archive, index, server

router = ToolRouter(agent="labs9to13")
ROWS = coordinator_client.read("department_reports", period=REPORTING_PERIOD)["rows"]


# ==========================================================================
# LAB 9 — evidence model
# ==========================================================================

# The only sources a claim may rest on. Anything else is out of scope.
IN_SCOPE_SOURCES = {
    "department reports":   "Registrar-authorised per-department metric rows",
    "KPI register":         "Approved KPI definitions, formulas and targets",
    "external benchmarks":  "Published NIRF cohort peer medians",
    "institutional archive": "Closed-year KPI snapshots and past decision briefs",
}


@dataclass
class Evidence:
    """What ties one claim to one verifiable place."""
    claim: str
    source: Optional[str] = None        # which in-scope source
    locator: Optional[str] = None       # exactly where inside it
    value: Optional[Any] = None         # the figure the source actually yields
    scope_tags: List[str] = field(default_factory=list)
    in_scope: bool = False
    reason: str = ""

    def row(self) -> Dict[str, Any]:
        return {"claim": self.claim, "source": self.source or "—",
                "locator": self.locator or "—", "value": self.value,
                "in_scope": self.in_scope, "reason": self.reason}


@dataclass
class Candidate:
    """Something the Report Generation Agent wants to put in the brief."""
    cid: str
    kind: str                            # finding | option | context
    text: str
    wants: Dict[str, Any] = field(default_factory=dict)   # what it claims to rest on
    evidence: Optional[Evidence] = None
    accepted: Optional[bool] = None


# ==========================================================================
# LAB 9 — research(): the grounding step
# ==========================================================================

def research(c: Candidate) -> Evidence:
    """Resolve a candidate against the in-scope sources. May fail."""
    want = c.wants

    # ---- a KPI figure: compute it and cite formula + source system ---------
    if want.get("kpi_id"):
        kpi_id = want["kpi_id"]
        if kpi_id not in KPI_DEFINITIONS:
            return Evidence(c.text, reason=f"'{kpi_id}' is not an approved KPI")
        computed = router.call("compute_kpi", reason=f"ground {c.cid} on {kpi_id}",
                               kpi_id=kpi_id, rows=ROWS)
        return Evidence(c.text, source="KPI register",
                        locator=f"{kpi_id} · {computed['formula']} · "
                                f"{computed['source_system']}",
                        value=computed["value"],
                        scope_tags=[computed["domain"].lower(), "kpi"], in_scope=True,
                        reason="computed from the approved formula over "
                               f"{computed['n_departments']} departments")

    # ---- a department-level figure ----------------------------------------
    if want.get("dept") and want.get("field"):
        row = next((r for r in ROWS if r["dept_code"] == want["dept"]), None)
        if row is None:
            return Evidence(c.text, reason=f"no department '{want['dept']}' in the export")
        if want["field"] not in row:
            return Evidence(c.text,
                            reason=f"'{want['field']}' is not a reported field")
        return Evidence(c.text, source="department reports",
                        locator=f"{want['dept']} · {want['field']}",
                        value=row[want["field"]], scope_tags=["department"], in_scope=True,
                        reason="read from the Registrar-authorised export")

    # ---- a peer benchmark --------------------------------------------------
    if want.get("benchmark_for"):
        kpi_id = want["benchmark_for"]
        try:
            bench = coordinator_client.read("external_benchmark", kpi_id=kpi_id)
        except Exception as exc:
            return Evidence(c.text, reason=f"benchmark API has no record: {exc}")
        return Evidence(c.text, source="external benchmarks",
                        locator=f"{bench['cohort']} · {bench['year']}",
                        value=bench["peer_median"], scope_tags=["benchmark"], in_scope=True,
                        reason="published peer median")

    # ---- a historical claim -------------------------------------------------
    if want.get("archive_id"):
        rid = want["archive_id"]
        if rid not in archive:
            return Evidence(c.text, reason=f"no archive record '{rid}'")
        rec = archive.get(rid)
        return Evidence(c.text, source="institutional archive",
                        locator=f"{rid} · {rec['period']}",
                        value=rec.get("values") or rec.get("outcome"),
                        scope_tags=["history"], in_scope=True,
                        reason="closed-year record in the append-only archive")

    # ---- nothing to stand on ------------------------------------------------
    return Evidence(c.text,
                    reason="no in-scope source was named or found for this claim")


# ==========================================================================
# LAB 10 — constraint + report model
# ==========================================================================

@dataclass
class Constraint:
    """One acceptance rule, with the repair that fixes exactly it."""
    cid: str
    text: str
    scope: str                       # "row" (per KPI) or "brief" (whole document)
    test: Callable                   # (brief, row) -> True if satisfied
    repair: Callable                 # (brief, row) -> mutates in place
    diagnosis: str


@dataclass
class Report:
    passed: bool
    failing: List[Dict[str, str]] = field(default_factory=list)   # {constraint, where}

    def summary(self) -> str:
        return ("all constraints satisfied" if self.passed else
                "; ".join(f"{f['constraint']} @ {f['where']}" for f in self.failing))


def build_brief(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A clean, fully-compliant brief. Faults are injected into copies of it."""
    kpi_rows = []
    for kpi_id in KPI_DEFINITIONS:
        c = compute_kpi(kpi_id, rows)
        t = compare_to_target(kpi_id, c["value"])
        kpi_rows.append({
            "kpi_id": kpi_id, "name": c["name"], "value": c["value"],
            "value_shown": f"{c['value']:.2f}", "unit": c["unit"],
            "target": t["target"], "status": t["status"],
            "source_system": c["source_system"],
            "figure_status": c["figure_status"],
            "caveat": c.get("caveat", ""),
            "rounding_warning": t["rounding_warning"]})
    return {"period": REPORTING_PERIOD, "kpis": kpi_rows,
            "assumptions": ["Analysis covers academic year 2025-26 only.",
                            "Only Registrar-authorised read access was used.",
                            "KPI definitions and targets are the approved set."],
            "options": [{"kpi_id": "KPI-P1", "title": "Core-branch placement drive",
                         "owner": "Placement Officer", "timeline": "2 semesters",
                         "risks": ["Core-branch hiring is market-driven."],
                         "trade_off": "Equity across branches vs total placement count."},
                        {"kpi_id": "KPI-R1", "title": "Seed-grant scheme",
                         "owner": "Dean (R&D)", "timeline": "2 semesters",
                         "risks": ["Counting publications alone rewards low-quality venues."],
                         "trade_off": "Output volume vs output quality."}],
            "status": "DRAFT"}


# ==========================================================================
# LAB 10 — the constraints and validate()
# ==========================================================================

def _rows_missing_source(b):   return [k for k in b["kpis"] if not k["source_system"]]
def _rows_unlabelled_prov(b):  return [k for k in b["kpis"]
                                       if k["figure_status"] != "final" and not k["caveat"]]
def _rows_rounded_over(b):
    out = []
    for k in b["kpis"]:
        if k["value"] < k["target"] and float(k["value_shown"]) >= k["target"]:
            out.append(k)
    return out


CONSTRAINTS = [
    Constraint("every-figure-cites-its-source",
               "Every figure cites its source system.", "row",
               lambda b, r: bool(r["source_system"]),
               lambda b, r: r.update(
                   source_system=KPI_DEFINITIONS[r["kpi_id"]]["source_system"]),
               "a KPI row reached the brief with an empty source_system"),
    Constraint("assumptions-stated",
               "Assumptions are stated explicitly (at least three).", "brief",
               lambda b, r: len(b.get("assumptions", [])) >= 3,
               lambda b, r: b.setdefault("assumptions", []).extend(
                   ["Analysis covers academic year 2025-26 only.",
                    "Only Registrar-authorised read access was used.",
                    "KPI definitions and targets are the approved set."][
                       len(b.get("assumptions", [])):]),
               "the assumptions block was dropped or truncated"),
    Constraint("options-carry-risks",
               "Each option lists its risks and its trade-off.", "brief",
               lambda b, r: all(o.get("risks") and o.get("trade_off")
                                for o in b.get("options", [])),
               lambda b, r: [o.update(
                   risks=o.get("risks") or ["Risk not yet assessed — "
                                            "flagged for the owner."],
                   trade_off=o.get("trade_off") or "Trade-off not yet stated.")
                   for o in b.get("options", [])],
               "an option was drafted without risks or without a trade-off"),
    Constraint("provisional-labelled",
               "Provisional figures carry their caveat.", "row",
               lambda b, r: r["figure_status"] == "final" or bool(r["caveat"]),
               lambda b, r: r.update(
                   caveat=KPI_DEFINITIONS[r["kpi_id"]].get("caveat", "Provisional.")),
               "an unreconciled figure was shown without its caveat"),
    Constraint("rounding-hides-nothing",
               "A displayed figure never rounds a miss into a hit.", "row",
               lambda b, r: not (r["value"] < r["target"]
                                 and float(r["value_shown"]) >= r["target"]),
               lambda b, r: r.update(value_shown=f"{r['value']:.2f}"),
               "a rounded display value made a missed target read as met"),
    Constraint("no-publish-without-approval",
               "Nothing is published without leadership approval.", "brief",
               lambda b, r: b.get("status") in ("DRAFT", "APPROVED"),
               lambda b, r: b.update(status="DRAFT"),
               "the brief carried a status that bypasses the human gate"),
]
BY_ID = {c.cid: c for c in CONSTRAINTS}


def validate(brief: Dict[str, Any]) -> Report:
    """Run every constraint and report WHICH failed and WHERE."""
    failing = []
    for c in CONSTRAINTS:
        if c.scope == "brief":
            if not c.test(brief, None):
                failing.append({"constraint": c.cid, "where": "brief"})
        else:
            for row in brief["kpis"]:
                if not c.test(brief, row):
                    failing.append({"constraint": c.cid, "where": row["kpi_id"]})
    return Report(passed=not failing, failing=failing)


# ==========================================================================
# LAB 10 — the self-healing loop
# ==========================================================================

RETRY_BUDGET = 3


class Escalation(Exception):
    """The loop could not repair the output; a human must look at it."""


def heal(brief: Dict[str, Any], budget: int = RETRY_BUDGET) -> Dict[str, Any]:
    """Returns a diagnosis log. Mutates `brief` in place, minimally."""
    log, attempts = [], 0
    report = validate(brief)
    log.append({"attempt": 0, "action": "validate", "passed": report.passed,
                "failing": [f"{f['constraint']}@{f['where']}" for f in report.failing]})

    while not report.passed and attempts < budget:
        attempts += 1
        repaired, unrepairable = [], []
        for fail in report.failing:
            c = BY_ID[fail["constraint"]]
            target = (None if fail["where"] == "brief"
                      else next((k for k in brief["kpis"]
                                 if k["kpi_id"] == fail["where"]), None))
            try:
                c.repair(brief, target)
                repaired.append(f"{c.cid}@{fail['where']}")
            except Exception as exc:
                unrepairable.append(f"{c.cid}@{fail['where']}: "
                                    f"{type(exc).__name__}: {exc}")
        report = validate(brief)
        log.append({"attempt": attempts, "action": "diagnose + targeted repair",
                    "repaired": repaired, "unrepairable": unrepairable,
                    "passed": report.passed,
                    "failing": [f"{f['constraint']}@{f['where']}" for f in report.failing]})

    if not report.passed:
        log.append({"attempt": attempts, "action": "ESCALATE",
                    "reason": f"still failing after {budget} attempts",
                    "failing": [f"{f['constraint']}@{f['where']}" for f in report.failing]})
        raise Escalation(json.dumps(log[-1]))
    return {"attempts": attempts, "log": log, "report": report}


def diagnose(report: Report) -> List[str]:
    """Human-readable: what broke, and what it means."""
    return [f"{f['where']}: {BY_ID[f['constraint']].diagnosis}" for f in report.failing]


# ==========================================================================
# LAB 11 — the spec
# ==========================================================================

# ---- the locked plan, exactly as Lab 1 produces it --------------------------
SPEC = {
    "spec_id": "PLAN-2025-26-r2",
    "period": REPORTING_PERIOD,
    "domains": ["Academic", "Research", "Placement"],      # Finance removed at r1
    "required_kpis": ["KPI-A1", "KPI-A2", "KPI-R1", "KPI-R2", "KPI-R3",
                      "KPI-P1", "KPI-P2", "KPI-P3"],
    "drilldown_policy": "mandatory for every KPI",
    "brief_sections": ["Executive summary", "KPI scorecard", "Off-target drill-down",
                       "Options", "Risks and trade-offs", "Assumptions",
                       "Evidence appendix"],
    "validation_checks": ["every figure cites its source",
                          "assumptions are stated explicitly",
                          "each option lists its risks and trade-offs",
                          "no action is taken without leadership approval"],
    "evidence_requirements": ["Every figure carries its source system and formula.",
                              "Provisional figures are labelled inline."],
    "min_options_per_off_target_kpi": 1,
}


# ==========================================================================
# LAB 11 — derive_suite() and the acceptance suite
# ==========================================================================

@dataclass
class Test:
    tid: str
    description: str
    derived_from: str                 # which spec field produced this test
    fn: Callable                      # (artifact) -> (bool, detail)


def derive_suite(spec: Dict[str, Any]) -> List[Test]:
    tests: List[Test] = []

    # one test per required KPI
    for kpi_id in spec["required_kpis"]:
        tests.append(Test(
            f"kpi-present:{kpi_id}",
            f"{kpi_id} is present and cites a source",
            "required_kpis",
            lambda a, k=kpi_id: (
                any(r["kpi_id"] == k and r.get("source_system") for r in a["kpis"]),
                f"{k} " + ("present with a source" if any(
                    r["kpi_id"] == k and r.get("source_system") for r in a["kpis"])
                    else "missing or uncited"))))

    # one test per required section
    for section in spec["brief_sections"]:
        tests.append(Test(
            f"section:{section}", f"section '{section}' exists and is non-empty",
            "brief_sections",
            lambda a, s=section: (bool(a.get("sections", {}).get(s)),
                                  f"'{s}' " + ("present" if a.get("sections", {}).get(s)
                                               else "missing or empty"))))

    # domains in scope — and nothing outside them
    tests.append(Test(
        "scope:domains", "every KPI belongs to a domain the spec allows", "domains",
        lambda a: (
            all(KPI_DEFINITIONS[r["kpi_id"]]["domain"] in spec["domains"]
                for r in a["kpis"] if r["kpi_id"] in KPI_DEFINITIONS),
            "out-of-scope: " + str([r["kpi_id"] for r in a["kpis"]
                                    if r["kpi_id"] in KPI_DEFINITIONS
                                    and KPI_DEFINITIONS[r["kpi_id"]]["domain"]
                                    not in spec["domains"]]))))

    # drill-down policy
    if spec["drilldown_policy"].startswith("mandatory"):
        tests.append(Test(
            "drilldown:every-kpi", "every KPI carries department drill-down",
            "drilldown_policy",
            lambda a: (all(r.get("drilldown") for r in a["kpis"]),
                       "missing drill-down: " + str([r["kpi_id"] for r in a["kpis"]
                                                     if not r.get("drilldown")]))))

    # options for every off-target KPI
    tests.append(Test(
        "options:coverage",
        f"every off-target KPI has >= {spec['min_options_per_off_target_kpi']} option",
        "min_options_per_off_target_kpi",
        lambda a: (
            all(sum(1 for o in a.get("options", []) if o["kpi_id"] == r["kpi_id"])
                >= spec["min_options_per_off_target_kpi"]
                for r in a["kpis"] if r["status"] != "on target"),
            "uncovered: " + str([r["kpi_id"] for r in a["kpis"]
                                 if r["status"] != "on target"
                                 and not any(o["kpi_id"] == r["kpi_id"]
                                             for o in a.get("options", []))]))))

    # the plan's own validation checks, as tests
    for chk in spec["validation_checks"]:
        if "risks" in chk:
            tests.append(Test("checks:option-risks", chk, "validation_checks",
                              lambda a: (all(o.get("risks") and o.get("trade_off")
                                             for o in a.get("options", [])),
                                         "options missing risks/trade-off")))
        elif "assumptions" in chk:
            tests.append(Test("checks:assumptions", chk, "validation_checks",
                              lambda a: (len(a.get("assumptions", [])) >= 3,
                                         f"{len(a.get('assumptions', []))} assumptions")))
        elif "approval" in chk:
            tests.append(Test("checks:not-published", chk, "validation_checks",
                              lambda a: (a.get("status") == "DRAFT",
                                         f"status={a.get('status')}")))
    return tests


@dataclass
class SuiteReport:
    results: List[Dict[str, Any]]

    @property
    def all_pass(self) -> bool:
        return all(r["passed"] for r in self.results)

    @property
    def failures(self) -> List[Dict[str, Any]]:
        return [r for r in self.results if not r["passed"]]

    def table(self) -> str:
        out = [f"  {'test':<34}{'from':<34}{'result'}"]
        for r in self.results:
            out.append(f"  {r['tid'][:32]:<34}{r['derived_from'][:32]:<34}"
                       f"{'pass' if r['passed'] else 'FAIL — ' + r['detail'][:30]}")
        return "\n".join(out)


def acceptance_suite(artifact: Dict[str, Any], spec: Dict[str, Any]) -> SuiteReport:
    results = []
    for t in derive_suite(spec):
        ok, detail = t.fn(artifact)
        results.append({"tid": t.tid, "description": t.description,
                        "derived_from": t.derived_from, "passed": ok, "detail": detail})
    return SuiteReport(results)


suite = derive_suite(SPEC)


# ==========================================================================
# LAB 11 — build() and the review gate
# ==========================================================================

def build(spec: Dict[str, Any], complete: bool = False) -> Dict[str, Any]:
    kpis = []
    for kpi_id in spec["required_kpis"]:
        c = compute_kpi(kpi_id, ROWS)
        t = compare_to_target(kpi_id, c["value"])
        row = {"kpi_id": kpi_id, "name": c["name"], "value": c["value"],
               "unit": c["unit"], "target": t["target"], "status": t["status"],
               "source_system": c["source_system"],
               "figure_status": c["figure_status"]}
        if complete:
            # Each department is judged by the SAME compare_to_target the
            # institution figure went through, so "below target" means exactly
            # one thing in this brief whichever row you are reading. Without
            # this a drill-down is eight bare numbers and the reader has to do
            # the comparison in their head.
            row["drilldown"] = department_breakdown(kpi_id, c["evidence"])
        kpis.append(row)

    sections = {"Executive summary": "…", "KPI scorecard": "…"}
    options = [{"kpi_id": "KPI-P1", "title": "Core-branch placement drive",
                "risks": ["Core-branch hiring is market-driven."],
                "trade_off": "Equity across branches vs total placement count."}]
    assumptions = ["Analysis covers academic year 2025-26 only."]

    if complete:
        sections = {s: "…" for s in spec["brief_sections"]}
        assumptions = ["Analysis covers academic year 2025-26 only.",
                       "Only Registrar-authorised read access was used.",
                       "KPI definitions and targets are the approved set."]
        options = [{"kpi_id": r["kpi_id"],
                    "title": f"Remediation option for {r['name']}",
                    "risks": [f"Effort may not move {r['name']} within one cycle."],
                    "trade_off": "Cost and attention against a lagging indicator."}
                   for r in kpis if r["status"] != "on target"]

    return {"spec_id": spec["spec_id"], "period": spec["period"], "kpis": kpis,
            "sections": sections, "options": options, "assumptions": assumptions,
            "status": "DRAFT"}


# ==========================================================================
# LAB 11 — submit_for_review()
# ==========================================================================

class AcceptanceGateError(Exception):
    pass


def submit_for_review(artifact: Dict[str, Any], report: SuiteReport,
                      reviewer: str) -> Dict[str, Any]:
    """The ONLY way to the human gate. Requires a fully green report."""
    if not report.all_pass:
        raise AcceptanceGateError(
            f"refusing to send to {reviewer}: {len(report.failures)} of "
            f"{len(report.results)} acceptance tests failing "
            f"({[f['tid'] for f in report.failures][:3]}…)")
    return {"submitted_to": reviewer, "spec_id": artifact["spec_id"],
            "tests_passed": len(report.results),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# ==========================================================================
# LAB 12 — roles and permissions
# ==========================================================================

@dataclass(frozen=True)
class Role:
    name: str
    can_view: bool
    can_edit: bool
    can_approve: bool
    can_rollback: bool
    sees_department_detail: bool      # confidentiality: department-level drill-down
    sees_provisional: bool            # may see unreconciled figures at all


ROLES = {
    "principal":  Role("Principal / Director", True, True, True, True, True, True),
    "registrar":  Role("Registrar", True, True, True, True, True, True),
    "dean":       Role("Dean", True, True, False, False, True, True),
    "council":    Role("Governing Council member", True, False, False, False,
                       False, False),
    "analyst":    Role("Planning analyst", True, False, False, False, True, True),
    "intern":     Role("Summer intern", True, False, False, False, False, False),
}


@dataclass
class Actor:
    name: str
    role_key: str

    @property
    def role(self) -> Role:
        return ROLES[self.role_key]

    def __str__(self):
        return f"{self.name} ({self.role.name})"


ACTORS = {
    "principal": Actor("Dr. A. Principal", "principal"),
    "registrar": Actor("S. Registrar", "registrar"),
    "dean": Actor("Dean (Academics)", "dean"),
    "council": Actor("Council member R. Rao", "council"),
    "analyst": Actor("P. Analyst", "analyst"),
    "intern": Actor("Summer intern", "intern"),
}


# ==========================================================================
# LAB 12 — the governed store
# ==========================================================================

class PermissionError_(Exception):
    pass


class StateError(Exception):
    pass


def make_brief() -> Dict[str, Any]:
    kpis = []
    for kpi_id in KPI_DEFINITIONS:
        c = compute_kpi(kpi_id, ROWS)
        t = compare_to_target(kpi_id, c["value"])
        kpis.append({"kpi_id": kpi_id, "name": c["name"], "value": c["value"],
                     "unit": c["unit"], "target": t["target"], "status": t["status"],
                     "source_system": c["source_system"],
                     "figure_status": c["figure_status"],
                     "departments": [{"dept": e["dept_code"], "value": e["dept_value"]}
                                     for e in c["evidence"]]})
    return {"period": REPORTING_PERIOD, "kpis": kpis, "status": "draft",
            "summary": "9 of 9 KPIs off target; placement improving, package declining.",
            "edits": []}


class Governance:
    """Versioned, auditable, reversible releases."""

    def __init__(self):
        self.versions: Dict[int, Dict[str, Any]] = {}
        self.current: Optional[int] = None
        self.audit: List[Dict[str, Any]] = []
        self.metrics: List[Dict[str, Any]] = []

    def _log(self, actor: Actor, action: str, detail: str, allowed: bool):
        self.audit.append({"seq": len(self.audit) + 1, "actor": str(actor),
                           "role": actor.role.name, "action": action,
                           "detail": detail, "allowed": allowed,
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    # ---- the approval gate ---------------------------------------------
    def approve_and_publish(self, actor: Actor, draft: Dict[str, Any],
                            edits: Optional[List[str]] = None) -> int:
        if not actor.role.can_approve:
            self._log(actor, "approve", "denied: role cannot approve", False)
            raise PermissionError_(f"{actor.name} ({actor.role.name}) may not approve "
                                   f"an executive brief")
        if draft.get("status") != "draft":
            self._log(actor, "approve", f"denied: status is '{draft.get('status')}'", False)
            raise StateError(f"only a draft may be approved; this is "
                             f"'{draft.get('status')}'")
        final = copy.deepcopy(draft)
        final["edits"] = list(edits or [])
        final["status"] = "approved"
        final["approved_by"] = str(actor)
        final["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        version = (max(self.versions) + 1) if self.versions else 1
        final["version"] = version
        self.versions[version] = final
        self.current = version
        self._log(actor, "approve+publish", f"v{version}", True)
        self.metrics.append({"version": version, "at": final["approved_at"],
                             "kpis": len(final["kpis"]),
                             "off_target": sum(1 for k in final["kpis"]
                                               if k["status"] != "on target"),
                             "edits_applied": len(final["edits"]),
                             "approved_by": str(actor)})
        return version

    # ---- rollback --------------------------------------------------------
    def rollback(self, actor: Actor, to_version: int) -> int:
        if not actor.role.can_rollback:
            self._log(actor, "rollback", f"denied: role cannot roll back", False)
            raise PermissionError_(f"{actor.name} ({actor.role.name}) may not roll back "
                                   f"a release")
        if to_version not in self.versions:
            self._log(actor, "rollback", f"denied: no v{to_version}", False)
            raise StateError(f"no version {to_version} to restore")
        self.current = to_version
        self._log(actor, "rollback", f"current -> v{to_version}", True)
        self.metrics.append({"version": to_version, "event": "rollback",
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "by": str(actor)})
        return to_version

    def live(self) -> Optional[Dict[str, Any]]:
        return self.versions.get(self.current) if self.current else None


# ==========================================================================
# LAB 12 — confidentiality views
# ==========================================================================

def view_for(actor: Actor, brief: Dict[str, Any]) -> Dict[str, Any]:
    """Redact per the reader's role. Redaction is recorded, not silent."""
    if not actor.role.can_view:
        raise PermissionError_(f"{actor.name} may not view this brief")
    v = copy.deepcopy(brief)
    redactions = []

    if not actor.role.sees_department_detail:
        for k in v["kpis"]:
            n = len(k.pop("departments", []))
            k["departments"] = f"[{n} departments — detail withheld at this access level]"
        redactions.append("department-level drill-down")

    if not actor.role.sees_provisional:
        kept = []
        for k in v["kpis"]:
            if k["figure_status"] != "final":
                redactions.append(f"{k['kpi_id']} (provisional)")
            else:
                kept.append(k)
        v["kpis"] = kept

    v["rendered_for"] = str(actor)
    v["redactions"] = redactions
    return v


draft = make_brief()


# ==========================================================================
# LAB 13 — the specialist contract
# ==========================================================================

@dataclass
class WorkItem:
    """One off-target KPI handed to whichever specialist owns its domain."""
    kpi_id: str
    name: str
    domain: str
    value: float
    unit: str
    target: float
    status: str
    figure_status: str
    evidence: List[Dict[str, Any]]


@dataclass
class SpecialistOutput:
    kpi_id: str
    specialist: str
    headline: str
    options: List[Dict[str, Any]]
    scheme_fields: Dict[str, Any]       # the domain's own checkable fields
    valid: Optional[bool] = None
    violations: List[str] = field(default_factory=list)


class Specialist:
    """A domain pack: vocabulary, option templates, and its OWN validator."""

    domain = "—"
    name = "—"
    vocabulary: List[str] = []
    required_scheme: List[str] = []

    def generate(self, item: WorkItem) -> SpecialistOutput:
        raise NotImplementedError

    def check(self, out: SpecialistOutput) -> SpecialistOutput:
        """The checkable scheme. Generic rules + whatever the domain adds."""
        v = []
        missing = [f for f in self.required_scheme if f not in out.scheme_fields
                   or out.scheme_fields[f] in (None, "", [])]
        if missing:
            v.append(f"scheme fields missing: {missing}")
        if not out.options:
            v.append("no option produced")
        for o in out.options:
            for required in ("title", "owner", "timeline", "risks", "trade_off",
                             "measure_of_success"):
                if not o.get(required):
                    v.append(f"option '{o.get('title', '?')}' missing {required}")
        if not any(w.lower() in out.headline.lower() for w in self.vocabulary):
            v.append(f"headline uses none of the {self.domain} vocabulary "
                     f"{self.vocabulary}")
        v += self.domain_rules(out)
        out.violations = v
        out.valid = not v
        return out

    def domain_rules(self, out: SpecialistOutput) -> List[str]:
        return []


REGISTRY: Dict[str, Specialist] = {}


def register(cls):
    """Decorator on a Specialist CLASS — stores a ready-to-use INSTANCE."""
    REGISTRY[cls.domain] = cls()
    return cls


# ==========================================================================
# LAB 13 — the four domain packs
# ==========================================================================

def fmt(value: float, unit: str) -> str:
    """Render a figure in its own unit — grants are lakh, not 'per faculty'."""
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "INR lakh":
        return f"INR {value:.2f} lakh"
    if unit == "per faculty":
        return f"{value:.2f} per faculty"
    if unit.startswith("index"):
        return f"{value:.3f} (index 0-3)"
    return f"{value:.2f} {unit}"


@register
class AcademicSpecialist(Specialist):
    domain, name = "Academic", "Academic affairs pack"
    vocabulary = ["pass percentage", "attainment", "remedial", "cohort", "examination"]
    required_scheme = ["affected_cohort", "assessment_cycle", "attainment_linked"]

    def generate(self, item):
        worst = sorted(item.evidence, key=lambda e: e["dept_value"])[:2]
        return SpecialistOutput(
            item.kpi_id, self.name,
            f"{item.name} is {fmt(item.value, item.unit)} against "
            f"{fmt(item.target, item.unit)}; the weakest cohort performance sits in "
            f"{', '.join(w['dept_code'] for w in worst)}.",
            [{"title": f"Remedial cohort coaching in {worst[0]['dept_code']}",
              "owner": "Dean (Academics)", "timeline": "1 semester",
              "risks": ["Diverts faculty hours from laboratory supervision.",
                        "Gains land in the next examination cycle, not this one."],
              "trade_off": "Staff time now against a lagging indicator later.",
              "measure_of_success": f"{item.name} ≥ {fmt(item.target, item.unit)} at "
                                    f"the next end-semester examination"}],
            {"affected_cohort": [w["dept_code"] for w in worst],
             "assessment_cycle": "end-semester 2025-26",
             "attainment_linked": True})

    def domain_rules(self, out):
        v = []
        if not out.scheme_fields.get("affected_cohort"):
            v.append("academic remedies must name the affected cohort")
        if not out.scheme_fields.get("attainment_linked"):
            v.append("academic options must link to a CO/PO attainment outcome")
        return v


@register
class ResearchSpecialist(Specialist):
    domain, name = "Research", "Research & publications pack"
    vocabulary = ["publication", "citation", "faculty", "grant", "indexed", "cohort"]
    required_scheme = ["indexing_basis", "lag_years", "double_count_checked"]

    def generate(self, item):
        return SpecialistOutput(
            item.kpi_id, self.name,
            f"{item.name} is {fmt(item.value, item.unit)} against "
            f"{fmt(item.target, item.unit)}; "
            + ("indexed-venue publication volume is the binding constraint."
               if item.unit == "per faculty"
               else "sanctioned grant volume is the binding constraint."),
            [{"title": "Seed-grant scheme tied to indexed venues",
              "owner": "Dean (R&D)", "timeline": "2 semesters",
              "risks": ["Counting publications alone rewards low-quality venues.",
                        "Citation effects lag publication by two to three years."],
              "trade_off": "Output volume against output quality.",
              "measure_of_success": f"{item.name} ≥ {fmt(item.target, item.unit)} "
                                    f"within two assessment cycles"}],
            {"indexing_basis": "Scopus/WoS indexed only", "lag_years": 2,
             "double_count_checked": True})

    def domain_rules(self, out):
        v = []
        if not out.scheme_fields.get("double_count_checked"):
            v.append("research outputs must confirm cross-department collaborations "
                     "are not double-counted")
        if not out.scheme_fields.get("indexing_basis"):
            v.append("research options must state the indexing basis")
        return v


@register
class PlacementSpecialist(Specialist):
    domain, name = "Placement", "Placement & careers pack"
    vocabulary = ["placement", "recruiter", "offer", "package", "internship", "eligible"]
    required_scheme = ["eligible_pool", "recruiter_action", "provisional_offers_excluded"]

    def generate(self, item):
        worst = sorted(item.evidence, key=lambda e: e["dept_value"])[:3]
        pool = sum(e.get("denominator", 0) for e in item.evidence)
        return SpecialistOutput(
            item.kpi_id, self.name,
            f"{item.name} is {fmt(item.value, item.unit)} against "
            f"{fmt(item.target, item.unit)}; recruiter coverage is thinnest for "
            f"{', '.join(w['dept_code'] for w in worst)}.",
            [{"title": "Targeted recruiter outreach for the weakest branches",
              "owner": "Placement Officer", "timeline": "2 semesters",
              "risks": ["Core-branch hiring is market-driven and may not convert.",
                        "A wider recruiter pool typically lowers the average package."],
              "trade_off": "Placement percentage against average package — these two "
                           "KPIs pull in opposite directions.",
              "measure_of_success": f"{item.name} ≥ {fmt(item.target, item.unit)} by "
                                    f"the close of the next placement season"}],
            {"eligible_pool": pool, "recruiter_action": "outreach + alumni referral",
             "provisional_offers_excluded": True})

    def domain_rules(self, out):
        v = []
        if not out.scheme_fields.get("provisional_offers_excluded"):
            v.append("placement outputs must confirm provisional offers are excluded")
        if not out.scheme_fields.get("eligible_pool"):
            v.append("placement options must state the eligible pool they act on")
        return v


@register
class FinanceSpecialist(Specialist):
    domain, name = "Finance", "Finance & accounts pack"
    vocabulary = ["budget", "utilisation", "reconcil", "audited", "allocation", "spend"]
    required_scheme = ["figure_status", "reconciliation_due", "action_permitted"]

    def generate(self, item):
        provisional = item.figure_status != "final"
        return SpecialistOutput(
            item.kpi_id, self.name,
            f"{item.name} is {item.value:.2f}% against {item.target:.2f}% on "
            f"{'PROVISIONAL, unreconciled' if provisional else 'audited'} figures.",
            [{"title": ("Defer any reallocation until the books close" if provisional
                        else "Reallocate the underspend to the research seed fund"),
              "owner": "Finance Office", "timeline": ("After the August book close"
                                                      if provisional else "This quarter"),
              "risks": (["Underspend becomes harder to redeploy later in the year.",
                         "The Council may read deferral as inaction."] if provisional
                        else ["Reallocation is hard to reverse mid-year."]),
              "trade_off": ("Decision speed against acting on a number that may move."
                            if provisional else "Flexibility against commitment."),
              "measure_of_success": f"Utilisation ≥ {item.target:.2f}% on audited "
                                    f"figures at year end"}],
            {"figure_status": item.figure_status,
             "reconciliation_due": "August book close" if provisional else "complete",
             "action_permitted": not provisional})

    def domain_rules(self, out):
        v = []
        if out.scheme_fields.get("figure_status") != "final" \
                and out.scheme_fields.get("action_permitted"):
            v.append("finance outputs may not permit action on an unreconciled figure")
        if out.scheme_fields.get("figure_status") != "final" \
                and "provisional" not in out.headline.lower():
            v.append("a provisional finance figure must be labelled in the headline")
        return v


# ==========================================================================
# LAB 13 — work items
# ==========================================================================

def work_items() -> List[WorkItem]:
    items = []
    for kpi_id, d in KPI_DEFINITIONS.items():
        c = compute_kpi(kpi_id, ROWS)
        t = compare_to_target(kpi_id, c["value"])
        if t["status"] == "on target":
            continue
        ev = [{"dept_code": e["dept_code"], "dept_value": e["dept_value"],
               "denominator": e.get("denominator")} for e in c["evidence"]]
        items.append(WorkItem(kpi_id, c["name"], d["domain"], c["value"], c["unit"],
                              t["target"], t["status"], c["figure_status"], ev))
    return items


ITEMS = work_items()

# ==========================================================================
# LAB 9 — the candidate set used to demonstrate grounding
# ==========================================================================

CANDIDATES = [
    Candidate("C1", "finding",
              "Placement percentage for 2025-26 is below the strategic-plan target.",
              {"kpi_id": "KPI-P1"}),
    Candidate("C2", "finding",
              "Civil Engineering placed 62 of its 118 eligible students.",
              {"dept": "CIVIL", "field": "placed_students"}),
    Candidate("C3", "finding",
              "Citations per faculty sit below the NIRF cohort peer median.",
              {"benchmark_for": "KPI-R2"}),
    Candidate("C4", "context",
              "The Council already approved a recruiter-outreach budget in 2023-24.",
              {"archive_id": "BRIEF-2023-24-Q4"}),
    Candidate("C5", "finding",
              "Budget utilisation is below target on provisional figures.",
              {"kpi_id": "KPI-F1"}),
    # ---- the three that must be rejected ---------------------------------
    Candidate("C6", "context",
              "A national hiring slowdown is the main reason placement fell short.",
              {}),
    Candidate("C7", "finding",
              "Student satisfaction with placement support is around 68%.",
              {"kpi_id": "KPI-S1"}),
    Candidate("C8", "finding",
              "Civil Engineering's alumni donation total was INR 4.2 lakh.",
              {"dept": "CIVIL", "field": "alumni_donations"}),
]


# ==========================================================================
# LAB 10 — the fault injectors used by the failure-injection campaign
# ==========================================================================

def inject_missing_source(b):
    b["kpis"][3]["source_system"] = ""
    return "KPI-R2 lost its source_system"

def inject_dropped_assumptions(b):
    b["assumptions"] = b["assumptions"][:1]
    return "the assumptions block was truncated to 1 entry"

def inject_option_without_risks(b):
    b["options"][1]["risks"] = []
    b["options"][1]["trade_off"] = ""
    return "the second option lost its risks and trade-off"

def inject_unlabelled_provisional(b):
    for k in b["kpis"]:
        if k["figure_status"] != "final":
            k["caveat"] = ""
    return "the provisional Finance figure lost its caveat"

def inject_rounding_cover_up(b):
    for k in b["kpis"]:
        if k["kpi_id"] == "KPI-A1":
            k["value_shown"] = f"{k['value']:.0f}"     # 91.85 -> "92"
    return "KPI-A1 was displayed rounded to 92, hiding a missed 92.00 target"
