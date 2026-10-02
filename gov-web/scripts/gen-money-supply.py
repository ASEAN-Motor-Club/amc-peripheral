#!/usr/bin/env python3
"""Generate money-supply data + charts for gov.aseanmotorclub.com.

Pulls live balances and monthly ledger flows from the PROD backend database
(over SSH), then emits:
  - gov-web/src/data/money-supply.json          (series + snapshot + projections)
  - gov-web/public/charts/money-supply-*.svg    (four charts embedded by the page)

Refresh = run this script, commit the outputs.
"""

import json
import subprocess
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]
DATA_OUT = REPO / "src" / "data"
CHART_OUT = REPO / "public" / "charts"

B = 1e9
M = 1e6

BALANCE_SQL = r"""
SET statement_timeout='90s';
SELECT 'vault', ROUND(SUM(balance)) FROM amc_finance_account
  WHERE book='BANK' AND account_type='ASSET' AND character_id IS NULL AND name ILIKE '%vault%'
UNION ALL
SELECT 'deposits', ROUND(SUM(balance)) FROM amc_finance_account
  WHERE book='BANK' AND account_type='LIABILITY' AND character_id IS NOT NULL
UNION ALL
SELECT 'loans', ROUND(SUM(balance)) FROM amc_finance_account
  WHERE book='BANK' AND account_type='ASSET' AND character_id IS NOT NULL
UNION ALL
SELECT 'expense', ROUND(SUM(balance)) FROM amc_finance_account
  WHERE book='BANK' AND account_type='EXPENSE'
UNION ALL
SELECT 'policy_rate', ROUND(MAX(daily_interest_rate),6) FROM amc_finance_bankpolicy;
"""

FLOW_SQL = r"""
SET statement_timeout='120s';
SELECT to_char(date_trunc('month', je.created_at), 'YYYY-MM') AS m,
  COALESCE(SUM(le.debit - le.credit) FILTER (
    WHERE a.book='BANK' AND a.account_type='ASSET' AND a.character_id IS NULL AND a.name ILIKE '%vault%'), 0) AS vault_net,
  COALESCE(SUM(le.credit - le.debit) FILTER (
    WHERE a.book='BANK' AND a.account_type='LIABILITY' AND a.character_id IS NOT NULL), 0) AS deposits_net,
  COALESCE(SUM(le.debit - le.credit) FILTER (
    WHERE a.book='BANK' AND a.account_type='ASSET' AND a.character_id IS NOT NULL), 0) AS loans_net,
  COALESCE(SUM(le.debit - le.credit) FILTER (
    WHERE a.book='BANK' AND a.account_type='EXPENSE'), 0) AS expense_net,
  COALESCE(SUM(le.credit) FILTER (WHERE je.description='Interest Payment'), 0) AS interest_paid,
  COALESCE(SUM(le.debit) FILTER (WHERE je.description='Wealth Tax'), 0) AS wealth_tax_legs,
  COALESCE(SUM(le.credit) FILTER (WHERE je.description='NIRC Transfer'), 0) AS nirc,
  COALESCE(SUM(le.credit - le.debit) FILTER (
    WHERE a.book='GOVERNMENT' AND a.account_type IN ('REVENUE','EQUITY','EXPENSE')), 0) AS treasury_net
FROM amc_finance_journalentry je
JOIN amc_finance_ledgerentry le ON le.journal_entry_id = je.id
JOIN amc_finance_account a ON a.id = le.account_id
GROUP BY date_trunc('month', je.created_at)
ORDER BY date_trunc('month', je.created_at);
"""

DELIVERY_SQL = r"""
SET statement_timeout='90s';
SELECT to_char(date_trunc('month', "timestamp"), 'YYYY-MM') AS m, ROUND(SUM(payment + subsidy))
FROM amc_delivery
GROUP BY date_trunc('month', "timestamp")
ORDER BY date_trunc('month', "timestamp");
"""


def ssh_psql(sql: str) -> str:
    cmd = ["ssh", "root@asean-mt-server", "psql -h ::1 -U amc -d amc -qAt -P pager=off"]
    out = subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr[-500:]}")
    return out.stdout


def parse_rows(text):
    rows = []
    for line in text.strip().splitlines():
        parts = line.split("|")
        rows.append(parts)
    return rows


def main():
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    CHART_OUT.mkdir(parents=True, exist_ok=True)

    # --- snapshot balances -------------------------------------------------
    balances = {}
    for k, v in parse_rows(ssh_psql(BALANCE_SQL)):
        balances[k] = float(v)
    vault_now = balances["vault"]
    deposits_now = balances["deposits"]
    loans_now = balances["loans"]
    expense_now = balances["expense"]
    rate = balances["policy_rate"]

    # --- monthly flows (forward) -------------------------------------------
    months, flows = [], []
    for row in parse_rows(ssh_psql(FLOW_SQL)):
        m, vn, dn, ln, en, ip, wt, nr, tr = row
        months.append(m)
        flows.append(
            {
                "vault_net": float(vn),
                "deposits_net": float(dn),
                "loans_net": float(ln),
                "expense_net": float(en),
                "interest_paid": float(ip),
                "wealth_tax": float(wt) / 2.0,  # legacy double-counted legs
                "nirc": float(nr),
                "treasury_net": float(tr),
            }
        )

    delivery = {m: float(v) for m, v in parse_rows(ssh_psql(DELIVERY_SQL)) if m in months}

    # --- backward-integrated monthly series (anchors at today's balances) ---
    # walk months newest -> oldest accumulating net flows, then reverse.
    def integrate(now, key):
        series, bal = [], now
        for f in reversed(flows):
            series.append(bal)
            bal -= f[key]
        series.append(bal)
        series.reverse()
        return series

    # integrate() emits len(flows)+1 points: one extra anchor month before the
    # ledger's first month. Extend the month labels to match.
    def _prev_month(m):
        y, mo = int(m[:4]), int(m[5:7])
        return f"{y - (mo == 1):04d}-{(mo - 1) or 12:02d}"

    months_ext = [_prev_month(months[0])] + months

    vault_s = integrate(vault_now, "vault_net")
    deposits_s = integrate(deposits_now, "deposits_net")
    loans_s = integrate(loans_now, "loans_net")
    expense_s = integrate(expense_now, "expense_net")
    backing_s = [v / d if d > 0 else None for v, d in zip(vault_s, deposits_s)]

    # --- projections (monthly steps, 12 months) -----------------------------
    # mint ~= deposits * daily_rate * k, k absorbs offline decay + threshold
    # falloff; k is calibrated from the last full month of observed interest.
    # k is calibrated on the CURRENT rate's observed daily interest (the last
    # flow month is the partial current month at today's rate).
    cur = flows[-1]
    cur_month = months[-1]
    import calendar

    day_now = date.today().day if cur_month == date.today().strftime("%Y-%m") else calendar.monthrange(int(cur_month[:4]), int(cur_month[5:7]))[1]
    k = (cur["interest_paid"] / day_now) / (deposits_now * rate) if rate > 0 else 0.35

    last_full = flows[-2] if len(flows) > 1 else flows[-1]
    wtax_daily = last_full["wealth_tax"] / 30.0

    def project(r_daily, months_ahead=12):
        d, b = deposits_now, vault_now
        dep, back = [d], [b / d]
        for _ in range(months_ahead):
            mint = d * r_daily * k * 30.0
            burn = wtax_daily * 30.0
            d += mint - burn
            # minted interest and the tax are both off-vault: the vault only
            # moves via cash deposit/withdrawal, which nets to ~zero monthly.
            dep.append(d)
            back.append(b / d)
        return dep, back

    scenarios = {}
    for label, r in [("current", rate), ("zero", 0.0), ("legacy", 0.022)]:
        dep, back = project(r)
        scenarios[label] = {"rate_daily": r, "deposits": dep, "backing": back}

    net_daily = deposits_now * rate * k - wtax_daily

    data = {
        "as_of": date.today().isoformat(),
        "policy_rate_daily": rate,
        "snapshot": {
            "vault": vault_now,
            "deposits": deposits_now,
            "loans": loans_now,
            "printed_interest": expense_now,
            "backing_ratio": vault_now / deposits_now,
            "net_mint_daily": net_daily,
            "interest_daily": deposits_now * rate * k,
            "wealth_tax_daily": wtax_daily,
            "decay_factor_k": round(k, 4),
        },
        "monthly": {
            "months": months_ext,
            "vault": vault_s,
            "deposits": deposits_s,
            "loans": loans_s,
            "printed_interest": expense_s,
            "backing": backing_s,
            "interest_paid": [f["interest_paid"] for f in flows],
            "wealth_tax": [f["wealth_tax"] for f in flows],
            "nirc": [f["nirc"] for f in flows],
            "delivery_income": [delivery.get(m) for m in months],
        },
        "projections": scenarios,
    }
    (DATA_OUT / "money-supply.json").write_text(json.dumps(data, indent=1))

    # --- charts -------------------------------------------------------------
    G = "#0b0c0c"
    plt.rcParams.update({"font.size": 11, "text.color": G, "axes.edgecolor": G,
                         "axes.labelcolor": G, "xtick.color": G, "ytick.color": G,
                         "axes.grid": True, "grid.alpha": 0.3})

    def bn(x):
        return x / B

    x = list(range(len(months_ext)))
    xt = months_ext

    # 1. backing over time
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.stackplot(x, [bn(v) for v in vault_s], labels=["Vault (real coins)"], colors=["#1d70b8"], alpha=0.85)
    ax.stackplot(x, [bn(max(0.0, d - v)) for d, v in zip(deposits_s, vault_s)],
                 labels=["Unbacked deposits"], colors=["#d4351c"], alpha=0.55)
    ax2 = ax.twinx()
    ax2.plot(x, [(b or 0) * 100 for b in backing_s], color="#0b0c0c", lw=2, label="Backing ratio")
    ax2.set_ylabel("Backing ratio (%)")
    ax2.set_ylim(0, 110)
    ax2.grid(False)
    ax.set_xticks(x[:: max(1, len(x) // 8)])
    ax.set_xticklabels(xt[:: max(1, len(x) // 8)], rotation=30, ha="right")
    ax.set_ylabel("$ billions")
    ax.set_title("Deposits vs vault: backing ratio over time", loc="left")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(CHART_OUT / "money-supply-backing.svg", format="svg")
    plt.close(fig)

    # 2. composition snapshot (horizontal stacked bar)
    fig, ax = plt.subplots(figsize=(9, 2.6))
    comps = [("Backed by vault", vault_now, "#1d70b8"),
             ("Printed interest (unbacked)", max(0, deposits_now - vault_now), "#d4351c")]
    left = 0
    for label, v, c in comps:
        ax.barh([0], [bn(v)], left=left, color=c, alpha=0.85, label=label)
        ax.text(left + bn(v) / 2, 0, f"{label}\n${v/B:.2f}B", ha="center", va="center",
                color="white", fontsize=10, fontweight="bold")
        left += bn(v)
    ax.set_xlim(0, bn(deposits_now) * 1.02)
    ax.set_yticks([])
    ax.set_xlabel("$ billions")
    ax.set_title(f"Composition of bank deposits — ${deposits_now/B:.2f}B total "
                 f"({vault_now/deposits_now*100:.0f}% backed)", loc="left")
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(CHART_OUT / "money-supply-composition.svg", format="svg")
    plt.close(fig)

    # 3. monthly flows
    fig, ax = plt.subplots(figsize=(9, 4.2))
    w = 0.27
    xs = range(len(months_ext))
    fm = data['monthly']['interest_paid']
    fm.insert(0, 0.0)  # anchor month has no flow data
    wt = data['monthly']['wealth_tax']; wt.insert(0, 0.0)
    di = data['monthly']['delivery_income']; di.insert(0, 0.0)
    ax.bar([i - w for i in xs], [f / M for f in fm],
           width=w, color="#d4351c", alpha=0.8, label="Interest minted")
    ax.bar(list(xs), [f / M for f in wt],
           width=w, color="#00703c", alpha=0.8, label="Wealth tax burned")
    ax.bar([i + w for i in xs], [(d or 0) / M for d in di],
           width=w, color="#1d70b8", alpha=0.8, label="Delivery income (real economy)")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(months_ext, rotation=30, ha="right")
    ax.set_ylabel("$ millions / month")
    ax.set_title("Money printing vs money sinks vs the real economy", loc="left")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(CHART_OUT / "money-supply-flows.svg", format="svg")
    plt.close(fig)

    # 4. projections
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    colors = {"current": "#1d70b8", "zero": "#00703c", "legacy": "#d4351c"}
    labels = {"current": f"Current rate ({rate*100:.1f}%/day)",
              "zero": "Zero interest", "legacy": "Legacy rate (2.2%/day)"}
    fwd_m = [months[-1]] + [f"M+{i}" for i in range(1, 13)]
    for label, s in scenarios.items():
        a1.plot(range(len(s["deposits"])), [bn(d) for d in s["deposits"]],
                color=colors[label], lw=2, label=labels[label])
        a2.plot(range(len(s["backing"])), [b * 100 for b in s["backing"]],
                color=colors[label], lw=2, label=labels[label])
    a1.set_title("Projected deposits", loc="left")
    a1.set_ylabel("$ billions")
    a2.set_title("Projected backing ratio", loc="left")
    a2.set_ylabel("%")
    for a in (a1, a2):
        a.set_xlabel("months ahead")
        a.legend(fontsize=8)
    fig.suptitle("12-month projections by interest rate (assumes flat deposit base, "
                 "constant wealth tax)", x=0.01, ha="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(CHART_OUT / "money-supply-projection.svg", format="svg")
    plt.close(fig)

    print("as_of", data["as_of"])
    print("rate/day", rate)
    print("vault/deposits", vault_now / B, deposits_now / B, vault_now / deposits_now)
    print("k", round(k, 4), "net_mint/day", round(net_daily / M, 2), "M")
    print("months", months[0], "->", months[-1], f"({len(months)})")
    print("wrote", DATA_OUT / "money-supply.json", "and 4 charts")


if __name__ == "__main__":
    main()
