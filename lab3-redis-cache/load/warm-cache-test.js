import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://api:8000';
const URL = `${BASE}/books/50000?cache=true`;

export const options = {
  scenarios: {
    warm_cache: {
      executor: 'constant-arrival-rate',
      rate: 1,
      timeUnit: '1s',
      duration: '20s',
      preAllocatedVUs: 2,
      maxVUs: 2,
    },
  },
  thresholds: {
    'http_req_duration{scenario:warm_cache}': ['p(95)<100'],
    'http_req_failed{scenario:warm_cache}': ['rate<0.01'],
    'checks': ['rate==1'],
  },
};

export function setup() {
  const r = http.get(URL);
  if (r.status !== 200) {
    throw new Error(`Warm-up failed: ${r.status}`);
  }
}

export default function () {
  const r = http.get(URL);
  check(r, {
    'HTTP 200': (x) => x.status === 200,
    'Cache HIT': (x) => x.headers['X-Cache'] === 'HIT',
  });
}
