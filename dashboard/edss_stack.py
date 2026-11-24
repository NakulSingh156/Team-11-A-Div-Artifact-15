"""edss_stack — the capabilities Labs 3, 4 and 5 added, in one importable layer.

Worklet 15 · Executive Decision Support System · Agentic AI (26ECAC401)

    Lab 3  Skill            reusable, schema-typed capability packages
    Lab 4  RunState/Archive short-term run state vs the long-term baseline,
                            with tag and TF-IDF-similarity retrieval
    Lab 5  MCPServer/Client one typed, scoped connector over file + SQLite + API

Labs 6-8 bind these together rather than restating them: Lab 6 puts a runtime
around them, Lab 7 wires them into a node graph, Lab 8 runs them in parallel.

Written to disk by the first code cells of Labs 6-8 so each notebook is
standalone.
"""

import csv
import io
import json
import math
import re
import sqlite3
import threading
import textwrap
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from edss_core import (DOMAINS, KPI_DEFINITIONS, REPORTING_PERIOD, ACCESS_REGISTER,
                       DEPARTMENT_REPORTS_CSV, NUMERIC_COLUMNS, BENCHMARK_API_DB,
                       ToolRouter, Connector, ToolError, ToolContractError,
                       compute_kpi, compare_to_target, validate_kpi_result,
                       _typed_rows)

_JSON_TYPES = {"string": str, "number": (int, float), "integer": int,
               "boolean": bool, "array": list, "object": dict}


# ==========================================================================
# LAB 3 — the Skill framework
# ==========================================================================

class SkillContractError(Exception):
    """Raised when a skill's input or output violates its declared schema."""


@dataclass
class Skill:
    """A reusable capability package.

    name          stable identifier
    description   what it does, in one line
    instructions  the procedure it follows — the part a human or a model reads
    constraints   what it must never do
    input_schema  typed contract, validated BEFORE the skill runs
    output_schema typed contract, validated AFTER it runs
    tools         the tool names it is permitted to call
    """
    name: str
    description: str
    instructions: str
    constraints: List[str]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    tools: List[str]
    _fn: Optional[Callable] = None
    invocations: List[Dict[str, Any]] = field(default_factory=list)

    # ---- schema validation, both directions ----------------------------
    def _validate(self, payload: Dict[str, Any], schema: Dict[str, Any],
                  where: str) -> None:
        props, required = schema.get("properties", {}), schema.get("required", [])
        for name in required:
            if name not in payload:
                raise SkillContractError(
                    f"{self.name} {where}: missing required field '{name}'")
        for name, value in payload.items():
            if name not in props:
                raise SkillContractError(
                    f"{self.name} {where}: unexpected field '{name}'; "
                    f"accepts {sorted(props)}")
            expected = _JSON_TYPES.get(props[name]["type"])
            if expected and not isinstance(value, expected):
                raise SkillContractError(
                    f"{self.name} {where}.{name}: expected {props[name]['type']}, "
                    f"got {type(value).__name__}")
            if props[name].get("enum") and value not in props[name]["enum"]:
                raise SkillContractError(
                    f"{self.name} {where}.{name}: {value!r} not in "
                    f"{props[name]['enum']}")

    def run(self, router: "ToolRouter", **inputs) -> Dict[str, Any]:
        self._validate(inputs, self.input_schema, "input")
        before = len(router.trace)
        result = self._fn(router, **inputs)
        self._validate(result, self.output_schema, "output")
        used = [e["tool"] for e in router.trace[before:]]
        stray = [t for t in used if t not in self.tools]
        if stray:
            raise SkillContractError(
                f"{self.name} called tools outside its declared surface: {stray}")
        self.invocations.append({"inputs": inputs, "tools_used": used,
                                 "output_keys": sorted(result)})
        return result

    def card(self) -> str:
        return (f"SKILL  {self.name}\n"
                f"  {self.description}\n"
                f"  inputs   : {list(self.input_schema.get('properties', {}))}"
                f"  (required: {self.input_schema.get('required', [])})\n"
                f"  outputs  : {list(self.output_schema.get('properties', {}))}\n"
                f"  tools    : {self.tools}\n"
                f"  constraints:\n"
                + "\n".join(f"    - {c}" for c in self.constraints))


SKILL_REGISTRY: Dict[str, Skill] = {}


def register(skill: Skill) -> Skill:
    SKILL_REGISTRY[skill.name] = skill
    return skill


# ==========================================================================
# LAB 3 — skill: review_domain
# ==========================================================================

REVIEW_DOMAIN = Skill(
    name="review_domain",
    description="Review one domain's approved KPIs against their targets, with "
                "per-department evidence.",
    instructions=(
        "1. Read the department rows for the requested period through the connector.\n"
        "2. If a department filter is supplied, narrow to it and refuse an empty subset.\n"
        "3. For every approved KPI belonging to the domain: read its definition, compute\n"
        "   it with the registered formula, and compare it to its approved target.\n"
        "4. Return the KPI set with variance, status, source system and figure status.\n"
        "5. Report which KPIs are off target; never recommend an action — that is the\n"
        "   Report Generation Agent's job, behind the human gate."),
    constraints=[
        "Use only approved KPI definitions; never invent a formula.",
        "Never average department percentages — aggregate raw counts.",
        "Label any figure that is not final; never present it as an actual.",
        "Emit no recommendation and take no action.",
    ],
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "enum": DOMAINS},
            "period": {"type": "string"},
            "category": {"type": "string", "enum": ["circuit", "core"]},
        },
        "required": ["domain", "period"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "period": {"type": "string"},
            "scope": {"type": "string"},
            "kpis": {"type": "array"},
            "off_target": {"type": "array"},
            "headline": {"type": "string"},
            "provisional": {"type": "boolean"},
        },
        "required": ["domain", "period", "scope", "kpis", "off_target", "headline",
                     "provisional"],
    },
    tools=["read_department_reports", "filter_rows", "read_kpi_definitions",
           "compute_kpi", "compare_to_target"],
)


def _review_domain(router, domain, period, category=None):
    connector = Connector(router)
    rows = connector.read("department reports",
                          reason=f"review_domain({domain}): per-department metrics",
                          period=period)["rows"]
    scope = "all departments"
    if category:
        rows = router.call("filter_rows",
                           reason=f"review_domain({domain}): narrow to {category} branches",
                           rows=rows, field="category", value=category)["rows"]
        scope = f"{category} departments"

    kpi_ids = [k for k, d in KPI_DEFINITIONS.items() if d["domain"] == domain]
    kpis, provisional = [], False
    for kpi_id in kpi_ids:
        connector.read("institutional KPIs & dashboards",
                       reason=f"{kpi_id}: approved formula and target",
                       kpi_ids=[kpi_id])
        computed = router.call("compute_kpi", reason=f"{kpi_id}: apply the formula",
                               kpi_id=kpi_id, rows=rows)
        compared = router.call("compare_to_target", reason=f"{kpi_id}: variance vs target",
                               kpi_id=kpi_id, value=computed["value"])
        gate = validate_kpi_result(computed, compared)
        if not gate.valid:
            raise ToolError(f"validation gate failed for {kpi_id}: {gate.failing}")
        provisional = provisional or computed["figure_status"] != "final"
        kpis.append({
            "kpi_id": kpi_id, "name": computed["name"], "value": computed["value"],
            "unit": computed["unit"], "target": compared["target"],
            "target_source": compared["target_source"], "variance": compared["variance"],
            "status": compared["status"], "formula": computed["formula"],
            "source_system": computed["source_system"],
            "figure_status": computed["figure_status"],
            "rounding_warning": compared["rounding_warning"],
            "evidence": computed["evidence"],
        })

    off = [k["kpi_id"] for k in kpis if k["status"] != "on target"]
    headline = (f"{domain}: {len(off)} of {len(kpis)} KPIs off target across {scope} "
                f"for {period}." + (" Figures include a provisional source."
                                    if provisional else ""))
    return {"domain": domain, "period": period, "scope": scope, "kpis": kpis,
            "off_target": off, "headline": headline, "provisional": provisional}


REVIEW_DOMAIN._fn = _review_domain
register(REVIEW_DOMAIN)


# ==========================================================================
# LAB 3 — skill: format_document
# ==========================================================================

FORMAT_DOCUMENT = Skill(
    name="format_document",
    description="Render a titled, sectioned payload as a leadership-ready document "
                "in a chosen template.",
    instructions=(
        "1. Emit the title, then the metadata block as key: value lines.\n"
        "2. Emit each section in order: a heading, then its bullets, then its table\n"
        "   if it has one.\n"
        "3. In 'brief' template, number the sections; in 'memo' template, do not.\n"
        "4. Append the source line verbatim if one is supplied.\n"
        "5. Reproduce every value exactly as given — never reformat a number."),
    constraints=[
        "Never compute, round or reword a value; this skill only lays out.",
        "Never drop a section or a caveat that was passed in.",
        "Stay domain-agnostic: no KPI, department or worklet logic here.",
    ],
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "meta": {"type": "object"},
            "sections": {"type": "array"},
            "template": {"type": "string", "enum": ["brief", "memo"]},
            "source_line": {"type": "string"},
        },
        "required": ["title", "sections"],
    },
    output_schema={
        "type": "object",
        "properties": {"document": {"type": "string"},
                       "template": {"type": "string"},
                       "section_count": {"type": "integer"},
                       "line_count": {"type": "integer"}},
        "required": ["document", "template", "section_count", "line_count"],
    },
    tools=[],          # a pure formatting skill: it calls no tool at all
)


def _format_document(router, title, sections, meta=None, template="brief",
                     source_line=None):
    out = [title, "=" * len(title)]
    for k, v in (meta or {}).items():
        out.append(f"{k}: {v}")
    out.append("")
    for i, sec in enumerate(sections, 1):
        heading = sec.get("heading", "")
        out.append(f"{i}. {heading}" if template == "brief" else heading.upper())
        out.append("-" * 70)
        for b in sec.get("bullets", []):
            out.append(textwrap.fill(f"  - {b}", 88, subsequent_indent="    "))
        table = sec.get("table")
        if table:
            widths = [max(len(str(r[c])) for r in [dict(zip(table["columns"],
                                                            table["columns"]))] + table["rows"])
                      for c in table["columns"]]
            out.append("  " + "  ".join(str(c).ljust(w) for c, w in
                                        zip(table["columns"], widths)))
            for row in table["rows"]:
                out.append("  " + "  ".join(str(row[c]).ljust(w) for c, w in
                                            zip(table["columns"], widths)))
        out.append("")
    if source_line:
        out.append(source_line)
    document = "\n".join(out)
    return {"document": document, "template": template,
            "section_count": len(sections), "line_count": len(document.splitlines())}


FORMAT_DOCUMENT._fn = _format_document
register(FORMAT_DOCUMENT)


# ==========================================================================
# LAB 4 — the memory split
# ==========================================================================

class ArchiveImmutableError(Exception):
    """Raised on any attempt to edit a record that is already archived."""


@dataclass
class RunState:
    """Short-term working memory. One run. Thrown away at the end."""
    run_id: str
    period: str
    draft: Dict[str, Any] = field(default_factory=dict)
    scratch: Dict[str, Any] = field(default_factory=dict)
    retrieved: List[Dict[str, Any]] = field(default_factory=list)

    def note(self, key: str, value: Any) -> None:
        self.scratch[key] = value

    def summary(self) -> str:
        return (f"RunState({self.run_id}) draft_keys={sorted(self.draft)} "
                f"scratch_keys={sorted(self.scratch)} retrieved={len(self.retrieved)}")


class Archive:
    """Long-term store. Append-only; every write is versioned and timestamped."""

    def __init__(self):
        self._records: Dict[str, Dict[str, Any]] = {}
        self.writes: List[Dict[str, Any]] = []

    # ---- writing -------------------------------------------------------
    def put(self, record_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        if record_id in self._records:
            raise ArchiveImmutableError(
                f"'{record_id}' is already archived; the archive is append-only. "
                f"Write a new version id instead of editing the baseline.")
        stored = {**record, "record_id": record_id,
                  "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._records[record_id] = stored
        self.writes.append({"record_id": record_id, "tags": record.get("tags", []),
                            "at": stored["archived_at"]})
        return stored

    # ---- reading -------------------------------------------------------
    def get(self, record_id: str) -> Dict[str, Any]:
        # A COPY, so a caller mutating what it read cannot corrupt the baseline.
        return json.loads(json.dumps(self._records[record_id]))

    def all(self) -> List[Dict[str, Any]]:
        return [self.get(rid) for rid in self._records]

    def __len__(self):
        return len(self._records)

    def __contains__(self, record_id):
        return record_id in self._records


# ==========================================================================
# LAB 4 — what is in the archive
# ==========================================================================

archive = Archive()

PRIOR_BRIEFS = [
    {"record_id": "BRIEF-2023-24-Q4",
     "type": "decision_brief", "period": "2023-24",
     "title": "Placement recovery after the 2023 hiring slowdown",
     "tags": ["placement", "core-branches", "recruiter-outreach", "below-target"],
     "summary": "Placement closed at 71.80% against an 80% target. Core branches drove "
                "the gap; circuit branches held. The Council approved a recruiter "
                "outreach drive and deferred the package target.",
     "decisions": ["Approved INR 12 lakh recruiter outreach budget",
                   "Deferred the average-package target by one year"],
     "outcome": "Placement rose to 73.50% the following year — short of target but "
                "the trend reversed. The wider recruiter pool brought in lower-paying "
                "offers, and average package began to slide."},
    {"record_id": "BRIEF-2024-25-Q2",
     "type": "decision_brief", "period": "2024-25",
     "title": "Research output against the NIRF submission",
     "tags": ["research", "publications", "citations", "nirf", "below-target"],
     "summary": "Publications per faculty stood at 1.05 against a 1.50 target and "
                "citations per faculty at 6.40. The Council approved a seed-grant "
                "scheme and asked for a per-department breakdown each quarter.",
     "decisions": ["Approved a seed-grant scheme for research-active faculty",
                   "Made department-level drill-down mandatory for research KPIs"],
     "outcome": "Publications rose to 1.12; the reporting change stuck and is now "
                "standing practice."},
    {"record_id": "BRIEF-2024-25-Q4",
     "type": "decision_brief", "period": "2024-25",
     "title": "Budget utilisation and the unreconciled Q4 position",
     "tags": ["finance", "budget-utilisation", "provisional", "reconciliation"],
     "summary": "Utilisation was reported at 88.10% but Q4 was unreconciled at the time "
                "of review. The Council declined to act on a provisional figure and "
                "deferred the decision to the post-audit cycle.",
     "decisions": ["Deferred all budget reallocation until the books closed",
                   "Required provisional figures to be labelled on the face of the brief"],
     "outcome": "Final utilisation came in at 86.90% — 1.2 points below the provisional "
                "figure, vindicating the deferral."},
    {"record_id": "BRIEF-2024-25-Q3",
     "type": "decision_brief", "period": "2024-25",
     "title": "Pass percentage and the rounding dispute",
     "tags": ["academic", "pass-percentage", "rounding", "at-risk"],
     "summary": "Pass percentage was circulated as '92%' when the unrounded figure was "
                "91.60%, which is below the 92.00% target. The Council directed that "
                "KPI figures be reported unrounded.",
     "decisions": ["Directed that all KPI figures be reported unrounded",
                   "Ordered remedial coaching in the two weakest departments"],
     "outcome": "The reporting rule is now enforced by the KPI engine itself."},
]

PRIOR_KPI_SNAPSHOTS = [
    {"record_id": "KPI-SNAPSHOT-2023-24", "type": "kpi_snapshot", "period": "2023-24",
     "title": "Institution KPI snapshot 2023-24",
     "tags": ["kpi-snapshot", "closed-year", "baseline"],
     "values": {"KPI-A1": 90.40, "KPI-A2": 2.38, "KPI-R1": 0.98, "KPI-R2": 5.90,
                "KPI-R3": 198.0, "KPI-P1": 71.80, "KPI-P2": 7.10, "KPI-P3": 64.20,
                "KPI-F1": 84.30}},
    {"record_id": "KPI-SNAPSHOT-2024-25", "type": "kpi_snapshot", "period": "2024-25",
     "title": "Institution KPI snapshot 2024-25",
     "tags": ["kpi-snapshot", "closed-year", "baseline"],
     "values": {"KPI-A1": 91.20, "KPI-A2": 2.44, "KPI-R1": 1.12, "KPI-R2": 6.40,
                "KPI-R3": 221.5, "KPI-P1": 73.50, "KPI-P2": 7.95, "KPI-P3": 69.10,
                "KPI-F1": 86.90}},
]

for rec in PRIOR_BRIEFS + PRIOR_KPI_SNAPSHOTS:
    archive.put(rec["record_id"], {k: v for k, v in rec.items() if k != "record_id"})


# ==========================================================================
# LAB 4 — retrieval by tag
# ==========================================================================

def retrieve_by_tags(store: Archive, tags: List[str], mode: str = "any",
                     record_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """mode='any' -> union; mode='all' -> records carrying every tag."""
    if mode not in ("any", "all"):
        raise ValueError("mode must be 'any' or 'all'")
    wanted = {t.lower() for t in tags}
    hits = []
    for rec in store.all():
        if record_type and rec.get("type") != record_type:
            continue
        have = {t.lower() for t in rec.get("tags", [])}
        overlap = wanted & have
        if (mode == "any" and overlap) or (mode == "all" and wanted <= have):
            hits.append({**rec, "matched_tags": sorted(overlap),
                         "tag_score": len(overlap) / len(wanted)})
    return sorted(hits, key=lambda r: -r["tag_score"])


# ==========================================================================
# LAB 4 — retrieval by similarity
# ==========================================================================

STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "was",
             "were", "is", "are", "be", "been", "by", "with", "that", "this", "it",
             "as", "from", "but", "not", "no", "we", "our", "its", "their", "has",
             "had", "have", "than", "then", "so", "which", "when", "all", "one"}


def tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9\-]+", text.lower())
            if t not in STOPWORDS and len(t) > 2]


class SimilarityIndex:
    """TF-IDF vectors + cosine similarity over the archive's text."""

    def __init__(self, records: List[Dict[str, Any]]):
        self.records = records
        self.docs = [self._text(r) for r in records]
        self.tokens = [tokenize(d) for d in self.docs]
        n = len(self.tokens)
        df = Counter(t for toks in self.tokens for t in set(toks))
        # Smoothed IDF, so a term in every document still carries a little weight.
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        self.vectors = [self._vector(toks) for toks in self.tokens]

    @staticmethod
    def _text(rec: Dict[str, Any]) -> str:
        parts = [rec.get("title", ""), rec.get("summary", ""),
                 " ".join(rec.get("tags", [])), " ".join(rec.get("decisions", [])),
                 rec.get("outcome", "")]
        return " ".join(p for p in parts if p)

    def _vector(self, toks: List[str]) -> Dict[str, float]:
        if not toks:
            return {}
        tf = Counter(toks)
        vec = {t: (c / len(toks)) * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        small, large = (a, b) if len(a) < len(b) else (b, a)
        return sum(v * large.get(t, 0.0) for t, v in small.items())

    def query(self, text: str, k: int = 3,
              record_type: Optional[str] = None) -> List[Dict[str, Any]]:
        qv = self._vector(tokenize(text))
        scored = []
        for rec, vec in zip(self.records, self.vectors):
            if record_type and rec.get("type") != record_type:
                continue
            scored.append({**rec, "similarity": round(self._cosine(qv, vec), 4)})
        return sorted(scored, key=lambda r: -r["similarity"])[:k]


index = SimilarityIndex(archive.all())


# ==========================================================================
# LAB 4 — hybrid retrieval
# ==========================================================================

def retrieve(store: Archive, idx: SimilarityIndex, text: str,
             tags: Optional[List[str]] = None, k: int = 3,
             record_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tag filter first (precision), then similarity rank (relevance)."""
    pool = (retrieve_by_tags(store, tags, "any", record_type) if tags
            else [r for r in store.all()
                  if not record_type or r.get("type") == record_type])
    if not pool:
        return []
    sub = SimilarityIndex(pool)
    hits = sub.query(text, k=k, record_type=record_type)
    by_id = {h["record_id"]: h for h in hits}
    for p in pool:
        if p["record_id"] in by_id and "tag_score" in p:
            by_id[p["record_id"]]["tag_score"] = p["tag_score"]
    return hits


# ==========================================================================
# LAB 5 — the MCP protocol
# ==========================================================================

# ---- error codes: one vocabulary for every backend ------------------------
E_UNKNOWN_RESOURCE = "UNKNOWN_RESOURCE"
E_UNAUTHORIZED     = "UNAUTHORIZED"
E_FORBIDDEN_SCOPE  = "FORBIDDEN_SCOPE"
E_BAD_REQUEST      = "BAD_REQUEST"
E_NOT_FOUND        = "NOT_FOUND"
E_BACKEND_FAILURE  = "BACKEND_FAILURE"


class MCPError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass
class Resource:
    """One advertised capability of the server."""
    name: str
    description: str
    params: Dict[str, Any]          # typed parameter schema
    returns: str
    scope: str                      # the scope a token must hold
    backend: str                    # which backend currently serves it
    handler: Callable = None

    def manifest(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "params": self.params, "returns": self.returns,
                "required_scope": self.scope, "served_by": self.backend}


class MCPServer:
    """One server, many backends. Agents never see which is which."""

    def __init__(self, name: str):
        self.name = name
        self.resources: Dict[str, Resource] = {}
        self.tokens: Dict[str, Dict[str, Any]] = {}
        self.log: List[Dict[str, Any]] = []
        # Lab 8 runs eight department agents at once and every one of them
        # calls this server. Sequence numbers are handed out at append time,
        # under a lock, so two concurrent calls cannot both be "seq 12".
        self._log_lock = threading.Lock()

    # ---- registration & auth -------------------------------------------
    def expose(self, resource: Resource) -> None:
        self.resources[resource.name] = resource

    def issue_token(self, token: str, holder: str, scopes: List[str]) -> None:
        self.tokens[token] = {"holder": holder, "scopes": set(scopes)}

    def describe(self) -> Dict[str, Any]:
        """Capability discovery — what a client may call, without calling it."""
        return {"server": self.name,
                "resources": [r.manifest() for r in self.resources.values()]}

    # ---- the single entry point ----------------------------------------
    def call(self, token: str, resource: str, **params) -> Dict[str, Any]:
        started = time.perf_counter()
        entry = {"resource": resource,
                 "holder": self.tokens.get(token, {}).get("holder", "<unknown>"),
                 "params": {k: (f"<{len(v)} rows>" if isinstance(v, list) else v)
                            for k, v in params.items()},
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

        def finish(ok, code=None, note=""):
            entry.update({"ok": ok, "error_code": code, "note": note,
                          "ms": round((time.perf_counter() - started) * 1000, 2)})
            with self._log_lock:
                entry["seq"] = len(self.log) + 1
                self.log.append(entry)

        if token not in self.tokens:
            finish(False, E_UNAUTHORIZED)
            raise MCPError(E_UNAUTHORIZED, "token not recognised by this server")
        if resource not in self.resources:
            finish(False, E_UNKNOWN_RESOURCE)
            raise MCPError(E_UNKNOWN_RESOURCE,
                           f"'{resource}' is not exposed; call describe() to see "
                           f"{sorted(self.resources)}")
        res = self.resources[resource]
        if res.scope not in self.tokens[token]["scopes"]:
            finish(False, E_FORBIDDEN_SCOPE)
            raise MCPError(E_FORBIDDEN_SCOPE,
                           f"'{resource}' needs scope '{res.scope}'; this token holds "
                           f"{sorted(self.tokens[token]['scopes'])}")
        for p, spec in res.params.items():
            if spec.get("required") and p not in params:
                finish(False, E_BAD_REQUEST)
                raise MCPError(E_BAD_REQUEST, f"{resource}: missing parameter '{p}'")
        try:
            data = res.handler(**params)
        except MCPError as exc:
            finish(False, exc.code, exc.message)
            raise
        except Exception as exc:
            finish(False, E_BACKEND_FAILURE, str(exc))
            raise MCPError(E_BACKEND_FAILURE, f"{res.backend} failed: {exc}")
        entry["served_by"] = res.backend
        finish(True)
        # The envelope is identical whatever the backend was.
        return {"ok": True, "resource": resource, "served_by": res.backend, "data": data,
                "meta": {"server": self.name, "at": entry["at"]}}


class MCPClient:
    """What an agent holds. It knows a token and resource names — nothing else."""

    def __init__(self, server: MCPServer, token: str):
        self._server, self._token = server, token

    def describe(self) -> Dict[str, Any]:
        return self._server.describe()

    def read(self, resource: str, **params) -> Any:
        return self._server.call(self._token, resource, **params)["data"]


# ==========================================================================
# LAB 5 — file, SQLite and API backends
# ==========================================================================

# The source files are a STATIC dataset that lives in one place, next to the
# project rather than next to whatever directory you happened to launch from.
# Path("lab5_sources") was relative to the cwd, which silently produced a
# separate copy per launch directory.
WORKDIR = Path(__file__).resolve().parent.parent / "lab5_sources"
WORKDIR.mkdir(parents=True, exist_ok=True)
DEPT_DETAIL_DIR = WORKDIR / "departments"

# ---- backend 1: a FILE ----------------------------------------------------
# Written once, then left alone. Rewriting on every import would silently throw
# away any edit made to the data between runs, and a dataset you cannot edit is
# not really a dataset.
CSV_PATH = WORKDIR / "department_reports_2025_26.csv"
if not CSV_PATH.exists():
    CSV_PATH.write_text(DEPARTMENT_REPORTS_CSV)


def _cast(row: Dict[str, str]) -> Dict[str, Any]:
    out = dict(row)
    for col, caster in NUMERIC_COLUMNS.items():
        if col in out:
            out[col] = caster(out[col])
    return out


class FileBackend:
    name = "file:csv"

    def __init__(self, path: Path):
        self.path = path

    def department_reports(self, period: str, category: str = None) -> Dict[str, Any]:
        if period != REPORTING_PERIOD:
            raise MCPError(E_NOT_FOUND, f"no export on disk for '{period}'")
        with self.path.open() as fh:
            rows = [_cast(r) for r in csv.DictReader(fh)]
        if category:
            rows = [r for r in rows if r["category"] == category]
            if not rows:
                raise MCPError(E_NOT_FOUND, f"no departments in category '{category}'")
        return {"rows": rows, "row_count": len(rows), "period": period,
                "source_system": "Department reports export (CSV on disk)"}


# ---- backend 2: SQLite ----------------------------------------------------
DB_PATH = WORKDIR / "institution.db"
if not DB_PATH.exists():                      # built once; see CSV_PATH above
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
CREATE TABLE kpi_definition (
        kpi_id TEXT PRIMARY KEY, name TEXT, domain TEXT, unit TEXT, formula TEXT,
        target REAL, target_source TEXT, source_system TEXT, figure_status TEXT,
        caveat TEXT);
CREATE TABLE department_report (
        dept_code TEXT PRIMARY KEY, dept_name TEXT, category TEXT, period TEXT,
        payload TEXT);
    """)
    conn.executemany(
        "INSERT INTO kpi_definition VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(k, d["name"], d["domain"], d["unit"], d["formula"], d["target"],
          d["target_source"], d["source_system"], d.get("figure_status", "final"),
          d.get("caveat")) for k, d in KPI_DEFINITIONS.items()])
    conn.executemany(
        "INSERT INTO department_report VALUES (?,?,?,?,?)",
        [(r["dept_code"], r["dept_name"], r["category"], REPORTING_PERIOD,
          json.dumps(r))
         for r in (_cast(x) for x in csv.DictReader(CSV_PATH.open()))])
    conn.commit()
    conn.close()


class SQLiteBackend:
    name = "sqlite"

    def __init__(self, path: Path):
        self.path = path

    def _rows(self, sql: str, args=()) -> List[sqlite3.Row]:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def kpi_definitions(self, kpi_ids: List[str] = None) -> Dict[str, Any]:
        if kpi_ids:
            marks = ",".join("?" * len(kpi_ids))
            rows = self._rows(
                f"SELECT * FROM kpi_definition WHERE kpi_id IN ({marks})", kpi_ids)
            if len(rows) != len(kpi_ids):
                found = {r["kpi_id"] for r in rows}
                raise MCPError(E_NOT_FOUND,
                               f"unknown KPI id(s): {sorted(set(kpi_ids) - found)}")
        else:
            rows = self._rows("SELECT * FROM kpi_definition ORDER BY kpi_id")
        defs = {}
        for r in rows:
            d = dict(KPI_DEFINITIONS[r["kpi_id"]])   # formula fields for the calculator
            d.update({"name": r["name"], "domain": r["domain"], "target": r["target"],
                      "target_source": r["target_source"],
                      "source_system": r["source_system"]})
            defs[r["kpi_id"]] = d
        return {"definitions": defs, "count": len(defs),
                "source_system": "Institutional KPI register (SQLite)"}

    # The SAME resource the file backend serves — used in Cell 6 to swap sources.
    def department_reports(self, period: str, category: str = None) -> Dict[str, Any]:
        sql = "SELECT payload FROM department_report WHERE period = ?"
        args = [period]
        if category:
            sql += " AND category = ?"
            args.append(category)
        rows = [json.loads(r["payload"]) for r in self._rows(sql, args)]
        if not rows:
            raise MCPError(E_NOT_FOUND,
                           f"no rows for period '{period}'"
                           + (f" and category '{category}'" if category else ""))
        return {"rows": rows, "row_count": len(rows), "period": period,
                "source_system": "Department reports (SQLite table)"}


# ---- backend 3: a mock HTTP API -------------------------------------------
class APIBackend:
    name = "http:benchmark-api"
    LATENCY_S = 0.02

    def external_benchmark(self, kpi_id: str) -> Dict[str, Any]:
        time.sleep(self.LATENCY_S)              # a network call is not free
        if kpi_id not in KPI_DEFINITIONS:
            raise MCPError(E_BAD_REQUEST, f"'{kpi_id}' is not a known KPI id")
        record = BENCHMARK_API_DB.get(kpi_id)
        if record is None:
            raise MCPError(E_NOT_FOUND,
                           f"no published external benchmark for {kpi_id} "
                           f"({KPI_DEFINITIONS[kpi_id]['name']})")
        return {"kpi_id": kpi_id, **record,
                "source_system": "External benchmark API (NIRF cohort)"}


class DeptDetailBackend:
    """Backend 4: the per-department fact tables, read on demand.

    One CSV per department under lab5_sources/departments/, in long form —
    624 rows across 8 departments, 2 periods and 4 domains. Nothing is held in
    memory between calls: each call opens only the files it needs, so the files
    on disk are always what the agent sees, and editing one changes the next
    answer without a restart.

    Every row carries its own `aggregation` rule (sum / weighted_mean /
    latest), so a caller cannot roll a mean up as though it were a total.
    """

    name = "file:csv-detail"

    def __init__(self, directory: Path):
        self.dir = directory

    def _depts(self) -> List[str]:
        return sorted(p.stem for p in self.dir.glob("*.csv"))

    def department_detail(self, dept_code: str = None, period: str = None,
                          domain: str = None, metric: str = None) -> Dict[str, Any]:
        available = self._depts()
        if not available:
            raise MCPError(E_NOT_FOUND,
                           f"no department files under {self.dir}; run "
                           f"tools/build_dataset.py once to create them")
        wanted = available
        if dept_code:
            wanted = [d for d in available if d.upper() == dept_code.upper()]
            if not wanted:
                raise MCPError(E_NOT_FOUND,
                               f"unknown department '{dept_code}'; this server "
                               f"serves {available}")
        rows: List[Dict[str, Any]] = []
        for dept in wanted:
            with (self.dir / f"{dept}.csv").open() as fh:
                for row in csv.DictReader(fh):
                    row["value"] = float(row["value"])
                    if row["unit"] == "count":
                        row["value"] = int(row["value"])
                    rows.append(row)
        for field, want in (("period", period), ("domain", domain),
                            ("metric", metric)):
            if want:
                rows = [r for r in rows if r[field].lower() == str(want).lower()]
                if not rows:
                    raise MCPError(E_NOT_FOUND,
                                   f"no rows with {field}='{want}' in "
                                   f"{wanted if dept_code else 'any department'}")
        return {"rows": rows, "row_count": len(rows),
                "departments": sorted({r["dept_code"] for r in rows}),
                "periods": sorted({r["period"] for r in rows}),
                "domains": sorted({r["domain"] for r in rows}),
                "filters": {"dept_code": dept_code, "period": period,
                            "domain": domain, "metric": metric},
                "source_system": "Department fact tables (CSV on disk)"}


file_backend, sqlite_backend, api_backend = (FileBackend(CSV_PATH),
                                             SQLiteBackend(DB_PATH), APIBackend())
detail_backend = DeptDetailBackend(DEPT_DETAIL_DIR)


# ==========================================================================
# LAB 5 — expose resources, issue scoped tokens
# ==========================================================================

server = MCPServer("edss-connector")

server.expose(Resource(
    name="department_reports",
    description="Per-department metric rows for one reporting period.",
    params={"period": {"type": "string", "required": True},
            "category": {"type": "string", "required": False,
                         "enum": ["circuit", "core"]}},
    returns="{rows, row_count, period, source_system}",
    scope="read:departments", backend=file_backend.name,
    handler=file_backend.department_reports))

server.expose(Resource(
    name="department_detail",
    description="Per-department fact rows: one row per department, period, "
                "domain, metric and sub-period. Filter by any combination.",
    params={"dept_code": {"type": "string", "required": False},
            "period": {"type": "string", "required": False,
                       "enum": ["2025-26", "2024-25"]},
            "domain": {"type": "string", "required": False,
                       "enum": ["Academic", "Research", "Placement", "Finance"]},
            "metric": {"type": "string", "required": False}},
    returns="{rows, row_count, departments, periods, domains, filters, "
            "source_system}",
    scope="read:department-detail", backend=detail_backend.name,
    handler=detail_backend.department_detail))

server.expose(Resource(
    name="kpi_definitions",
    description="Approved institution KPI definitions: formula, unit, target, authority.",
    params={"kpi_ids": {"type": "array", "required": False}},
    returns="{definitions, count, source_system}",
    scope="read:kpi-register", backend=sqlite_backend.name,
    handler=sqlite_backend.kpi_definitions))

server.expose(Resource(
    name="external_benchmark",
    description="Published peer median for a KPI. Coverage is partial.",
    params={"kpi_id": {"type": "string", "required": True}},
    returns="{kpi_id, peer_median, cohort, year, source_system}",
    scope="read:benchmarks", backend=api_backend.name,
    handler=api_backend.external_benchmark))

# ---- scoped tokens: the Registrar's authorisation, expressed as data -------
server.issue_token("tok-coordinator", "apniLeap AURA Coordinator",
                   ["read:departments", "read:department-detail",
                    "read:kpi-register", "read:benchmarks"])
server.issue_token("tok-academic-agent", "Academic Agent",
                   ["read:departments", "read:department-detail",
                    "read:kpi-register"])                       # no benchmark access
server.issue_token("tok-intern", "Summer intern (read-only KPI register)",
                   ["read:kpi-register"])
# The Lab 8 department agents. One scope: their own fact rows. They cannot
# reach the KPI register, the benchmark API or the institution-wide aggregate,
# so a department agent physically cannot report an institution figure.
server.issue_token("tok-department-agent", "Department reporting agent",
                   ["read:department-detail"])

# ==========================================================================
# A ready-made client for the coordinator
# ==========================================================================

coordinator_client = MCPClient(server, "tok-coordinator")
department_agent_client = MCPClient(server, "tok-department-agent")
