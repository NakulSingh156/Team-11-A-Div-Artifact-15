# Worklet 15 — Executive Decision Support System

**Agentic AI (26ECAC401) · KLE Technological University · CSE (AI), batch 2027**
**Team 11, A Division** — Nakul Singh · Riya Ajit Magadum · Surabhi P · Shreya Vasavad

One free-text request from leadership becomes an **approved, published, reversible
decision brief**. Agents draft, compute and flag; a named human approves. Nothing
reaches leadership that has not passed a test suite derived from the request itself.

---

## What problem this solves

A Principal asking *"how are we doing?"* currently waits days while departments
email spreadsheets that are summed by hand. Three things go wrong every time:

| Failure | What this system does about it |
|---|---|
| Nobody agrees what "doing well" means | The agent refuses to start until scope, period, KPI set, targets and drill-down policy are pinned down |
| Department numbers double-count | Claims are reconciled by record ID — 174 claimed publications become **171** once jointly authored papers are de-duplicated |
| A provisional figure gets read as final | Every figure carries its status, its source and its locator; an ungrounded claim is dropped, not softened |

The output is a **decision brief** — options and risks per off-target KPI — not a
dashboard to stare at.

---

## Quickstart

```bash
git clone https://github.com/VII-Sem-Agentic-AI-2026/Team-11-A-Div-Artifact-15-Executive-Decision-Support-System.git
cd Team-11-A-Div-Artifact-15-Executive-Decision-Support-System/dashboard
pip install -r requirements.txt
streamlit run pipeline_app.py
```

Launch from inside `dashboard/` — Streamlit reads the theme from
`dashboard/.streamlit/config.toml` relative to your working directory.

**No API key, no network, no database server.** The dataset ships with the repo
and the run is deterministic.

---

## The two dashboards

### 1 · `pipeline_app.py` — the system as one run

A single scrolling page. You are asked for exactly three things; everything
between them is automatic.

| | You do | The agent does |
|---|---|---|
| 1 | Type the request — `Analyze our college performance.` | Refuses it as too vague and asks **6 questions**, each with clickable options and a free-text box |
| 2 | Answer (click, type, or both) | Locks a plan and derives the spec the whole run obeys |
| 3 | — | 19 stages: reads data, runs 8 department agents in parallel, reconciles, computes, grounds, validates, **repairs itself**, runs its own acceptance suite |
| 4 | Approve or reject | Publishes, versions, archives — or escalates and publishes nothing |

The stages are grouped into the six phases a run moves through — **understand,
gather, analyse, check, decide, record** — and the agent narrates what it is
calling as it calls it. Afterwards, on the same page: the KPI board with a
per-department breakdown, the path the graph walked, the audit trail, the
lab-coverage table read off the run itself, and version rollback.

**Worth demonstrating** from the sidebar's *Run conditions*:

| Setting | What it proves |
|---|---|
| *A KPI loses its source* (default) | Lab 10 diagnoses it and repairs **1 row of 9** |
| *An unapproved KPI row* | Repair budget spent → **escalates, publishes nothing** |
| Reviewer = *Governing Council member* | The gate **refuses the role**, by name |
| Reject at the gate | Nothing is published; the audit records who rejected it |

### 2 · `app.py` — one tab per lab

```bash
cd dashboard && streamlit run app.py
```

Fourteen tabs, one per lab, each driving the same code its notebook is graded on.

---

## Architecture

```
request ──► Lab 1  clarify loop ──► locked plan ──► SPEC
                                                     │
        ┌────────────────────────────────────────────┘
        ▼
   Lab 7 GRAPH decides the order        Lab 6 RUNTIME executes every stage
   ├─ 18 nodes, conditional edges       ├─ budgets  (actions / connector / seconds)
   ├─ back-edge for the repair cycle    ├─ audit    (append-only)
   └─ 3 escalation exits                ├─ checkpoints (after every action)
                                        └─ gates    (ApprovalRequired)
        │
        ├─ Lab 4  recall ─────── TF-IDF + cosine over an append-only archive
        ├─ Lab 5  connector ──── MCP server · 4 resources · 3 swappable backends
        ├─ Lab 8  swarm ──────── 8 department agents in parallel, then reconcile
        ├─ Lab 3  skill ──────── one reusable `domain_review` across domains
        ├─ Lab 2  tools ──────── schema-validated calls; Python does the arithmetic
        ├─ Lab 13 specialists ── 4 domain packs draft options and risks
        ├─ Lab 9  grounding ──── source + locator + value, or the claim is dropped
        ├─ Lab 10 validate ───── fail → diagnose → minimal repair → re-validate
        ├─ Lab 11 acceptance ─── suite DERIVED from the spec, gates the human
        └─ Lab 12 governance ─── role-checked approval, versioning, rollback, audit
```

**Lab 7 is the control flow, Lab 6 is the executor.** Every stage runs through
`Runtime.perform()`, so each one is budget-checked, audited and checkpointed —
and the human approval pause reuses the same checkpoint/resume mechanism as
crash recovery.

---

## What makes the run agentic

Not a script with an LLM bolted on. Four properties, each demonstrable:

1. **It refuses to guess.** A vague request produces questions, not an answer.
   Six become three once you answer the first round; a fully specified request
   is asked nothing at all.
2. **Your answers change what executes** — not just what is printed:

   | Request | Domains | KPIs | Tests derived | Stages |
   |---|---|---|---|---|
   | All four domains | 4 | 9 | **21** | 18 |
   | Placement only | 1 | 3 | **15** | 16 |
   | Research + Finance | 2 | 4 | **16** | 18 |
   | Period with no export | — | — | — | **3 → escalates** |

3. **It repairs itself, surgically.** Validation fails on one KPI; the repair
   touches **1 row of 9** and leaves the other eight byte-identical, then
   follows the graph's back-edge to re-validate.
4. **It knows when to stop.** Three escalation exits. An unrepairable defect, a
   role that may not approve, and a period with no authorised export each end
   with nothing published and a named reason.

---

## The dataset

Static, synthetic, generated by the project itself — nothing to download.

```
lab5_sources/
├── department_reports_2025_26.csv     8 rows · the institution-wide aggregate
├── institution.db                     SQLite · KPI register (9 definitions)
└── departments/                       8 files · 624 rows · 78 per department
    CSE.csv  ECE.csv  ISE.csv  EEE.csv  MECH.csv  CIVIL.csv  CHEM.csv  BT.csv
```

Each department file is a long fact table — one row per period, domain, metric
and sub-period, across **two academic years** and **all four domains**:

```csv
dept_code,dept_name,category,period,grain,sub_period,domain,metric,value,unit,aggregation,figure_status,source_system,recorded_on
CSE,Computer Science & Engineering,circuit,2025-26,quarter,Q1,Research,publications,10,count,sum,final,Research repository,2025-09-30
```

Grain follows the metric: exams on semesters, research and spend on quarters,
headcounts annual. Every row carries its own **`aggregation`** rule (`sum`,
`weighted_mean`, `latest`), so a consumer cannot roll a mean up as a total.

The files are **written once and never regenerated**, so hand edits survive a
restart. `tools/build_dataset.py` rebuilds them on request (`--force`) and
refuses to write unless two invariants hold:

* the 2025-26 detail rolls up to `department_reports_2025_26.csv` **exactly**;
* the 2024-25 detail reproduces all nine KPI values archived as
  `KPI-SNAPSHOT-2024-25`.

The MCP connector serves them through `department_detail`, filterable by
department, period, domain and metric. Lab 8's agents hold
`tok-department-agent` — one scope, `read:department-detail` — so each fetches
only its own department. Eight agents make eight independent connector calls,
all on the server log and all counted against the Lab 6 budget.

---

## Testing

```bash
cd dashboard
python3 test_app.py            # 14 lab tabs · 186 acceptance checks
python3 test_pipeline_app.py   # 98 end-to-end pipeline UI paths
```

**284 checks, no browser required.** `streamlit.testing.v1.AppTest` drives the
real UI headlessly. The pipeline suite proves every refusal path, not just the
happy one: rejection, a role that may not approve, an unrepairable defect, a
period with no export, revision → v2 → rollback to v1, and that clicking the
clarify options alone is enough to drive a complete run.

---

## Repository layout

| Path | What is in it |
|---|---|
| `notebooks/` | 14 lab notebooks, committed **with outputs**. Each writes the layers it needs in its own first cells, so any one runs standalone in Colab |
| `engine/` | The shared implementation: core, stack (Labs 3–5), labs 6–8, labs 9–13, capstone, pipeline |
| `dashboard/` | Both Streamlit apps, `pipeline_ui.py` (presentation only), and the two headless test suites |
| `lab5_sources/` | The static dataset the connector serves |
| `tools/` | `build_dataset.py` — the dataset generator and its invariants |
| `evidence/` | Per-lab artifacts produced by real runs |
| `docs/` | Review sheet, worklet canvas, and `SYSTEM_WALKTHROUGH.md` |

---

## Design decisions worth defending

**No LLM in the dashboard run.** Labs 1 and 2 carry a real Gemini integration —
`response_schema`-constrained JSON and a hand-written function-calling loop with
automatic calling disabled — plus a deterministic `OfflineBrain` fallback. The
dashboard runs the deterministic path, which is why the run is byte-reproducible
and why 284 tests give the same numbers every time. The agentic behaviour lives
in the loop, the branching and the refusals, not in a model.

**Memory is two stores, not one.** A `RunState` for the run, thrown away at the
end; an append-only `Archive` for history that raises on any attempt to edit a
record. Retrieval is hand-written TF-IDF plus cosine similarity — no embeddings,
no vector database.

**The connector is the only door to data.** Four resources, three interchangeable
backends (CSV, SQLite, HTTP-shaped), scope-checked tokens. The agent never learns
which backend served it, so pointing this at a real ERP is a fourth backend, not
a rewrite.

**Presentation is separated from logic.** `pipeline_ui.py` never reads a KPI or
decides a status; every value it draws is passed in already computed.

---

## Known limitations

Stated plainly, because a reviewer will find them:

* **Nothing runs in the cloud.** Build, test and deploy are local. There is no
  CI pipeline and no deployment target.
* **The MCP server is in-process.** It implements resources, typed parameters,
  scopes and tokens, but an external MCP client cannot connect to it over stdio.
* **Grounding is internal.** Claims are tied to authorised institutional sources;
  there is no external or web research.
* **Run history does not survive a restart.** The archive is in-process. The
  checkpoints on disk are read for resume within a session, not at launch.
* **The prior year is computed but unused.** 2024-25 detail exists and is
  consistent with the archived baseline; the brief does not yet show
  year-on-year movement.

---

## Course mapping

| Phase | Labs | |
|---|---|---|
| **A · Foundations** | 1–6 | agent loop · typed tools · skills · memory · connector · runtime |
| **B · Orchestration** | 7–8 | node graph · parallel swarm |
| **C · Applied reliability** | 9–11 | grounding · self-healing · SDLC factory |
| **D · Governance & capstone** | 12–14 | safety & governance · domain specialists · capstone |

| Lab | Notebook | Checks |
|---|---|---|
| 1 · Agent vs Chatbot | `LAB_1_…` | 16/16 |
| 2 · Tool-Using Agent | `LAB_2_…` | 21/21 + 38 eval |
| 3 · Skill Creation | `LAB_3_…` | 10/10 |
| 4 · Memory & Retrieval | `LAB_4_…` | 13/13 |
| 5 · MCP-Style Connector | `LAB_5_…` | 13/13 |
| 6 · OpenCLA/OpenClaw Runtime | `LAB_6_…` | 13/13 |
| 7 · Agentic Node Graph | `LAB_7_…` | 14/14 |
| 8 · Parallel Swarm | `LAB_8_…` | 12/12 |
| 9 · Deep Research / Grounding | `LAB_9_…` | 10/10 |
| 10 · Ops Resilience | `LAB_10_…` | 12/12 |
| 11 · Agentic SDLC Factory | `LAB_11_…` | 12/12 |
| 12 · Safety & Governance | `LAB_12_…` | 14/14 |
| 13 · Domain Specialists | `LAB_13_…` | 13/13 |
| 14 · Capstone | `LAB_14_…` | 13/13 |

**186 / 186 acceptance checks passing · 0 execution errors.**
