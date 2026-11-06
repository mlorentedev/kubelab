// One open-model load step against one staging URL, run by `make load-test`.
//
// Open model on purpose: requests arrive at a fixed rate whether or not earlier
// ones finished, so a slow server cannot slow the generator down and hide its own
// latency (coordinated omission). Parameters arrive from toolkit/features/load_test.py.
import http from 'k6/http';
import { Counter } from 'k6/metrics';

const { LT_HOST, LT_PATH, LT_ADDRESS, LT_RATE, LT_SECONDS, LT_BYPASS_HEADER, LT_BYPASS_VALUE, LT_ACCEPT_ENCODING } = __ENV;

// Second lock behind the toolkit's: this file refuses a host that is not a staging
// name, and `hosts` below sends the name to the staging node whatever DNS says.
if (!/(^|\.)staging\.[a-z0-9.-]+$/.test(LT_HOST || '') || !LT_ADDRESS) {
  throw new Error(`refusing to run: ${LT_HOST} is not a staging host with a pinned address`);
}

const rate = Number(LT_RATE);
const status429 = new Counter('status_429');
const headers = LT_BYPASS_HEADER ? { [LT_BYPASS_HEADER]: LT_BYPASS_VALUE } : {};
// Unset, k6 sends its own `Accept-Encoding: gzip`; set, it replaces that (an A/B on compression).
if (LT_ACCEPT_ENCODING) headers['Accept-Encoding'] = LT_ACCEPT_ENCODING;

export const options = {
  hosts: { [LT_HOST]: LT_ADDRESS },
  // A redirect could leave staging; the step reads it as a non-200 instead.
  maxRedirects: 0,
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  scenarios: {
    step: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration: `${LT_SECONDS}s`,
      preAllocatedVUs: Math.max(20, Math.ceil(rate / 10)),
      maxVUs: Math.max(200, rate * 2),
    },
  },
};

export default function () {
  const response = http.get(`https://${LT_HOST}${LT_PATH}`, { headers, timeout: '5s' });
  if (response.status === 429) status429.add(1);
}

export function handleSummary(data) {
  return { stdout: JSON.stringify(data.metrics) };
}
