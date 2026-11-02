-- The forge task view's read model (CONSOLE-004, ADR-066 amendment A2 and A6).
-- A cache: every row but the unprojected events can be rebuilt from the forges.

-- One row per source. as_of only moves on a successful full read, so a source
-- that cannot be read keeps its last known time and is never shown as empty.
CREATE TABLE forge_source (
    forge            text        NOT NULL,
    owner            text        NOT NULL,
    repo             text        NOT NULL,
    as_of            timestamptz,
    source_reachable boolean     NOT NULL DEFAULT false,
    last_attempt_at  timestamptz,
    PRIMARY KEY (forge, owner, repo)
);

CREATE TABLE forge_item (
    forge      text        NOT NULL,
    owner      text        NOT NULL,
    repo       text        NOT NULL,
    number     integer     NOT NULL,
    kind       text        NOT NULL CHECK (kind IN ('issue', 'pull')),
    title      text        NOT NULL,
    state      text        NOT NULL CHECK (state IN ('open', 'closed')),
    author     text        NOT NULL,
    assignees  text[]      NOT NULL DEFAULT '{}',
    labels     text[]      NOT NULL DEFAULT '{}',
    url        text        NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (forge, owner, repo, number),
    FOREIGN KEY (forge, owner, repo) REFERENCES forge_source (forge, owner, repo) ON DELETE CASCADE
);

CREATE INDEX forge_item_queue ON forge_item (state, updated_at DESC);

-- A webhook is stored before it is projected, so a failed projection replays.
-- The unique delivery id is what makes the same delivery project once.
CREATE TABLE forge_event (
    forge        text        NOT NULL,
    delivery_id  text        NOT NULL,
    event_type   text        NOT NULL,
    payload      jsonb       NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now(),
    projected_at timestamptz,
    PRIMARY KEY (forge, delivery_id)
);

CREATE INDEX forge_event_pending ON forge_event (received_at) WHERE projected_at IS NULL;
