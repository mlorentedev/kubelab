// Answers `GET /console/queue` from recorded responses, so `astro dev` needs no cluster and no
// session (ADR-074, Consequences: the development loop needs an auth path).
//
// `fixtures/<scenario>/page-N.json` are whole responses in the API's wire shape. Page N's
// `next` cursor is the key that leads to page N+1, the way the real keyset cursor does.
// `CONSOLE_FIXTURE=<scenario>` picks one; `default` is used when it is unset. Two scenarios are
// not recordings but the two ways the real path fails: `unavailable` is the API's 503 and
// `expired` is the redirect Authelia answers an expired session with.
//
// It never proxies to a real host and never reads a cookie from a file or the environment.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

const fixturesDir = fileURLToPath(new URL('../fixtures/', import.meta.url));

export interface Answer {
  status: number;
  body?: unknown;
  headers?: Record<string, string>;
}

const FAILURES = ['unavailable', 'expired'];

export function scenarioNames(): string[] {
  const recorded = readdirSync(fixturesDir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);
  return [...recorded, ...FAILURES].sort();
}

function pages(scenario: string): { next: string | null }[] {
  const out: { next: string | null }[] = [];
  for (let n = 1; existsSync(`${fixturesDir}${scenario}/page-${n}.json`); n++) {
    out.push(JSON.parse(readFileSync(`${fixturesDir}${scenario}/page-${n}.json`, 'utf8')));
  }
  return out;
}

export function answerQueue(scenario: string, query: URLSearchParams): Answer {
  if (scenario === 'unavailable') return { status: 503 };
  if (scenario === 'expired') return { status: 302, headers: { Location: '/login' } };
  // Only a name listed under fixtures/ reaches the filesystem, so `../x` cannot read outside it.
  const recorded = scenarioNames().includes(scenario) ? pages(scenario) : [];
  if (recorded.length === 0) {
    throw new Error(`no fixture scenario "${scenario}"; choose one of: ${scenarioNames().join(', ')}`);
  }
  const after = query.get('after');
  if (!after) return { status: 200, body: recorded[0] };
  const at = recorded.findIndex((p) => p.next === after);
  if (at === -1) return { status: 400, body: { error: 'not a queue cursor' } };
  return { status: 200, body: recorded[at + 1] };
}

/** Vite plugin for `astro dev` only: it has no effect on `astro build`. */
export function fixtureApi(): Plugin {
  return {
    name: 'console-fixture-api',
    apply: 'serve',
    configureServer(server) {
      const scenario = process.env.CONSOLE_FIXTURE || 'default';
      // Fail at start, not on the first request, if the name is wrong.
      answerQueue(scenario, new URLSearchParams());
      server.config.logger.info(`console fixtures: scenario "${scenario}" answers /console/queue`);
      server.middlewares.use('/console/queue', (req, res) => {
        const url = new URL(req.url ?? '', 'http://localhost');
        const a = answerQueue(scenario, url.searchParams);
        res.statusCode = a.status;
        for (const [k, v] of Object.entries(a.headers ?? {})) res.setHeader(k, v);
        res.setHeader('Cache-Control', 'no-store');
        if (a.body !== undefined) {
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(a.body));
        } else {
          res.end();
        }
      });
    },
  };
}
