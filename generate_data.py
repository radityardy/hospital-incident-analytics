#!/usr/bin/env python3
"""
generate_data.py — Synthetic IT Incident Data Generator
=========================================================
Produces 500 realistic enterprise IT incident records and writes them as
INSERT statements to ``populate_data.sql``.

Operational patterns injected
-----------------------------
* **Monday spike** — ~30 % more tickets on Mondays (simulates weekend backlog).
* **SLA breaches** — ~3-5 % of tickets intentionally miss SLA (target < 99 %).
* **Severity distribution** — weighted toward Low/Medium (realistic bell-curve).
* **Resolution time** — correlated with severity (Critical takes longer).
* **Multi-branch** — 8 branches spread across regions.
* **Business-hours bias** — most tickets created 07:00-19:00, with a long tail.

Usage
-----
    python generate_data.py          # writes populate_data.sql to cwd
    python generate_data.py --rows 1000   # override row count
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

# ── Reproducibility ──────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)

# ── Constants ────────────────────────────────────────────────────────────────

AGENTS: list[dict] = [
    {"name": "Aisha Patel",      "tier": "Tier 1"},
    {"name": "Carlos Rivera",    "tier": "Tier 1"},
    {"name": "Mei-Ling Chen",    "tier": "Tier 1"},
    {"name": "Dmitri Volkov",    "tier": "Tier 2"},
    {"name": "Fatima Al-Rashid", "tier": "Tier 2"},
    {"name": "James Okonkwo",   "tier": "Tier 2"},
    {"name": "Hana Bergström",  "tier": "Tier 3"},
    {"name": "Lucas Moreau",    "tier": "Tier 3"},
    {"name": "Priya Sharma",    "tier": "Tier 3"},
    {"name": "Ben Nakamura",    "tier": "Tier 1"},
]

CATEGORIES: list[dict] = [
    {"name": "Network Outage",          "dept": "Infrastructure Ops"},
    {"name": "Software Bug",            "dept": "Application Support"},
    {"name": "Hardware Failure",        "dept": "Facilities & IT Assets"},
    {"name": "Access / Permissions",    "dept": "Identity & Access Mgmt"},
    {"name": "Email / Messaging",       "dept": "Collaboration Services"},
    {"name": "Database Issue",          "dept": "Data Engineering"},
    {"name": "Security Incident",       "dept": "Cybersecurity"},
    {"name": "Printer / Peripheral",    "dept": "End-User Computing"},
    {"name": "VPN / Remote Access",     "dept": "Infrastructure Ops"},
    {"name": "Cloud Service Disruption","dept": "Cloud Platform Team"},
]

BRANCHES = list(range(1, 9))  # branch_id 1..8

SEVERITIES_WEIGHTS: list[tuple[str, int]] = [
    ("Low",      35),
    ("Medium",   40),
    ("High",     18),
    ("Critical",  7),
]

STATUSES_WEIGHTS: list[tuple[str, int]] = [
    ("Resolved",    55),
    ("Closed",      25),
    ("In Progress", 10),
    ("Open",         7),
    ("Escalated",    3),
]

# Average resolution hours by severity (mean, std-dev)
RESOLUTION_HOURS: dict[str, tuple[float, float]] = {
    "Low":      (4.0,  2.0),
    "Medium":   (8.0,  4.0),
    "High":     (18.0, 8.0),
    "Critical": (36.0, 14.0),
}

# Date range: last 12 months
END_DATE   = datetime(2026, 5, 28, 17, 0, 0)
START_DATE = END_DATE - timedelta(days=365)


# ── Helpers ──────────────────────────────────────────────────────────────────

def weighted_choice(options_weights: list[tuple[str, int]]) -> str:
    """Pick from a list of (value, weight) tuples."""
    values, weights = zip(*options_weights)
    return random.choices(values, weights=weights, k=1)[0]


def random_timestamp(start: datetime, end: datetime, monday_bias: bool = True) -> datetime:
    """Generate a random timestamp, with optional Monday weighting."""
    delta = end - start
    total_seconds = int(delta.total_seconds())

    for _ in range(200):  # retry loop for Monday bias
        ts = start + timedelta(seconds=random.randint(0, total_seconds))
        # Business-hours bias: 70 % chance hour falls in 07-19
        if random.random() < 0.70:
            ts = ts.replace(hour=random.randint(7, 18), minute=random.randint(0, 59))

        if monday_bias and ts.weekday() == 0:
            return ts  # accept all Mondays immediately (over-represent)
        if random.random() < 0.75:
            return ts
    return ts


def escape_sql(value: str) -> str:
    """Escape single quotes for SQL string literals."""
    return value.replace("'", "''")


# ── Main Generator ───────────────────────────────────────────────────────────

def generate_tickets(n: int = 500) -> Tuple[list[dict], list[dict], list[dict]]:
    """Return (agents, categories, tickets) lists."""
    agents = [
        {"agent_id": i + 1, **a}
        for i, a in enumerate(AGENTS)
    ]
    categories = [
        {"category_id": i + 1, **c}
        for i, c in enumerate(CATEGORIES)
    ]

    # Map tiers to agent IDs for realistic assignment
    tier_agents: dict[str, list[int]] = {}
    for a in agents:
        tier_agents.setdefault(a["tier"], []).append(a["agent_id"])

    tickets: list[dict] = []
    for ticket_id in range(1, n + 1):
        severity = weighted_choice(SEVERITIES_WEIGHTS)
        status   = weighted_choice(STATUSES_WEIGHTS)

        # Higher severity → higher tier agent (probabilistic)
        if severity in ("Critical", "High"):
            tier_pick = random.choices(
                ["Tier 1", "Tier 2", "Tier 3"], weights=[10, 40, 50], k=1
            )[0]
        else:
            tier_pick = random.choices(
                ["Tier 1", "Tier 2", "Tier 3"], weights=[60, 30, 10], k=1
            )[0]

        agent_id    = random.choice(tier_agents[tier_pick])
        category_id = random.choice(categories)["category_id"]
        branch_id   = random.choice(BRANCHES)
        created_at  = random_timestamp(START_DATE, END_DATE)

        # Resolution time (only if status is Resolved / Closed)
        resolved_at = None
        if status in ("Resolved", "Closed"):
            mean_h, std_h = RESOLUTION_HOURS[severity]
            hours = max(0.5, random.gauss(mean_h, std_h))
            resolved_at = created_at + timedelta(hours=hours)

        # SLA logic: 96-97 % met overall (so some branches dip below 99 %)
        sla_met = random.random() < 0.965

        tickets.append({
            "ticket_id":   ticket_id,
            "created_at":  created_at,
            "resolved_at": resolved_at,
            "severity":    severity,
            "status":      status,
            "agent_id":    agent_id,
            "category_id": category_id,
            "branch_id":   branch_id,
            "sla_met":     sla_met,
        })

    return agents, categories, tickets


def write_sql(agents, categories, tickets, path: Path) -> None:
    """Write INSERT statements to a SQL file."""
    lines: list[str] = [
        "-- ============================================================================",
        "-- populate_data.sql — Auto-generated synthetic data",
        f"-- Generated: {datetime.now().isoformat()}",
        f"-- Rows: {len(tickets)} tickets, {len(agents)} agents, {len(categories)} categories",
        "-- ============================================================================",
        "",
        "BEGIN;",
        "",
        "-- ── dim_agents ─────────────────────────────────────────────────────────────",
    ]

    for a in agents:
        lines.append(
            f"INSERT INTO dim_agents (agent_id, agent_name, tier) VALUES "
            f"({a['agent_id']}, '{escape_sql(a['name'])}', '{a['tier']}');"
        )

    lines += [
        "",
        "-- ── dim_categories ─────────────────────────────────────────────────────────",
    ]

    for c in categories:
        lines.append(
            f"INSERT INTO dim_categories (category_id, category_name, department_target) VALUES "
            f"({c['category_id']}, '{escape_sql(c['name'])}', '{escape_sql(c['dept'])}');"
        )

    lines += [
        "",
        "-- ── fact_tickets ───────────────────────────────────────────────────────────",
    ]

    for t in tickets:
        resolved = f"'{t['resolved_at'].strftime('%Y-%m-%d %H:%M:%S')}'" if t["resolved_at"] else "NULL"
        sla      = "TRUE" if t["sla_met"] else "FALSE"
        lines.append(
            f"INSERT INTO fact_tickets "
            f"(ticket_id, created_at, resolved_at, severity, status, agent_id, category_id, branch_id, sla_met) "
            f"VALUES ("
            f"{t['ticket_id']}, "
            f"'{t['created_at'].strftime('%Y-%m-%d %H:%M:%S')}', "
            f"{resolved}, "
            f"'{t['severity']}', "
            f"'{t['status']}', "
            f"{t['agent_id']}, "
            f"{t['category_id']}, "
            f"{t['branch_id']}, "
            f"{sla});"
        )

    lines += [
        "",
        "-- Reset sequences to max id + 1 so future inserts work correctly",
        "SELECT setval('dim_agents_agent_id_seq',       (SELECT COALESCE(MAX(agent_id), 0)    + 1 FROM dim_agents),       false);",
        "SELECT setval('dim_categories_category_id_seq',(SELECT COALESCE(MAX(category_id), 0) + 1 FROM dim_categories), false);",
        "SELECT setval('fact_tickets_ticket_id_seq',    (SELECT COALESCE(MAX(ticket_id), 0)   + 1 FROM fact_tickets),   false);",
        "",
        "COMMIT;",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(tickets, path: Path) -> None:
    """Also dump tickets to CSV for quick analysis outside PostgreSQL."""
    fieldnames = [
        "ticket_id", "created_at", "resolved_at", "severity",
        "status", "agent_id", "category_id", "branch_id", "sla_met",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in tickets:
            row = dict(t)
            row["created_at"]  = row["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            row["resolved_at"] = row["resolved_at"].strftime("%Y-%m-%d %H:%M:%S") if row["resolved_at"] else ""
            writer.writerow(row)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic IT incident data.")
    parser.add_argument("--rows", type=int, default=500, help="Number of ticket rows (default 500)")
    parser.add_argument("--out-dir", type=str, default=".", help="Output directory")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[*] Generating {args.rows} synthetic tickets (seed={SEED})...")
    agents, categories, tickets = generate_tickets(args.rows)

    sql_path = out / "populate_data.sql"
    csv_path = out / "tickets.csv"

    write_sql(agents, categories, tickets, sql_path)
    print(f"[+] SQL  -> {sql_path.resolve()}")

    write_csv(tickets, csv_path)
    print(f"[+] CSV  -> {csv_path.resolve()}")

    # Summary stats
    sla_pct = sum(1 for t in tickets if t["sla_met"]) / len(tickets) * 100
    resolved = [t for t in tickets if t["resolved_at"]]
    avg_hours = (
        sum((t["resolved_at"] - t["created_at"]).total_seconds() for t in resolved)
        / len(resolved) / 3600
        if resolved else 0
    )
    print(f"\n--- Summary ---")
    print(f"   Tickets generated : {len(tickets)}")
    print(f"   Agents            : {len(agents)}")
    print(f"   Categories        : {len(categories)}")
    print(f"   Overall SLA met   : {sla_pct:.1f} %")
    print(f"   Avg resolution    : {avg_hours:.1f} h (resolved tickets only)")
    print(f"   Date range        : {START_DATE.date()} -> {END_DATE.date()}")


if __name__ == "__main__":
    main()
