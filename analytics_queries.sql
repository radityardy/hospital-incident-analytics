-- ============================================================================
-- analytics_queries.sql — Production-Grade Analytical Queries
-- Target : PostgreSQL 14+
-- ============================================================================

-- ============================================================================
-- QUERY A — Monthly Trend of Total Tickets & Top Category by Volume
-- ============================================================================

WITH monthly_category AS (
    SELECT
        DATE_TRUNC('month', ft.created_at)::DATE AS month,
        dc.category_name,
        COUNT(*) AS category_tickets
    FROM fact_tickets ft
    JOIN dim_categories dc ON dc.category_id = ft.category_id
    GROUP BY 1, 2
),
ranked AS (
    SELECT month, category_name, category_tickets,
           ROW_NUMBER() OVER (PARTITION BY month ORDER BY category_tickets DESC) AS rn
    FROM monthly_category
),
monthly_totals AS (
    SELECT
        DATE_TRUNC('month', created_at)::DATE AS month,
        COUNT(*) AS total_tickets,
        LAG(COUNT(*)) OVER (ORDER BY DATE_TRUNC('month', created_at)) AS prev_month
    FROM fact_tickets
    GROUP BY 1
)
SELECT
    mt.month,
    mt.total_tickets,
    ROUND(
        CASE WHEN mt.prev_month > 0
             THEN (mt.total_tickets - mt.prev_month)::NUMERIC / mt.prev_month * 100
        END, 1
    ) AS mom_growth_pct,
    r.category_name  AS top_category,
    r.category_tickets AS top_category_volume
FROM monthly_totals mt
LEFT JOIN ranked r ON r.month = mt.month AND r.rn = 1
ORDER BY mt.month;


-- ============================================================================
-- QUERY B — SLA Achievement Rate per Month & Branch (flag < 99%)
-- ============================================================================

WITH branch_monthly AS (
    SELECT
        DATE_TRUNC('month', created_at)::DATE AS month,
        branch_id,
        COUNT(*) AS total_tickets,
        SUM(CASE WHEN sla_met THEN 1 ELSE 0 END) AS sla_met_count,
        ROUND(SUM(CASE WHEN sla_met THEN 1 ELSE 0 END)::NUMERIC / NULLIF(COUNT(*),0) * 100, 2) AS sla_pct
    FROM fact_tickets
    GROUP BY 1, 2
),
rolling AS (
    SELECT *,
        ROUND(AVG(sla_pct) OVER (
            PARTITION BY branch_id ORDER BY month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 2) AS rolling_3m_sla_pct
    FROM branch_monthly
)
SELECT month, branch_id, total_tickets, sla_met_count, sla_pct, rolling_3m_sla_pct,
    CASE WHEN sla_pct < 99.00 THEN 'BELOW TARGET' ELSE 'On Track' END AS sla_status
FROM rolling
ORDER BY month, branch_id;


-- ============================================================================
-- QUERY C — Avg Resolution Time (hours) for High Severity per Agent
-- ============================================================================

WITH high_sev AS (
    SELECT
        ft.agent_id, da.agent_name, da.tier, ft.severity,
        EXTRACT(EPOCH FROM (ft.resolved_at - ft.created_at)) / 3600.0 AS resolution_hours
    FROM fact_tickets ft
    JOIN dim_agents da ON da.agent_id = ft.agent_id
    WHERE ft.severity IN ('High','Critical') AND ft.resolved_at IS NOT NULL
),
agent_stats AS (
    SELECT
        agent_id, agent_name, tier,
        COUNT(*) AS tickets_resolved,
        ROUND(AVG(resolution_hours)::NUMERIC, 2) AS avg_hrs,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours)::NUMERIC, 2) AS median_hrs,
        ROUND(MIN(resolution_hours)::NUMERIC, 2) AS min_hrs,
        ROUND(MAX(resolution_hours)::NUMERIC, 2) AS max_hrs
    FROM high_sev
    GROUP BY agent_id, agent_name, tier
)
SELECT
    RANK() OVER (ORDER BY avg_hrs DESC) AS slowest_rank,
    agent_name, tier, tickets_resolved,
    avg_hrs, median_hrs, min_hrs, max_hrs,
    ROUND(AVG(avg_hrs) OVER ()::NUMERIC, 2) AS team_avg_hrs,
    ROUND(avg_hrs - AVG(avg_hrs) OVER (), 2) AS delta_vs_team,
    CASE
        WHEN avg_hrs > AVG(avg_hrs) OVER () * 1.25 THEN 'Bottleneck'
        WHEN avg_hrs > AVG(avg_hrs) OVER ()        THEN 'Above Average'
        ELSE 'Performing Well'
    END AS performance_flag
FROM agent_stats
ORDER BY slowest_rank;
