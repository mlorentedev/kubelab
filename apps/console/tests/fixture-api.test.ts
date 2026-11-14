// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { answerQueue, scenarioNames } from '../dev/fixture-api';
import { parseQueuePage } from '../src/lib/contract';

const get = (scenario: string, query = '') => answerQueue(scenario, new URLSearchParams(query));

describe('the fixture API', () => {
  it('answers the first page with a cursor, and the cursor leads to the next page', () => {
    const first = get('default');
    expect(first.status).toBe(200);
    const p1 = parseQueuePage(first.body);
    expect(p1.next).not.toBeNull();
    expect(p1.total).toBeGreaterThan(p1.items.length);

    const second = parseQueuePage(get('default', `after=${encodeURIComponent(p1.next!)}`).body);
    expect(second.items[0].number).not.toBe(p1.items[0].number);
  });

  it('pages until a null cursor and has handed out every item the total promises', () => {
    let seen = 0;
    let after: string | null = null;
    let total = 0;
    for (let guard = 0; guard < 20; guard++) {
      const r = parseQueuePage(get('default', after ? `after=${encodeURIComponent(after)}` : '').body);
      seen += r.items.length;
      total = r.total;
      after = r.next;
      if (after === null) break;
    }
    expect(after).toBeNull();
    expect(seen).toBe(total);
  });

  it('refuses a cursor it did not issue, as the API refuses a bad one', () => {
    expect(get('default', 'after=not-a-cursor').status).toBe(400);
  });

  it('every recorded scenario parses against the contract', () => {
    for (const name of scenarioNames()) {
      const r = get(name);
      if (r.status === 200) expect(() => parseQueuePage(r.body)).not.toThrow();
    }
  });

  it('the degraded scenario has an unreachable source and a never-read one', () => {
    const r = parseQueuePage(get('degraded').body);
    expect(r.sources.some((s) => !s.reachable)).toBe(true);
    expect(r.sources.some((s) => s.as_of === null)).toBe(true);
  });

  it('the failure scenarios answer what the real edge and API answer', () => {
    expect(get('unavailable').status).toBe(503);
    const expired = get('expired');
    expect(expired.status).toBe(302);
    expect(expired.headers?.Location).toBeTruthy();
  });

  it('an unknown scenario is an error naming the choices, not a silent default', () => {
    expect(() => get('nope')).toThrow(/default/);
  });

  it('a scenario that names a path outside fixtures/ is refused before any file is read', () => {
    for (const name of ['../fixtures/default', 'default/../default', '/etc', '..']) {
      expect(() => get(name)).toThrow(/no fixture scenario/);
    }
  });
});
