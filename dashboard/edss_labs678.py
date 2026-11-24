"""edss_labs678 — the Lab 6, 7 and 8 machinery, importable.

    Lab 6  Runtime / Budget / CheckpointStore   budgets, audit, gates, crash-resume
    Lab 7  Graph / Node / Edge                  explicit wiring, back-edges, renderers
    Lab 8  Swarm / merge                        per-unit parallelism, retry, conflict merge

Extracted verbatim from the lab notebooks so the dashboard demonstrates the same
code that the notebooks are graded on.
"""

import json
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from edss_core import (DOMAINS, KPI_DEFINITIONS, REPORTING_PERIOD,
                       DEPARTMENT_REPORTS_CSV, _typed_rows, ToolRouter)
from edss_stack import (SKILL_REGISTRY, RunState, Archive, archive, index,
                        retrieve_by_tags, server, coordinator_client, MCPError,
                        MCPClient)


# ==========================================================================
# LAB 6 — runtime primitives
# ==========================================================================

class BudgetExceeded(Exception):
    """Raised when a run tries to spend past its granted budget."""


class ApprovalRequired(Exception):
    """Raised when an action needs a named human and has not got one."""


@dataclass
class Budget:
    """What this run is allowed to spend. Checked before every action."""
    max_actions: int = 50
    max_connector_calls: int = 60
    max_seconds: float = 120.0

    def report(self, used_actions, used_calls, elapsed) -> str:
        return (f"actions {used_actions}/{self.max_actions} · "
                f"connector {used_calls}/{self.max_connector_calls} · "
                f"{elapsed:.2f}s/{self.max_seconds:.0f}s")


@dataclass
class Action:
    """One unit of work the runtime will perform, log and checkpoint."""
    name: str
    kind: str                       # tool | skill | memory | compute | gate | publish
    description: str
    fn: Callable
    requires_approval: bool = False
    depends_on: List[str] = field(default_factory=list)


class CheckpointStore:
    """Run state persisted to disk after every completed action."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, run_id: str) -> Path:
        return self.dir / f"{run_id}.checkpoint.json"

    def save(self, run_id: str, payload: Dict[str, Any]) -> Path:
        p = self.path(run_id)
        p.write_text(json.dumps(payload, indent=2, default=str))
        return p

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        p = self.path(run_id)
        return json.loads(p.read_text()) if p.exists() else None

    def exists(self, run_id: str) -> bool:
        return self.path(run_id).exists()


# ==========================================================================
# LAB 6 — the Runtime
# ==========================================================================

class Runtime:
    """OpenCLA/OpenClaw-style runtime: skills + tools + memory + audit + gates."""

    def __init__(self, run_id: str, budget: Budget, checkpoints: CheckpointStore,
                 client=coordinator_client, skills=SKILL_REGISTRY,
                 store: Archive = archive):
        self.run_id = run_id
        self.budget = budget
        self.checkpoints = checkpoints
        self.client = client                 # Lab 5 — the only door to data
        self.skills = skills                 # Lab 3
        self.store = store                   # Lab 4
        self.router = ToolRouter(agent=f"runtime:{run_id}")
        self.state = RunState(run_id=run_id, period=REPORTING_PERIOD)
        self.audit: List[Dict[str, Any]] = []
        self.completed: List[str] = []
        self.results: Dict[str, Any] = {}
        self.approvals: Dict[str, str] = {}
        self.started = time.perf_counter()
        self.connector_calls_at_start = len(server.log)

    # ---- accounting ----------------------------------------------------
    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    @property
    def connector_calls(self) -> int:
        return len(server.log) - self.connector_calls_at_start

    def _check_budget(self, action_name: str) -> None:
        if len(self.completed) >= self.budget.max_actions:
            raise BudgetExceeded(f"{action_name}: action budget spent "
                                 f"({self.budget.max_actions})")
        if self.connector_calls >= self.budget.max_connector_calls:
            raise BudgetExceeded(f"{action_name}: connector-call budget spent "
                                 f"({self.budget.max_connector_calls})")
        if self.elapsed >= self.budget.max_seconds:
            raise BudgetExceeded(f"{action_name}: wall-time budget spent "
                                 f"({self.budget.max_seconds}s)")

    # ---- audit ---------------------------------------------------------
    def _log(self, action: Action, status: str, inputs, output, error=None,
             ms: float = 0.0) -> None:
        self.audit.append({
            "seq": len(self.audit) + 1, "run_id": self.run_id, "action": action.name,
            "kind": action.kind, "status": status,
            "inputs": inputs, "output": output, "error": error,
            "ms": round(ms, 2),
            "budget": self.budget.report(len(self.completed), self.connector_calls,
                                         self.elapsed),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    @staticmethod
    def _summarise(value, depth=0):
        if isinstance(value, dict):
            return {k: Runtime._summarise(v, depth + 1) for k, v in list(value.items())[:8]}
        if isinstance(value, list):
            return f"<{len(value)} items>" if len(value) > 4 else [
                Runtime._summarise(v, depth + 1) for v in value]
        if isinstance(value, str) and len(value) > 120:
            return value[:117] + "..."
        return value

    # ---- the single entry point ----------------------------------------
    def perform(self, action: Action, **inputs) -> Any:
        if action.name in self.completed:               # resume: never redo work
            self._log(action, "skipped (already completed)", inputs,
                      self._summarise(self.results.get(action.name)))
            return self.results[action.name]

        missing = [d for d in action.depends_on if d not in self.completed]
        if missing:
            raise RuntimeError(f"{action.name}: depends on {missing}, not yet completed")

        self._check_budget(action.name)

        if action.requires_approval and action.name not in self.approvals:
            self._log(action, "blocked: awaiting approval", inputs, None)
            raise ApprovalRequired(
                f"{action.name} requires a named human. Call runtime.approve("
                f"'{action.name}', by='...') and run again.")

        t0 = time.perf_counter()
        try:
            output = action.fn(self, **inputs)
        except Exception as exc:
            self._log(action, "failed", inputs, None, error=f"{type(exc).__name__}: {exc}",
                      ms=(time.perf_counter() - t0) * 1000)
            self.checkpoint()                            # a crash still checkpoints
            raise
        self.results[action.name] = output
        self.completed.append(action.name)
        self._log(action, "ok", inputs, self._summarise(output),
                  ms=(time.perf_counter() - t0) * 1000)
        self.checkpoint()
        return output

    # ---- gates ---------------------------------------------------------
    def approve(self, action_name: str, by: str) -> None:
        self.approvals[action_name] = by
        self.audit.append({"seq": len(self.audit) + 1, "run_id": self.run_id,
                           "action": action_name, "kind": "gate", "status": "approved",
                           "inputs": {"by": by}, "output": None, "error": None, "ms": 0.0,
                           "budget": "-",
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    # ---- checkpoint / resume -------------------------------------------
    def checkpoint(self) -> Path:
        return self.checkpoints.save(self.run_id, {
            "run_id": self.run_id, "period": self.state.period,
            "completed": self.completed, "results": self.results,
            "approvals": self.approvals, "audit": self.audit,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    @classmethod
    def resume(cls, run_id: str, budget: Budget, checkpoints: CheckpointStore) -> "Runtime":
        snap = checkpoints.load(run_id)
        if snap is None:
            raise FileNotFoundError(f"no checkpoint for run '{run_id}'")
        rt = cls(run_id, budget, checkpoints)
        rt.completed = list(snap["completed"])
        rt.results = dict(snap["results"])
        rt.approvals = dict(snap["approvals"])
        rt.audit = list(snap["audit"])
        rt.audit.append({"seq": len(rt.audit) + 1, "run_id": run_id, "action": "-",
                         "kind": "runtime", "status": "resumed from checkpoint",
                         "inputs": {"completed_before_crash": rt.completed},
                         "output": None, "error": None, "ms": 0.0, "budget": "-",
                         "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return rt


# ==========================================================================
# LAB 6 — the run plan
# ==========================================================================

FAULT = {"armed": True}


def a_load_departments(rt, **_):
    reports = rt.client.read("department_reports", period=rt.state.period)
    rt.state.note("row_count", reports["row_count"])
    return {"row_count": reports["row_count"], "source": reports["source_system"]}


def a_review_domains(rt, **_):
    out = {}
    for domain in DOMAINS:
        review = rt.skills["review_domain"].run(rt.router, domain=domain,
                                                period=rt.state.period)
        out[domain] = {"headline": review["headline"],
                       "off_target": review["off_target"],
                       "kpis": {k["kpi_id"]: k["value"] for k in review["kpis"]}}
    return out


def a_retrieve_baseline(rt, **_):
    snaps = retrieve_by_tags(rt.store, ["kpi-snapshot"], "any")
    return {s["period"]: s["values"] for s in snaps}


def a_compute_trend(rt, **_):
    if FAULT["armed"]:                      # <-- the simulated crash
        FAULT["armed"] = False
        raise MCPError("BACKEND_FAILURE",
                       "benchmark service dropped the connection mid-run")
    current = {k: v for d in rt.results["review_domains"].values()
               for k, v in d["kpis"].items()}
    base = rt.results["retrieve_baseline"]["2024-25"]
    return {k: {"now": round(current[k], 2), "prior": base[k],
                "yoy": round(current[k] - base[k], 2),
                "direction": "improving" if current[k] > base[k] else "declining"}
            for k in current}


def a_assemble_brief(rt, **_):
    trend = rt.results["compute_trend"]
    declining = [k for k, t in trend.items() if t["direction"] == "declining"]
    off = sorted({k for d in rt.results["review_domains"].values()
                  for k in d["off_target"]})
    doc = rt.skills["format_document"].run(
        rt.router,
        title=f"Executive decision brief — {rt.state.period}",
        meta={"Run": rt.run_id, "Status": "DRAFT — not circulated"},
        template="brief",
        sections=[
            {"heading": "Headline", "bullets":
                [d["headline"] for d in rt.results["review_domains"].values()]},
            {"heading": "Off target", "bullets": off},
            {"heading": "Declining year on year", "bullets": declining or ["none"]}])
    rt.state.draft = {"document": doc["document"], "status": "DRAFT"}
    return {"lines": doc["line_count"], "off_target": off, "declining": declining}


def a_human_gate(rt, **_):
    who = rt.approvals["human_gate"]
    rt.state.draft["status"] = "APPROVED"
    return {"approved_by": who, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def a_publish(rt, **_):
    return {"published": True, "version": 1,
            "circulated_to": "Governing Council",
            "approved_by": rt.results["human_gate"]["approved_by"]}


PLAN = [
    Action("load_departments", "tool", "Read department rows through the connector",
           a_load_departments),
    Action("review_domains", "skill", "Run the review_domain skill for all four domains",
           a_review_domains, depends_on=["load_departments"]),
    Action("retrieve_baseline", "memory", "Read closed-year KPI snapshots from the archive",
           a_retrieve_baseline, depends_on=["load_departments"]),
    Action("compute_trend", "compute", "Year-on-year movement per KPI",
           a_compute_trend, depends_on=["review_domains", "retrieve_baseline"]),
    Action("assemble_brief", "skill", "Render the brief with the format_document skill",
           a_assemble_brief, depends_on=["compute_trend"]),
    Action("human_gate", "gate", "Principal / Registrar approval",
           a_human_gate, requires_approval=True, depends_on=["assemble_brief"]),
    Action("publish", "publish", "Release the approved, versioned brief",
           a_publish, depends_on=["human_gate"]),
]


# ==========================================================================
# LAB 7 — graph primitives
# ==========================================================================

COORDINATOR, AGENT, JOIN, VALIDATION, GATE, PUBLISH = (
    "coordinator", "agent", "join", "validation", "gate", "publish")


class GraphError(Exception):
    pass


@dataclass
class Node:
    name: str
    kind: str
    label: str
    fn: Callable
    parallel_group: Optional[str] = None      # nodes sharing a group run together


@dataclass
class Edge:
    src: str
    dst: str
    condition: Optional[str] = None           # None = unconditional
    back_edge: bool = False                   # a loop back to an earlier node


class Graph:
    """An explicit node graph with parallel groups, conditional edges and back-edges."""

    def __init__(self, name: str, max_steps: int = 40):
        self.name = name
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self.routers: Dict[str, Callable] = {}   # node -> picks the condition label
        self.max_steps = max_steps
        self.trace: List[Dict[str, Any]] = []
        self.state: Dict[str, Any] = {}

    # ---- construction ---------------------------------------------------
    def add_node(self, node: Node) -> "Graph":
        self.nodes[node.name] = node
        return self

    def add_edge(self, src: str, dst: str, condition: str = None,
                 back_edge: bool = False) -> "Graph":
        for n in (src, dst):
            if n not in self.nodes:
                raise GraphError(f"edge references unknown node '{n}'")
        self.edges.append(Edge(src, dst, condition, back_edge))
        return self

    def set_router(self, node: str, router: Callable) -> "Graph":
        """A router returns the CONDITION LABEL to follow out of this node."""
        self.routers[node] = router
        return self

    # ---- static checks --------------------------------------------------
    def successors(self, node: str, condition: str = None) -> List[str]:
        return [e.dst for e in self.edges
                if e.src == node and (e.condition is None or e.condition == condition)]

    def validate(self, entry: str) -> Dict[str, Any]:
        """Reachability and wiring problems, found before anything runs."""
        seen, stack = set(), [entry]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(e.dst for e in self.edges if e.src == n)
        unreachable = sorted(set(self.nodes) - seen)
        dangling = sorted({e.dst for e in self.edges} - set(self.nodes))
        terminals = sorted(n for n in self.nodes
                           if not [e for e in self.edges if e.src == n])
        conditional_without_router = sorted(
            {e.src for e in self.edges if e.condition} - set(self.routers))
        return {"unreachable": unreachable, "dangling": dangling,
                "terminal_nodes": terminals,
                "conditional_edges_without_a_router": conditional_without_router,
                "ok": not (unreachable or dangling or conditional_without_router)}

    # ---- execution ------------------------------------------------------
    def _log(self, node: str, kind: str, note: str, ms: float, condition=None):
        self.trace.append({"step": len(self.trace) + 1, "node": node, "kind": kind,
                           "note": note, "condition_taken": condition,
                           "ms": round(ms, 2),
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    def run(self, entry: str, state: Dict[str, Any] = None) -> Dict[str, Any]:
        check = self.validate(entry)
        if not check["ok"]:
            raise GraphError(f"graph will not run: {check}")
        self.state = dict(state or {})
        current, steps = entry, 0

        while current is not None:
            steps += 1
            if steps > self.max_steps:
                raise GraphError(f"cycle budget of {self.max_steps} steps exhausted at "
                                 f"'{current}' — a back-edge is not converging")
            node = self.nodes[current]

            # --- parallel group: run every node in the group at once -------
            group = [n for n in self.nodes.values()
                     if node.parallel_group and n.parallel_group == node.parallel_group]
            t0 = time.perf_counter()
            if len(group) > 1:
                with ThreadPoolExecutor(max_workers=len(group)) as pool:
                    futures = {pool.submit(g.fn, self.state): g for g in group}
                    for fut, g in futures.items():
                        self.state[g.name] = fut.result()
                self._log(node.parallel_group, "parallel",
                          f"{len(group)} nodes in parallel: "
                          f"{[g.name for g in group]}",
                          (time.perf_counter() - t0) * 1000)
                current = self.successors(group[0].name)[0] if self.successors(group[0].name) else None
                continue

            # --- ordinary node ---------------------------------------------
            result = node.fn(self.state)
            self.state[node.name] = result
            condition = self.routers[node.name](self.state) if node.name in self.routers else None
            nxt = self.successors(node.name, condition)
            self._log(node.name, node.kind,
                      result.get("note", "") if isinstance(result, dict) else "",
                      (time.perf_counter() - t0) * 1000, condition)
            current = nxt[0] if nxt else None
        return self.state


# ==========================================================================
# LAB 7 — the Worklet 15 graph
# ==========================================================================

router = ToolRouter(agent="graph")
REGEN = {"count": 0}          # how many times the back-edge has fired


def n_coordinator(state):
    reports = coordinator_client.read("department_reports", period=REPORTING_PERIOD)
    state["rows"] = reports["rows"]
    return {"note": f"{reports['row_count']} department rows, access confirmed"}


def _domain_node(domain):
    def run(state):
        review = SKILL_REGISTRY["review_domain"].run(router, domain=domain,
                                                     period=REPORTING_PERIOD)
        return {"domain": domain, "kpis": review["kpis"],
                "off_target": review["off_target"],
                "note": review["headline"]}
    return run


def n_kpi_join(state):
    kpis = [k for d in DOMAINS for k in state[f"{d.lower()}_agent"]["kpis"]]
    state["kpis"] = kpis
    return {"note": f"{len(kpis)} institution KPIs synthesised from 4 domain views"}


def n_report(state):
    # On the first pass the report omits the source system for one KPI — the
    # defect validation is there to catch. The back-edge repairs it.
    kpis = state["kpis"]
    rows = []
    for k in kpis:
        cited = k["source_system"]
        if REGEN["count"] == 0 and k["kpi_id"] == "KPI-R2":
            cited = ""                      # <- the injected defect
        rows.append({"kpi_id": k["kpi_id"], "name": k["name"], "value": k["value"],
                     "target": k["target"], "status": k["status"],
                     "source_system": cited,
                     "figure_status": k["figure_status"]})
    state["brief"] = {"rows": rows, "revision": REGEN["count"]}
    return {"note": f"brief drafted, revision {REGEN['count']}, {len(rows)} KPI rows"}


def n_validation(state):
    """The four Chapter 15 checks. Returns which KPIs failed, if any."""
    rows = state["brief"]["rows"]
    failing = [r["kpi_id"] for r in rows if not r["source_system"]]
    provisional_unlabelled = [r["kpi_id"] for r in rows
                              if r["figure_status"] != "final" and not r.get("caveat_ok", True)]
    # The engine stores a node's return value under the node's own name, so the
    # result IS state["validation"] — a node must not also write that key itself.
    return {"passed": not failing and not provisional_unlabelled,
            "failing": failing,
            "note": ("all checks passed" if not failing
                     else f"FAILED: {failing} cite no source system")}


def route_validation(state):
    return "pass" if state["validation"]["passed"] else "fail"


def n_regenerate(state):
    """Only the failing part is redone — not the whole run."""
    REGEN["count"] += 1
    return {"note": f"regenerating only {state['validation']['failing']} "
                    f"(attempt {REGEN['count']})"}


def n_human_gate(state):
    state["approval"] = {"by": "Dr. A. Principal", "decision": "approve"}
    return {"note": "Principal / Registrar approved for circulation"}


def route_gate(state):
    return state["approval"]["decision"]


def n_publish(state):
    state["published"] = {"version": 1, "to": "Governing Council"}
    return {"note": "versioned brief released to the Governing Council"}


g = Graph("worklet-15-executive-decision-support")
g.add_node(Node("coordinator", COORDINATOR, "apniLeap AURA Coordinator", n_coordinator))
for d in DOMAINS:
    g.add_node(Node(f"{d.lower()}_agent", AGENT, f"{d} Agent", _domain_node(d),
                    parallel_group="domain_agents"))
g.add_node(Node("kpi_agent", JOIN, "KPI Agent — synthesis", n_kpi_join))
g.add_node(Node("report_agent", AGENT, "Report Generation Agent", n_report))
g.add_node(Node("validation", VALIDATION, "Validation gate (hard)", n_validation))
g.add_node(Node("regenerate", AGENT, "Regenerate the failing KPI only", n_regenerate))
g.add_node(Node("human_gate", GATE, "Principal / Registrar review", n_human_gate))
g.add_node(Node("publish", PUBLISH, "Governed publish + audit", n_publish))

# The fan-out is expressed as four real edges. Leaving it implicit in the
# parallel group makes three agents unreachable — which the static check in
# validate() catches before a single node runs.
for d in DOMAINS:
    g.add_edge("coordinator", f"{d.lower()}_agent")
    g.add_edge(f"{d.lower()}_agent", "kpi_agent")
g.add_edge("kpi_agent", "report_agent")
g.add_edge("report_agent", "validation")
g.add_edge("validation", "human_gate", condition="pass")
g.add_edge("validation", "regenerate", condition="fail")
g.add_edge("regenerate", "report_agent", back_edge=True)     # <- the red back-edge
g.add_edge("human_gate", "publish", condition="approve")
g.add_edge("human_gate", "regenerate", condition="edit", back_edge=True)
g.set_router("validation", route_validation)
g.set_router("human_gate", route_gate)


# ==========================================================================
# LAB 7 — renderers
# ==========================================================================

LEGEND = {COORDINATOR: "navy   ", AGENT: "lt blue", JOIN: "lt blue",
          VALIDATION: "red    ", GATE: "amber  ", PUBLISH: "green  "}


def render_ascii(graph: Graph) -> str:
    out = [f"  {graph.name}", ""]
    groups = defaultdict(list)
    for n in graph.nodes.values():
        if n.parallel_group:
            groups[n.parallel_group].append(n.name)
    out.append("  [coordinator]  apniLeap AURA Coordinator")
    out.append("        |")
    out.append("        +--- fan-out, all four at once ---+")
    for name in groups["domain_agents"]:
        out.append(f"        |    [{name}]".ljust(46) + "|")
    out.append("        +---------------------------------+")
    out.append("        v")
    for name in ["kpi_agent", "report_agent", "validation"]:
        out.append(f"  [{name}]  {graph.nodes[name].label}")
        out.append("        |")
    out.append("        +-- fail --> [regenerate] --(back-edge)--> [report_agent]")
    out.append("        |")
    out.append("        +-- pass --> [human_gate]  Principal / Registrar")
    out.append("                          |")
    out.append("                          +-- edit --(back-edge)--> [regenerate]")
    out.append("                          |")
    out.append("                          +-- approve --> [publish]  governed, versioned")
    return "\n".join(out)


def render_mermaid(graph: Graph) -> str:
    lines = ["flowchart TD"]
    for n in graph.nodes.values():
        shape = ("{{%s}}" if n.kind == VALIDATION else
                 "[[%s]]" if n.kind == GATE else
                 "([%s])" if n.kind == PUBLISH else "[%s]")
        lines.append(f"    {n.name}{shape % n.label}")
    for e in graph.edges:
        label = f"|{e.condition}|" if e.condition else ""
        arrow = "-.->" if e.back_edge else "-->"
        lines.append(f"    {e.src} {arrow}{label} {e.dst}")
    return "\n".join(lines)


# ==========================================================================
# LAB 8 — swarm primitives
# ==========================================================================

from edss_stack import coordinator_client, department_agent_client


@dataclass
class AgentResult:
    """The envelope every swarm agent returns — success or failure."""
    unit: str
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: int = 1
    ms: float = 0.0


class Swarm:
    """Runs one worker per unit, in parallel, with retry and timeout."""

    def __init__(self, worker: Callable[[str], Dict[str, Any]],
                 max_retries: int = 2, backoff_s: float = 0.05,
                 timeout_s: float = 2.0):
        self.worker = worker
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.timeout_s = timeout_s
        self.log: List[Dict[str, Any]] = []

    def _run_one(self, unit: str) -> AgentResult:
        t0 = time.perf_counter()
        last = None
        for attempt in range(1, self.max_retries + 2):
            try:
                data = self.worker(unit)
                return AgentResult(unit, True, data, None, attempt,
                                   (time.perf_counter() - t0) * 1000)
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                self.log.append({"unit": unit, "attempt": attempt, "error": last})
                if attempt <= self.max_retries:
                    time.sleep(self.backoff_s * attempt)      # backoff
        return AgentResult(unit, False, None, last, self.max_retries + 1,
                           (time.perf_counter() - t0) * 1000)

    def run(self, units: List[str]) -> Dict[str, AgentResult]:
        started = time.perf_counter()
        results: Dict[str, AgentResult] = {}
        with ThreadPoolExecutor(max_workers=len(units)) as pool:
            futures = {pool.submit(self._run_one, u): u for u in units}
            for fut in as_completed(futures, timeout=self.timeout_s * 4):
                r = fut.result()
                results[r.unit] = r
        self.wall_ms = (time.perf_counter() - started) * 1000
        self.serial_ms = sum(r.ms for r in results.values())
        return {u: results[u] for u in units if u in results}


# ==========================================================================
# LAB 8 — department agents and injected faults
# ==========================================================================

ROWS = {r["dept_code"]: r for r in _typed_rows(DEPARTMENT_REPORTS_CSV)}
UNITS = list(ROWS)

# Publication ids per department. PUB-J1..J3 are joint CSE+ECE papers and
# appear in BOTH lists — exactly as they do in the two departments' own returns.
JOINT = ["PUB-J1", "PUB-J2", "PUB-J3"]


def publication_ids(code: str, n: int) -> List[str]:
    """The n paper ids a department claims. CSE and ECE co-authored three of
    them, so those three ids appear in both lists — which is exactly why a sum
    of counts overstates research output and a union of ids does not."""
    if code in ("CSE", "ECE"):
        own = [f"PUB-{code}-{i}" for i in range(1, max(n - len(JOINT), 0) + 1)]
        return own + JOINT[:n]
    return [f"PUB-{code}-{i}" for i in range(1, n + 1)]


PUBLICATION_IDS = {code: publication_ids(code, row["publications"])
                   for code, row in ROWS.items()}

FAULTS = {"CHEM": {"fail_until_attempt": 2}, "CIVIL": {"always_fail": True}}
ATTEMPTS = defaultdict(int)
AGENT_LATENCY_S = 0.06          # each agent talks to a departmental system


DETAIL_PERIOD = REPORTING_PERIOD.replace("academic year ", "")


def _rollup(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fact rows -> one figure per metric, obeying each row's own rule.

    The `aggregation` column travels with the data precisely so this function
    does not have to guess. Summing a weighted mean would be silent nonsense.
    """
    out: Dict[str, Any] = {}
    for r in rows:
        metric, value, rule = r["metric"], r["value"], r["aggregation"]
        if rule == "sum":
            out[metric] = round(out.get(metric, 0) + value, 2)
        else:                       # latest / weighted_mean arrive as one row
            out[metric] = value
    return out


def department_agent(unit: str) -> Dict[str, Any]:
    """One agent, one department. Same code for all eight.

    The agent owns no data. It holds a token with a single scope and pulls its
    own department's fact rows through the Lab 5 connector, then rolls them up
    itself. Eight agents therefore make eight independent connector calls — all
    of them on the server's log, and all of them counted against the Lab 6
    connector budget, because that budget is measured from the same log.
    """
    ATTEMPTS[unit] += 1
    time.sleep(AGENT_LATENCY_S)

    fault = FAULTS.get(unit, {})
    if fault.get("always_fail"):
        raise ConnectionError(f"{unit} departmental server unreachable")
    if ATTEMPTS[unit] < fault.get("fail_until_attempt", 0):
        raise TimeoutError(f"{unit} reporting system timed out")

    fetched = department_agent_client.read(
        "department_detail", dept_code=unit, period=DETAIL_PERIOD)
    rows = fetched["rows"]
    if not rows:
        raise ConnectionError(f"{unit} returned no rows for {DETAIL_PERIOD}")
    figures = _rollup(rows)
    head = rows[0]

    # The ids come from the research repository, not the department: a jointly
    # authored paper appears in BOTH departments' lists, which is the thing the
    # reconcile step has to resolve. The COUNT, though, is whatever the agent
    # just fetched — so editing the CSV moves it.
    ids = publication_ids(unit, int(figures["publications"]))
    return {
        "dept_code": unit, "dept_name": head["dept_name"],
        "category": head["category"],
        "students_appeared": int(figures["students_appeared"]),
        "students_passed": int(figures["students_passed"]),
        "sanctioned_faculty": int(figures["sanctioned_faculty"]),
        "publication_ids": ids,
        "publication_count_claimed": len(ids),
        "eligible_students": int(figures["eligible_students"]),
        "placed_students": int(figures["placed_students"]),
        "rows_fetched": len(rows),
        "domains_fetched": sorted({r["domain"] for r in rows}),
        "source_system": fetched["source_system"],
    }


# ==========================================================================
# LAB 8 — the merge
# ==========================================================================

def merge(results: Dict[str, AgentResult]) -> Dict[str, Any]:
    reporting = {u: r.data for u, r in results.items() if r.ok}
    missing = [u for u, r in results.items() if not r.ok]

    # --- conflict resolution: union of ids, not sum of counts ---------------
    claimed_by: Dict[str, List[str]] = defaultdict(list)
    for unit, d in reporting.items():
        for pub in d["publication_ids"]:
            claimed_by[pub].append(unit)
    contested = {p: u for p, u in claimed_by.items() if len(u) > 1}

    naive = sum(d["publication_count_claimed"] for d in reporting.values())
    reconciled = len(claimed_by)

    totals = {
        "students_appeared": sum(d["students_appeared"] for d in reporting.values()),
        "students_passed": sum(d["students_passed"] for d in reporting.values()),
        "sanctioned_faculty": sum(d["sanctioned_faculty"] for d in reporting.values()),
        "eligible_students": sum(d["eligible_students"] for d in reporting.values()),
        "placed_students": sum(d["placed_students"] for d in reporting.values()),
    }
    coverage = len(reporting) / len(results) * 100
    return {
        "reporting_departments": sorted(reporting),
        "missing_departments": missing,
        "coverage_pct": round(coverage, 2),
        "complete": not missing,
        "publications_naive_sum": naive,
        "publications_reconciled": reconciled,
        "double_counted_removed": naive - reconciled,
        "contested_publications": {p: sorted(u) for p, u in contested.items()},
        "totals": totals,
        "kpis": {
            "pass_percentage": round(totals["students_passed"]
                                     / totals["students_appeared"] * 100, 4),
            "publications_per_faculty_naive": round(naive / totals["sanctioned_faculty"], 4),
            "publications_per_faculty_reconciled": round(
                reconciled / totals["sanctioned_faculty"], 4),
            "placement_percentage": round(totals["placed_students"]
                                          / totals["eligible_students"] * 100, 4),
        },
    }




# ==========================================================================
# Reset helpers — the dashboard re-runs these demos on demand
# ==========================================================================

def reset_graph_state():
    """Re-arm the Lab 7 injected defect and clear the trace."""
    REGEN["count"] = 0
    g.trace.clear()
    g.state.clear()


def reset_swarm_state():
    """Re-arm the Lab 8 faults so CHEM fails once and CIVIL stays dead."""
    ATTEMPTS.clear()


def reset_runtime_fault():
    """Re-arm the Lab 6 transient backend failure."""
    FAULT["armed"] = True
