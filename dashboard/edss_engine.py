"""Executive Decision Support System — Worklet 15 engine.

This module is the Lab 1 + Lab 2 engine, lifted out of the notebooks unchanged
in substance, plus the pieces Chapter 15 needs for a working dashboard:

    Labs 1-2 (already graded)      This module adds
    ------------------------      ---------------------------------------
    typed tools + contracts       Domain agents (A-D), run in parallel
    ToolRouter choke point        KPI Agent (E) synthesis
    Connector over 3 sources      Report Generation Agent (F)
    validation gate               Brief validation (the 4 Chapter 15 checks)
    coordinator planner loop      Human approval gate + versioning + audit

Nothing here fabricates a figure. Every number in the dashboard comes out of
compute_kpi()/compare_to_target() on the department rows, exactly as in Lab 2.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
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
# 4 · Agents A-F (Chapter 15 roster)
# =============================================================================

@dataclass
class KPIResult:
    kpi_id: str
    computed: Dict[str, Any]
    compared: Dict[str, Any]
    validation: Validated
    benchmark: Optional[Dict[str, Any]] = None

    @property
    def name(self) -> str:
        return self.computed["name"]

    @property
    def domain(self) -> str:
        return self.computed["domain"]

    @property
    def value(self) -> float:
        return self.computed["value"]

    @property
    def status(self) -> str:
        return self.compared["status"]

    @property
    def provisional(self) -> bool:
        return self.computed.get("figure_status") != "final"


class DomainAgent:
    """Groups A-D. One domain, its own router, so its trace is attributable."""

    def __init__(self, domain: str):
        self.domain = domain
        self.kpi_ids = DOMAIN_KPIS[domain]
        self.router = ToolRouter(agent=f"{domain} Agent")
        self.connector = Connector(self.router)
        self.elapsed_ms = 0.0

    def run(self, period: str = REPORTING_PERIOD) -> List[KPIResult]:
        started = time.perf_counter()
        rows = self.connector.read(
            "department reports",
            reason=f"{self.domain} Agent aggregates its metrics across departments",
            period=period)["rows"]
        results = []
        for kpi_id in self.kpi_ids:
            self.connector.read(
                "institutional KPIs & dashboards",
                reason=f"{kpi_id}: formula and target must come from the approved register",
                kpi_ids=[kpi_id])
            computed = self.router.call(
                "compute_kpi", reason=f"{kpi_id}: apply the registered formula",
                kpi_id=kpi_id, rows=rows)
            compared = self.router.call(
                "compare_to_target", reason=f"{kpi_id}: variance against the approved target",
                kpi_id=kpi_id, value=computed["value"])
            validation = validate_kpi_result(computed, compared)
            if not validation.valid:
                raise ToolError(f"validation gate failed for {kpi_id}: {validation.failing}")
            bench = self.connector.read(
                "external benchmarks",
                reason=f"{kpi_id}: peer benchmark if one is published",
                required=False, kpi_id=kpi_id)
            results.append(KPIResult(kpi_id, computed, compared, validation,
                                     None if "error" in bench else bench))
        self.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return results


class KPIAgent:
    """Group E. Synthesises the four domain views into the institution KPI set."""

    def __init__(self):
        self.router = ToolRouter(agent="KPI Agent")

    def synthesise(self, domain_results: Dict[str, List[KPIResult]]) -> List[KPIResult]:
        merged: List[KPIResult] = []
        for domain in DOMAINS:
            merged.extend(domain_results.get(domain, []))
        for r in merged:                       # peer gaps are arithmetic -> a tool
            if r.benchmark:
                gap = self.router.call(
                    "compute_variance",
                    reason=f"{r.kpi_id}: gap to the published peer median",
                    value=r.value, reference=r.benchmark["peer_median"],
                    label=f"{r.name} vs {r.benchmark['cohort']}")
                r.benchmark = {**r.benchmark, "gap": gap}
        return merged


# --- Option playbook: drafted courses of action, never taken autonomously ----
# Each option carries owner, timeline, indicative cost, risks and the trade-off
# it forces, because Chapter 15's validation gate requires exactly that.
OPTION_PLAYBOOK: Dict[str, List[Dict[str, Any]]] = {
    "KPI-A1": [
        {"title": "Targeted remedial coaching in the lowest-performing departments",
         "detail": "Run structured remedial batches in the departments furthest below the "
                   "institution figure, with weekly progress tests.",
         "owner": "Dean (Academics)", "timeline": "1 semester",
         "indicative_cost": "INR 6 lakh",
         "risks": ["Diverts faculty hours from lab supervision.",
                   "Gains appear only in the next examination cycle, not this one."],
         "trade_off": "Staff time now against a lagging indicator later."},
        {"title": "Mid-semester diagnostic with an early-warning list",
         "detail": "Add a compulsory mid-semester diagnostic and route at-risk students to "
                   "mentors before the end-semester examination.",
         "owner": "Controller of Examinations", "timeline": "8 weeks",
         "indicative_cost": "INR 2 lakh",
         "risks": ["Adds assessment load on an already full calendar.",
                   "Identifies students late if the diagnostic slips past week 8."],
         "trade_off": "More assessment overhead for earlier intervention."},
        {"title": "Re-baseline the target with the Governing Council",
         "detail": "Take the variance to the Council and agree either a revised target or a "
                   "multi-year path to the existing one.",
         "owner": "Registrar", "timeline": "Next planning cycle",
         "indicative_cost": "Nil",
         "risks": ["Reads externally as lowering the bar.",
                   "Affects NAAC narrative if not documented with a rationale."],
         "trade_off": "Realism against stated ambition."},
    ],
    "KPI-A2": [
        {"title": "OBE re-training for course coordinators",
         "detail": "Re-train coordinators in departments below the index on CO/PO mapping and "
                   "attainment computation.",
         "owner": "Dean (Academics) / IQAC", "timeline": "1 semester",
         "indicative_cost": "INR 4 lakh",
         "risks": ["A rise may reflect better mapping rather than better learning.",
                   "Requires coordinator release time."],
         "trade_off": "Measurement quality against measured outcomes."},
        {"title": "Standardise assessment rubrics institution-wide",
         "detail": "Publish one rubric template so attainment is comparable across departments.",
         "owner": "IQAC", "timeline": "2 semesters", "indicative_cost": "INR 3 lakh",
         "risks": ["Departments with mature rubrics may see attainment fall.",
                   "Comparability gains are invisible to students."],
         "trade_off": "Short-term optics against defensible NAAC evidence."},
    ],
    "KPI-R1": [
        {"title": "Seed-grant scheme for research-active faculty",
         "detail": "Competitive internal seed grants with a publication deliverable.",
         "owner": "Dean (R&D)", "timeline": "2 semesters", "indicative_cost": "INR 25 lakh",
         "risks": ["Counting publications alone can reward low-quality venues.",
                   "Commits recurring budget before the finance position is reconciled."],
         "trade_off": "Output volume against output quality."},
        {"title": "Publication incentive restricted to indexed venues",
         "detail": "Pay the incentive only for Scopus/WoS-indexed venues, verified centrally.",
         "owner": "Dean (R&D)", "timeline": "1 year", "indicative_cost": "INR 12 lakh",
         "risks": ["Encourages splitting one result across several papers.",
                   "Excludes legitimate conference-led disciplines."],
         "trade_off": "Indexing rigour against disciplinary fairness."},
    ],
    "KPI-R2": [
        {"title": "Collaboration MoUs with the NIRF peer cohort",
         "detail": "Co-authorship agreements with institutions in the same rank band.",
         "owner": "Dean (R&D)", "timeline": "2 years", "indicative_cost": "INR 8 lakh",
         "risks": ["Citations lag publication by two to three years; this will not move the "
                   "current cycle.",
                   "Cross-institution credit must not be double-counted."],
         "trade_off": "A real long-term gain against no visible movement this review."},
        {"title": "Open-access publishing fund",
         "detail": "Central fund for article processing charges at reputable OA venues.",
         "owner": "Dean (R&D)", "timeline": "1 year", "indicative_cost": "INR 15 lakh",
         "risks": ["APCs are a recurring, rising cost.",
                   "Requires a vetted venue list to avoid predatory publishers."],
         "trade_off": "Visibility against sustained expenditure."},
    ],
    "KPI-R3": [
        {"title": "Proposal-writing cell with internal pre-review",
         "detail": "A small cell that edits and pre-reviews every external proposal before "
                   "submission.",
         "owner": "Dean (R&D)", "timeline": "2 semesters", "indicative_cost": "INR 10 lakh",
         "risks": ["Adds a step that can delay submission past a funding deadline.",
                   "Success depends on call timing outside institutional control."],
         "trade_off": "Submission speed against submission quality."},
        {"title": "Concentrate on three named funding calls",
         "detail": "Pick three calls matched to existing strengths and resource them properly "
                   "rather than spreading thin.",
         "owner": "Dean (R&D)", "timeline": "1 year", "indicative_cost": "Nil marginal",
         "risks": ["Concentration risk: missing all three leaves the year empty."],
         "trade_off": "Focus against portfolio diversification."},
    ],
    "KPI-P1": [
        {"title": "Core-branch placement drive",
         "detail": "A dedicated recruiter-outreach and training push for the core-branch "
                   "departments, which sit far below the circuit branches.",
         "owner": "Placement Officer", "timeline": "2 semesters",
         "indicative_cost": "INR 18 lakh",
         "risks": ["Core-branch hiring is market-driven; outreach may not convert.",
                   "Concentrating effort here may slow circuit-branch recruiter servicing."],
         "trade_off": "Equity across branches against total placement count."},
        {"title": "Structured pre-placement training from semester 5",
         "detail": "Aptitude, communication and technical interview preparation embedded in "
                   "the timetable from the fifth semester.",
         "owner": "Placement Officer / Dean (Academics)", "timeline": "1 year",
         "indicative_cost": "INR 14 lakh",
         "risks": ["Consumes timetable hours that departments currently use for electives.",
                   "Benefits the next graduating cohort, not the current one."],
         "trade_off": "Curriculum time against employability outcomes."},
        {"title": "Expand the recruiter base beyond the current pool",
         "detail": "Systematic outreach to firms that have never recruited here, with an "
                   "alumni-referral channel.",
         "owner": "Placement Officer", "timeline": "1 year", "indicative_cost": "INR 9 lakh",
         "risks": ["New recruiters typically offer lower packages, which pulls the average "
                   "package KPI down.",
                   "Outreach cost is incurred before any offer materialises."],
         "trade_off": "Placement percentage against average package."},
    ],
    "KPI-P2": [
        {"title": "Dream-offer policy for higher-band recruiters",
         "detail": "Allow students holding an offer to appear for a higher band, with a cap.",
         "owner": "Placement Officer", "timeline": "1 year", "indicative_cost": "Nil marginal",
         "risks": ["Students holding out can reduce the total number placed, working directly "
                   "against the placement-percentage KPI.",
                   "Requires recruiter consent to be workable."],
         "trade_off": "Average package against placement percentage — these two KPIs pull in "
                      "opposite directions and leadership must choose."},
    ],
    "KPI-P3": [
        {"title": "Credit-bearing mandatory summer internship",
         "detail": "Make the summer internship a graded credit so completion is tracked and "
                   "enforced.",
         "owner": "Dean (Academics) / Placement Officer", "timeline": "2 semesters",
         "indicative_cost": "INR 5 lakh",
         "risks": ["There may not be enough industry slots for every eligible student.",
                   "Students without a slot would fail a compulsory credit through no fault "
                   "of their own."],
         "trade_off": "Enforceability against fairness to students."},
        {"title": "Expand industry MoUs for guaranteed intern slots",
         "detail": "Negotiate a minimum intern intake into each MoU at renewal.",
         "owner": "Placement Officer", "timeline": "1 year", "indicative_cost": "INR 6 lakh",
         "risks": ["MoU commitments are rarely enforceable in practice.",
                   "Concentrates interns in a few firms."],
         "trade_off": "Volume certainty against experience diversity."},
    ],
    "KPI-F1": [
        {"title": "Defer any budget decision until the books close",
         "detail": "This figure is provisional and unreconciled. Chapter 15's Finance "
                   "guardrail forbids presenting it as an actual, so the drafted option is "
                   "explicitly to take no action on it in this cycle.",
         "owner": "Finance Office", "timeline": "After the August book close",
         "indicative_cost": "Nil",
         "risks": ["Underspend, if real, becomes harder to redeploy later in the year.",
                   "The Council may read deferral as inaction."],
         "trade_off": "Decision speed against acting on a number that may still move."},
    ],
}


class ReportGenerationAgent:
    """Group F. Compiles the leadership brief with drill-down evidence."""

    def __init__(self):
        self.router = ToolRouter(agent="Report Generation Agent")

    @staticmethod
    def _fmt(value: float, unit: str) -> str:
        if unit == "%":
            return f"{value:.2f}%"
        if unit == "LPA":
            return f"{value:.2f} LPA"
        if unit == "INR lakh":
            return f"INR {value:.2f} lakh"
        if unit.startswith("index"):
            return f"{value:.3f} (scale 0-3)"
        return f"{value:.2f} {unit}"

    def build_brief(self, kpi_results: List[KPIResult], period: str) -> Dict[str, Any]:
        off_target = [r for r in kpi_results if r.status != "on target"]
        below = [r for r in kpi_results if r.status == "below target"]
        provisional = [r for r in kpi_results if r.provisional]
        rounding = [r for r in kpi_results if r.compared.get("rounding_warning")]

        # --- executive summary: three decision-ready bullets, all grounded ---
        worst = sorted(below, key=lambda r: r.compared["variance"] / r.compared["target"])
        summary = [
            f"{len(off_target)} of {len(kpi_results)} institution KPIs are off target for "
            f"{period}; {len(below)} are below target and "
            f"{len(off_target) - len(below)} are at risk.",
        ]
        if worst:
            w = worst[0]
            summary.append(
                f"The widest gap is {w.name} at {self._fmt(w.value, w.compared['unit'])} "
                f"against a {w.compared['target_source']} target of "
                f"{self._fmt(w.compared['target'], w.compared['unit'])} "
                f"({abs(w.compared['variance']):.2f} short).")
        if provisional:
            summary.append(
                f"{len(provisional)} KPI(s) rest on provisional figures and are labelled as "
                f"such; no decision should be taken on them this cycle.")
        if rounding:
            summary.append(
                f"{len(rounding)} KPI(s) would read as on-target if rounded — "
                f"{', '.join(r.kpi_id for r in rounding)} are reported unrounded here.")

        # --- scorecard ---------------------------------------------------
        scorecard = [{
            "kpi_id": r.kpi_id, "name": r.name, "domain": r.domain,
            "value": r.value, "unit": r.compared["unit"], "target": r.compared["target"],
            "target_source": r.compared["target_source"],
            "variance": r.compared["variance"], "status": r.status,
            "pct_of_target": r.compared["pct_of_target"],
            "figure_status": r.computed["figure_status"],
            "formula": r.computed["formula"], "source_system": r.computed["source_system"],
            "inputs_used": r.computed["inputs_used"],
            "rounding_warning": r.compared.get("rounding_warning"),
            "peer_median": (r.benchmark or {}).get("peer_median"),
            "peer_cohort": (r.benchmark or {}).get("cohort"),
        } for r in kpi_results]

        # --- drill-down: which departments drive each off-target KPI ------
        findings = []
        for r in off_target:
            ranked = sorted(r.computed["evidence"], key=lambda e: (e["dept_value"] is None,
                                                                   e["dept_value"]))
            findings.append({
                "kpi_id": r.kpi_id, "name": r.name, "domain": r.domain,
                "value": r.value, "unit": r.compared["unit"],
                "target": r.compared["target"], "status": r.status,
                "variance": r.compared["variance"],
                "source_system": r.computed["source_system"],
                "drivers": ranked[:3],
                "statement": (
                    f"{r.name} is {self._fmt(r.value, r.compared['unit'])} against a target "
                    f"of {self._fmt(r.compared['target'], r.compared['unit'])} "
                    f"({r.status}). Source: {r.computed['source_system']}."),
            })

        # --- options and risks, one block per off-target KPI --------------
        options = []
        for r in off_target:
            for opt in OPTION_PLAYBOOK.get(r.kpi_id, []):
                options.append({**opt, "kpi_id": r.kpi_id, "kpi_name": r.name,
                                "domain": r.domain})

        # --- assumptions and data caveats --------------------------------
        assumptions = [
            f"Analysis covers {period} only; prior years are not included.",
            "Only Registrar-authorised, institution-level read access was used; no department "
            "was queried directly.",
            "KPI definitions and target values are the approved set; this brief does not "
            "redefine them.",
            "Institution figures aggregate raw counts, never the mean of department "
            "percentages, so department size is respected.",
        ]
        for domain, rec in ACCESS_REGISTER.items():
            if rec.get("caveat"):
                assumptions.append(f"{domain}: {rec['caveat']}")
        for r in provisional:
            assumptions.append(f"{r.kpi_id} ({r.name}) is PROVISIONAL. "
                               f"{r.computed.get('caveat', '')}".strip())

        # --- evidence appendix -------------------------------------------
        evidence = [{
            "kpi_id": r.kpi_id, "name": r.name, "formula": r.computed["formula"],
            "inputs_used": r.computed["inputs_used"],
            "source_system": r.computed["source_system"],
            "n_departments": r.computed["n_departments"],
            "rows": r.computed["evidence"],
        } for r in kpi_results]

        return {
            "title": f"Executive Decision Brief — institution performance, {period}",
            "period": period,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "DRAFT — pending Principal / Registrar approval",
            "version": None,
            "executive_summary": summary,
            "scorecard": scorecard,
            "findings": findings,
            "options": options,
            "assumptions": assumptions,
            "evidence": evidence,
            "counts": {"total": len(kpi_results), "off_target": len(off_target),
                       "below_target": len(below), "provisional": len(provisional),
                       "rounding_flags": len(rounding)},
        }


def validate_brief(brief: Dict[str, Any]) -> Validated:
    """The four Chapter 15 acceptance checks, run as a hard gate."""
    scorecard = brief.get("scorecard", [])
    options = brief.get("options", [])
    checks = [
        ("every figure cites its source",
         bool(scorecard) and all(r.get("source_system") and r.get("target_source")
                                 for r in scorecard),
         f"{len(scorecard)} KPIs, each with a source system and a target authority"),
        ("assumptions are stated explicitly",
         len(brief.get("assumptions", [])) >= 4,
         f"{len(brief.get('assumptions', []))} assumptions recorded"),
        ("each option lists its risks and trade-offs",
         bool(options) and all(o.get("risks") and o.get("trade_off") for o in options),
         f"{len(options)} options, each with risks and a stated trade-off"),
        ("no action is taken without leadership approval",
         brief.get("status", "").startswith("DRAFT") or brief.get("approved_by"),
         brief.get("status", "")),
        ("provisional figures are labelled, never presented as final",
         all(r["figure_status"] == "final"
             or any(r["kpi_id"] in a for a in brief.get("assumptions", []))
             for r in scorecard),
         f"{brief['counts']['provisional']} provisional KPI(s) labelled"),
        ("a rounding that would hide a miss is flagged",
         all(r.get("rounding_warning") is not None
             for r in scorecard if r["status"] != "on target"
             and round(r["value"]) >= r["target"] > r["value"]),
         f"{brief['counts']['rounding_flags']} rounding flag(s) raised"),
    ]
    return Validated(checks, "executive decision brief")


# =============================================================================
# 5 · The Coordinator: hybrid execution, human gate, versioning, audit
# =============================================================================

@dataclass
class Stage:
    name: str
    mode: str                  # "sequential" | "parallel" | "human gate"
    detail: str
    started_ms: float = 0.0
    elapsed_ms: float = 0.0
    status: str = "pending"    # pending | done | blocked


class ExecutiveRun:
    """apniLeap AURA Coordinator — owns run state, the plan, the audit log.

    Runs the four domain agents in parallel and everything else sequentially,
    exactly as the hybrid execution methodology specifies. Nothing is published
    until a named human approves it.
    """

    def __init__(self, period: str = REPORTING_PERIOD, domains: Optional[List[str]] = None):
        self.period = period
        self.domains = domains or list(DOMAINS)
        self.run_id = datetime.now(timezone.utc).strftime("EDSS-%Y%m%d-%H%M%S")
        self.stages: List[Stage] = [
            Stage("Gate 1: access intake", "sequential",
                  "Start only after each domain grants institution-level read access "
                  "authorised by the Registrar."),
            Stage("Parallel domain aggregation", "parallel",
                  "Academic, Research, Placement and Finance agents aggregate at the same time."),
            Stage("KPI synthesis", "sequential",
                  "KPIs are computed only after all domain agents return."),
            Stage("Report generation", "sequential",
                  "The brief is compiled after the KPI set is finalised."),
            Stage("Validation gate", "sequential",
                  "Four Chapter 15 checks; a failure blocks the human review."),
            Stage("Stakeholder approval", "human gate",
                  "Principal / Registrar approves before the Governing Council sees it."),
            Stage("Dashboard publish", "parallel",
                  "KPIs, domain metrics and the report publish together, once approved."),
        ]
        self.access: Dict[str, Any] = {}
        self.domain_agents: Dict[str, DomainAgent] = {}
        self.kpi_results: List[KPIResult] = []
        self.brief: Optional[Dict[str, Any]] = None
        self.brief_validation: Optional[Validated] = None
        self.audit: List[Dict[str, Any]] = []
        self.flags: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self.version: int = 0
        self.published: List[Dict[str, Any]] = []
        self.wall_ms: float = 0.0
        self.serial_ms: float = 0.0

    # ---- audit ---------------------------------------------------------
    def log(self, actor: str, action: str, detail: str = "", **extra) -> None:
        self.audit.append({"seq": len(self.audit) + 1, "actor": actor, "action": action,
                           "detail": detail,
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           **extra})

    def _stage(self, name: str) -> Stage:
        return next(s for s in self.stages if s.name == name)

    @property
    def trace(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for agent in self.domain_agents.values():
            rows.extend(agent.router.trace)
        rows.extend(self._kpi_agent.router.trace if hasattr(self, "_kpi_agent") else [])
        for i, r in enumerate(rows, 1):
            r["seq"] = i
        return rows

    @property
    def approved(self) -> bool:
        return self.version > 0

    # ---- the run -------------------------------------------------------
    def execute(self) -> "ExecutiveRun":
        run_started = time.perf_counter()
        self.log("Coordinator", "run started", f"{self.run_id} · period {self.period}")

        # Stage 1 — access intake (sequential gate)
        s = self._stage("Gate 1: access intake")
        t0 = time.perf_counter()
        self.access = {d: ACCESS_REGISTER[d] for d in self.domains}
        for d, rec in self.access.items():
            self.log(f"{d} Agent", "read access confirmed", rec["read_access"],
                     source_system=rec["source_system"], figure_status=rec["figure_status"])
        s.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        s.status = "done"

        # Stage 2 — domain aggregation (genuinely parallel)
        s = self._stage("Parallel domain aggregation")
        t0 = time.perf_counter()
        self.domain_agents = {d: DomainAgent(d) for d in self.domains}
        results: Dict[str, List[KPIResult]] = {}
        with ThreadPoolExecutor(max_workers=len(self.domain_agents) or 1) as pool:
            futures = {pool.submit(agent.run, self.period): d
                       for d, agent in self.domain_agents.items()}
            for fut, d in futures.items():
                results[d] = fut.result()
        s.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        s.status = "done"
        self.serial_ms = round(sum(a.elapsed_ms for a in self.domain_agents.values()), 2)
        for d, agent in self.domain_agents.items():
            self.log(f"{d} Agent", "domain metrics aggregated",
                     f"{len(results[d])} KPI(s) in {agent.elapsed_ms} ms",
                     kpis=[r.kpi_id for r in results[d]])

        # Stage 3 — KPI synthesis (sequential, after all four return)
        s = self._stage("KPI synthesis")
        t0 = time.perf_counter()
        self._kpi_agent = KPIAgent()
        self.kpi_results = self._kpi_agent.synthesise(results)
        s.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        s.status = "done"
        self.log("KPI Agent", "institution KPI set synthesised",
                 f"{len(self.kpi_results)} KPIs against NIRF / NAAC / strategic-plan targets")

        # Stage 4 — report generation (sequential)
        s = self._stage("Report generation")
        t0 = time.perf_counter()
        self.brief = ReportGenerationAgent().build_brief(self.kpi_results, self.period)
        self.brief["run_id"] = self.run_id
        s.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        s.status = "done"
        self.log("Report Generation Agent", "decision brief drafted",
                 f"{self.brief['counts']['off_target']} off-target KPI(s), "
                 f"{len(self.brief['options'])} drafted options")

        # Stage 5 — validation (hard gate)
        s = self._stage("Validation gate")
        t0 = time.perf_counter()
        self.brief_validation = validate_brief(self.brief)
        s.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        s.status = "done" if self.brief_validation.valid else "blocked"
        self.log("Coordinator", "validation gate",
                 "passed" if self.brief_validation.valid
                 else f"FAILED: {self.brief_validation.failing}")

        self._stage("Stakeholder approval").status = "pending"
        self.wall_ms = round((time.perf_counter() - run_started) * 1000, 2)
        self.log("Coordinator", "awaiting human approval",
                 "no figure is circulated until the Principal / Registrar approves")
        return self

    # ---- the human gate -------------------------------------------------
    def flag_kpi(self, kpi_id: str, by: str, note: str) -> None:
        self.flags.append({"kpi_id": kpi_id, "by": by, "note": note, "resolved": False,
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self.log(by, "flagged KPI for clarification", f"{kpi_id}: {note}")

    def approve(self, by: str, note: str = "") -> Dict[str, Any]:
        if not self.brief:
            raise RuntimeError("nothing to approve — run the pipeline first")
        if not (self.brief_validation and self.brief_validation.valid):
            raise RuntimeError("validation gate has not passed; approval is blocked")
        open_flags = [f for f in self.flags if not f["resolved"]]
        if open_flags:
            raise RuntimeError(f"{len(open_flags)} KPI(s) are flagged for clarification; "
                               f"resolve them before approving")
        self.version += 1
        self.brief["version"] = self.version
        self.brief["status"] = f"APPROVED v{self.version}"
        self.brief["approved_by"] = by
        self.brief["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.brief["approval_note"] = note
        record = {"version": self.version, "by": by, "note": note,
                  "at": self.brief["approved_at"], "decision": "approved"}
        self.decisions.append(record)
        self.published.append({**record, "circulated_to": "Governing Council",
                               "run_id": self.run_id})
        self._stage("Stakeholder approval").status = "done"
        self._stage("Dashboard publish").status = "done"
        self.log(by, "APPROVED for circulation",
                 f"version {self.version} released to the Governing Council")
        return record

    def override(self, by: str, note: str) -> Dict[str, Any]:
        record = {"by": by, "note": note, "decision": "override",
                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.decisions.append(record)
        self.log(by, "OVERRIDE recorded", note)
        return record

    def resolve_flag(self, index: int, by: str) -> None:
        self.flags[index]["resolved"] = True
        self.log(by, "flag resolved", self.flags[index]["kpi_id"])

    # ---- export ---------------------------------------------------------
    def to_markdown(self) -> str:
        b = self.brief
        if not b:
            return "# No brief generated yet."
        fmt = ReportGenerationAgent._fmt
        out = [f"# {b['title']}", "",
               f"**Status:** {b['status']}  ",
               f"**Run:** {self.run_id}  ",
               f"**Generated:** {b['generated_at']}  "]
        if b.get("approved_by"):
            out.append(f"**Approved by:** {b['approved_by']} on {b['approved_at']}  ")
        out += ["", "## 1. Executive summary", ""]
        out += [f"- {s}" for s in b["executive_summary"]]
        out += ["", "## 2. KPI scorecard against targets", "",
                "| KPI | Name | Value | Target | Variance | Status | Source |",
                "|---|---|---|---|---|---|---|"]
        for r in b["scorecard"]:
            flag = " ⚠ PROVISIONAL" if r["figure_status"] != "final" else ""
            out.append(f"| {r['kpi_id']} | {r['name']} | {fmt(r['value'], r['unit'])} | "
                       f"{fmt(r['target'], r['unit'])} | {r['variance']:+.2f} | "
                       f"{r['status']}{flag} | {r['source_system']} |")
        out += ["", "## 3. Off-target KPIs with department drill-down", ""]
        for f in b["findings"]:
            out.append(f"### {f['kpi_id']} — {f['name']}")
            out.append("")
            out.append(f["statement"])
            out.append("")
            out.append("Departments furthest below the institution figure:")
            out.append("")
            for d in f["drivers"]:
                out.append(f"- **{d['dept_code']}** ({d['dept_name']}): "
                           f"{d['dept_value']} — {d['numerator']} of {d['denominator']} "
                           f"({d['numerator_field']} / {d['denominator_field']})")
            out.append("")
        out += ["## 4. Options, with owner, timeline and indicative cost", ""]
        for o in b["options"]:
            out.append(f"### {o['kpi_id']} — {o['title']}")
            out += ["", o["detail"], "",
                    f"- **Owner:** {o['owner']}",
                    f"- **Timeline:** {o['timeline']}",
                    f"- **Indicative cost:** {o['indicative_cost']}",
                    "- **Risks:**"]
            out += [f"    - {r}" for r in o["risks"]]
            out += [f"- **Trade-off:** {o['trade_off']}", ""]
        out += ["## 5. Assumptions and data caveats", ""]
        out += [f"- {a}" for a in b["assumptions"]]
        out += ["", "## 6. Evidence appendix", ""]
        for e in b["evidence"]:
            inputs = ", ".join(f"{k} = {v}" for k, v in e["inputs_used"].items())
            out.append(f"- **{e['kpi_id']}** ({e['name']}): `{e['formula']}` — {inputs}; "
                       f"source: {e['source_system']}; {e['n_departments']} departments.")
        out += ["", "---", "",
                "*Every figure in this brief was computed by the KPI engine from "
                "Registrar-authorised department records. No figure was written by hand or "
                "by a language model.*"]
        return "\n".join(out)

    def to_json(self) -> str:
        return json.dumps({
            "run_id": self.run_id, "period": self.period, "domains": self.domains,
            "version": self.version, "approved": self.approved,
            "brief": self.brief,
            "validation": {"valid": self.brief_validation.valid if self.brief_validation
                           else None,
                           "failing": self.brief_validation.failing if self.brief_validation
                           else None},
            "flags": self.flags, "decisions": self.decisions, "published": self.published,
            "audit": self.audit, "tool_trace": self.trace,
        }, indent=2, default=str)


# =============================================================================
# 6 · Natural-language query — the Lab 2 question router, exposed in the UI
# =============================================================================
# Ask a question in plain English; the assistant works out which domain and KPI
# it is about, picks a tool chain, runs it, and answers only from what the tools
# returned. If it has no tool path for the question it says so rather than
# guessing — the Lab 2 behaviour, unchanged.

# Which words point at which KPI. Data-driven, so adding a KPI to the register
# is all it takes to make it answerable.
KPI_KEYWORDS: Dict[str, List[str]] = {
    "KPI-A1": ["pass percentage", "pass rate", "pass %", "passing", "results"],
    "KPI-A2": ["co/po", "co po", "copo", "attainment", "obe", "outcome"],
    "KPI-R1": ["publication", "papers", "publishing"],
    "KPI-R2": ["citation", "cited", "impact"],
    "KPI-R3": ["grant", "funding", "sanctioned", "research money"],
    # Deliberately tight: "recruit"/"hiring" are about appointing people, not the
    # placement KPI, and matching them made "who should we recruit as Dean?"
    # answer with a placement figure instead of declining.
    "KPI-P1": ["placement", "placed", "placement rate", "placement percentage"],
    "KPI-P2": ["package", "salary", "ctc", "compensation", "pay"],
    "KPI-P3": ["internship", "intern"],
    "KPI-F1": ["budget", "utilisation", "utilization", "spend", "expenditure", "finance"],
}

INTENT_PATTERNS = [
    ("drilldown", r"which department|what department|department[- ]wise|drill|breakdown|"
                  r"worst|lowest|weakest|dragging|pulling (it )?down|behind"),
    ("benchmark", r"peer|benchmark|nirf cohort|other institution|compare(d)? (with|to) other|"
                  r"rank band|competitor"),
    ("subset",    r"\bcircuit\b|\bcore\b"),
    ("status",    r"how (are|is|did)|what is|what's|are we|status|against target|vs target|"
                  r"meeting|on track|performance"),
]


def _allowed_numbers(objs: List[Any]) -> set:
    """Every number a tool actually produced, at the precisions we might print."""
    found, out = [], set()

    def walk(o):
        if isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, list):
            [walk(v) for v in o]
        elif isinstance(o, bool):
            pass
        elif isinstance(o, (int, float)):
            found.append(float(o))
        elif isinstance(o, str):
            out.update(re.findall(r"\d+(?:\.\d+)?", o))

    walk(objs)
    found = [x for n in found for x in (n, abs(n))]
    for n in found:
        for places in (0, 1, 2, 3, 4):
            out.add(f"{n:.{places}f}")
            out.add(f"{n:.{places}f}".rstrip("0").rstrip("."))
        out.add(str(n))
        if float(n).is_integer():
            out.add(str(int(n)))
    return out


_PERIOD_TOKENS = {"2025", "26", "2024", "27", "2023", "2026", "15", "3", "8"}


def ground_check(answer: str, tool_outputs: List[Any]) -> Tuple[bool, List[str]]:
    """Reject any answer containing a figure no tool produced."""
    allowed = _allowed_numbers(tool_outputs) | _PERIOD_TOKENS
    bad = [t for t in re.findall(r"\d+(?:\.\d+)?", answer) if t not in allowed]
    return (not bad), bad


@dataclass
class Answer:
    question: str
    routed: bool
    kpi_id: Optional[str]
    domain: Optional[str]
    intent: Optional[str]
    text: str
    tools_used: List[str] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    grounded: bool = True
    ungrounded_tokens: List[str] = field(default_factory=list)


class ExecutiveAssistant:
    """Answers plain-English questions using only the typed tool layer."""

    def __init__(self):
        self.router = ToolRouter(agent="Query Assistant")
        self.connector = Connector(self.router)
        self.history: List[Answer] = []

    # ---- routing --------------------------------------------------------
    @staticmethod
    def detect_kpi(question: str) -> Optional[str]:
        q = re.sub(r"\s+", " ", question.lower())
        best, best_len = None, 0
        for kpi_id, words in KPI_KEYWORDS.items():
            for w in words:
                if w in q and len(w) > best_len:      # longest keyword wins
                    best, best_len = kpi_id, len(w)
        if best is None:                               # fall back to the KPI's own name
            for kpi_id, d in KPI_DEFINITIONS.items():
                if d["name"].lower() in q:
                    return kpi_id
        return best

    @staticmethod
    def detect_intent(question: str) -> Optional[str]:
        q = re.sub(r"\s+", " ", question.lower())
        for name, pattern in INTENT_PATTERNS:
            if re.search(pattern, q):
                return name
        return None

    # ---- the tool chains -------------------------------------------------
    def _chain(self, kpi_id: str, why: str, rows=None, scope="all 8 departments"):
        if rows is None:
            rows = self.connector.read(
                "department reports",
                reason=f"{why}: per-department metrics live in the reports export",
                period=REPORTING_PERIOD)["rows"]
        self.connector.read(
            "institutional KPIs & dashboards",
            reason=f"{why}: the formula and target must come from the approved register",
            kpi_ids=[kpi_id])
        computed = self.router.call("compute_kpi",
                                    reason=f"{why}: apply the registered formula over {scope}",
                                    kpi_id=kpi_id, rows=rows)
        compared = self.router.call("compare_to_target",
                                    reason=f"{why}: variance against the approved target",
                                    kpi_id=kpi_id, value=computed["value"])
        v = validate_kpi_result(computed, compared)
        if not v.valid:
            raise ToolError(f"validation gate failed for {kpi_id}: {v.failing}")
        return computed, compared, rows

    @staticmethod
    def _disclosures(computed, compared) -> str:
        bits = []
        if computed.get("figure_status") != "final":
            bits.append(f"PROVISIONAL FIGURE — {computed.get('caveat', '')}".strip())
        if compared.get("rounding_warning"):
            bits.append(f"ROUNDING WARNING — {compared['rounding_warning']}")
        return (" " + " ".join(bits)) if bits else ""

    def ask(self, question: str) -> Answer:
        start = len(self.router.trace)
        kpi_id = self.detect_kpi(question)
        intent = self.detect_intent(question) or ("status" if kpi_id else None)
        fmt = ReportGenerationAgent._fmt

        if kpi_id is None:
            ans = Answer(question, False, None, None, None,
                         "I have no tool path for that question. I can report any of the "
                         f"{len(KPI_DEFINITIONS)} approved institution KPIs — their value "
                         "against target, the departments behind them, a peer benchmark "
                         "where one is published, or a circuit/core split. I am not going "
                         "to answer it from memory.")
            self.history.append(ans)
            return ans

        domain = KPI_DEFINITIONS[kpi_id]["domain"]
        try:
            if intent == "subset":
                category = "circuit" if "circuit" in question.lower() else "core"
                all_rows = self.connector.read(
                    "department reports",
                    reason=f"step 1 of 3: read every department row before filtering",
                    period=REPORTING_PERIOD)["rows"]
                subset = self.router.call(
                    "filter_rows",
                    reason=f"step 2 of 3: restrict to {category}-branch departments only",
                    rows=all_rows, field="category", value=category)
                computed, compared, _ = self._chain(
                    kpi_id, f"step 3 of 3: compute over the {category} subset",
                    rows=subset["rows"], scope=f"{category} departments")
                text = (f"Across the {subset['row_count']} {category}-branch departments "
                        f"({', '.join(computed['departments'])}), "
                        f"{computed['name']} is {fmt(computed['value'], computed['unit'])} — "
                        f"computed on the filtered subset, not on all {len(all_rows)} "
                        f"departments. Against the {compared['target_source']} target of "
                        f"{fmt(compared['target'], compared['unit'])} that is "
                        f"{compared['status']}. Source: {computed['source_system']}."
                        + self._disclosures(computed, compared))

            elif intent == "drilldown":
                computed, compared, _ = self._chain(kpi_id, "which departments drive this KPI")
                ranked = sorted(computed["evidence"],
                                key=lambda e: (e["dept_value"] is None, e["dept_value"]))
                worst = ranked[:3]
                lines = "; ".join(
                    f"{e['dept_code']} at {e['dept_value']} "
                    f"({e['numerator']} of {e['denominator']})" for e in worst)
                text = (f"{computed['name']} is {fmt(computed['value'], computed['unit'])} "
                        f"against a target of {fmt(compared['target'], compared['unit'])}. "
                        f"The departments furthest below the institution figure are: {lines}. "
                        f"Each figure traces to {computed['source_system']}."
                        + self._disclosures(computed, compared))

            elif intent == "benchmark":
                computed, compared, _ = self._chain(kpi_id, "peer comparison requested")
                bench = self.connector.read(
                    "external benchmarks",
                    reason="a peer comparison needs the published benchmark, which is not "
                           "in our own data",
                    required=False, kpi_id=kpi_id)
                if "error" in bench:
                    text = (f"{computed['name']} is "
                            f"{fmt(computed['value'], computed['unit'])} against our "
                            f"{compared['target_source']} target of "
                            f"{fmt(compared['target'], compared['unit'])} "
                            f"({compared['status']}). I cannot give you a peer comparison: "
                            f"{bench['error']}. I am not going to estimate one. "
                            f"Source: {computed['source_system']}."
                            + self._disclosures(computed, compared))
                else:
                    gap = self.router.call(
                        "compute_variance",
                        reason="the gap to the peer median is arithmetic, so it goes "
                               "through a tool",
                        value=computed["value"], reference=bench["peer_median"],
                        label=f"{computed['name']} vs {bench['cohort']}")
                    text = (f"{computed['name']} is "
                            f"{fmt(computed['value'], computed['unit'])}. The "
                            f"{bench['cohort']} peer median for {bench['year']} is "
                            f"{bench['peer_median']:.2f}, so we sit "
                            f"{gap['abs_variance']:.2f} "
                            f"{'below' if gap['variance'] < 0 else 'above'} the cohort, and "
                            f"{abs(compared['variance']):.2f} "
                            f"{'below' if compared['variance'] < 0 else 'above'} our own "
                            f"{compared['target_source']} target of "
                            f"{compared['target']:.2f}. "
                            f"Sources: {computed['source_system']}; {bench['source_system']}."
                            + self._disclosures(computed, compared))

            else:   # status
                computed, compared, _ = self._chain(kpi_id, "status against target requested")
                inputs = ", ".join(f"{k} = {v}" for k, v in computed["inputs_used"].items())
                text = (f"{computed['name']} for {REPORTING_PERIOD} is "
                        f"{fmt(computed['value'], computed['unit'])}, computed as "
                        f"{computed['formula']} over {computed['n_departments']} departments "
                        f"({inputs}). The {compared['target_source']} target is "
                        f"{fmt(compared['target'], compared['unit'])}, so we are "
                        f"{abs(compared['variance']):.2f} "
                        f"{'below' if compared['variance'] < 0 else 'above'} it — status: "
                        f"{compared['status']}. Source: {computed['source_system']}."
                        + self._disclosures(computed, compared))

        except (ToolError, ToolContractError) as exc:
            text = f"I could not answer that: {exc}"

        used = self.router.trace[start:]
        grounded, bad = ground_check(text, self.router.raw_outputs[start:])
        ans = Answer(question, True, kpi_id, domain, intent, text,
                     [t["tool"] for t in used], used, grounded, bad)
        self.history.append(ans)
        return ans


EXAMPLE_QUESTIONS = [
    "How is placement doing against target this year?",
    "Which departments are dragging the pass percentage down?",
    "How do our citations per faculty compare with peer institutions?",
    "What is the placement percentage for core-branch departments only?",
    "How does internship completion compare with peers?",
    "What is our budget utilisation?",
    "Who should we recruit as Dean of Research next year?",
]


# =============================================================================
# 7 · The Lab 1 planner — clarify → plan → revise
# =============================================================================
# Lab 1's graded core, ported from the notebook and reshaped as a step-wise
# session so a UI can drive it: the agent asks, waits for a human reply, then
# continues. The two properties instructors check first are preserved exactly:
#
#   * it asks only for what is genuinely missing (never a fixed questionnaire),
#   * revise() MUTATES the existing plan via typed patch operations; it never
#     regenerates the plan from scratch.

SLOT_QUESTIONS = {
    "domains":   "Which performance domains must the brief cover — Academic, Research, "
                 "Placement, Finance, or a subset?",
    "period":    "Which reporting period does this cover (e.g. academic year 2025-26)?",
    "kpis":      "Which KPIs should be reported, or should the approved institution-wide "
                 "KPI set be used in full?",
    "targets":   "Which target set should performance be compared against — NIRF, NAAC, "
                 "the internal strategic plan, or all three?",
    "drilldown": "Is department-level drill-down required for every KPI, or only for KPIs "
                 "that miss their target?",
    "output":    "What should leadership receive — a decision brief with options and "
                 "risks, a dashboard, or both?",
}
REQUIRED_SLOTS = list(SLOT_QUESTIONS)


# ==========================================================================
# LAB 1 — the questions, composed from THIS request
# ==========================================================================
# SLOT_QUESTIONS above is the fallback wording. What the agent actually asks is
# built here, from two things it has already observed: whatever the request did
# state, and what the data-scope register says can be served. So the question
# about the period offers the periods that exist, and the question about
# domains reacts to the domains the request already named instead of reading
# out the same sentence every time.

def _periods_available() -> List[str]:
    """Periods the register can actually serve, newest first."""
    seen = set()
    for rec in ACCESS_REGISTER.values():
        seen.update(rec.get("periods", []))
    return sorted(seen, reverse=True)


def ask_for(slot: str, goal: "PlanGoal", context: str) -> Dict[str, Any]:
    """One question plus the answers worth offering as a click.

    Returns {slot, question, options, why}. `options` are suggestions, never a
    closed list — the caller can always type something else, and the typed
    answer goes through the same extractor.
    """
    named = extract_slots(context)
    q = SLOT_QUESTIONS[slot]
    options: List[str] = []
    why = ""

    if slot == "domains":
        already = named.get("domains") or []
        rest = [d for d in DOMAINS if d not in already]
        if already and rest:
            q = (f"Your request points at {_join(already)}. Should the brief stay "
                 f"there, or widen to the other domain(s) — {_join(rest)}?")
            options = [f"{_join(already)} only",
                       f"{_join(already)} and {rest[0]}",
                       "All four domains"]
        else:
            q = ("Which performance domains should the brief cover? The register "
                 f"serves {_join(list(DOMAINS))}.")
            options = ["All four domains", "Academic and Research",
                       "Placement only", "Finance only"]
        why = "the domains decide which KPIs are computed and which packs are called"

    elif slot == "period":
        avail = _periods_available()
        provisional = [d for d, r in ACCESS_REGISTER.items()
                       if r.get("figure_status") != "final"]
        q = (f"Which reporting period does this cover? The register holds "
             f"{_join(avail)}.")
        options = [f"academic year {p}" for p in avail]
        why = (f"{_join(provisional)} figures are still provisional, so the period "
               f"changes what can be stated as final" if provisional
               else "the period decides which export is read")

    elif slot == "kpis":
        hinted = named.get("kpis") or []
        if hinted and hinted != ["approved institution-wide KPI set"]:
            q = (f"You named {_join(hinted)}. Report just those, or the full "
                 f"approved institution-wide KPI set?")
            options = [f"Only {_join(hinted)}",
                       "The approved institution-wide KPI set"]
        else:
            q = ("Which KPIs should be reported — the approved institution-wide "
                 "set in full, or a named subset?")
            options = ["The approved institution-wide KPI set",
                       "Only the pass percentage and placement percentage"]
        why = "an unnamed KPI set is the most common way a brief quietly changes scope"

    elif slot == "targets":
        q = ("What should performance be measured against — the external "
             "rankings, the internal plan, or both?")
        options = ["NIRF, NAAC and the strategic plan", "NIRF and NAAC only",
                   "The internal strategic plan only"]
        why = "a figure with no target is a number, not a finding"

    elif slot == "drilldown":
        doms = goal.domains or named.get("domains") or list(DOMAINS)
        q = (f"Should the brief break {_join(doms)} down by department for every "
             f"KPI, or only where a target is missed?")
        # Every option has to be readable BACK by extract_slots — an option the
        # extractor cannot parse is a button that silently does nothing, so the
        # wording carries the words the extractor looks for.
        options = ["Department-level drill-down only for KPIs that miss their "
                   "target",
                   "Department-level drill-down for every KPI"]
        why = "drill-down policy is a derived acceptance test, so it changes the suite"

    elif slot == "output":
        q = "What should leadership receive at the end of this?"
        options = ["A decision brief with options and risks",
                   "A decision brief with options, risks and a dashboard",
                   "A dashboard only"]
        why = "options and risks are what makes it a decision brief, not a report"

    return {"slot": slot, "question": q, "options": options, "why": why}


def _join(items: List[str]) -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


@dataclass
class PlanGoal:
    """Run-state for the planner. Empty slots are what drive the loop."""
    domains: Optional[List[str]] = None
    period: Optional[str] = None
    kpis: Optional[List[str]] = None
    targets: Optional[List[str]] = None
    drilldown: Optional[str] = None
    output: Optional[str] = None
    plan_locked: bool = False        # <-- THE stopping condition
    scope_checked: bool = False

    def missing(self) -> List[str]:
        return [s for s in REQUIRED_SLOTS if getattr(self, s) in (None, [], "")]

    def satisfied(self) -> bool:
        return self.plan_locked is True

    def as_dict(self) -> Dict[str, Any]:
        return {s: getattr(self, s) for s in REQUIRED_SLOTS}


def extract_slots(text: str) -> Dict[str, Any]:
    """Pull whatever the request already states. Never guesses a default."""
    text = re.sub(r"\s+", " ", text).strip()
    t = text.lower()
    out: Dict[str, Any] = {}

    domain_patterns = {
        "Academic":  r"\bacademic(s)?\b(?!\s+year)|\bpass (percentage|rate)\b|\bco ?/? ?po\b",
        "Research":  r"\bresearch\b|\bpublication|\bcitation",
        "Placement": r"\bplacement|\binternship\b|\baverage package\b",
        "Finance":   r"\bfinance\b|\bfinancial\b|\bbudget\b|\brevenue\b",
    }
    domains = [d for d, pat in domain_patterns.items() if re.search(pat, t)]
    if re.search(r"\ball (four|4)\b|\ball domains\b|\bevery domain\b", t):
        domains = list(DOMAINS)
    if domains:
        out["domains"] = domains

    m = re.search(r"\b(20\d{2}\s*[-–/]\s*\d{2,4})\b", text)
    if m:
        out["period"] = "academic year " + m.group(1).replace(" ", "")

    if re.search(r"approved .*kpi|full kpi set|all (approved )?kpis|institution-wide kpi", t):
        out["kpis"] = ["approved institution-wide KPI set"]
    else:
        named = [n for n, pat in {
            "pass percentage": r"pass (percentage|%|rate)", "CO/PO attainment": r"co ?/? ?po",
            "publications": r"publication", "citations": r"citation", "grants": r"grant",
            "placement percentage": r"placement (percentage|%|rate)",
            "average package": r"average package", "internship completion": r"internship",
            "budget utilisation": r"budget utili",
            "carbon footprint": r"carbon footprint", "alumni donations": r"alumni donation",
            "student satisfaction index": r"student satisfaction",
        }.items() if re.search(pat, t)]
        if named:
            out["kpis"] = named

    targets = [n for n, pat in {"NIRF": r"nirf", "NAAC": r"naac",
                                "strategic plan": r"strategic[- ]plan"}.items()
               if re.search(pat, t)]
    if targets:
        out["targets"] = targets

    if re.search(r"drill[- ]?down|department[- ]level", t):
        if re.search(r"only\b.*(miss|below|off|short of).{0,20}target", t):
            out["drilldown"] = "only for KPIs that miss their target"
        elif re.search(r"every kpi|all kpis|mandatory|each kpi", t):
            out["drilldown"] = "mandatory for every KPI"
        else:
            out["drilldown"] = "department-level drill-down required"

    if "dashboard" in t and ("brief" in t or "report" in t):
        out["output"] = "decision brief and executive dashboard"
    elif "dashboard" in t:
        out["output"] = "executive dashboard"
    elif re.search(r"decision brief|executive brief|leadership report|executive report", t):
        out["output"] = "decision brief with options and risks"
    return out


def clarify(context: str, goal: PlanGoal) -> Dict[str, Any]:
    """Extract what is stated; ask ONLY about what is still empty."""
    missing = goal.missing()
    if not missing:
        return {"status": "REQUIREMENTS_COMPLETE", "extracted": {}, "questions": [],
                "asked_about": []}
    found = {k: v for k, v in extract_slots(context).items() if k in missing}
    still = [s for s in missing if s not in found]
    prompts = [ask_for(s, goal, context) for s in still]
    return {"status": "NEEDS_INFO" if still else "REQUIREMENTS_COMPLETE",
            "extracted": found,
            "questions": [p["question"] for p in prompts],
            "prompts": prompts,
            "asked_about": still}


def read_data_scope_register(domains: List[str], period: str) -> Dict[str, Any]:
    """TOOL. Access + coverage record for the requested domains, or an error."""
    unlinked = [d for d in domains if d not in ACCESS_REGISTER]
    if unlinked:
        return {"error": f"no source system linked for domain(s): {unlinked}"}
    return {"register": {d: ACCESS_REGISTER[d] for d in domains},
            "period_requested": period}


def detect_conflicts(goal: PlanGoal, register: Dict[str, Any], period: str):
    """What leadership asked for, against what the register can actually serve."""
    conflicts = []
    key = re.sub(r"^academic year\s*", "", period.strip(), flags=re.I)
    for domain, rec in register.items():
        if key not in rec.get("periods", []):
            conflicts.append({
                "type": "PERIOD_NOT_COVERED", "domain": domain,
                "detail": f"{domain} source covers {rec.get('periods')}, but the request "
                          f"asks for {key}.",
                "required_action": f"Either exclude {domain}, or report it against the last "
                                   f"closed period with an explicit label."})
        if rec["figure_status"] != "final":
            conflicts.append({
                "type": "FIGURES_NOT_FINAL", "domain": domain,
                "detail": f"{domain} figures are '{rec['figure_status']}'. "
                          f"{rec.get('caveat','')}".strip(),
                "required_action": "Label every figure from this domain as provisional, or "
                                   "drop the domain until reconciliation completes."})
        elif rec.get("caveat"):
            conflicts.append({"type": "SCOPE_CAVEAT", "domain": domain,
                              "detail": rec["caveat"],
                              "required_action": "Record the caveat in the assumptions."})
    if goal.kpis and goal.kpis != ["approved institution-wide KPI set"]:
        available = {m.lower() for rec in register.values() for m in rec.get("metrics", [])}
        for kpi in goal.kpis:
            if not any(kpi.lower() in m or m in kpi.lower() for m in available):
                conflicts.append({
                    "type": "KPI_NOT_SOURCED", "domain": "—",
                    "detail": f"No linked source system reports '{kpi}'.",
                    "required_action": f"Drop '{kpi}' from scope or authorise a new source."})
    return conflicts


@dataclass
class Plan:
    """A mutable, addressable plan. revise() edits THIS object in place."""
    body: Dict[str, Any]
    revision: int = 0
    patch_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"revision": self.revision, **self.body, "patch_history": self.patch_history}


def build_plan(goal: PlanGoal, register: Dict[str, Any], conflicts) -> Plan:
    """Template-driven plan. Produces a PLAN only — never a figure, never a result."""
    domains, period = goal.domains, goal.period
    catalog = {
        "Academic":  [("Pass percentage", "sum(students_passed) / sum(students_appeared) x 100", "%"),
                      ("CO/PO attainment", "weighted mean of attainment over enrolment", "index 0-3")],
        "Research":  [("Publications per faculty", "sum(publications) / sum(sanctioned_faculty)", "count"),
                      ("Citations per faculty", "sum(citations) / sum(sanctioned_faculty)", "count"),
                      ("Grants sanctioned", "sum(grants_lakh)", "INR lakh")],
        "Placement": [("Placement percentage", "sum(placed) / sum(eligible) x 100", "%"),
                      ("Average package", "sum(package) / sum(placed)", "LPA"),
                      ("Internship completion", "sum(interns) / sum(eligible) x 100", "%")],
        "Finance":   [("Budget utilisation", "sum(spent) / sum(allocated) x 100", "%"),
                      ("Grant funds received", "sum(grant_credits)", "INR lakh")],
    }
    kpis = [{"kpi": k, "formula": f, "unit": u,
             "source": register.get(d, {}).get("source_system", "—")}
            for d in domains for (k, f, u) in catalog.get(d, [])]

    steps = [{"id": "S1", "title": "Confirm read access and freeze the data cut",
              "detail": f"Re-read the data-scope register for {', '.join(domains)} and record "
                        "the cut timestamp so every figure is reproducible.",
              "owner_agent": "Coordinator"}]
    for i, d in enumerate(domains, start=2):
        steps.append({"id": f"S{i}",
                      "title": f"Aggregate {d.lower()} metrics across departments",
                      "detail": f"{d} Agent pulls "
                                f"{', '.join(register.get(d, {}).get('metrics', []))} per "
                                f"department for {period}, keeps the per-department spread, "
                                f"and flags stale or missing data.",
                      "owner_agent": f"{d} Agent"})
    n = len(steps)
    steps += [
        {"id": f"S{n+1}", "title": "Synthesise institution-wide KPIs",
         "detail": "KPI Agent applies only approved KPI definitions to the domain aggregates, "
                   "showing formula and source; enrolment-weighted, never a plain mean of "
                   "department percentages.", "owner_agent": "KPI Agent"},
        {"id": f"S{n+2}", "title": "Compare each KPI to its approved target",
         "detail": f"Compute variance against {', '.join(goal.targets)}; classify each KPI as "
                   "on-target / at-risk / below-target.", "owner_agent": "KPI Agent"},
        {"id": f"S{n+3}", "title": "Attach department-level drill-down evidence",
         "detail": "Record the traceable path KPI -> department -> source metric -> source "
                   "system for each KPI.", "owner_agent": "Report Generation Agent"},
        {"id": f"S{n+4}", "title": "Draft options and risks for every below-target KPI",
         "detail": "For each KPI missing target, draft 2-3 options with cost, owner, timeline "
                   "and the risks/trade-offs of each. Options only — no action is taken.",
         "owner_agent": "Report Generation Agent"},
        {"id": f"S{n+5}", "title": "Run validation, then route to the human gate",
         "detail": "Validation is a hard gate; on failure only the failing KPI is regenerated. "
                   "The Principal/Registrar then approves, edits or overrides.",
         "owner_agent": "Coordinator + Executive gate"},
    ]

    assumptions = [
        f"Analysis is limited to {period}; prior years appear only as trend context.",
        "Only Registrar-authorised, institution-level read access is used.",
        "KPI definitions and target values are the approved set; this plan does not "
        "redefine them.",
    ] + [f"{c['type']}: {c['detail']} -> {c['required_action']}" for c in conflicts]

    body = {
        "objective": f"Produce a leadership decision brief comparing {', '.join(domains)} "
                     f"performance for {period} against {', '.join(goal.targets)}, "
                     "identifying below-target areas with options and risks.",
        "scope": {"domains": list(domains), "period": period,
                  "unit_of_analysis": "institution level, with department-level drill-down"},
        "data_required": [{"domain": d,
                           "source_system": register.get(d, {}).get("source_system", "—"),
                           "fields": register.get(d, {}).get("metrics", []),
                           "access": register.get(d, {}).get("read_access", "—")}
                          for d in domains],
        "analysis_steps": steps,
        "kpi_calculations": kpis,
        "target_comparison": {"target_sets": list(goal.targets),
                              "method": "variance = actual - target, in the KPI's own unit "
                                        "alongside % of target achieved; no rounding may "
                                        "hide a miss"},
        "drilldown_policy": goal.drilldown,
        "evidence_requirements": [
            "Every figure carries source system, extraction timestamp and department scope.",
            "Every KPI carries its formula and the approved target it is measured against.",
            "Provisional figures are labelled inline, never presented as final.",
            "Every option carries its risks, trade-offs and named owner.",
        ],
        "brief_structure": [
            "1. Executive summary (3 bullets, decision-ready)",
            "2. KPI scorecard vs targets, with variance",
            "3. Below-target KPIs with department-level drill-down",
            "4. Options with cost, owner, timeline",
            "5. Risks and trade-offs per option",
            "6. Assumptions and data caveats",
            "7. Evidence appendix (source trace per figure)",
        ],
        "validation_checks": [
            "every figure cites its source",
            "assumptions are stated explicitly",
            "each option lists its risks and trade-offs",
            "no action is taken without leadership approval",
        ],
        "assumptions": assumptions,
    }
    return Plan(body=body)


# ---- Revision: the model may only emit a PATCH; Python applies it in place ---
PATCH_OPS = ["remove_domain", "add_domain", "set_field", "add_item", "remove_item",
             "modify_step", "add_step", "remove_step"]


def make_patch(feedback: str) -> List[Dict[str, Any]]:
    """Turn free-text feedback into typed operations. Never rewrites the plan."""
    fb, ops = feedback.lower(), []
    for d in DOMAINS:
        if re.search(rf"(remove|drop|exclude|without)\b[^.]*\b{d.lower()}", fb):
            ops.append({"op": "remove_domain", "value": d,
                        "why": f"feedback asks to remove the {d} domain"})
        elif re.search(rf"(add|include|also cover)\b[^.]*\b{d.lower()}", fb):
            ops.append({"op": "add_domain", "value": d,
                        "why": f"feedback asks to add the {d} domain"})
    # "only Placement" / "just placement" / "placement only" / "focus on X".
    # Narrowing to a domain is expressed as removing the others, so it goes
    # through the same remove_domain path that already drops the domain's data
    # source, its KPI rows, its analysis steps and retires its assumptions.
    already = {o["value"] for o in ops if o["op"] == "remove_domain"}
    keep = [d for d in DOMAINS
            if re.search(rf"(?:only|just|restrict to|limit to|focus on|nothing but)"
                         rf"\b[^.]{{0,40}}?\b{d.lower()}\b", fb)
            or re.search(rf"\b{d.lower()}\b[^.]{{0,25}}?\bonly\b", fb)]
    if keep and len(keep) < len(DOMAINS):
        for d in DOMAINS:
            if d not in keep and d not in already:
                ops.append({"op": "remove_domain", "value": d,
                            "why": f"feedback narrows the brief to "
                                   f"{', '.join(keep)}, so {d} leaves scope"})

    # "drill-down", but also the way people actually say it: department-wise,
    # by department, dept wise. A bare request for a department breakdown means
    # every KPI unless the feedback says otherwise.
    drillish = re.search(r"drill[- ]?down|department[- ]?wise|dept[- ]?wise|"
                         r"by department|department[- ]level|per department", fb)
    negated = re.search(r"(no|without|remove|drop)\b[^.]{0,20}"
                        r"(drill[- ]?down|department)", fb)
    if drillish and not negated:
        if re.search(r"only\b[^.]{0,30}(miss|below|off|short of)[^.]{0,20}target", fb):
            ops.append({"op": "set_field", "path": "drilldown_policy",
                        "value": "only for KPIs that miss their target",
                        "why": "feedback limits drill-down to KPIs that miss target"})
        else:
            ops.append({"op": "set_field", "path": "drilldown_policy",
                        "value": "mandatory for every KPI — each KPI must carry its "
                                 "full department-level trace, not only the KPIs "
                                 "that miss target",
                        "why": "feedback asks for a department-level breakdown, "
                               "which applies to every KPI unless it says otherwise"})
    m = re.search(r"\b(one|two|three|1|2|3)[- ]page", fb)
    if m:
        word = {"1": "one", "2": "two", "3": "three"}.get(m.group(1), m.group(1))
        ops.append({"op": "set_field", "path": "brief_length_limit",
                    "value": f"maximum {word} pages for the main brief; the evidence "
                             "appendix ships as a separate annexure",
                    "why": "feedback caps the length of the main brief"})
    if re.search(r"risk owner|named owner|owner for (each|every)|accountab", fb):
        ops.append({"op": "add_item", "path": "evidence_requirements",
                    "value": "Every option names an accountable owner and the risk that "
                             "owner is accepting.",
                    "why": "feedback requires an accountable owner against every option"})
    if re.search(r"trend|year[- ]on[- ]year|yoy|previous year|last year", fb):
        ops.append({"op": "add_step", "after": "S1",
                    "title": "Pull the prior-year baseline for trend context",
                    "value": "Retrieve the same KPI set for the preceding closed year so "
                             "every KPI carries its year-on-year movement, labelled as trend "
                             "context rather than as the reporting-period figure.",
                    "owner_agent": "Coordinator",
                    "why": "feedback asks for year-on-year trend context"})
    if re.search(r"remove .*(executive summary|summary section)", fb):
        ops.append({"op": "remove_item", "path": "brief_structure",
                    "value": "Executive summary",
                    "why": "feedback removes the executive summary section"})
    return ops


def _get_parent(body: Dict[str, Any], path: str):
    parts, cur = path.split("."), body
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    return cur, parts[-1]


def apply_patch(plan: Plan, ops: List[Dict[str, Any]]) -> List[str]:
    """Apply operations IN PLACE to `plan`. The only code allowed to change one."""
    b, effects = plan.body, []
    b.setdefault("scope", {}).setdefault("domains", [])
    for key in ("data_required", "kpi_calculations", "analysis_steps", "assumptions"):
        b.setdefault(key, [])

    for op in ops:
        kind = op.get("op")
        if kind in ("remove_domain", "add_domain"):
            dom = str(op.get("value", "")).strip().title()
            if dom not in DOMAINS:
                effects.append(f"IGNORED {kind}: '{op.get('value')}' is not an approved domain")
                continue
            if kind == "remove_domain":
                if dom not in b["scope"]["domains"]:
                    effects.append(f"IGNORED remove_domain: {dom} is not in scope")
                    continue
                b["scope"]["domains"].remove(dom)
                b["data_required"] = [d for d in b["data_required"] if d["domain"] != dom]
                src = ACCESS_REGISTER.get(dom, {}).get("source_system", "~none~")
                b["kpi_calculations"] = [k for k in b["kpi_calculations"]
                                         if k.get("source") != src]
                dropped = [s["id"] for s in b["analysis_steps"]
                           if s.get("owner_agent", "").startswith(dom)]
                b["analysis_steps"] = [s for s in b["analysis_steps"]
                                       if s["id"] not in dropped]
                b["assumptions"] = [
                    (f"[retired at r{plan.revision + 1}: {dom} removed from scope] {a}"
                     if (dom in a and a.split(":")[0].isupper()) else a)
                    for a in b["assumptions"]]
                effects.append(f"removed domain {dom}: dropped steps {dropped or '[]'}, its "
                               f"data source and its KPI rows")
            else:
                if dom in b["scope"]["domains"]:
                    effects.append(f"IGNORED add_domain: {dom} already in scope")
                    continue
                b["scope"]["domains"].append(dom)
                rec = ACCESS_REGISTER.get(dom, {})
                b["data_required"].append({"domain": dom,
                                           "source_system": rec.get("source_system", "—"),
                                           "fields": rec.get("metrics", []),
                                           "access": rec.get("read_access", "—")})
                effects.append(f"added domain {dom} with its source system")
        elif kind == "set_field":
            parent, leaf = _get_parent(b, op["path"])
            old = parent.get(leaf)
            parent[leaf] = op["value"]
            effects.append(f"set {op['path']}"
                           + (f" (was '{str(old)[:48]}…')" if old is not None else " (new field)"))
        elif kind == "add_item":
            parent, leaf = _get_parent(b, op["path"])
            parent.setdefault(leaf, []).append(op["value"])
            effects.append(f"appended one entry to {op['path']}")
        elif kind == "remove_item":
            parent, leaf = _get_parent(b, op["path"])
            before = list(parent.get(leaf, []))
            parent[leaf] = [x for x in before if op["value"].lower() not in str(x).lower()]
            effects.append(f"removed {len(before) - len(parent[leaf])} entry(ies) from "
                           f"{op['path']}")
        elif kind == "modify_step":
            for st in b["analysis_steps"]:
                if st["id"] == op.get("step_id"):
                    st["detail"] = op["value"]
                    effects.append(f"rewrote detail of step {st['id']}")
                    break
            else:
                effects.append(f"IGNORED modify_step: no step {op.get('step_id')}")
        elif kind == "remove_step":
            n = len(b["analysis_steps"])
            b["analysis_steps"] = [s for s in b["analysis_steps"]
                                   if s["id"] != op.get("step_id")]
            effects.append(f"removed step {op.get('step_id')}" if len(b["analysis_steps"]) < n
                           else f"IGNORED remove_step: no step {op.get('step_id')}")
        elif kind == "add_step":
            ids = [s["id"] for s in b["analysis_steps"]]
            new_id = f"S{max([int(i[1:]) for i in ids if i[1:].isdigit()] + [0]) + 1}"
            new = {"id": new_id, "title": op.get("title", "additional step"),
                   "detail": op.get("value", ""),
                   "owner_agent": op.get("owner_agent", "Coordinator")}
            pos = ids.index(op["after"]) + 1 if op.get("after") in ids else len(ids)
            b["analysis_steps"].insert(pos, new)
            effects.append(f"inserted step {new_id} after {op.get('after', 'end')}")
        else:
            effects.append(f"IGNORED unknown op: {kind}")
    return effects


def revise(plan: Plan, feedback: str) -> Plan:
    """Apply feedback to the SAME Plan object. Returns the same instance."""
    ops = make_patch(feedback)
    effects = apply_patch(plan, ops)                     # <-- in-place mutation
    plan.revision += 1
    for op, eff in zip(ops, effects):
        plan.patch_history.append({"revision": plan.revision, "op": op.get("op"),
                                   "why": op.get("why", ""), "effect": eff})
    if not ops:
        plan.patch_history.append({"revision": plan.revision, "op": "none",
                                   "why": "no actionable change found in the feedback",
                                   "effect": "plan left unchanged"})
    return plan


class PlannerSession:
    """The Lab 1 loop, driven one step at a time so a UI can sit inside it.

    States:  awaiting_input -> (more rounds) -> plan_ready
             abandoned  (requirements never supplied; the agent refuses to guess)
    """

    MAX_CLARIFY_ROUNDS = 4

    def __init__(self):
        self.goal = PlanGoal()
        self.plan: Optional[Plan] = None
        self.register: Dict[str, Any] = {}
        self.conflicts: List[Dict[str, Any]] = []
        self.log: List[Dict[str, Any]] = []
        self.context = ""
        self.rounds = 0
        self.pending_questions: List[str] = []
        self.pending_prompts: List[Dict[str, Any]] = []   # question + clickable options
        self.status = "new"
        self.snapshots: List[Dict[str, Any]] = []      # plan body before each revision

    # ---- logging -------------------------------------------------------
    def _log(self, planned, action, observed, stopped=False, stop_reason=None):
        entry = {"iteration": len(self.log) + 1, "planned": planned, "action": action,
                 "observed": observed, "stopped": stopped,
                 "goal_state": {"missing": self.goal.missing(),
                                "scope_checked": self.goal.scope_checked,
                                "plan_locked": self.goal.plan_locked}}
        if stop_reason:
            entry["stop_reason"] = stop_reason
        self.log.append(entry)

    # ---- planner: what next? -------------------------------------------
    def next_step(self):
        if self.goal.missing():
            return ("clarify", self.goal.missing())
        if not self.goal.scope_checked:
            return ("check_scope", None)
        return ("generate_plan", None)

    # ---- the loop, run until it needs a human or locks the plan ---------
    def _advance(self) -> str:
        while not self.goal.satisfied():
            step, arg = self.next_step()

            if step == "clarify":
                self.rounds += 1
                before = set(REQUIRED_SLOTS) - set(self.goal.missing())
                result = clarify(self.context, self.goal)
                for slot, value in result["extracted"].items():
                    setattr(self.goal, slot, value)
                gained = sorted((set(REQUIRED_SLOTS) - set(self.goal.missing())) - before)
                self._log(planned=f"clarify {len(arg)} unspecified requirement(s): {arg}",
                          action=f"round {self.rounds}: extracted {gained or 'nothing'}; "
                                 f"asked {len(result['questions'])} question(s)",
                          observed={"questions": result["questions"],
                                    "extracted": result["extracted"]})
                if result["questions"]:
                    if self.rounds > self.MAX_CLARIFY_ROUNDS:
                        self._log("stop rather than assume", "clarification budget exhausted",
                                  {"still_missing": self.goal.missing()}, True,
                                  f"requirements still incomplete after "
                                  f"{self.MAX_CLARIFY_ROUNDS} rounds; the agent refuses to "
                                  f"invent the missing slots")
                        self.status = "abandoned"
                        return self.status
                    self.pending_questions = result["questions"]
                    self.pending_prompts = result.get("prompts", [])
                    self.status = "awaiting_input"
                    return self.status

            elif step == "check_scope":
                out = read_data_scope_register(self.goal.domains, self.goal.period)
                if "error" in out:
                    self._log("read the data-scope register before planning",
                              "tool call: read_data_scope_register()", out, True,
                              f"tool error: {out['error']}")
                    self.status = "abandoned"
                    return self.status
                self.register = out["register"]
                self.conflicts = detect_conflicts(self.goal, self.register, self.goal.period)
                self.goal.scope_checked = True
                self._log("read the data-scope register before locking the plan",
                          f"tool call: read_data_scope_register("
                          f"domains={self.goal.domains}, period='{self.goal.period}')",
                          {"access": {d: r["read_access"] for d, r in self.register.items()},
                           "figure_status": {d: r["figure_status"]
                                             for d, r in self.register.items()},
                           "conflicts_found": len(self.conflicts)})
                for c in self.conflicts:
                    self._log("reconcile the request against observed data scope",
                              f"conflict detected: {c['type']} ({c['domain']})",
                              {"detail": c["detail"],
                               "required_action": c["required_action"]})

            elif step == "generate_plan":
                self.plan = build_plan(self.goal, self.register, self.conflicts)
                self.goal.plan_locked = True
                self._log("draft the execution plan from the locked requirements",
                          f"built plan: {len(self.plan.body['analysis_steps'])} steps, "
                          f"{len(self.plan.body['kpi_calculations'])} KPI calculations, "
                          f"{len(self.conflicts)} caveat(s) carried into assumptions",
                          {"objective": self.plan.body["objective"]},
                          True, "goal.plan_locked is now True")
        self.pending_questions = []
        self.pending_prompts = []
        self.status = "plan_ready"
        return self.status

    # ---- entry points ---------------------------------------------------
    def start(self, request: str) -> str:
        self.context = request.strip()
        self._log("ingest the leadership request", "received free-text request", self.context)
        return self._advance()

    def answer(self, reply: str) -> str:
        self.context += "\n\nUSER REPLY:\n" + reply.strip()
        self._log("fold the reply into the run context and re-check",
                  f"received reply to round {self.rounds}", reply.strip())
        return self._advance()

    def apply_feedback(self, feedback: str) -> Plan:
        if self.plan is None:
            raise RuntimeError("no plan to revise")
        before_id, before_rev = id(self.plan), self.plan.revision
        import copy as _copy
        self.snapshots.append(_copy.deepcopy(self.plan.body))
        self._log("apply user feedback to the existing plan",
                  f"feedback received: {feedback.strip()!r}", None)
        self.plan = revise(self.plan, feedback)
        new_ops = [p for p in self.plan.patch_history if p["revision"] == self.plan.revision]
        self._log("confirm the revision touched only what was asked",
                  "mutated the existing plan object in place (not regenerated)",
                  {"same_object": id(self.plan) == before_id,
                   "revision": f"r{before_rev} -> r{self.plan.revision}",
                   "operations": new_ops},
                  True, "revision applied without restarting the loop")
        return self.plan

    def diff_last_revision(self) -> Dict[str, List[str]]:
        """Which top-level keys the last feedback round touched, and which it did not."""
        if not self.snapshots or self.plan is None:
            return {"changed": [], "added": [], "untouched": []}
        before, after = self.snapshots[-1], self.plan.body
        return {"changed": [k for k in after if k in before and before[k] != after[k]],
                "added": [k for k in after if k not in before],
                "untouched": [k for k in after if k in before and before[k] == after[k]]}


PLANNER_EXAMPLE_REQUESTS = [
    "Analyze our college performance.",
    "Give me a performance report for the Governing Council.",
    "Prepare a two-page decision brief on Placement and Research for academic year 2025-26, "
    "benchmarked against NIRF and our strategic plan, reporting placement percentage, "
    "publications and carbon footprint, with department-level drill-down for every KPI.",
]
