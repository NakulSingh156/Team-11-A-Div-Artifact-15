"""edss_core — shared foundation for the Worklet 15 lab notebooks.

Worklet 15 · Executive Decision Support System · Agentic AI (26ECAC401)

This is the Lab 1 + Lab 2 foundation, unchanged: the institutional data, the
typed tool contracts, the single ToolRouter choke point, the Connector, and the
validation gate. Labs 3-8 build on top of it rather than restating it, so every
notebook works against the same tools and the same numbers.

Written to disk by the first code cell of each lab notebook, so each notebook
runs standalone in Colab with no setup.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# 1 · Institutional data (identical to Lab 2, Cell 3)
# =============================================================================

REPORTING_PERIOD = "academic year 2025-26"

DEPARTMENT_REPORTS_CSV = """dept_code,dept_name,category,students_appeared,students_passed,co_po_attainment,sanctioned_faculty,publications,citations,grants_lakh,eligible_students,placed_students,total_package_lpa,interns_completed,budget_allocated_lakh,budget_spent_lakh,figure_status
CSE,Computer Science & Engineering,circuit,240,231,2.71,34,58,402,96.5,228,212,2247.2,205,420,393,final
ECE,Electronics & Communication,circuit,180,168,2.58,26,34,221,41.0,172,143,1058.2,149,310,276,final
ISE,Information Science & Engineering,circuit,120,116,2.66,18,21,140,22.5,114,103,947.6,96,240,221,final
EEE,Electrical & Electronics,circuit,120,109,2.41,17,16,88,18.0,116,86,524.6,84,210,181,final
MECH,Mechanical Engineering,core,180,158,2.33,24,19,95,27.5,174,111,599.4,102,300,247,final
CIVIL,Civil Engineering,core,120,101,2.19,16,11,47,12.0,118,62,285.2,61,190,149,final
CHEM,Chemical Engineering,core,60,54,2.28,11,14,76,15.5,58,33,168.3,34,140,118,final
BT,Biotechnology,core,60,55,2.35,10,12,63,9.5,57,29,142.1,30,130,102,final
"""

NUMERIC_COLUMNS = {
    "students_appeared": int, "students_passed": int, "co_po_attainment": float,
    "sanctioned_faculty": int, "publications": int, "citations": int,
    "grants_lakh": float, "eligible_students": int, "placed_students": int,
    "total_package_lpa": float, "interns_completed": int,
    "budget_allocated_lakh": float, "budget_spent_lakh": float,
}

KPI_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "KPI-A1": {"name": "Institution pass percentage", "domain": "Academic",
               "method": "ratio", "numerator": "students_passed",
               "denominator": "students_appeared", "scale": 100, "unit": "%",
               "formula": "sum(students_passed) / sum(students_appeared) x 100",
               "target": 92.0, "target_source": "Strategic Plan 2024-27",
               "direction": "higher_is_better", "source_system": "Academic ERP"},
    "KPI-A2": {"name": "CO/PO attainment index", "domain": "Academic",
               "method": "weighted_mean", "value_field": "co_po_attainment",
               "weight_field": "students_appeared", "unit": "index 0-3",
               "formula": "sum(co_po_attainment x students_appeared) / sum(students_appeared)",
               "target": 2.50, "target_source": "NAAC criterion 2",
               "direction": "higher_is_better", "source_system": "Academic ERP (OBE module)"},
    "KPI-R1": {"name": "Publications per faculty", "domain": "Research",
               "method": "ratio", "numerator": "publications",
               "denominator": "sanctioned_faculty", "scale": 1, "unit": "per faculty",
               "formula": "sum(publications) / sum(sanctioned_faculty)",
               "target": 1.50, "target_source": "NIRF Research & Professional Practice",
               "direction": "higher_is_better", "source_system": "Research repository"},
    "KPI-R2": {"name": "Citations per faculty", "domain": "Research",
               "method": "ratio", "numerator": "citations",
               "denominator": "sanctioned_faculty", "scale": 1, "unit": "per faculty",
               "formula": "sum(citations) / sum(sanctioned_faculty)",
               "target": 9.00, "target_source": "NIRF Research & Professional Practice",
               "direction": "higher_is_better", "source_system": "Research repository"},
    "KPI-R3": {"name": "Grants sanctioned", "domain": "Research",
               "method": "sum", "value_field": "grants_lakh", "unit": "INR lakh",
               "formula": "sum(grants_lakh)",
               "target": 300.0, "target_source": "Strategic Plan 2024-27",
               "direction": "higher_is_better", "source_system": "Research repository"},
    "KPI-P1": {"name": "Placement percentage", "domain": "Placement",
               "method": "ratio", "numerator": "placed_students",
               "denominator": "eligible_students", "scale": 100, "unit": "%",
               "formula": "sum(placed_students) / sum(eligible_students) x 100",
               "target": 80.0, "target_source": "Strategic Plan 2024-27",
               "direction": "higher_is_better", "source_system": "Placement Cell tracker"},
    "KPI-P2": {"name": "Average package", "domain": "Placement",
               "method": "ratio", "numerator": "total_package_lpa",
               "denominator": "placed_students", "scale": 1, "unit": "LPA",
               "formula": "sum(total_package_lpa) / sum(placed_students)",
               "target": 8.00, "target_source": "Strategic Plan 2024-27",
               "direction": "higher_is_better", "source_system": "Placement Cell tracker"},
    "KPI-P3": {"name": "Internship completion", "domain": "Placement",
               "method": "ratio", "numerator": "interns_completed",
               "denominator": "eligible_students", "scale": 100, "unit": "%",
               "formula": "sum(interns_completed) / sum(eligible_students) x 100",
               "target": 85.0, "target_source": "Strategic Plan 2024-27",
               "direction": "higher_is_better", "source_system": "Placement Cell tracker"},
    "KPI-F1": {"name": "Budget utilisation", "domain": "Finance",
               "method": "ratio", "numerator": "budget_spent_lakh",
               "denominator": "budget_allocated_lakh", "scale": 100, "unit": "%",
               "formula": "sum(budget_spent_lakh) / sum(budget_allocated_lakh) x 100",
               "target": 90.0, "target_source": "Strategic Plan 2024-27",
               "direction": "higher_is_better", "source_system": "Finance & Accounts ledger",
               "figure_status": "provisional",
               "caveat": "Q3-Q4 of 2025-26 are unreconciled; the Finance Office closes "
                         "books in August."},
}

BENCHMARK_API_DB = {
    "KPI-R1": {"peer_median": 1.82, "cohort": "NIRF Engineering rank band 51-100", "year": "2025"},
    "KPI-R2": {"peer_median": 11.40, "cohort": "NIRF Engineering rank band 51-100", "year": "2025"},
    "KPI-P1": {"peer_median": 78.60, "cohort": "NIRF Engineering rank band 51-100", "year": "2025"},
}

DOMAINS = ["Academic", "Research", "Placement", "Finance"]
DOMAIN_KPIS = {d: [k for k, v in KPI_DEFINITIONS.items() if v["domain"] == d] for d in DOMAINS}

# Registrar-authorised read access, per Gate 1 of the hybrid execution methodology.
ACCESS_REGISTER = {
    "Academic":  {"source_system": "Academic ERP — examination & OBE records",
                  "read_access": "granted by Registrar on 2026-06-01", "figure_status": "final",
                  "periods": ["2023-24", "2024-25", "2025-26"],
                  "metrics": ["pass percentage", "CO/PO attainment", "curriculum compliance"]},
    "Research":  {"source_system": "Research & Publications repository (Scopus-synced)",
                  "read_access": "granted by Registrar on 2026-06-01", "figure_status": "final",
                  "periods": ["2023-24", "2024-25", "2025-26"],
                  "metrics": ["publications", "citations", "grants sanctioned"]},
    "Placement": {"source_system": "Placement Cell tracker",
                  "read_access": "granted by Registrar on 2026-06-04", "figure_status": "final",
                  "periods": ["2023-24", "2024-25", "2025-26"],
                  "metrics": ["placement percentage", "average package",
                              "internship completion"],
                  "caveat": "3 provisional offers are excluded until the Placement Cell "
                            "verifies them."},
    "Finance":   {"source_system": "Finance & Accounts ledger",
                  "read_access": "granted by Registrar on 2026-06-07",
                  "figure_status": "provisional",
                  # 2025-26 is deliberately absent: the books are not closed, and the
                  # Lab 1 planner must notice that rather than plan over it.
                  "periods": ["2023-24", "2024-25"],
                  "metrics": ["budget utilisation", "revenue", "grant funds"],
                  "caveat": "Q3-Q4 of 2025-26 are unreconciled; the Finance Office closes "
                            "books in August."},
}


# =============================================================================
# 2 · Tool contracts (identical to Lab 2, Cell 4)
# =============================================================================

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "read_department_reports": {
        "description": "Read per-department metric rows for one reporting period.",
        "parameters": {"type": "object", "properties": {
            "period": {"type": "string"},
            "departments": {"type": "array", "items": {"type": "string"}},
            "category": {"type": "string", "enum": ["circuit", "core"]}},
            "required": ["period"]},
        "returns": "{rows, row_count, source_system} | {error}"},
    "read_kpi_definitions": {
        "description": "Read approved KPI definitions: formula, unit, target, authority.",
        "parameters": {"type": "object", "properties": {
            "kpi_ids": {"type": "array", "items": {"type": "string"}}}, "required": []},
        "returns": "{definitions, count} | {error}"},
    "read_external_benchmark": {
        "description": "Published peer median for a KPI. Coverage is partial.",
        "parameters": {"type": "object", "properties": {"kpi_id": {"type": "string"}},
                       "required": ["kpi_id"]},
        "returns": "{kpi_id, peer_median, cohort, year} | {error}"},
    "filter_rows": {
        "description": "Filter department rows by an exact field value; errors on empty.",
        "parameters": {"type": "object", "properties": {
            "rows": {"type": "array", "items": {"type": "object"}},
            "field": {"type": "string"}, "value": {"type": "string"}},
            "required": ["rows", "field", "value"]},
        "returns": "{rows, row_count, filter} | {error}"},
    "compute_kpi": {
        "description": "Compute one approved KPI over department rows, with evidence.",
        "parameters": {"type": "object", "properties": {
            "kpi_id": {"type": "string"},
            "rows": {"type": "array", "items": {"type": "object"}}},
            "required": ["kpi_id", "rows"]},
        "returns": "{kpi_id, value, unit, formula, evidence, source_system} | {error}"},
    "compare_to_target": {
        "description": "Compare a KPI value to its approved target; flags rounding risk.",
        "parameters": {"type": "object", "properties": {
            "kpi_id": {"type": "string"}, "value": {"type": "number"}},
            "required": ["kpi_id", "value"]},
        "returns": "{value, target, variance, status, rounding_warning} | {error}"},
    "compute_variance": {
        "description": "Difference between a KPI value and any reference figure.",
        "parameters": {"type": "object", "properties": {
            "value": {"type": "number"}, "reference": {"type": "number"},
            "label": {"type": "string"}}, "required": ["value", "reference", "label"]},
        "returns": "{variance, abs_variance, pct_of_reference} | {error}"},
    "draft_notification": {
        "description": "DRAFT a leadership notification. Never sends. Sources required.",
        "parameters": {"type": "object", "properties": {
            "audience": {"type": "string"}, "subject": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "object"}}},
            "required": ["audience", "subject", "findings"]},
        "returns": "{status: 'DRAFT - NOT SENT', body, requires_approval_from} | {error}"},
}


def _typed_rows(text: str) -> List[Dict[str, Any]]:
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        row = dict(raw)
        for col, caster in NUMERIC_COLUMNS.items():
            if col in row:
                try:
                    row[col] = caster(row[col])
                except (TypeError, ValueError):
                    return [{"error": f"column '{col}' is not {caster.__name__}"}]
        rows.append(row)
    return rows


# Optional demo latency, so the parallel/sequential distinction in the run
# timeline is visible. Off by default; never affects any computed figure.
SOURCE_LATENCY_SECONDS = 0.0


def read_department_reports(period: str, departments=None, category=None) -> Dict[str, Any]:
    if period != REPORTING_PERIOD:
        return {"error": f"no department report export for '{period}'; the only loaded "
                         f"period is '{REPORTING_PERIOD}'"}
    if SOURCE_LATENCY_SECONDS:
        time.sleep(SOURCE_LATENCY_SECONDS)
    rows = _typed_rows(DEPARTMENT_REPORTS_CSV)
    if rows and "error" in rows[0]:
        return {"error": rows[0]["error"]}
    if departments:
        known = {r["dept_code"] for r in rows}
        unknown = [d for d in departments if d not in known]
        if unknown:
            return {"error": f"unknown department code(s): {unknown}; known: {sorted(known)}"}
        rows = [r for r in rows if r["dept_code"] in departments]
    if category:
        rows = [r for r in rows if r["category"] == category]
        if not rows:
            return {"error": f"no departments in category '{category}'"}
    if not rows:
        return {"error": "empty department report export"}
    return {"rows": rows, "row_count": len(rows), "period": period,
            "source_system": "Department reports export (Registrar-authorised read)"}


def read_kpi_definitions(kpi_ids=None) -> Dict[str, Any]:
    if kpi_ids:
        unknown = [k for k in kpi_ids if k not in KPI_DEFINITIONS]
        if unknown:
            return {"error": f"unknown KPI id(s): {unknown}"}
        defs = {k: KPI_DEFINITIONS[k] for k in kpi_ids}
    else:
        defs = dict(KPI_DEFINITIONS)
    return {"definitions": defs, "count": len(defs),
            "source_system": "Institutional KPI register (approved definitions)"}


def read_external_benchmark(kpi_id: str) -> Dict[str, Any]:
    if kpi_id not in KPI_DEFINITIONS:
        return {"error": f"unknown KPI id '{kpi_id}'"}
    record = BENCHMARK_API_DB.get(kpi_id)
    if record is None:
        return {"error": f"no published external benchmark for {kpi_id} "
                         f"({KPI_DEFINITIONS[kpi_id]['name']}) in the benchmark API"}
    return {"kpi_id": kpi_id, **record, "source_system": "External benchmark API (NIRF cohort)"}


def filter_rows(rows, field: str, value: str) -> Dict[str, Any]:
    if not rows:
        return {"error": "filter_rows received an empty row set"}
    if field not in rows[0]:
        return {"error": f"unknown field '{field}'; available: {sorted(rows[0])}"}
    subset = [r for r in rows if str(r[field]) == str(value)]
    if not subset:
        return {"error": f"filter {field}={value!r} matched 0 of {len(rows)} rows — "
                         f"refusing to return an empty subset"}
    return {"rows": subset, "row_count": len(subset), "filter": f"{field}=={value}",
            "filtered_from": len(rows)}


def compute_kpi(kpi_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generic: the arithmetic comes from the KPI definition, not from this code."""
    if kpi_id not in KPI_DEFINITIONS:
        return {"error": f"unknown KPI id '{kpi_id}'"}
    if not rows:
        return {"error": f"cannot compute {kpi_id} over an empty row set"}
    d = KPI_DEFINITIONS[kpi_id]
    method, evidence = d["method"], []
    try:
        if method == "ratio":
            num_f, den_f, scale = d["numerator"], d["denominator"], d["scale"]
            num = sum(r[num_f] for r in rows)
            den = sum(r[den_f] for r in rows)
            if den == 0:
                return {"error": f"{kpi_id}: denominator sum({den_f}) is zero"}
            value = num / den * scale
            inputs = {f"sum({num_f})": round(num, 4), f"sum({den_f})": round(den, 4)}
            for r in rows:
                dv = (r[num_f] / r[den_f] * scale) if r[den_f] else None
                evidence.append({"dept_code": r["dept_code"], "dept_name": r["dept_name"],
                                 "numerator": r[num_f], "denominator": r[den_f],
                                 "numerator_field": num_f, "denominator_field": den_f,
                                 "dept_value": round(dv, 2) if dv is not None else None,
                                 "share_of_denominator_pct": round(r[den_f] / den * 100, 2)})
        elif method == "weighted_mean":
            vf, wf = d["value_field"], d["weight_field"]
            wsum = sum(r[wf] for r in rows)
            if wsum == 0:
                return {"error": f"{kpi_id}: total weight sum({wf}) is zero"}
            value = sum(r[vf] * r[wf] for r in rows) / wsum
            inputs = {f"sum({vf} x {wf})": round(sum(r[vf] * r[wf] for r in rows), 4),
                      f"sum({wf})": wsum}
            for r in rows:
                evidence.append({"dept_code": r["dept_code"], "dept_name": r["dept_name"],
                                 "numerator": r[vf], "denominator": r[wf],
                                 "numerator_field": vf, "denominator_field": wf,
                                 "dept_value": r[vf],
                                 "share_of_denominator_pct": round(r[wf] / wsum * 100, 2)})
        elif method == "sum":
            vf = d["value_field"]
            value = sum(r[vf] for r in rows)
            inputs = {f"sum({vf})": round(value, 4)}
            for r in rows:
                evidence.append({"dept_code": r["dept_code"], "dept_name": r["dept_name"],
                                 "numerator": r[vf], "denominator": None,
                                 "numerator_field": vf, "denominator_field": None,
                                 "dept_value": r[vf],
                                 "share_of_denominator_pct": round(r[vf] / value * 100, 2)
                                 if value else None})
        else:
            return {"error": f"unsupported KPI method '{method}' for {kpi_id}"}
    except KeyError as missing:
        return {"error": f"{kpi_id}: department rows are missing column {missing}"}

    statuses = {r.get("figure_status", "final") for r in rows}
    figure_status = d.get("figure_status") or ("final" if statuses == {"final"} else "mixed")
    out = {"kpi_id": kpi_id, "name": d["name"], "domain": d["domain"],
           "value": round(value, 4), "unit": d["unit"], "formula": d["formula"],
           "method": method, "n_departments": len(rows),
           "departments": [r["dept_code"] for r in rows],
           "inputs_used": inputs, "evidence": evidence,
           "source_system": d["source_system"], "figure_status": figure_status}
    if d.get("caveat"):
        out["caveat"] = d["caveat"]
    return out


def compare_to_target(kpi_id: str, value: float) -> Dict[str, Any]:
    if kpi_id not in KPI_DEFINITIONS:
        return {"error": f"unknown KPI id '{kpi_id}'"}
    d = KPI_DEFINITIONS[kpi_id]
    target = d["target"]
    variance = value - target
    pct_of_target = value / target * 100 if target else None
    gap_pct = abs(variance) / target * 100 if target else 0
    status = "on target" if variance >= 0 else ("at risk" if gap_pct <= 2.0 else "below target")
    rounding_warning = None
    if variance < 0:
        for places in (0, 1):
            if round(value, places) >= target:
                rounding_warning = (f"{value:.4g} rounds to {round(value, places)} at "
                                    f"{places} decimal place(s), which would read as meeting "
                                    f"the target of {target}. Report the unrounded figure.")
                break
    return {"kpi_id": kpi_id, "name": d["name"], "value": round(value, 4), "target": target,
            "target_source": d["target_source"], "unit": d["unit"],
            "variance": round(variance, 4),
            "pct_of_target": round(pct_of_target, 2) if pct_of_target else None,
            "status": status, "rounding_warning": rounding_warning}


def department_breakdown(kpi_id: str, evidence: List[Dict[str, Any]]
                         ) -> List[Dict[str, Any]]:
    """Per-department rows for one KPI, each judged by compare_to_target.

    Lab 11's builder and the capstone builder both need this, and a drill-down
    where "below target" meant something different from the institution row
    would be worse than no drill-down at all — so the comparison is done here,
    once, by the same function that grades the institution figure.

    Sorted worst first: a reader opening a breakdown wants the problem, not
    the alphabet.
    """
    out: List[Dict[str, Any]] = []
    for e in evidence:
        dv = e.get("dept_value")
        if dv is None:
            out.append({"dept": e["dept_code"], "dept_name": e.get("dept_name", ""),
                        "value": None, "variance": None, "status": "no data"})
            continue
        t = compare_to_target(kpi_id, dv)
        out.append({"dept": e["dept_code"], "dept_name": e.get("dept_name", ""),
                    "value": dv, "variance": t["variance"], "status": t["status"]})
    out.sort(key=lambda d: (d["variance"] is None, d["variance"]))
    return out


def compute_variance(value: float, reference: float, label: str) -> Dict[str, Any]:
    if reference == 0:
        return {"error": f"cannot compute variance against a zero reference ({label})"}
    variance = value - reference
    return {"value": round(value, 4), "reference": round(reference, 4), "label": label,
            "variance": round(variance, 4), "abs_variance": round(abs(variance), 4),
            "pct_of_reference": round(value / reference * 100, 2)}


def draft_notification(audience: str, subject: str, findings: List[Dict[str, Any]]):
    if not findings:
        return {"error": "refusing to draft a notification with no findings"}
    unsourced = [f for f in findings if not f.get("source")]
    if unsourced:
        return {"error": f"{len(unsourced)} finding(s) carry no source; every figure in a "
                         f"leadership notification must cite where it came from"}
    body = "\n".join(f"  {i}. {f['statement']}\n     source: {f['source']}"
                     for i, f in enumerate(findings, 1))
    return {"status": "DRAFT - NOT SENT", "audience": audience, "subject": subject,
            "body": body, "findings_cited": len(findings),
            "requires_approval_from": "Principal / Registrar (Chapter 15 human gate)",
            "note": "This tool cannot send. Circulation happens only after human approval."}


TOOLS = {
    "read_department_reports": read_department_reports,
    "read_kpi_definitions": read_kpi_definitions,
    "read_external_benchmark": read_external_benchmark,
    "filter_rows": filter_rows,
    "compute_kpi": compute_kpi,
    "compare_to_target": compare_to_target,
    "compute_variance": compute_variance,
    "draft_notification": draft_notification,
}


# =============================================================================
# 3 · Router, connector, validation gate (Lab 2, Cells 5-6)
# =============================================================================

class ToolContractError(Exception):
    """Raised before a call when arguments do not satisfy the tool schema."""


class ToolError(Exception):
    """Raised after a call when the tool returned an explicit error."""


_JSON_TYPES = {"string": str, "number": (int, float), "integer": int,
               "boolean": bool, "array": list, "object": dict}


def _summarise(obj, _depth=0):
    if isinstance(obj, list):
        if len(obj) > 3 and all(isinstance(x, dict) for x in obj):
            return f"[{len(obj)} rows: {', '.join(str(x.get('dept_code', '?')) for x in obj)}]"
        return [_summarise(x, _depth + 1) for x in obj]
    if isinstance(obj, dict):
        return {k: _summarise(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, str) and len(obj) > 160:
        return obj[:157] + "..."
    return obj


class ToolRouter:
    """The single choke point. Validates, executes, logs, raises on error."""

    def __init__(self, agent: str = "Coordinator"):
        self.agent = agent
        self.trace: List[Dict[str, Any]] = []
        self.raw_outputs: List[Any] = []

    def validate_input(self, tool: str, kwargs: Dict[str, Any]) -> None:
        if tool not in TOOL_SCHEMAS:
            raise ToolContractError(f"no such tool: '{tool}'")
        schema = TOOL_SCHEMAS[tool]["parameters"]
        props, required = schema["properties"], schema.get("required", [])
        for name in required:
            if name not in kwargs:
                raise ToolContractError(f"{tool}: missing required argument '{name}'")
        for name, val in kwargs.items():
            if name not in props:
                raise ToolContractError(
                    f"{tool}: unknown argument '{name}'; accepts {sorted(props)}")
            spec = props[name]
            expected = _JSON_TYPES.get(spec["type"])
            if expected and not isinstance(val, expected):
                raise ToolContractError(
                    f"{tool}.{name}: expected {spec['type']}, got {type(val).__name__}")
            if spec.get("enum") and val not in spec["enum"]:
                raise ToolContractError(f"{tool}.{name}: {val!r} not in {spec['enum']}")

    def call(self, tool: str, reason: str, **kwargs) -> Dict[str, Any]:
        self.validate_input(tool, kwargs)
        started = time.perf_counter()
        result = TOOLS[tool](**kwargs)
        entry = {"step": len(self.trace) + 1, "agent": self.agent, "tool": tool,
                 "reason": reason, "input": _summarise(kwargs), "output": _summarise(result),
                 "ok": "error" not in result,
                 "ms": round((time.perf_counter() - started) * 1000, 2),
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.trace.append(entry)
        self.raw_outputs.append(result)
        if "error" in result:
            raise ToolError(f"{tool} failed: {result['error']}")
        return result

    def try_call(self, tool: str, reason: str, **kwargs) -> Dict[str, Any]:
        try:
            return self.call(tool, reason, **kwargs)
        except ToolError:
            return dict(TOOLS[tool](**kwargs))


class Connector:
    """One governed surface over every source. No agent touches a source directly."""

    RESOURCES = {
        "department reports":              "read_department_reports",
        "institutional KPIs & dashboards": "read_kpi_definitions",
        "external benchmarks":             "read_external_benchmark",
    }

    def __init__(self, router: ToolRouter):
        self.router = router

    def read(self, resource: str, reason: str, required: bool = True, **params):
        if resource not in self.RESOURCES:
            raise ToolContractError(f"connector exposes no resource '{resource}'; "
                                    f"available: {sorted(self.RESOURCES)}")
        caller = self.router.call if required else self.router.try_call
        return caller(self.RESOURCES[resource], reason, **params)


class Validated:
    def __init__(self, checks: List[tuple], subject: str):
        self.checks, self.subject = checks, subject
        self.failing = [name for name, ok, _ in checks if not ok]
        self.valid = not self.failing

    def __repr__(self):
        return f"<Validated {self.subject}: {'VALID' if self.valid else self.failing}>"


def validate_kpi_result(computed: Dict[str, Any],
                        compared: Optional[Dict[str, Any]] = None) -> Validated:
    ev = computed.get("evidence", [])
    checks = [
        ("value is a finite number",
         isinstance(computed.get("value"), (int, float)) and math.isfinite(computed["value"]),
         f"value={computed.get('value')}"),
        ("the formula used is recorded", bool(computed.get("formula")),
         computed.get("formula", "")),
        ("the figure cites its source system", bool(computed.get("source_system")),
         computed.get("source_system", "")),
        ("raw inputs are recorded", bool(computed.get("inputs_used")),
         str(computed.get("inputs_used", ""))),
        ("every department in the evidence is identified",
         bool(ev) and all(e.get("dept_code") for e in ev), f"{len(ev)} evidence rows"),
        ("evidence covers exactly the departments computed over",
         len(ev) == computed.get("n_departments"), f"{len(ev)} rows"),
        ("provisional figures carry a caveat",
         computed.get("figure_status") == "final" or bool(computed.get("caveat")),
         f"figure_status={computed.get('figure_status')}"),
    ]
    if compared is not None:
        checks.append(("the target names the authority that set it",
                       bool(compared.get("target_source")), compared.get("target_source", "")))
    return Validated(checks, computed.get("kpi_id", "?"))


# =============================================================================
