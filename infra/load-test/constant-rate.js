// One open-model load step against one staging URL, run by `make load-test`.
//
// Open model on purpose: requests arrive at a fixed rate whether or not earlier
// ones finished, so a slow server cannot slow the generator down and hide its own
// latency (coordinated omission). Parameters arrive from toolkit/features/load_test.py.
//
// The step opens with LT_WARMUP seconds on the same virtual users, and every request is
// tagged with its phase: `cold` while connections are still being opened, `warm` after.
// One scenario on purpose: each scenario has its own VU pool, so a separate warm-up
// scenario would reopen every connection at its end and move the burst, not exclude it
// (#3294). The toolkit judges the step on `warm` and reports `cold` as the burst.
import http from 'k6/http';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';

const { LT_HOST, LT_PATH, LT_ADDRESS, LT_RATE, LT_SECONDS, LT_WARMUP, LT_MAX_VUS, LT_BYPASS_HEADER, LT_BYPASS_VALUE, LT_ACCEPT_ENCODING } = __ENV;

// Second lock behind the toolkit's: this file refuses a host that is not a staging
// name, and `hosts` below sends the name to the staging node whatever DNS says.
if (!/(^|\.)staging\.[a-z0-9.-]+$/.test(LT_HOST || '') || !LT_ADDRESS) {
  throw new Error(`refusing to run: ${LT_HOST} is not a staging host with a pinned address`);
}

const rate = Number(LT_RATE);
const seconds = Number(LT_SECONDS);
const warmup = Number(LT_WARMUP || 0);
// A cap on the pool holds the connection count below what a cold burst would open (#3308).
if (LT_MAX_VUS && !/^[1-9][0-9]*$/.test(LT_MAX_VUS)) throw new Error(`refusing to run: LT_MAX_VUS=${LT_MAX_VUS} is not a positive integer`);
const maxVUs = LT_MAX_VUS ? Number(LT_MAX_VUS) : Math.max(200, rate * 2);
const status429 = new Counter('status_429');
const headers = LT_BYPASS_HEADER ? { [LT_BYPASS_HEADER]: LT_BYPASS_VALUE } : {};
// Unset, k6 sends its own `Accept-Encoding: gzip`; set, it replaces that (an A/B on compression).
if (LT_ACCEPT_ENCODING) headers['Accept-Encoding'] = LT_ACCEPT_ENCODING;

// k6 summarises a tagged submetric only when a threshold names it, so each figure the
// toolkit reads per phase gets one that always holds. Without a warm-up there are none.
const PER_PHASE = [
  ['http_req_duration', 'max>=0'],
  ['http_reqs', 'count>=0'],
  ['http_req_failed', 'rate>=0'],
  ['http_req_blocked', 'max>=0'],
  ['http_req_connecting', 'max>=0'],
  ['http_req_tls_handshaking', 'max>=0'],
  ['http_req_waiting', 'max>=0'],
  ['http_req_receiving', 'max>=0'],
];
const thresholds = {};
if (warmup > 0) {
  for (const phase of ['cold', 'warm']) {
    for (const [metric, always] of PER_PHASE) thresholds[`${metric}{phase:${phase}}`] = [always];
  }
}

export const options = {
  hosts: { [LT_HOST]: LT_ADDRESS },
  // A redirect could leave staging; the step reads it as a non-200 instead.
  maxRedirects: 0,
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds,
  scenarios: {
    step: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration: `${warmup + seconds}s`,
      preAllocatedVUs: Math.min(maxVUs, Math.max(20, Math.ceil(rate / 10))),
      maxVUs,
    },
  },
};

export default function () {
  // Decided before sending: a request that starts cold and ends warm counts as cold.
  const phase = Date.now() - exec.scenario.startTime < warmup * 1000 ? 'cold' : 'warm';
  const response = http.get(`https://${LT_HOST}${LT_PATH}`, { headers, timeout: '5s', tags: { phase } });
  if (response.status === 429) status429.add(1);
}

export function handleSummary(data) {
  return { stdout: JSON.stringify(data.metrics) };
}
