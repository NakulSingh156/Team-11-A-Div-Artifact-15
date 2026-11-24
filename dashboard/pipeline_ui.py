"""pipeline_ui — the look of the end-to-end dashboard.

Presentation only. Nothing here reads a KPI, decides a status or computes a
figure: every value it draws was produced by the pipeline and is passed in. It
exists so pipeline_app.py can stay about the flow of the run.

The design rules it enforces:

    * one accent colour, three status colours, everything else grey
    * raised cards on a dark ground, 1px borders, light placed once from the
      top-left rather than a flat fill
    * numbers are large and set in a tabular font so columns line up
    * every status is a pill with the same shape wherever it appears
    * the stage log is grouped into six phases, so a run reads as a process
      rather than as nineteen consecutive lines
"""

from typing import Any, Dict, List, Optional, Sequence

# ==========================================================================
# the six phases a run moves through
# ==========================================================================
# Each graph node belongs to exactly one. The order here is the order a run
# walks them, so grouping the event list by phase never reorders it.

PHASES: List[Dict[str, Any]] = [
    {"key": "UNDERSTAND", "title": "Understand the request",
     "labs": "Lab 1 · Lab 4",
     "nodes": ["plan_locked", "recall"]},
    {"key": "GATHER", "title": "Get the data",
     "labs": "Lab 5 · Lab 8",
     "nodes": ["connector_read", "swarm", "reconcile"]},
    {"key": "ANALYSE", "title": "Work out what it means",
     "labs": "Lab 2 · Lab 3 · Lab 13 · Lab 14",
     "nodes": ["domain_skills", "compute_kpis", "specialists", "compose"]},
    {"key": "CHECK", "title": "Prove it before anyone reads it",
     "labs": "Lab 9 · Lab 10 · Lab 11",
     "nodes": ["grounding", "validate", "heal", "acceptance"]},
    {"key": "DECIDE", "title": "Route it to a named human",
     "labs": "Lab 11 · Lab 12",
     "nodes": ["submit", "approval", "publish"]},
    {"key": "RECORD", "title": "Keep the record",
     "labs": "Lab 4 · Lab 10",
     "nodes": ["archive", "escalate"]},
]

PHASE_OF = {n: p["key"] for p in PHASES for n in p["nodes"]}
PHASE_BY_KEY = {p["key"]: p for p in PHASES}


def phase_of(node: str) -> str:
    return PHASE_OF.get(node, "RECORD")


# ==========================================================================
# the stylesheet
# ==========================================================================

CSS = """<style>
:root{
  --bg:#0c0f16; --card:#141924; --card-2:#181e2b; --line:#262e3d;
  --line2:#1d2432;
  --ink:#e9edf5; --ink2:#aeb9cb; --muted:#78849a;
  --brand:#8098ff; --brand-soft:rgba(109,131,255,.13);
  --brand-line:rgba(128,152,255,.32);
  --ok:#5fd68f; --ok-bg:rgba(45,190,110,.12); --ok-line:rgba(70,200,130,.30);
  --warn:#f3b64b; --warn-bg:rgba(230,165,50,.12);
  --warn-line:rgba(235,175,70,.30);
  --bad:#ff8077; --bad-bg:rgba(240,90,80,.12); --bad-line:rgba(245,110,100,.30);
}
/* A flat fill reads as "unstyled dark". The light is placed once, top-left,
   and everything else sits on it — which is what makes a dark page look lit
   rather than merely switched off. */
.stApp{background:
  radial-gradient(1100px 620px at 12% -12%, #1a2132 0%, rgba(12,15,22,0) 62%),
  radial-gradient(900px 500px at 92% 4%, #15203a 0%, rgba(12,15,22,0) 55%),
  var(--bg);
  background-attachment:fixed;}
body, .stApp{-webkit-font-smoothing:antialiased;}
/* Streamlit floats its own toolbar over the top-right of the page, so the
   bar below has to start underneath it. */
.block-container{padding-top:3.2rem; padding-bottom:4rem; max-width:63rem;}
header[data-testid="stHeader"]{background:transparent;}
/* Streamlit's own containers are the panels behind the stage log. */
div[data-testid="stVerticalBlockBorderWrapper"]{background:var(--card);
  border-radius:12px;}
section[data-testid="stSidebar"]{background:rgba(18,23,33,.72);
  border-right:1px solid var(--line); backdrop-filter:blur(8px);}
section[data-testid="stSidebar"] .block-container{padding-top:1.2rem;}

/* ---------- top bar ---------- */
.topbar{display:flex; align-items:center; justify-content:space-between;
  gap:1rem; flex-wrap:wrap; padding:.1rem 0 .8rem 0;
  border-bottom:1px solid var(--line); margin-bottom:1.15rem;}
.brand{display:flex; align-items:center; gap:.6rem;}
.mark{width:30px; height:30px; border-radius:8px;
  background:linear-gradient(145deg, #6d83ff, #4b5fe0);
  box-shadow:0 0 0 1px rgba(128,152,255,.35), 0 4px 14px rgba(77,97,224,.35);
  color:#fff; font-weight:700; font-size:.78rem; letter-spacing:.02em;
  display:flex; align-items:center; justify-content:center;}
.brand b{font-size:1.02rem; color:var(--ink); letter-spacing:-.01em;
  display:block; line-height:1.15;}
.brand small{font-size:.76rem; color:var(--muted);}
.chips{display:flex; gap:.4rem; flex-wrap:wrap; align-items:center;}
.chip{font-size:.74rem; color:var(--ink2); background:rgba(255,255,255,.035);
  border:1px solid var(--line); border-radius:999px; padding:.2rem .6rem;
  white-space:nowrap;}
.chip.who{background:var(--brand-soft); border-color:var(--brand-line);
  color:var(--brand); font-weight:600;}

/* ---------- section headings ---------- */
.sec{margin:1.5rem 0 .6rem 0;}
.sec .k{font-size:.7rem; font-weight:700; letter-spacing:.09em;
  color:var(--muted); text-transform:uppercase;}
.sec .t{font-size:1.06rem; font-weight:650; color:var(--ink);
  letter-spacing:-.01em; margin-top:.1rem;}
.sec .s{font-size:.84rem; color:var(--muted); margin-top:.12rem;}

/* ---------- the transcript of what was said ---------- */
.said{border-left:3px solid var(--line); padding:.08rem 0 .08rem .85rem;
  margin:.15rem 0 .9rem 0; color:var(--ink2); font-size:.93rem;}
.ask{border-left:3px solid var(--warn-line); background:var(--warn-bg);
  padding:.5rem .85rem; margin:.3rem 0; border-radius:0 7px 7px 0;
  font-size:.92rem; color:var(--ink);}

/* ---------- the live line ---------- */
.now{color:var(--brand); font-size:.93rem; padding:.5rem .8rem; font-weight:500;
  background:var(--brand-soft); border:1px solid var(--brand-line);
  border-radius:9px; margin-bottom:.5rem;}

/* ---------- phase panels + the stage log ---------- */
.ph{display:flex; align-items:baseline; gap:.55rem; flex-wrap:wrap;
  padding:.1rem .1rem .45rem .1rem; margin-bottom:.25rem;
  border-bottom:1px solid var(--line2);}
.ph .k{font-size:.7rem; font-weight:700; letter-spacing:.09em;
  color:var(--brand);}
.ph .t{font-size:.9rem; color:var(--ink); font-weight:600;}
.ph .l{font-size:.73rem; color:var(--muted); margin-left:auto;}
div[data-testid="stExpander"] details{border:none; border-radius:0;
  background:transparent; border-bottom:1px solid var(--line2);}
div[data-testid="stExpander"]:last-child details{border-bottom:none;}
div[data-testid="stExpander"] summary{padding:.36rem .1rem; font-size:.9rem;}
div[data-testid="stExpander"] summary:hover{color:var(--brand);}

/* ---------- status tiles ---------- */
.tiles{display:grid; grid-template-columns:repeat(4,1fr); gap:.65rem;
  margin:.2rem 0 .3rem 0;}
.tile{background:linear-gradient(180deg, var(--card-2) 0%, var(--card) 100%);
  border:1px solid var(--line); border-radius:11px; padding:.75rem .85rem;
  box-shadow:0 1px 0 rgba(255,255,255,.03) inset;}
.tile .n{font-size:1.55rem; font-weight:680; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums; line-height:1.1;}
.tile .l{font-size:.78rem; color:var(--muted); margin-top:.1rem;}
.tile.bad .n{color:var(--bad);} .tile.warn .n{color:var(--warn);}
.tile.ok .n{color:var(--ok);}   .tile.n0 .n{color:var(--ink2);}

/* ---------- KPI cards ---------- */
.cards{display:grid; grid-template-columns:repeat(3,1fr); gap:.65rem;}
.kcard{background:linear-gradient(180deg, var(--card-2) 0%, var(--card) 100%);
  border:1px solid var(--line); border-radius:11px;
  padding:.8rem .85rem; border-top:3px solid var(--line);
  box-shadow:0 1px 0 rgba(255,255,255,.03) inset;}
.kcard.bad{border-top-color:var(--bad);} .kcard.warn{border-top-color:var(--warn);}
.kcard.ok{border-top-color:var(--ok);}
.kcard .dom{font-size:.71rem; font-weight:700; letter-spacing:.07em;
  color:var(--muted); text-transform:uppercase;}
.kcard .nm{font-size:.92rem; font-weight:620; color:var(--ink);
  margin:.12rem 0 .45rem 0; line-height:1.25;}
.kcard .v{font-size:1.75rem; font-weight:680; letter-spacing:-.025em;
  color:var(--ink); font-variant-numeric:tabular-nums; line-height:1;}
.kcard .u{font-size:.8rem; color:var(--muted); font-weight:500;
  margin-left:.22rem;}
.kcard .tg{font-size:.79rem; color:var(--muted); margin-top:.4rem;}
.kcard .tg b{font-weight:600;}
.kcard .note{font-size:.76rem; color:var(--warn); margin-top:.4rem;
  line-height:1.35;}
.kcard .flags{margin-top:.5rem; display:flex; gap:.3rem; flex-wrap:wrap;}
.spark{margin:.5rem 0 .1rem 0;}

/* ---------- pills ---------- */
.pill{display:inline-block; font-size:.72rem; font-weight:600;
  padding:.13rem .5rem; border-radius:999px; border:1px solid transparent;
  white-space:nowrap;}
.pill.ok{color:var(--ok); background:var(--ok-bg); border-color:var(--ok-line);}
.pill.warn{color:var(--warn); background:var(--warn-bg);
  border-color:var(--warn-line);}
.pill.bad{color:var(--bad); background:var(--bad-bg); border-color:var(--bad-line);}
.pill.grey{color:var(--ink2); background:rgba(255,255,255,.045);
  border-color:var(--line);}

/* ---------- the KPI table ---------- */
.ktab{width:100%; border-collapse:collapse; background:var(--card);
  color:var(--ink2);
  border:1px solid var(--line); border-radius:11px; overflow:hidden;
  font-size:.86rem;}
.ktab th{text-align:left; font-size:.72rem; font-weight:700; color:var(--muted);
  letter-spacing:.05em; text-transform:uppercase; padding:.55rem .8rem;
  border-bottom:1px solid var(--line); background:var(--card-2);}
.ktab th.r, .ktab td.r{text-align:right;}
.ktab td{padding:.5rem .8rem; border-bottom:1px solid var(--line2);
  color:var(--ink2); vertical-align:middle;}
.ktab tr:last-child td{border-bottom:none;}
.ktab td.nm{color:var(--ink); font-weight:550;}
.ktab td.num{font-variant-numeric:tabular-nums; font-weight:620;
  color:var(--ink);}
.ktab tr.grp td{background:var(--card-2); font-size:.7rem; font-weight:700;
  letter-spacing:.08em; color:var(--muted); text-transform:uppercase;
  padding:.4rem .8rem;}
.ktab .sub{display:block; font-size:.73rem; color:var(--muted);
  font-weight:400; margin-top:.12rem;}

/* ---------- controls ---------- */
.stButton button{border-radius:8px; font-weight:600;}
.stButton button[kind="primary"]{color:#fff; border:1px solid var(--brand-line);
  background:linear-gradient(145deg, #6d83ff 0%, #4a5ddb 100%);
  box-shadow:0 4px 16px rgba(74,93,219,.28);}
.stButton button[kind="primary"]:hover{filter:brightness(1.07);
  border-color:rgba(150,170,255,.55);}
/* inputs sit on the same tone as the cards, so they need their own edge */
.stTextArea textarea, .stTextInput input,
div[data-baseweb="select"] > div{border:1px solid var(--line) !important;}
.stTextArea textarea:focus, .stTextInput input:focus{
  border-color:var(--brand-line) !important;}

/* ---------- misc ---------- */
div[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;}
hr{margin:1.1rem 0; border-color:var(--line);}
@media (max-width: 900px){
  .tiles{grid-template-columns:repeat(2,1fr);}
  .cards{grid-template-columns:1fr;}
}
</style>"""


# ==========================================================================
# small pieces
# ==========================================================================

KIND_OF_STATUS = {"on target": "ok", "at risk": "warn", "below target": "bad",
                  "missed": "bad"}


def pill(text: str, kind: str = "grey") -> str:
    return f'<span class="pill {kind}">{text}</span>'


def status_pill(status: str) -> str:
    return pill(status, KIND_OF_STATUS.get(status, "grey"))


def topbar(actor: str, chips: Sequence[str]) -> str:
    bits = "".join(f'<span class="chip">{c}</span>' for c in chips)
    return (f'<div class="topbar"><div class="brand"><span class="mark">ED</span>'
            f'<div><b>EDSS</b><small>Executive Decision Support</small></div></div>'
            f'<div class="chips">{bits}'
            f'<span class="chip who">{actor}</span></div></div>')


def section(key: str, title: str, sub: str = "") -> str:
    s = f'<div class="s">{sub}</div>' if sub else ""
    return (f'<div class="sec"><div class="k">{key}</div>'
            f'<div class="t">{title}</div>{s}</div>')


def phase_header(key: str) -> str:
    p = PHASE_BY_KEY[key]
    return (f'<div class="ph"><span class="k">{key}</span>'
            f'<span class="t">{p["title"]}</span>'
            f'<span class="l">{p["labs"]}</span></div>')


def tiles(items: Sequence[Sequence[Any]]) -> str:
    """items: (count, label, kind). kind picks the number's colour."""
    cells = "".join(
        f'<div class="tile {kind if n else "n0"}"><div class="n">{n}</div>'
        f'<div class="l">{label}</div></div>' for n, label, kind in items)
    return f'<div class="tiles">{cells}</div>'


# ==========================================================================
# KPI presentation
# ==========================================================================

def _trim(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def amount(value: Any, unit: str) -> str:
    """A figure and its unit, spaced the way each unit is actually written.

    "91.85%" takes no space; "1.19 per faculty" does. Getting this wrong is the
    fastest way to make a careful number look careless.
    """
    unit = unit or ""
    if unit in ("%",):
        return f"{value}{unit}"
    return f"{value} {unit}".strip()


def gap_text(kpi: Dict[str, Any]) -> str:
    """How far off target, in the KPI's own unit. Never recomputes a status."""
    try:
        delta = float(kpi["value"]) - float(kpi["target"])
    except (TypeError, ValueError, KeyError):
        return ""
    unit = kpi.get("unit", "")
    word = "pts" if unit == "%" else unit
    if abs(delta) < 5e-3:
        return "exactly on target"
    return f"{_trim(abs(delta))} {word} {'above' if delta > 0 else 'below'} target"


def sparkline(values: Sequence[float], kind: str = "ok",
              w: int = 150, h: int = 26) -> str:
    """Department spread as a tiny inline SVG — no chart library, no axes.

    It is a shape, not a reading: the numbers themselves are in the drill-down.
    """
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = w / (len(vals) - 1)
    pts = " ".join(f"{i * step:.1f},{h - 3 - (v - lo) / span * (h - 8):.1f}"
                   for i, v in enumerate(vals))
    colour = {"ok": "#5fd68f", "warn": "#f3b64b", "bad": "#ff8077"}.get(kind,
                                                                       "#78849a")
    last_x, last_y = pts.split(" ")[-1].split(",")
    return (f'<div class="spark"><svg width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="{colour}" '
            f'stroke-width="1.6" stroke-linejoin="round" opacity=".75"/>'
            f'<circle cx="{last_x}" cy="{last_y}" r="2.6" fill="{colour}"/>'
            f'</svg></div>')


def kpi_card(kpi: Dict[str, Any], domain: str) -> str:
    kind = KIND_OF_STATUS.get(kpi.get("status", ""), "grey")
    flags = [status_pill(kpi.get("status", "—"))]
    if kpi.get("figure_status") and kpi["figure_status"] != "final":
        flags.append(pill(kpi["figure_status"], "warn"))
    if kpi.get("caveat"):
        flags.append(pill(str(kpi["caveat"])[:40], "grey"))
    note = ""
    if kpi.get("rounding_warning"):
        note = ('<div class="note">⚠ rounds to the target but does not meet '
                'it — the unrounded figure is reported</div>')
    spark = sparkline([d.get("value") for d in kpi.get("drilldown") or []], kind)
    return (f'<div class="kcard {kind}">'
            f'<div class="dom">{domain}</div>'
            f'<div class="nm">{kpi.get("name", "")}</div>'
            f'<div><span class="v">{kpi.get("value_shown", "")}</span>'
            f'<span class="u">{kpi.get("unit", "")}</span></div>'
            f'{spark}'
            f'<div class="tg">Target '
            f'<b>{amount(kpi.get("target", ""), kpi.get("unit", ""))}</b>'
            f' · {gap_text(kpi)}</div>'
            f'{note}'
            f'<div class="flags">{"".join(flags)}</div></div>')


def kpi_cards(kpis: Sequence[Dict[str, Any]], domain_of) -> str:
    inner = "".join(kpi_card(k, domain_of(k["kpi_id"])) for k in kpis)
    return f'<div class="cards">{inner}</div>'


def dept_table(kpi: Dict[str, Any]) -> str:
    """One KPI broken out by department, worst first.

    Each department carries the status the KPI engine gave it, from the same
    comparison the institution figure went through — so a reader never has to
    work out whether 63.79 against a target of 80 is a miss.
    """
    rows = kpi.get("drilldown") or []
    if not rows:
        return ('<div class="sec"><div class="s">No department drill-down was '
                'produced for this KPI under the agreed policy.</div></div>')
    unit = kpi.get("unit", "")
    out = []
    for d in rows:
        if d.get("value") is None:
            out.append(f'<tr><td class="nm">{d["dept"]}</td>'
                       f'<td class="r">—</td><td class="r">—</td>'
                       f'<td class="r">{pill("no data", "grey")}</td></tr>')
            continue
        v = d.get("variance")
        gap = "" if v is None else f'{"+" if v > 0 else ""}{_trim(v)}'
        out.append(
            f'<tr><td class="nm">{d["dept"]}'
            f'<span class="sub">{d.get("dept_name", "")}</span></td>'
            f'<td class="r num">{amount(d["value"], unit)}</td>'
            f'<td class="r">{gap}</td>'
            f'<td class="r">{status_pill(d.get("status", "—"))}</td></tr>')
    return ('<table class="ktab"><colgroup><col style="width:46%">'
            '<col style="width:18%"><col style="width:18%">'
            '<col style="width:18%"></colgroup><thead><tr><th>Department</th>'
            f'<th class="r">Value</th><th class="r">vs target '
            f'{amount(kpi.get("target", ""), unit)}</th>'
            '<th class="r">Status</th></tr></thead><tbody>'
            + "".join(out) + "</tbody></table>")


def kpi_table(kpis: Sequence[Dict[str, Any]], domain_of) -> str:
    """Every KPI, grouped by domain, in source order."""
    rows: List[str] = []
    seen: Optional[str] = None
    for k in kpis:
        dom = domain_of(k["kpi_id"])
        if dom != seen:
            seen = dom
            rows.append(f'<tr class="grp"><td colspan="5">{dom}</td></tr>')
        sub = ""
        if k.get("figure_status") and k["figure_status"] != "final":
            sub = f'<span class="sub">{k["figure_status"]} figure</span>'
        elif k.get("caveat"):
            sub = f'<span class="sub">{str(k["caveat"])[:60]}</span>'
        rows.append(
            f'<tr><td class="nm">{k.get("name", "")}{sub}</td>'
            f'<td class="r num">'
            f'{amount(k.get("value_shown", ""), k.get("unit", ""))}</td>'
            f'<td class="r">'
            f'{amount(k.get("target", ""), k.get("unit", ""))}</td>'
            f'<td>{gap_text(k)}</td>'
            f'<td class="r">{status_pill(k.get("status", "—"))}</td></tr>')
    return ('<table class="ktab"><colgroup><col style="width:36%">'
            '<col style="width:15%"><col style="width:15%">'
            '<col style="width:22%"><col style="width:12%"></colgroup>'
            '<thead><tr><th>KPI</th><th class="r">Value</th>'
            '<th class="r">Target</th><th>Gap</th><th class="r">Status</th>'
            '</tr></thead><tbody>' + "".join(rows) + "</tbody></table>")
