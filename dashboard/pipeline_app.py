"""Worklet 15 — the end-to-end pipeline, as ONE page.

The companion app (app.py) has one tab per lab, for grading lab by lab. This
one is the system itself: a single scrolling run. You type the request, the
agent asks for whatever it is missing, works through the stages announcing what
it is calling as it calls it, stops for a signature, and publishes.

There are no phases on screen. Everything that has happened stays on the page,
newest at the bottom, and the only things ever asked of the human are:

    1. the request
    2. answers to what the agent says it is missing   (Lab 1 — it refuses to guess)
    3. an approval decision                           (Lab 12 — role-checked)

The look lives in pipeline_ui.py; this file is the flow.

    cd dashboard && streamlit run pipeline_app.py
"""

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# resolve() matters: `streamlit run pipeline_app.py` from inside this folder
# gives a RELATIVE __file__, so .parent.parent would be "." and every path
# built from it would be resolved against whatever directory you launched from.
HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))

from edss_core import KPI_DEFINITIONS
from edss_engine import PlannerSession
import edss_labs9to13 as L913
import edss_pipeline as P
import edss_stack as L345
import pipeline_ui as UI

st.set_page_config(page_title="EDSS — Executive Decision Support",
                   page_icon="◆", layout="centered")

CHECKPOINTS = HERE.parent / "evidence" / "pipeline_checkpoints"
CHECKPOINTS.mkdir(parents=True, exist_ok=True)


def domain_of(kpi_id: str) -> str:
    return KPI_DEFINITIONS.get(kpi_id, {}).get("domain", "—")


EXAMPLES = {
    "Vague — makes the agent clarify (use this for the demo)":
        "Analyze our college performance.",
    "Partly specified — two rounds become one":
        "Give the Governing Council a decision brief on Placement and Research "
        "for academic year 2025-26.",
    "Fully specified — the agent asks nothing":
        "Prepare a decision brief with options and risks on Academic, Research, "
        "Placement and Finance for academic year 2025-26, using the approved "
        "institution-wide KPI set, benchmarked against NIRF, NAAC and the "
        "strategic plan, with department-level drill-down mandatory for every KPI.",
}

COMPLETE_ANSWERS = [
    "All four domains for academic year 2025-26. Leadership wants a decision "
    "brief with options and risks.",
    "Use the approved institution-wide KPI set, compare against NIRF, NAAC and "
    "the strategic plan, drill-down only for KPIs that miss their target.",
]

EDITS_DEFAULT = "Lead with the average-package decline."
FEEDBACK_DEFAULT = ("Remove the Finance domain and make drill-down mandatory "
                    "for every KPI")

# What each stage is DOING, in the present tense, with the thing it calls named.
# This is the running commentary — it is keyed by graph node, so it can never
# drift out of step with what actually executed.
DOING = {
    "plan_locked":    "turning your answers into the spec the rest of the run "
                      "is bound by",
    "recall":         "searching the archive of past releases — TF-IDF "
                      "retrieval, top-k by cosine similarity",
    "connector_read": "calling `connector.read(domain, period)` — the only door "
                      "to data, and it checks scope before it opens",
    "swarm":          "dispatching 8 department agents in parallel and waiting "
                      "on all of them",
    "reconcile":      "comparing what the departments each claimed and "
                      "de-duplicating by record id",
    "domain_skills":  "running the one reusable `domain_review` skill once per "
                      "domain in scope",
    "compute_kpis":   "one checked function call per KPI — no figure is written "
                      "by prose",
    "specialists":    "waking Placement / Research / Academic / Finance to "
                      "draft options and risks",
    "compose":        "assembling the draft brief from the parts the stages "
                      "produced",
    "grounding":      "linking every claim back to the source row it came from",
    "validate":       "checking the draft against the constraints the spec set",
    "heal":           "diagnosing the failure and fixing the smallest thing "
                      "that fixes it",
    "acceptance":     "running the tests derived from your spec — not a fixed "
                      "list",
    "submit":         "routing the result to a named human",
    "approval":       "asking for a signature — the runtime will not publish "
                      "without one",
    "publish":        "publishing, versioning and writing the audit entry",
    "archive":        "archiving the release, append-only",
    "escalate":       "stopping and handing the problem back to a human",
}

STATUS_ICON = {"ok": "✅", "skipped": "⏩", "paused": "⏸️", "failed": "⛔",
               "escalated": "🚩"}


# ==========================================================================
# session
# ==========================================================================

def init():
    ss = st.session_state
    ss.setdefault("phase", "Brief")      # internal only — never drawn as a tab
    ss.setdefault("planner", None)
    ss.setdefault("pipe", None)
    ss.setdefault("gov", L913.Governance())
    ss.setdefault("runs", [])            # summaries of every run this session
    ss.setdefault("run_n", 0)
    ss.setdefault("qa", [])              # the clarify transcript, for the feed
    ss.setdefault("sent", None)          # the request, once it has been sent
    # Each box below lives in one part of the flow only, so its key is seeded
    # here and kept alive — a key dropped when its box stops rendering cannot be
    # read back. `request` is deliberately NOT seeded: its box renders on the
    # very first run, and seeding a key in the same run that its widget passes a
    # default is what makes Streamlit print a warning into the page.
    ss.setdefault("edits", EDITS_DEFAULT)
    ss.setdefault("fb", FEEDBACK_DEFAULT)


def reset_all():
    for k in ("phase", "planner", "pipe", "gov", "runs", "run_n", "ex", "qa",
              "sent", "request", "reply", "clear_reply", "edits", "fb", "go",
              "last_diff"):
        st.session_state.pop(k, None)
    for k in [k for k in st.session_state if str(k).startswith("pick_")]:
        st.session_state.pop(k, None)
    import edss_labs678 as L678
    L678.reset_swarm_state()
    L678.reset_graph_state()
    L678.reset_runtime_fault()
    init()


init()
ss = st.session_state
st.markdown(UI.CSS, unsafe_allow_html=True)


# ==========================================================================
# sidebar — settings, not flow
# ==========================================================================

with st.sidebar:
    st.markdown('<div class="sec" style="margin-top:0"><div class="k">'
                'Reviewer</div></div>', unsafe_allow_html=True)
    actor_key = st.selectbox(
        "Reviewing authority", list(L913.ACTORS), index=0,
        format_func=lambda k: str(L913.ACTORS[k]), key="who",
        label_visibility="collapsed")
    actor = L913.ACTORS[actor_key]
    r = actor.role
    st.markdown(" ".join(
        UI.pill(t, "ok" if on else "grey") for t, on in
        [("approve", r.can_approve), ("roll back", r.can_rollback),
         ("dept detail", r.sees_department_detail),
         ("provisional", r.sees_provisional)]), unsafe_allow_html=True)
    if not r.can_approve:
        st.warning("This role may not approve. The run will reach the gate and "
                   "be refused — which is the point of the gate.")

    st.markdown('<div class="sec"><div class="k">Run conditions</div></div>',
                unsafe_allow_html=True)
    with st.expander("What the data throws at it"):
        chaos = st.radio(
            "What the data throws at it",
            ["defect", "none", "unrepairable"], index=0,
            format_func=lambda c: {
                "defect": "A KPI loses its source — repairable",
                "none": "Clean data — nothing to repair",
                "unrepairable": "An unapproved KPI row — unrepairable",
            }[c], key="chaos", label_visibility="collapsed")
        pace = st.slider("Narration pace (s per stage)", 0.0, 0.8, 0.25, 0.05,
                         key="pace",
                         help="Slows the display so each stage can be read out "
                              "loud. It does not slow the agent.")
        max_actions = st.slider("Action budget", 15, 60, 40, 1, key="max_actions")
        max_seconds = st.slider("Wall-clock budget (s)", 10, 180, 120, 10,
                                key="max_seconds")

    if ss.pipe is not None:
        st.markdown('<div class="sec"><div class="k">This run</div></div>',
                    unsafe_allow_html=True)
        st.caption(ss.pipe._budget())
        with st.expander("Where it is in the graph"):
            current = ss.pipe.events[-1].node if ss.pipe.events else None
            st.graphviz_chart(P.render_dot(ss.pipe, current),
                              use_container_width=True)
            st.caption("Shaded = run. Dashed = the repair cycle. Octagons = "
                       "exits where it hands the problem back.")

    st.divider()
    if st.button("Start over", use_container_width=True):
        reset_all()
        st.rerun()
    st.caption("Lab-by-lab view: `streamlit run app.py`")


# ==========================================================================
# top bar
# ==========================================================================

period = None
if ss.planner is not None and getattr(ss.planner, "goal", None) is not None:
    period = ss.planner.goal.period
st.markdown(UI.topbar(str(actor),
                      ["Synthetic data", "Runs on this machine"]
                      + ([period] if period else [])),
            unsafe_allow_html=True)


# ==========================================================================
# the stage log
# ==========================================================================

class StageLog:
    """The run as six phases. A panel opens when its first stage arrives.

    The same class draws the live stream and the static re-render, so a stage
    can never look one way while it happens and another way afterwards.
    """

    def __init__(self, parent):
        self.parent = parent
        self.phase = None
        self.panel = None

    def add(self, ev):
        ph = UI.phase_of(ev.node)
        if ph != self.phase:
            self.phase = ph
            with self.parent:
                self.panel = st.container(border=True)
            with self.panel:
                st.markdown(UI.phase_header(ph), unsafe_allow_html=True)
        with self.panel:
            self._row(ev)

    @staticmethod
    def _row(ev):
        icon = STATUS_ICON.get(ev.status, "•")
        pass_tag = f" · pass {ev.visit}" if ev.visit > 1 else ""
        with st.expander(f"{icon}  {ev.headline}  ·  _{ev.lab}{pass_tag}_"):
            why = ev.detail.pop("why", None) if isinstance(ev.detail, dict) else None
            st.caption(f"**{ev.title}** — {DOING.get(ev.node, '')}.")
            if why:
                st.caption(f"Why it matters: {why}")
            if ev.status == "skipped":
                st.caption("Replayed from the checkpoint — the result was "
                           "reused, the work was not redone.")
            if ev.detail:
                st.json(ev.detail, expanded=False)
            st.caption(f"{ev.ms:.1f} ms · budget {ev.budget}")
            if why:
                ev.detail["why"] = why


def drive(pipe, pace):
    """Stream the pipeline, narrating each stage before and after it runs.

    The live line sits ABOVE the log: the log grows downward, so a status line
    under it would walk off the bottom of the screen within a few stages.
    """
    now = st.empty()
    log = StageLog(st.container())

    def announce(node, lab, title, visit):
        again = " (again)" if visit > 1 else ""
        now.markdown(f'<div class="now">⏳ <b>{lab}</b> — '
                     f'{DOING.get(node, title)}{again} …</div>',
                     unsafe_allow_html=True)
        if pace:
            time.sleep(pace * 0.6)

    replayed = 0
    for ev in pipe.stream(on_start=announce):
        if ev.status == "skipped":
            # a resume replays the completed prefix. Fifteen identical rows say
            # nothing; one line that counts them says the thing that matters.
            replayed += 1
            now.markdown(f'<div class="now">⏩ replaying {replayed} completed '
                         f'stage(s) from the checkpoint — reusing results, '
                         f're-running nothing …</div>', unsafe_allow_html=True)
            continue
        log.add(ev)
        if pace:
            time.sleep(pace * 0.4)
    now.empty()
    return pipe


def kpi_board(kpis, key, title, sub=""):
    """Status tiles, the KPIs that need attention, then every KPI."""
    missed = [k for k in kpis if k.get("status") == "below target"]
    at_risk = [k for k in kpis if k.get("status") == "at risk"]
    met = [k for k in kpis if k.get("status") == "on target"]
    prov = [k for k in kpis if k.get("figure_status") not in (None, "final")]

    st.markdown(UI.section(key, title, sub), unsafe_allow_html=True)
    st.markdown(UI.tiles([(len(missed), "Missed", "bad"),
                          (len(at_risk), "At risk", "warn"),
                          (len(met), "Met", "ok"),
                          (len(prov), "Provisional figures", "warn")]),
                unsafe_allow_html=True)

    attention = missed + at_risk
    if attention:
        shown = attention[:6]
        st.markdown(f'<div class="sec"><div class="t">Needs attention</div>'
                    f'<div class="s">{len(attention)} of {len(kpis)} KPIs are '
                    f'off target. Open a stage above to see how any figure was '
                    f'calculated and where it came from.</div></div>',
                    unsafe_allow_html=True)
        st.markdown(UI.kpi_cards(shown, domain_of), unsafe_allow_html=True)
        if len(attention) > len(shown):
            st.caption(f"{len(attention) - len(shown)} more off-target KPI(s) "
                       f"in the full table below.")

    st.markdown('<div class="sec"><div class="t">All KPIs</div></div>',
                unsafe_allow_html=True)
    st.markdown(UI.kpi_table(kpis, domain_of), unsafe_allow_html=True)

    with_detail = [k for k in kpis if k.get("drilldown")]
    if with_detail:
        st.markdown(
            f'<div class="sec"><div class="t">By department</div>'
            f'<div class="s">{len(with_detail)} of {len(kpis)} KPIs carry a '
            f'department breakdown under the drill-down policy you agreed. '
            f'Each department is measured against the same target, worst '
            f'first.</div></div>', unsafe_allow_html=True)
        for k in with_detail:
            worst = k["drilldown"][0]
            miss = len([d for d in k["drilldown"]
                        if d.get("status") not in ("on target", "no data")])
            head = (f'{k["name"]} — {miss} of {len(k["drilldown"])} departments '
                    f'below target, worst {worst["dept"]} at '
                    f'{UI.amount(worst["value"], k.get("unit", ""))}'
                    if worst.get("value") is not None
                    else f'{k["name"]} — department breakdown')
            with st.expander(head):
                st.markdown(UI.dept_table(k), unsafe_allow_html=True)
    elif kpis:
        st.caption("No department drill-down in this brief — the agreed policy "
                   "was institution level only.")


# ==========================================================================
# 1 · the request
# ==========================================================================

if ss.sent is None:
    st.markdown(UI.section("New brief", "What does leadership want?",
                           "Type anything. The vaguer it is, the more the agent "
                           "will refuse to guess."), unsafe_allow_html=True)
    choice = st.selectbox("Start from", list(EXAMPLES), key="ex")
    request = st.text_area("Request", EXAMPLES[choice], height=96, key="request",
                           label_visibility="collapsed")
    if st.button("Send it to the agent", type="primary"):
        pl = PlannerSession()
        pl.start(request)
        ss.planner = pl
        ss.sent = request
        ss.phase = "Clarify" if pl.status == "awaiting_input" else "Run"
        st.rerun()
    st.stop()


pl = ss.planner

# Once a run is under way the conversation folds into one line. It is still on
# the page — but the stage log grows downward, and a demo that has to scroll
# past the whole back-story to see the agent work is the thing this dashboard
# exists to avoid.
folded = bool(ss.get("go")) or ss.pipe is not None
convo = (st.expander(f"You asked “{ss.sent[:60]}"
                     f"{'…' if len(ss.sent) > 60 else ''}”"
                     + (f" · {len(ss.qa)} clarify round(s)" if ss.qa else "")
                     + " — show the conversation")
         if folded else st.container())

with convo:
    if not folded:
        st.markdown(UI.section("New brief", "You asked"), unsafe_allow_html=True)
    st.markdown(f'<div class="said">{ss.sent}</div>', unsafe_allow_html=True)
    for turn in ss.qa:
        st.markdown(f"**The agent asked for {len(turn['questions'])} thing(s)**")
        for q in turn["questions"]:
            st.markdown(f'<div class="ask">{q}</div>', unsafe_allow_html=True)
        st.markdown("**You answered**")
        st.markdown(f'<div class="said">{turn["answer"]}</div>',
                    unsafe_allow_html=True)


# ==========================================================================
# 2 · what it is missing
# ==========================================================================

if ss.phase == "Clarify":
    st.markdown(UI.section(
        f"Clarify · round {pl.rounds}",
        f"The agent needs {len(pl.pending_questions)} more thing(s) before it "
        f"will start",
        "It will not invent a scope, a period or a KPI set. This is the whole "
        "difference between an agent and a chatbot."), unsafe_allow_html=True)
    # Each question offers the answers worth clicking, and the box below takes
    # anything the options do not cover. Both feed the same extractor — a
    # clicked answer is not a special case, it is text the agent reads.
    prompts = pl.pending_prompts or [{"slot": f"q{i}", "question": q, "options": [],
                                      "why": ""}
                                     for i, q in enumerate(pl.pending_questions)]
    picks = {}
    for p in prompts:
        st.markdown(f'<div class="ask">{p["question"]}</div>',
                    unsafe_allow_html=True)
        if p["options"]:
            # multi, not single: Streamlit's own AppTest harness cannot read a
            # single-select pills widget whose value is still None, and a
            # question nobody can test headlessly is a question that will break
            # unnoticed. Multi also lets two partial answers be clicked.
            chosen = st.pills(p["question"], p["options"], selection_mode="multi",
                              key=f"pick_{p['slot']}", label_visibility="collapsed")
            if chosen:
                picks[p["slot"]] = ", ".join(chosen)
        if p.get("why"):
            st.caption(f"why it needs this: {p['why']}")

    # Clearing has to happen BEFORE the box is instantiated: Streamlit refuses
    # a write to a widget's key once that widget exists in the current run.
    if ss.pop("clear_reply", False):
        ss["reply"] = ""
    typed = st.text_area(
        "In your own words", key="reply", height=80, label_visibility="collapsed",
        placeholder="…or type your own answer here. Anything you type is read "
                    "the same way a clicked option is.")
    answer = ". ".join(list(picks.values())
                       + ([typed.strip()] if typed.strip() else []))
    if answer:
        st.caption(f"Sending to the agent: _{answer}_")
    else:
        st.caption("Click an option above, or type an answer.")

    if st.button("Answer", type="primary", disabled=not answer):
        ss.qa = ss.qa + [{"questions": list(pl.pending_questions),
                          "answer": answer}]
        pl.answer(answer)
        ss["clear_reply"] = True             # a fresh box for the next round
        if pl.status == "plan_ready":
            ss.phase = "Run"
        elif pl.status == "abandoned":
            st.error("The agent gave up rather than assume: " +
                     pl.log[-1].get("stop_reason", ""))
        st.rerun()
    with st.expander("What it has pinned down so far"):
        st.json(pl.goal.as_dict(), expanded=True)
    st.stop()


# ==========================================================================
# 3 · the plan it locked
# ==========================================================================

spec_preview = P.spec_from_plan(pl.plan, pl.goal)
body = pl.plan.body

if "last_diff" in ss:
    d = ss.pop("last_diff")
    # A revision that changed nothing must not be reported as a success. The
    # run would produce byte-identical output and the honest reason is that the
    # feedback named nothing the planner can act on.
    if not d["changed"]:
        st.warning(
            f"**Nothing changed.** r{pl.plan.revision} is identical to "
            f"r{pl.plan.revision - 1}: the feedback named no field this planner "
            f"can patch, so re-running it would produce exactly the same brief.")
        st.caption("It acts on: narrowing or widening the domains (“only "
                   "Placement”, “drop Finance”, “also cover Research”), the "
                   "department-level drill-down policy, a page limit, named "
                   "risk owners, year-on-year trend context, and removing the "
                   "executive summary.")
    else:
        st.info(f"Plan revised **in place** — r{pl.plan.revision}. It changed "
                f"{len(d['changed'])} field(s) ({', '.join(d['changed'])}) and "
                f"left {len(d['untouched'])} untouched "
                f"({', '.join(d['untouched'])}). A chatbot would have "
                f"regenerated the lot.")
        done = [h for h in pl.plan.patch_history
                if h.get("revision") == pl.plan.revision]
        if done:
            with st.expander(f"What the {len(done)} patch operation(s) did"):
                for h in done:
                    st.markdown(f"- `{h['op']}` — {h.get('why', '')}  \n"
                                f"  → {h.get('effect', '')}")

plan_line = (f"**Plan locked** — r{pl.plan.revision} · "
             f"{len(body['analysis_steps'])} analysis steps · "
             f"{len(spec_preview['required_kpis'])} KPIs in scope · "
             f"{len(pl.conflicts)} conflict(s) it refused to hide")
scope_line = ("Scope: " + ", ".join(spec_preview["domains"]) + " · "
              + spec_preview["period"] + " · drill-down "
              + spec_preview["drilldown_policy"])
if not folded:
    st.markdown(UI.section("Plan", f"Locked at revision r{pl.plan.revision}",
                           scope_line), unsafe_allow_html=True)
    st.markdown(plan_line)

with st.expander(f"The contract your answers produced — "
                 f"{len(spec_preview['required_kpis'])} KPIs over "
                 f"{len(spec_preview['domains'])} domain(s); this is what the "
                 f"rest of the run obeys"):
    if folded:
        st.markdown(plan_line)
        st.caption(scope_line)
    st.caption("Change your answers and these change with them: which KPIs are "
               "computed, which domain packs are called, and which acceptance "
               "tests get derived. The plan is the contract, not a printout.")
    st.markdown(f"_{body['objective']}_")
    st.json({"spec_id": spec_preview["spec_id"],
             "period": spec_preview["period"],
             "domains": spec_preview["domains"],
             "required_kpis": spec_preview["required_kpis"],
             "drilldown_policy": spec_preview["drilldown_policy"],
             "target_sets": spec_preview.get("target_sets", []),
             "brief_sections": spec_preview["brief_sections"]}, expanded=True)
    if pl.conflicts:
        st.markdown("**Conflicts carried into the assumptions, not resolved "
                    "silently**")
        for c in pl.conflicts:
            st.markdown(f"- **{c['type']}** ({c['domain']}) — {c['detail']}  \n"
                        f"  → {c['required_action']}")

if ss.phase == "Run":
    # Two passes: the click only raises a flag and reruns, so that the fold
    # above is already closed before the first stage is drawn.
    if not ss.get("go"):
        st.caption("From here to the signature, nothing is asked of you.")
        if st.button("▶  Run the pipeline", type="primary"):
            ss.go = True
            st.rerun()
        st.stop()

    import edss_labs678 as L678
    ss.go = False
    ss.run_n += 1
    pipe = P.Pipeline(
        f"pipeline-{ss.run_n:02d}", pl.plan, pl.goal, actor, ss.gov,
        checkpoint_dir=CHECKPOINTS, chaos=chaos,
        budget=L678.Budget(max_actions=max_actions, max_connector_calls=120,
                           max_seconds=float(max_seconds)))
    ss.pipe = pipe
    st.markdown(UI.section("Run", "What it is doing, unattended"),
                unsafe_allow_html=True)
    drive(pipe, pace)
    ss.phase = {"paused": "Approve", "published": "Published",
                "escalated": "Published"}.get(pipe.outcome, "Published")
    st.rerun()


# ==========================================================================
# 4 · what it did, unattended
# ==========================================================================

pipe = ss.pipe
st.markdown(UI.section("Run", "What it did on its own",
                       "Every line is one action the runtime performed, in the "
                       "order the graph chose. Open one to see the call, the "
                       "result and what it cost."), unsafe_allow_html=True)

replayed = [e for e in pipe.events if e.status == "skipped"]
log = StageLog(st.container())
grouped = False
for ev in pipe.events:
    if ev.status == "skipped":
        if grouped:
            continue
        grouped = True
        with st.expander(f"⏩  {len(replayed)} stage(s) replayed from the "
                         f"checkpoint when the run resumed after the signature "
                         f"— reused, not re-executed"):
            st.caption("The approval gate stops the world. Resuming does not "
                       "redo the work: the runtime recognises every completed "
                       "action and returns its stored result, which is the same "
                       "mechanism that makes a crashed run recoverable.")
            for e in replayed:
                st.markdown(f"- `{e.node}` · {e.lab} — {e.ms:.2f} ms")
        continue
    log.add(ev)


# ==========================================================================
# 5 · the signature
# ==========================================================================

if ss.phase == "Approve":
    suite = pipe.state.get("suite")
    view = L913.view_for(actor, pipe.artifact)

    st.markdown(UI.section(
        "Review queue", "⏸️ It stopped and asked for a named human",
        f"{len([e for e in pipe.events if e.status == 'ok'])} stages · "
        + (f"{sum(r['passed'] for r in suite.results)}/{len(suite.results)} "
           f"acceptance tests green" if suite else "no suite")
        + f" · {len([e for e in pipe.events if e.node == 'heal' and e.status == 'ok'])}"
          f" self-repair(s) · {len(pipe.runtime.audit)} audit entries. Nothing "
          f"is published until someone signs."), unsafe_allow_html=True)

    kpi_board(view["kpis"], "Draft", "The draft, as this reader sees it",
              (f"{len(view['redactions'])} redaction(s) for {actor}: "
               f"{', '.join(view['redactions'])}" if view["redactions"]
               else f"Nothing withheld from {actor} at this access level."))

    st.markdown('<div class="sec"><div class="k">Decision</div></div>',
                unsafe_allow_html=True)
    edits = st.text_input("Edits you want recorded with the approval",
                          value=ss.edits, key="edits")
    g1, g2 = st.columns(2)
    if g1.button("✔  Approve and publish", type="primary",
                 use_container_width=True):
        pipe.edits = [e.strip() for e in edits.split(";") if e.strip()]
        pipe.approve()
        drive(pipe, pace)
        ss.phase = "Published"
        st.rerun()
    if g2.button("✖  Reject", use_container_width=True):
        pipe.reject()
        drive(pipe, pace)
        ss.phase = "Published"
        st.rerun()
    st.caption("The runtime blocks the publish action until a named human is "
               "recorded against it — the same mechanism that makes a crashed "
               "run resumable.")
    st.stop()


# ==========================================================================
# 6 · the result
# ==========================================================================

s = pipe.summary()
# keyed by run_id: the budget line carries elapsed wall time, so two summaries
# of the same run are never equal and a value check would append a duplicate
# row on every rerun
ss.runs = [r for r in ss.runs if r["run_id"] != s["run_id"]] + [s]

if pipe.outcome == "published":
    st.success(f"Published **v{pipe.version}** · approved by {actor} · reversible")
else:
    st.error(f"Not published — {pipe.escalation}")
    st.caption("This is a success for the system: it stopped, named the reason "
               "and handed the problem to a human rather than shipping "
               "something it could not stand behind.")

st.caption(f"{s['stages']} stages · {s['wall_ms']:.0f} ms of agent time "
           f"(display pacing and human time excluded) · {s['tests_green']}/"
           f"{s['tests_total']} tests green · {s['heal_rounds']} self-repair(s) "
           f"· {s['graph_steps']} graph steps · {s['replayed']} stage(s) "
           f"replayed from the checkpoint, 0 re-executed · budget left: "
           f"{s['budget']}")

live = pipe.governance.live()
if live:
    kpi_board(live["kpis"], "Report",
              f"Decision brief {live['period']}, version {live['version']}",
              f"{live['spec_id']} · approved by {live['approved_by']} at "
              f"{live['approved_at']}")

    with st.expander("Options the domain packs drafted, and the assumptions"):
        for o in live["options"]:
            st.markdown(f"**{o['kpi_id']} — {o['title']}**  ·  _{o['specialist']}_")
            for risk in o.get("risks", []):
                st.markdown(f"- risk: {risk}")
            if o.get("trade_off"):
                st.markdown(f"- trade-off: {o['trade_off']}")
        st.markdown("**Assumptions**")
        for a in live["assumptions"]:
            st.markdown(f"- {a}")
        if live.get("edits"):
            st.markdown("**Edits recorded at approval**")
            for e in live["edits"]:
                st.markdown(f"- {e}")
    d1, d2 = st.columns(2)
    d1.download_button("Download the brief (Markdown)", P.brief_markdown(live, s),
                       file_name=f"decision_brief_v{live['version']}.md",
                       use_container_width=True)
    d2.download_button("Download the brief (JSON)",
                       json.dumps(live, indent=2, default=str),
                       file_name=f"decision_brief_v{live['version']}.json",
                       use_container_width=True)

st.markdown(UI.section("Evidence", "Everything behind that brief",
                       "Nothing here is typed by hand — each section is read "
                       "off this run."), unsafe_allow_html=True)

with st.expander("The path the graph actually walked"):
    st.code(" → ".join(
        t["node"] + (f"[{t['condition_taken']}]" if t["condition_taken"] else "")
        for t in pipe.graph.trace), language=None)
    st.caption("The prefix repeats because the graph was walked a second time "
               "when the run resumed after the signature — those stages were "
               "replayed from the checkpoint, not re-executed.")
    st.graphviz_chart(P.render_dot(pipe), use_container_width=True)

with st.expander("Audit trail — every action, its budget at the time, its outcome"):
    st.dataframe(pd.DataFrame(
        [{"#": a["seq"], "Action": a["action"], "Kind": a["kind"],
          "Status": a["status"], "ms": a["ms"], "Budget": a["budget"],
          "At": a["at"]} for a in pipe.runtime.audit]),
        use_container_width=True, hide_index=True, height=300)
    st.markdown("**Governance audit** — who did what to the release")
    if pipe.governance.audit:
        st.dataframe(pd.DataFrame(pipe.governance.audit),
                     use_container_width=True, hide_index=True)
    else:
        st.caption("No release event — nothing reached the governed store.")

with st.expander("Which of the fourteen labs this run actually used"):
    st.caption("Read off this run's own events, not from a list. A lab with no "
               "stage did not participate.")
    st.dataframe(pd.DataFrame(pipe.lab_coverage()).rename(
        columns={"lab": "Lab", "where": "Stage(s) in this run",
                 "note": "What it contributed", "evidence": "Evidence"}),
        use_container_width=True, hide_index=True, height=530)

with st.expander("Versions, and rolling back"):
    gov = pipe.governance
    if not gov.versions:
        st.info("Nothing published yet in this session.")
    else:
        st.dataframe(pd.DataFrame(
            [{"Version": v, "Live": v == gov.current,
              "Approved by": b["approved_by"], "At": b["approved_at"],
              "KPIs": len(b["kpis"]),
              "Off target": sum(1 for k in b["kpis"]
                                if k["status"] != "on target"),
              "Edits": len(b.get("edits", []))}
             for v, b in sorted(gov.versions.items())]),
            use_container_width=True, hide_index=True)
        others = [v for v in sorted(gov.versions) if v != gov.current]
        if others:
            cols = st.columns(min(len(others), 4))
            for i, v in enumerate(others):
                # a button per version: nothing to keep in state between reruns
                if cols[i % len(cols)].button(f"⟲  Roll back to v{v}",
                                              key=f"rb_{v}",
                                              use_container_width=True):
                    try:
                        gov.rollback(actor, v)
                        st.success(f"Live release is now v{v}. The rollback is a "
                                   f"new audit entry — history was not rewritten.")
                        st.rerun()
                    except L913.PermissionError_ as exc:
                        st.error(str(exc))
        else:
            st.caption("Only one version exists. Ask for a revision below to "
                       "produce v2, then roll back to v1.")

if ss.runs and len(ss.runs) > 1:
    with st.expander("Every run in this session"):
        st.dataframe(pd.DataFrame(
            [{"Run": r["run_id"], "Outcome": r["outcome"], "v": r["version"],
              "Stages": r["stages"],
              "Tests": f"{r['tests_green']}/{r['tests_total']}",
              "Agent ms": r["wall_ms"], "Domains": len(r["domains"])}
             for r in ss.runs]),
            use_container_width=True, hide_index=True)


# ==========================================================================
# 7 · the loop back
# ==========================================================================

st.markdown(UI.section("Revise", "Want it changed?",
                       "Feedback revises the plan you already locked — Lab 1's "
                       "revise, not a replan — and the pipeline runs again to "
                       "produce the next version."), unsafe_allow_html=True)
fb = st.text_input("Feedback", value=ss.fb, key="fb",
                   label_visibility="collapsed")
if st.button("Revise and run again"):
    pl.apply_feedback(fb)
    ss["last_diff"] = pl.diff_last_revision()
    ss.phase = "Run"
    st.rerun()
