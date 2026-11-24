# Executive Decision Support System — leadership dashboard

Worklet 15 · the UI layer over the Lab 1 + Lab 2 agent engine.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens on <http://localhost:8501>. No API key needed — the dashboard is the
deterministic tool layer, not the language model.

## What it is

| File | Role |
|---|---|
| `edss_engine.py` | §1–§6: the Lab 2 engine — typed tools, `ToolRouter`, `Connector`, KPI computation, validation gate, question router — plus agents A–F, the human approval gate, versioning and the audit log. §7: the Lab 1 planner — `PlanGoal`, `clarify`, `build_plan`, `apply_patch`, `revise`, `PlannerSession`. |
| `app.py` | The Streamlit dashboard. Presentation only; it computes nothing itself. |
| `test_app.py` | Headless UI test: all 6 panels, query routing, refusal, flag-blocks-approval, approve, publish. |

**No number in this dashboard is hardcoded.** Every figure on every panel comes
out of `compute_kpi()` / `compare_to_target()` on the department records, through
the same typed tool contracts that Lab 2 was graded on. Delete a department row
and every panel changes.

## Two tabs, one per lab

### Tab 1 · Plan the review (Lab 1)

The clarify → plan → revise loop, driven live. Type a vague request and it asks only for
the slots that are genuinely missing; answer some and it asks only for the rest. It calls
the data-scope register before committing, surfaces conflicts (Finance 2025-26 is
unreconciled), and produces a plan whose steps carry stable ids.

Feedback then **patches the plan in place** — the tab prints the revision history, a
computed changed/added/untouched diff, and a badge confirming the same object was mutated
rather than regenerated. Works before any pipeline run, because planning comes first.

### Tab 2 · Run the pipeline (Lab 2)

The whole execution loop on one page:

1. **The run** — which stages were sequential gates and which ran in parallel, with timings
2. **Institution KPIs** — all 9 against NIRF / NAAC / strategic-plan targets, with variance,
   provisional labels and rounding flags
3. **Ask a question** — plain English in, routed to a tool chain, answered only from what
   the tools returned, with a grounded badge and the chain that produced it
4. **Drill-down evidence** *(collapsed)* — trace any KPI back to its source department
5. **Decision brief** — summary, validation gate, options with risks and trade-offs
6. **Principal / Registrar gate** — flag, approve, publish, export
7. **Audit trail** *(collapsed)* — every tool call with the reason it was made

## Governance, enforced rather than described

- **Nothing is circulated without a named human.** The brief carries
  `DRAFT — NOT CIRCULATED` until the reviewer approves; approval assigns a version
  and writes a publish record.
- **A flagged KPI blocks approval.** Raise a clarification on any KPI and the
  approve button disables until it is resolved.
- **Provisional figures are labelled everywhere.** `KPI-F1` (budget utilisation) is
  unreconciled, so it is badged on the card, in the drill-down, in the assumptions
  and in the export — and its only drafted option is *defer the decision*.
- **A rounding that would hide a miss is flagged.** Pass percentage is 91.85% against
  a 92.00% target; rounded it reads as on target. The engine raises the warning.
- **Aggregation is over raw counts, never over department percentages.** Placement is
  75.12% weighted; the naive mean of the eight department percentages is 70.59%.

## Hybrid execution

The four domain agents run in a real `ThreadPoolExecutor`; everything else is a
sequential gate, exactly as the methodology table specifies. With the in-memory
dataset the timings are sub-millisecond, so set **simulated source latency** in the
sidebar to model real source systems — at 150 ms per read the parallel stage
finishes in ~153 ms against ~606 ms for the same work run one agent after another.

## Tests

```bash
python test_app.py
```

Drives the app headlessly through every interactive path and asserts no exception —
including that a vague request triggers at least two clarifying questions, that answered
slots are never re-asked, that `revise()` mutates the same plan object across two
revision rounds, that approval is blocked while a KPI is flagged, that an out-of-scope
question is declined with zero tool calls, and that the selected panel survives a rerun.

## Two Streamlit details worth knowing

- **Inputs that clear themselves use `st.form(clear_on_submit=True)`.** Hand-managing a
  "clear this widget next run" flag fights Streamlit's widget-state model.
- **Panels are a keyed radio, not `st.tabs`.** `st.tabs` resets to the first tab on every
  `st.rerun()`, which bounced the reviewer back to panel 1 each time they flagged or
  approved a KPI. A keyed radio keeps the selection in session state, and unlike
  `st.segmented_control` it is drivable by Streamlit's AppTest harness.
- **The question box is a keyed widget.** Passing a changing `value=` to `st.text_input`
  blanks it on the next rerun, which swallowed the answer.
