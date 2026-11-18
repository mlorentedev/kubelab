-- One audit row per forge call, not per write (ADR-066 W9, CONSOLE-004 AC2). The outbox's
-- first migration allowed only the two outcomes that end a write, applied and failed. A call
-- that settled nothing is also a call: a 5xx, a 429 or a network error leaves the write
-- pending (retry), and a create whose answer was lost may or may not have been made
-- (unknown), so the audit now names both.
ALTER TABLE forge_write_audit DROP CONSTRAINT forge_write_audit_outcome_check;
ALTER TABLE forge_write_audit ADD CONSTRAINT forge_write_audit_outcome_check
    CHECK (outcome IN ('applied', 'failed', 'retry', 'unknown'));

COMMENT ON TABLE forge_write_audit IS
    'One row per call made to a forge for a write, whatever the answer: applied or refused for good '
    '(failed), left to try again (retry) or a create whose outcome is not known (unknown). A record, '
    'not a cache: a rebuild of the read model never deletes a row, and it has no foreign key.';
