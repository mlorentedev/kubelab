-- The statistics view of the forge read model (CONSOLE-004 AC6): what Grafana's read-only
-- role selects, and the only thing it can select. It carries counts' inputs and no
-- identity: no title, URL, author or assignee login, no free-text label, and no issue
-- number (owner, repo and number rebuild an item's address). A column added here is a
-- decision, and store/forge_stats_test.go lists the allowed ones.
--
-- A plain view, so it runs with its owner's rights: the role needs SELECT on the view and
-- nothing on forge_item or forge_source. Do not make it security_invoker.
--
-- One row per item, and one row per source that holds none, so a source never read or
-- read empty still shows its freshness. The model keeps no created_at or closed_at, so
-- updated_at is the only age an item has.
CREATE VIEW forge_stats AS
SELECT
    s.forge,
    s.owner,
    s.repo,
    s.as_of,
    s.source_reachable,
    s.last_attempt_at,
    i.kind,
    i.state,
    i.updated_at,
    (SELECT substr(l, length('status:') + 1) FROM unnest(i.labels) AS l
      WHERE starts_with(l, 'status:') ORDER BY l LIMIT 1) AS status,
    (SELECT substr(l, length('priority:') + 1) FROM unnest(i.labels) AS l
      WHERE starts_with(l, 'priority:') ORDER BY l LIMIT 1) AS priority,
    (SELECT substr(l, length('area:') + 1) FROM unnest(i.labels) AS l
      WHERE starts_with(l, 'area:') ORDER BY l LIMIT 1) AS area
FROM forge_source AS s
LEFT JOIN forge_item AS i USING (forge, owner, repo);

-- The role is created by the toolkit's Postgres provisioner (`make provision-postgres-tenant`),
-- which a tenant's migration cannot do, so it may not exist yet when this runs. The
-- provisioner grants the same SELECT when it runs after this migration; either order ends
-- with the grant in place.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'forge_stats') THEN
    GRANT SELECT ON forge_stats TO forge_stats;
  END IF;
END
$$;
