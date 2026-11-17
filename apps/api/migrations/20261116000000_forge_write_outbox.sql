-- The forge task view's write path (CONSOLE-004 AC2, ADR-066 amendment of 2026-11-16).
-- Unlike the read model these two tables are NOT a cache: no forge can replay a write
-- that was accepted and not yet delivered, or say who asked for it. So neither has a
-- foreign key to forge_source or forge_item, and a rebuild of the read model, which
-- empties those, leaves both alone.

-- One row per write the operator or a machine caller asked for. A row is committed
-- before the forge is called and is what the view shows as pending until the forge
-- answers 2xx.
CREATE TABLE forge_outbox (
    id              bigserial   PRIMARY KEY,
    -- Remote-User, or the machine identity on the token route.
    actor           text        NOT NULL,
    -- Required on every write. The pair (actor, key) is unique, so a replay finds its row.
    idempotency_key text        NOT NULL,
    -- Digest of the request. The same key with a different request is refused (422).
    request_hash    text        NOT NULL,
    forge           text        NOT NULL,
    owner           text        NOT NULL,
    repo            text        NOT NULL,
    -- NULL for a create until the forge answers.
    number          integer,
    action          text        NOT NULL CHECK (action IN (
        'create', 'add_label', 'remove_label', 'add_assignee', 'remove_assignee', 'close', 'reopen'
    )),
    payload         jsonb       NOT NULL,
    -- in_flight is set (and committed) before the forge is called, so a crash leaves a
    -- row the worker can tell apart from one never tried.
    status          text        NOT NULL CHECK (status IN ('pending', 'in_flight', 'applied', 'failed')),
    -- What the forge answered (a created issue's number and url), returned on a replay.
    response        jsonb,
    attempts        integer     NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    applied_at      timestamptz,
    UNIQUE (actor, idempotency_key)
);

-- What the worker scans: rows still owed to a forge, oldest due first.
CREATE INDEX forge_outbox_due ON forge_outbox (next_attempt_at) WHERE status IN ('pending', 'in_flight');

-- What the forge settled for a write, applied or refused for good. A record, not a
-- cache: it is never deleted by a rebuild and has no foreign key, so removing an
-- outbox row cannot take its audit with it.
CREATE TABLE forge_write_audit (
    id           bigserial   PRIMARY KEY,
    outbox_id    bigint      NOT NULL,
    actor        text        NOT NULL,
    action       text        NOT NULL,
    forge        text        NOT NULL,
    owner        text        NOT NULL,
    repo         text        NOT NULL,
    number       integer,
    -- The label, the login or the title. Never the issue body.
    detail       jsonb,
    outcome      text        NOT NULL CHECK (outcome IN ('applied', 'failed')),
    -- The HTTP status the forge answered with.
    forge_status integer,
    at           timestamptz NOT NULL DEFAULT now()
);
