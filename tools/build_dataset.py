"""Build the static per-department fact tables under lab5_sources/departments/.

Run ONCE. The files it writes are the dataset; nothing regenerates them at
import, so they can be edited by hand afterwards and the edits survive.

    python3 tools/build_dataset.py            # writes only if files are missing
    python3 tools/build_dataset.py --force    # overwrite (destroys hand edits)

What it produces
----------------
One CSV per department, in long (tidy) form — one row per
(department, period, domain, metric, sub-period):

    dept_code,dept_name,category,period,grain,sub_period,domain,metric,
    value,unit,aggregation,figure_status,source_system,recorded_on

`aggregation` carries the rollup rule with the data, so a consumer cannot
sum a mean by accident. Three rules are used: `sum` for flows (publications,
placements, spend), `weighted_mean` for index figures (CO/PO attainment,
weighted by students appeared) and `latest` for stocks (sanctioned faculty,
eligible students).

Two invariants, both asserted before anything is written
--------------------------------------------------------
1. Rolling the 2025-26 detail up by its own `aggregation` rule reproduces
   `department_reports_2025_26.csv` exactly — the aggregate the KPI engine
   already reads. The detail is therefore a decomposition of the published
   figures, not a second set of numbers that disagrees with them.
2. Rolling the 2024-25 detail up reproduces the institution KPI values held in
   the archive as KPI-SNAPSHOT-2024-25 (to 2 dp), so last year's detail and
   last year's baseline tell the same story.

Quarterly and semester splits use the largest-remainder method over integer
units (whole counts, or hundredths for money), so the parts sum back to the
total exactly rather than approximately.
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

from edss_core import KPI_DEFINITIONS, NUMERIC_COLUMNS, REPORTING_PERIOD  # noqa: E402

SOURCES = ROOT / "lab5_sources"
AGGREGATE = SOURCES / "department_reports_2025_26.csv"
OUT_DIR = SOURCES / "departments"

THIS_YEAR = "2025-26"
PRIOR_YEAR = "2024-25"

QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
SEMESTERS = ["SEM-1", "SEM-2"]

# How each column of the aggregate decomposes: (domain, grain, rule, unit)
METRICS = {
    "students_appeared":     ("Academic",  "semester", "sum",           "count"),
    "students_passed":       ("Academic",  "semester", "sum",           "count"),
    "co_po_attainment":      ("Academic",  "annual",   "weighted_mean", "index 0-3"),
    "sanctioned_faculty":    ("Research",  "annual",   "latest",        "count"),
    "publications":          ("Research",  "quarter",  "sum",           "count"),
    "citations":             ("Research",  "quarter",  "sum",           "count"),
    "grants_lakh":           ("Research",  "quarter",  "sum",           "INR lakh"),
    "eligible_students":     ("Placement", "annual",   "latest",        "count"),
    "placed_students":       ("Placement", "quarter",  "sum",           "count"),
    "total_package_lpa":     ("Placement", "quarter",  "sum",           "LPA"),
    "interns_completed":     ("Placement", "quarter",  "sum",           "count"),
    "budget_allocated_lakh": ("Finance",   "quarter",  "sum",           "INR lakh"),
    "budget_spent_lakh":     ("Finance",   "quarter",  "sum",           "INR lakh"),
}

SOURCE_SYSTEM = {"Academic": "Academic ERP", "Research": "Research repository",
                 "Placement": "Placement Cell tracker",
                 "Finance": "Finance & Accounts ledger"}

# Seasonality. Academic work lands on exam cycles, research and placement build
# through the year, and spend is back-loaded the way institutional budgets are.
SHAPE = {
    "students_appeared":     [0.50, 0.50],
    "students_passed":       [0.50, 0.50],
    "publications":          [0.18, 0.24, 0.29, 0.29],
    "citations":             [0.21, 0.24, 0.27, 0.28],
    "grants_lakh":           [0.31, 0.19, 0.27, 0.23],
    "placed_students":       [0.09, 0.34, 0.41, 0.16],
    "total_package_lpa":     [0.08, 0.33, 0.43, 0.16],
    "interns_completed":     [0.12, 0.17, 0.39, 0.32],
    "budget_allocated_lakh": [0.25, 0.25, 0.25, 0.25],
    "budget_spent_lakh":     [0.17, 0.22, 0.26, 0.35],
}

RECORDED = {("2025-26", "Q1"): "2025-09-30", ("2025-26", "Q2"): "2025-12-31",
            ("2025-26", "Q3"): "2026-03-31", ("2025-26", "Q4"): "2026-06-30",
            ("2025-26", "SEM-1"): "2025-12-31", ("2025-26", "SEM-2"): "2026-06-30",
            ("2025-26", "FY"): "2026-06-30",
            ("2024-25", "Q1"): "2024-09-30", ("2024-25", "Q2"): "2024-12-31",
            ("2024-25", "Q3"): "2025-03-31", ("2024-25", "Q4"): "2025-06-30",
            ("2024-25", "SEM-1"): "2024-12-31", ("2024-25", "SEM-2"): "2025-06-30",
            ("2024-25", "FY"): "2025-06-30"}

# The institution KPI baseline this prior year has to reproduce. Same values as
# KPI-SNAPSHOT-2024-25 in the Lab 4 archive.
BASELINE_2024_25 = {"KPI-A1": 91.20, "KPI-A2": 2.44, "KPI-R1": 1.12,
                    "KPI-R2": 6.40, "KPI-R3": 221.5, "KPI-P1": 73.50,
                    "KPI-P2": 7.95, "KPI-P3": 69.10, "KPI-F1": 86.90}

# Students are whole people, so not every eligible-pool size can produce the
# archived rates exactly. 73.50% and 69.10% of this year's pool of 1037 land on
# 73.48% and 69.14%. A pool of 1000 is the only size anywhere near it that
# yields both exactly — and a placement pool that grew by ~4% in a year is
# ordinary. The alternative was to let the detail disagree with the archive by
# a couple of hundredths, which is exactly the kind of drift Lab 9 exists to
# catch.
PRIOR_ELIGIBLE_TOTAL = 1000


# ==========================================================================
# exact splitting
# ==========================================================================

def split_int(total: int, weights: List[float]) -> List[int]:
    """Largest remainder: the parts sum to `total` exactly, never total±1."""
    raw = [total * w for w in weights]
    base = [int(x) for x in raw]
    short = total - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[:short]:
        base[i] += 1
    return base


def split_money(total: float, weights: List[float]) -> List[float]:
    """Same, carried out in hundredths so no rupee is invented or lost."""
    parts = split_int(round(total * 100), weights)
    return [p / 100 for p in parts]


def apportion_int(total: int, shares: List[float]) -> List[int]:
    s = sum(shares) or 1.0
    return split_int(total, [x / s for x in shares])


def apportion_money(total: float, shares: List[float]) -> List[float]:
    s = sum(shares) or 1.0
    return split_money(total, [x / s for x in shares])


def apportion_capped(total: int, shares: List[float], caps: List[int]) -> List[int]:
    """Apportion `total` without letting any department exceed its cap.

    Clamping after the fact would quietly lose whatever was clipped, and the
    institution figure would then miss its baseline by a tenth of a point. The
    surplus is pushed back to the departments that still have headroom instead.
    """
    parts = apportion_int(total, shares)
    for _ in range(len(parts) + 1):
        spill = sum(max(0, p - c) for p, c in zip(parts, caps))
        if not spill:
            return parts
        parts = [min(p, c) for p, c in zip(parts, caps)]
        head = [c - p for p, c in zip(parts, caps)]
        if sum(head) < spill:
            raise ValueError(f"cannot place {spill} within the caps available")
        for i, extra in enumerate(apportion_int(spill, [float(h) for h in head])):
            parts[i] += extra
    raise ValueError("apportionment did not settle")


# ==========================================================================
# the aggregate we must agree with
# ==========================================================================

def read_aggregate() -> List[Dict]:
    with AGGREGATE.open() as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for col, caster in NUMERIC_COLUMNS.items():
            if col in r:
                r[col] = caster(r[col])
    return rows


def institution_kpis(rows: List[Dict]) -> Dict[str, float]:
    """The same nine formulas the KPI engine uses, at institution level."""
    out = {}
    for kid, d in KPI_DEFINITIONS.items():
        if d["method"] == "sum":
            out[kid] = round(sum(r[_col_for(kid)] for r in rows), 2)
        elif d["method"] == "weighted_mean":
            w = sum(r["students_appeared"] for r in rows)
            out[kid] = round(sum(r["co_po_attainment"] * r["students_appeared"]
                                 for r in rows) / w, 2)
        else:
            num = sum(r[d["numerator"]] for r in rows)
            den = sum(r[d["denominator"]] for r in rows)
            out[kid] = round(num / den * (d.get("scale") or 1), 2)
    return out


def _col_for(kid: str) -> str:
    return {"KPI-R3": "grants_lakh"}[kid]


# ==========================================================================
# the prior year, solved back from the baseline
# ==========================================================================

def build_prior_year(this_year: List[Dict]) -> List[Dict]:
    """Last year's department rows, chosen so the institution rollup equals
    KPI-SNAPSHOT-2024-25. Stocks carry over; flows are apportioned to the
    department shape of this year."""
    prior = [{k: v for k, v in r.items()} for r in this_year]
    b = BASELINE_2024_25

    # stocks carry over unchanged — faculty lines and cohort sizes are stable
    appeared = [r["students_appeared"] for r in this_year]
    faculty = [r["sanctioned_faculty"] for r in this_year]
    allocated = [r["budget_allocated_lakh"] for r in this_year]

    def put(col, values):
        for r, v in zip(prior, values):
            r[col] = v

    # last year's placement pool, split to this year's departmental shape
    eligible = apportion_int(PRIOR_ELIGIBLE_TOTAL,
                             [r["eligible_students"] for r in this_year])
    put("eligible_students", eligible)

    # KPI-A1 = passed / appeared x 100
    put("students_passed", apportion_capped(
        round(b["KPI-A1"] / 100 * sum(appeared)),
        [r["students_passed"] for r in this_year], appeared))

    # KPI-A2 = mean CO/PO weighted by students appeared
    scale = b["KPI-A2"] / institution_kpis(this_year)["KPI-A2"]
    copo = [round(r["co_po_attainment"] * scale, 2) for r in this_year]
    put("co_po_attainment", copo)
    # a 2 dp rounding drift of a few hundredths is absorbed by the largest cohort
    big = max(range(len(prior)), key=lambda i: appeared[i])
    need = b["KPI-A2"] * sum(appeared) - sum(c * a for c, a in zip(copo, appeared))
    copo[big] = round(copo[big] + need / appeared[big], 2)
    put("co_po_attainment", copo)

    # KPI-R1 publications / faculty, KPI-R2 citations / faculty, KPI-R3 grants
    put("publications", apportion_int(round(b["KPI-R1"] * sum(faculty)),
                                      [r["publications"] for r in this_year]))
    put("citations", apportion_int(round(b["KPI-R2"] * sum(faculty)),
                                   [r["citations"] for r in this_year]))
    put("grants_lakh", apportion_money(b["KPI-R3"],
                                       [r["grants_lakh"] for r in this_year]))

    # KPI-P1 placed / eligible, KPI-P2 package / placed, KPI-P3 interns / eligible
    placed = apportion_capped(round(b["KPI-P1"] / 100 * sum(eligible)),
                              [r["placed_students"] for r in this_year], eligible)
    put("placed_students", placed)
    put("total_package_lpa", apportion_money(
        round(b["KPI-P2"] * sum(placed), 2),
        [r["total_package_lpa"] for r in this_year]))
    put("interns_completed", apportion_capped(
        round(b["KPI-P3"] / 100 * sum(eligible)),
        [r["interns_completed"] for r in this_year], eligible))

    # KPI-F1 spent / allocated
    put("budget_spent_lakh", apportion_money(
        round(b["KPI-F1"] / 100 * sum(allocated), 2), allocated))

    for r in prior:
        r["figure_status"] = "final"       # last year's books are closed
    return prior


# ==========================================================================
# aggregate row -> fact rows
# ==========================================================================

def fact_rows(row: Dict, period: str) -> List[Dict]:
    out = []
    for metric, (domain, grain, rule, unit) in METRICS.items():
        total = row[metric]
        if grain == "annual":
            subs, parts = ["FY"], [total]
        else:
            subs = SEMESTERS if grain == "semester" else QUARTERS
            shape = SHAPE[metric]
            parts = (split_money(total, shape) if isinstance(total, float)
                     else split_int(total, shape))
        for sub, value in zip(subs, parts):
            out.append({
                "dept_code": row["dept_code"], "dept_name": row["dept_name"],
                "category": row["category"], "period": period,
                "grain": grain, "sub_period": sub, "domain": domain,
                "metric": metric, "value": value, "unit": unit,
                "aggregation": rule,
                "figure_status": row["figure_status"],
                "source_system": SOURCE_SYSTEM[domain],
                "recorded_on": RECORDED[(period, sub)]})
    return out


FIELDS = ["dept_code", "dept_name", "category", "period", "grain", "sub_period",
          "domain", "metric", "value", "unit", "aggregation", "figure_status",
          "source_system", "recorded_on"]


# ==========================================================================
# verification — run before a single file is written
# ==========================================================================

def rollup(rows: List[Dict], period: str) -> Dict[str, Dict[str, float]]:
    """Fact rows back to one aggregate row per department, by `aggregation`."""
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        if r["period"] != period:
            continue
        d = out.setdefault(r["dept_code"], {})
        rule, m, v = r["aggregation"], r["metric"], r["value"]
        if rule == "sum":
            d[m] = round(d.get(m, 0) + v, 2)
        else:                                   # latest / weighted_mean: one row
            d[m] = v
    return out


def verify(facts: List[Dict], this_year: List[Dict], prior: List[Dict]) -> None:
    back = rollup(facts, THIS_YEAR)
    for row in this_year:
        got = back[row["dept_code"]]
        for metric in METRICS:
            a, b = row[metric], got[metric]
            assert abs(a - b) < 0.005, (
                f"{row['dept_code']}.{metric}: detail rolls up to {b}, "
                f"the published aggregate says {a}")
    print(f"  ok   {THIS_YEAR} detail rolls up to the published aggregate "
          f"({len(this_year)} departments x {len(METRICS)} metrics)")

    back_prior = rollup(facts, PRIOR_YEAR)
    rebuilt = [{**{"dept_code": c}, **v} for c, v in back_prior.items()]
    got = institution_kpis(rebuilt)
    for kid, want in BASELINE_2024_25.items():
        assert abs(got[kid] - want) < 0.005, (
            f"{kid}: {PRIOR_YEAR} detail gives {got[kid]}, "
            f"KPI-SNAPSHOT-2024-25 says {want}")
    print(f"  ok   {PRIOR_YEAR} detail reproduces all 9 archived baseline KPIs")


# ==========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing files (destroys hand edits)")
    args = ap.parse_args()

    if not AGGREGATE.exists():
        print(f"missing {AGGREGATE} — import edss_stack once to write it")
        return 1

    this_year = read_aggregate()
    prior = build_prior_year(this_year)

    facts: List[Dict] = []
    for row in this_year:
        facts += fact_rows(row, THIS_YEAR)
    for row in prior:
        facts += fact_rows(row, PRIOR_YEAR)

    print(f"built {len(facts)} fact rows across {len(this_year)} departments "
          f"and 2 periods")
    verify(facts, this_year, prior)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(OUT_DIR.glob("*.csv"))
    if existing and not args.force:
        print(f"\n{len(existing)} file(s) already in {OUT_DIR} — left untouched. "
              f"Use --force to rebuild.")
        return 0

    by_dept: Dict[str, List[Dict]] = {}
    for r in facts:
        by_dept.setdefault(r["dept_code"], []).append(r)
    for dept, rows in sorted(by_dept.items()):
        path = OUT_DIR / f"{dept}.csv"
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        domains = sorted({r["domain"] for r in rows})
        print(f"  wrote {path.name:<12} {len(rows):>3} rows · {', '.join(domains)}")
    print(f"\n{len(facts)} rows in {len(by_dept)} files under {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
