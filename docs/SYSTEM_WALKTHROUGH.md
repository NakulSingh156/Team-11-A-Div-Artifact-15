# Worklet 15 — how every part actually works

Study sheet for the review. Part 0 is the one you memorise.

---

## 0 · The drill-down answers

| If sir asks… | Say exactly this |
|---|---|
| **What do you use for memory?** | Two things, deliberately split. **Working memory** is `RunState` — a dataclass holding one run's draft and scratch, thrown away at the end. **Long-term memory** is `Archive` — a Python class wrapping a dict, **append-only**: `put()` raises `ArchiveImmutableError` if the record id already exists, and `get()` returns a deep copy so a caller can't corrupt the baseline. |
| **Which database?** | None for memory — it is a Python object. `sqlite3` appears only as **one of three interchangeable backends** behind the connector, to prove the swap. |
| **What do you use for retrieval?** | Two retrievers. **(a)** `retrieve_by_tags()` — exact tag match, scored by overlap ÷ tags asked for. **(b)** `SimilarityIndex` — **TF-IDF vectors + cosine similarity**, hand-written in ~30 lines using `math` and `collections.Counter`. |
| **Embedding model? Vector DB?** | Neither. No FAISS, no Chroma, no sentence-transformers. The archive holds 6 records; TF-IDF is the right size of tool and every weight is inspectable. |
| **What exactly is the TF-IDF?** | `tf` = term count ÷ document length. `idf = log((N+1)/(df+1)) + 1` (smoothed, so a word in every doc still carries weight). Vector is L2-normalised, so cosine is just a dot product. Stopword list of 48 words, tokens must be >2 chars. |
| **Which LLM?** | **Google Gemini** through the `google-genai` SDK. Model `gemini-3.6-flash`, with a fall-forward list (`gemini-flash-latest`, `gemini-2.5-flash`, `gemini-2.0-flash`) and a preflight probe, so a retired model degrades to offline instead of crashing. `temperature=0.0, seed=7` for reproducibility. |
| **Where does the LLM run?** | Exactly two places, both in Labs 1–2. **Never** on a number. |
| **Where does it NOT run?** | Every figure. All 9 KPIs come from `compute_kpi()` in Python. **Labs 3–14 need no API key and no network.** |
| **Is that real MCP?** | No — a hand-written `MCPServer`/`MCPClient` pair following the MCP pattern: named resources, scopes, bearer tokens, one uniform response envelope. Not the Anthropic MCP SDK. |
| **Is that LangGraph?** | No — `Graph`/`Node`/`Edge` written from scratch (~130 lines) with parallel groups, conditional edges, back-edges and a static reachability check. |
| **Why write them yourself?** | The labs grade the concept. A 120-line server we can read beats a black box we can't — and it is why we have 253 assertions over it. |
| **How do agents get data?** | Only `MCPClient.read()`. No agent opens a file or a socket. |
| **Parallelism?** | `concurrent.futures.ThreadPoolExecutor`, 8 workers — one per department. |

---

## 1 · The stack

**Libraries:** `streamlit`, `pandas`, `altair` (UI only) · `google-genai` (optional, Labs 1–2 only).

**Python standard library doing the real work:** `csv`, `sqlite3`, `json`, `re`, `math`, `collections`, `concurrent.futures`, `dataclasses`, `pathlib`, `datetime`, `copy`, `time`.

**Written by us:** the tools, the router, the connector, skills, memory, retrieval, the runtime, the graph, the swarm, grounding, self-healing, the test factory, governance, the specialists, the pipeline. ~3,400 lines of engine.

---

## 2 · The parts list

### 2.1 The 8 tools — `edss_core.py`

Each has a **JSON Schema**, so a wrong argument is rejected before the function runs.

| Tool | Takes | Gives back |
|---|---|---|
| `read_department_reports` | `period`, *departments*, *category* | 8 department rows |
| `read_kpi_definitions` | *kpi_ids* | formula, target, unit, source system |
| `read_external_benchmark` | `kpi_id` | NIRF peer median — **only 3 of 9 KPIs have one** |
| `filter_rows` | `rows`, `field`, `value` | the narrowed subset |
| `compute_kpi` | `kpi_id`, `rows` | value + formula + per-department evidence |
| `compare_to_target` | `kpi_id`, `value` | variance, status, rounding flag |
| `compute_variance` | `value`, `reference`, `label` | difference + % of reference |
| `draft_notification` | `audience`, `subject`, `findings` | a **draft** — never sends |

**`compute_kpi` is the heart.** Three methods: `ratio` (sum numerator ÷ sum denominator × scale), `weighted_mean`, `sum`. It returns the value **and** `formula`, `inputs_used`, `source_system`, `figure_status`, and an `evidence` list with one row per department. That evidence list is what every later lab cites.

> **Why ratios, not averages:** placement % is `sum(placed)/sum(eligible)`, never the mean of 8 department percentages. A small department with 100% would otherwise drag the institution figure up. This is a written constraint on the skill.

### 2.2 The router — the choke point

`ToolRouter.call(tool, reason, **kwargs)` does four things, in order:

1. `validate_input()` — unknown tool, missing required arg, wrong type, value outside an enum → `ToolContractError`.
2. Runs the plain Python function.
3. Appends to `self.trace`: tool, reason, args, ok, ms, timestamp.
4. If the result has an `error` key → raises `ToolError`.

**Every tool call in the system goes through one of these.** That trace is the audit evidence.

### 2.3 The connector — Lab 5's MCP

```
MCPServer(name)
 ├── resources : name → Resource(scope, params, handler, backend)
 ├── tokens    : token → {holder, scopes}
 └── log       : every call, allowed or refused
MCPClient(server, token).read(resource, **params)
```

`server.call()` checks, in order: **token known → resource exists → token holds the resource's scope → required params present → run the backend**. Any failure raises `MCPError` with a code (`UNAUTHORIZED`, `FORBIDDEN_SCOPE`, `NOT_FOUND`, `BACKEND_FAILURE`) and is still logged.

Three backends serve the **same** resource name:

| Backend | What it is |
|---|---|
| `file:csv` | `csv.DictReader` over `department_reports_2025_26.csv` |
| `sqlite` | `sqlite3` over `institution.db` |
| `api` | a simulated HTTP source with latency and flaky responses |

Swapping them changes nothing for the caller — the envelope is identical. **That is the MCP point.**

Three tokens: `tok-coordinator` (all scopes), `tok-academic-agent` (narrow), `tok-intern` (KPI register only).

### 2.4 Skills — Lab 3

A `Skill` is a dataclass with 7 fields: `name`, `description`, `instructions`, `constraints`, `input_schema`, `output_schema`, `tools`.

`skill.run(router, **inputs)` does four checks:

1. Validate inputs against `input_schema`.
2. Run the function.
3. Validate outputs against `output_schema`.
4. **Compare the router trace to the declared `tools`** — a tool outside the declared surface raises `SkillContractError`.

Two skills: `review_domain` (declares 5 tools) and `format_document`. One `review_domain` serves all four domains — add a KPI to the register at runtime and the same object picks it up.

### 2.5 Memory — Lab 4

| | Working | Long-term |
|---|---|---|
| Class | `RunState` | `Archive` |
| Holds | `draft`, `scratch`, `retrieved` | 6 records: KPI snapshots + past decision briefs |
| Mutable? | Yes | **No** — `put()` on an existing id raises `ArchiveImmutableError` |
| Reads | direct | `get()` returns a **deep copy** |

**Retrieval 1 — by tag:** `retrieve_by_tags(store, tags, mode)`, `mode="any"` (union) or `"all"` (must carry every tag), scored `len(overlap)/len(wanted)`.

**Retrieval 2 — by meaning:** `SimilarityIndex.query(text, k, record_type)`. Builds the document text from `title + summary + tags + decisions + outcome`, tokenises, builds TF-IDF vectors at construction, and scores the query by cosine.

### 2.6 The agents

| Agent | Where | Job |
|---|---|---|
| `PlannerSession` | Lab 1 | The coordinator loop: clarify → check scope → plan → revise |
| `DomainAgent` ×4 | Lab 2 | Pull one domain's metrics |
| `KPIAgent` | Lab 2 | Apply approved formulas to the aggregates |
| `ReportGenerationAgent` | Lab 2 | Assemble the brief — **options only, never actions** |
| `ExecutiveAssistant` | Lab 2 | Answer ad-hoc leadership questions |
| `department_agent` ×8 | Lab 8 | One per department, run in parallel |
| 4 `Specialist` packs | Lab 13 | Domain-correct options, own vocabulary and units |

### 2.7 The runtime — Lab 6

`Runtime.perform(action)` on every action:

1. Already completed? → return the cached result, **skip the work** (this is resume).
2. `depends_on` not all completed? → refuse.
3. Budget check: actions, connector calls, wall seconds.
4. `requires_approval` and no named human? → raise `ApprovalRequired`.
5. Run it, log it, **checkpoint to JSON** — a crash still checkpoints.

`Budget(max_actions, max_connector_calls, max_seconds)` · `CheckpointStore` writes `<run_id>.checkpoint.json` · `Runtime.resume()` reloads completed, results, approvals, audit.

### 2.8 The graph — Lab 7

`Graph` with `Node(name, kind, label, fn, parallel_group)` and `Edge(src, dst, condition, back_edge)`.

- `validate(entry)` — unreachable nodes, dangling edges, conditional edges with no router. **Runs before anything executes.**
- `set_router(node, fn)` — the router returns the **condition label** to follow.
- `run(entry, state)` — walks it, running `parallel_group` nodes together in a thread pool, with a `max_steps` cycle budget so a non-converging back-edge fails loudly.

⚠️ **Trap we hit:** `successors()` treats an unconditional edge as matching *every* condition, so a node must never mix conditional and unconditional out-edges. `check_branches()` in `edss_pipeline.py` now fails the build if one does.

### 2.9 Grounding, healing, factory, governance, specialists

| | What it is |
|---|---|
| **Grounding (9)** | `research(Candidate) → Evidence(source, locator, value, in_scope)`. 4 in-scope sources only. No source → `in_scope=False` → the claim is **dropped**. |
| **Healing (10)** | 6 `Constraint` objects, each with a `test` **and its own `repair`**. `validate()` names the constraint *and the row*. `heal()` repairs only failing rows, budget 3, then raises `Escalation`. |
| **Factory (11)** | `derive_suite(spec)` **generates** tests from the spec: one per required KPI, one per section, scope, drill-down, option coverage, plus the plan's own validation checks. `submit_for_review()` refuses anything not fully green. |
| **Governance (12)** | 6 roles × 6 permissions. `approve_and_publish()` checks `can_approve`, versions, appends audit. `view_for()` redacts per role **and records what it withheld**. `rollback()` is a new audit entry — history is never rewritten. |
| **Specialists (13)** | `Specialist.check()` applies generic rules (6 required option fields, domain vocabulary in the headline) **plus** `domain_rules()`. `fmt(value, unit)` renders grants as `INR 242.50 lakh`, not `242.50 per faculty`. |

---

## 3 · Lab by lab — the call chain

**Lab 1 — Agent vs chatbot.** `start(request)` → `_advance()` loops: `clarify()` extracts what's stated with regex and asks only about empty slots → `read_data_scope_register()` → `detect_conflicts()` → `build_plan()`. `apply_feedback()` → `revise()` **mutates the same Plan object** and records a patch; `diff_last_revision()` proves which fields were untouched.

**Lab 2 — Typed tools.** `ExecutiveRun.execute()` → 4 `DomainAgent`s → `KPIAgent.synthesise()` → `validate_kpi_result()` (8 checks) → `ReportGenerationAgent.build_brief()`.
`ExecutiveAssistant.ask()` → `route()` picks the question type **by regex** → `kpi_chain()` runs the tools → the answer text is built in **Python** → `compose()` sends it to Gemini **only to rephrase**, with `must_include` strings that must survive → `ground_check()` rejects any number the tools didn't produce.
The notebook also has `gemini_function_calling()`: real `FunctionDeclaration`s, automatic function calling **disabled**, and a manual loop reading `part.function_call` and replying with `Part.from_function_response` — so the model choosing tools is visible, not hidden.

**Lab 3 — Skills.** `SKILL_REGISTRY["review_domain"].run(router, domain=…, period=…)`.

**Lab 4 — Memory.** `archive.put()` / `retrieve_by_tags()` / `index.query()`.

**Lab 5 — Connector.** `coordinator_client.read("department_reports", period=…)` → `server.call()` → scope check → backend.

**Lab 6 — Runtime.** `Runtime(run_id, Budget, CheckpointStore).perform(Action)` ×7, crash at 3, `resume()` skips 3 and finishes 7/7.

**Lab 7 — Graph.** 10 nodes; `validation` fails → back-edge → `regenerate` → passes → `human_gate` → `publish`.

**Lab 8 — Swarm.** `Swarm(department_agent, max_retries=2).run(UNITS)` in a thread pool → `merge()` takes the **union of publication ids**, not the sum of counts → 174 → 171.

**Lab 9 — Grounding.** `research(c)` per claim; ungrounded claims dropped.

**Lab 10 — Healing.** `validate()` → `diagnose()` → `heal()` → repair or `Escalation`.

**Lab 11 — Factory.** `derive_suite(SPEC)` → `acceptance_suite()` → `submit_for_review()`.

**Lab 12 — Governance.** `view_for(actor, brief)` → `approve_and_publish()` → `rollback()`.

**Lab 13 — Specialists.** `REGISTRY[domain].check(.generate(item))`.

**Lab 14 — Capstone.** `deploy()` returns a `System` holding **references** to the other labs' objects; identity assertions prove nothing was reimplemented.

---

## 4 · Follow one number

> **"Placement is 75.12%" — where did that come from?**

1. **CSV row** `CSE,...,eligible_students=420,placed_students=338`
2. `FileBackend.department_reports()` casts the numerics
3. `MCPServer.call()` checks `tok-coordinator` holds scope `reports:read`, logs it
4. `MCPClient.read()` returns `{rows, row_count, source_system}`
5. `ToolRouter.call("compute_kpi", kpi_id="KPI-P1", rows=rows)` — schema validated
6. `compute_kpi` → `sum(placed)/sum(eligible)×100 = 75.12`, plus 8 evidence rows
7. `compare_to_target` → target 80 (NIRF), variance −4.88, status `below target`
8. `validate_kpi_result` → 8 checks: has a formula, cites a source, evidence covers every department…
9. `research()` attaches source `KPI register`, locator `KPI-P1 · formula · source system`
10. `validate()` confirms the row cites its source; `heal()` repairs it if not
11. `acceptance_suite` test `kpi-present:KPI-P1` goes green
12. Principal approves → `approve_and_publish()` → **v1**, audited, reversible
13. `archive.put()` — it becomes next run's prior context

**Every step is logged. No step involved a language model.**

---

## 5 · The traps

| Question | Answer |
|---|---|
| "So the AI calculates the KPIs?" | **No.** The model picks which tool to call. Python does the arithmetic. That's the whole design. |
| "What if the LLM is down?" | Labs 3–14 don't use one. Lab 2 degrades to offline with a printed diagnostic — it never crashes. |
| "Is the brief's text LLM-generated?" | The facts are Python. The LLM only rephrases, and `must_include` + `ground_check` reject it if it drops a disclosure or invents a number. |
| "How do you know the agents didn't double-count?" | We do — 8 agents claimed 174 publications; the union of ids is 171. The merge shows which 3 were contested and by whom. |
| "What happens if it can't fix something?" | 3 repair attempts, then `Escalation` with the failing constraint named. It publishes nothing. |
| "Can an intern see department detail?" | No. `view_for()` replaces it with `[8 departments — detail withheld]` and lists the redaction. |
| "Can you undo a release?" | `rollback()` — and the rollback is a **new** audit entry. The old version still exists. |
| "How do you know all 14 labs run?" | The pipeline dashboard's **Lab coverage** table is read off that run's own event list, not a hard-coded list. |
