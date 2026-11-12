-- The console's usage counter (CONSOLE-004, ADR-066 amendment A8): one row per operator
-- identity and UTC day on which the console page was opened. Vikunja retires only after
-- the console is opened on 5 of 14 consecutive days, read from here.
-- Not part of the read model: no forge can rebuild it, so it is never truncated with the
-- forge tables, and the nightly pg_dumpall of this database is what keeps it.
CREATE TABLE console_usage (
    identity   text        NOT NULL,
    day        date        NOT NULL,
    first_seen timestamptz NOT NULL,
    PRIMARY KEY (identity, day)
);
