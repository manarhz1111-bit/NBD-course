import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const RATE = Number(__ENV.RATE || 100);
const DURATION = __ENV.DURATION || '2m';
const PAUSE = '5s';
const BOOKS = 100000;
const HOTNESS = Number(__ENV.HOTNESS || 4);
const HOT_BOOKS = Number(__ENV.HOT_BOOKS || BOOKS);   // whole catalogue by default
const WARM_BOOKS = Number(__ENV.WARM_BOOKS || 64);    // books warmed in setup()
const GENRES = ['fantasy', 'science', 'history', 'detective', 'romance', 'poetry',
  'biography', 'horror', 'children', 'business', 'philosophy', 'travel'];

function seconds(d) {
  const m = /^(\d+)(s|m)$/.exec(d);
  return m[2] === 'm' ? Number(m[1]) * 60 : Number(m[1]);
}

const RAMP = '5s';

const scenario = (cache, startTime) => ({
  executor: 'ramping-arrival-rate',
  startRate: Math.min(10, RATE),
  timeUnit: '1s',
  stages: [
    { target: RATE, duration: RAMP },
    { target: RATE, duration: DURATION },
  ],
  preAllocatedVUs: 50,
  maxVUs: 500,
  startTime,
  env: { CACHE: cache },
  tags: { cache_mode: cache === 'true' ? 'cache' : 'no_cache' },
});

export const options = {
  scenarios: {
    with_cache: scenario('true', '0s'),
    without_cache: scenario('false', `${seconds(RAMP) + seconds(DURATION) + seconds(PAUSE)}s`),
  },
  systemTags: ['status', 'method', 'name', 'scenario', 'expected_response', 'error_code'],
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    'http_req_failed{scenario:with_cache}': ['rate<0.01'],
    'http_req_duration{scenario:with_cache}': ['p(95)<100'],
    'http_req_failed{scenario:without_cache}': ['rate<0.01'],
    'http_req_duration{scenario:without_cache}': ['p(95)<60000'],
    'dropped_iterations{scenario:with_cache}': ['count==0'],
    'dropped_iterations{scenario:without_cache}': ['count==0'],
    'checks': ['rate==1'],
  },
};

export function setup() {
  function warm(path) {
    const first = http.get(`${BASE}${path}`);
    const second = http.get(`${BASE}${path}`);

    if (first.status !== 200 ||
        second.status !== 200 ||
        second.headers['X-Cache'] !== 'HIT') {
      throw new Error(`Cache warm-up failed: ${path}`);
    }
  }

  for (let id = 1; id <= WARM_BOOKS; id++) {
    warm(`/books/${id}?cache=true`);
  }

  for (const genre of GENRES) {
    warm(`/genres/${genre}/top?limit=10&cache=true`);
  }

  warm('/genres?cache=true');
}

function bookId() {
  return 1 + Math.floor(HOT_BOOKS * Math.pow(Math.random(), HOTNESS));
}


const hitDuration = new Trend('cache_hit_duration', true);
const otherDuration = new Trend('cache_other_duration', true);
const hitRatio = new Rate('cache_hit_ratio');

function trackCacheResult(res) {
  if (__ENV.CACHE !== 'true') return;

  const result = String(res.headers['X-Cache'] || '').toUpperCase();
  if (!result) return;

  const hit = result === 'HIT' || result === 'NEGATIVE_HIT' || result === 'WAIT_HIT';

  if (hit) {
    hitDuration.add(res.timings.duration);
  } else {
    otherDuration.add(res.timings.duration);
  }

  hitRatio.add(hit);
}

export default function () {
  const cache = __ENV.CACHE;
  const r = Math.random();
  let res;

  if (r < 0.74) {
    res = http.get(`${BASE}/books/${bookId()}?cache=${cache}`, { tags: { name: 'GET /books/:id' } });
    check(res, { 'book 200': (x) => x.status === 200 });
  } else if (r < 0.75) {
    const missing = BOOKS + 1 + Math.floor(Math.random() * 500);
    res = http.get(`${BASE}/books/${missing}?cache=${cache}`, { tags: { name: 'GET /books/:id (missing)' }, responseCallback: http.expectedStatuses(404) });
    check(res, { 'missing 404': (x) => x.status === 404 });
  } else if (r < 0.93) {
    const g = GENRES[Math.floor(Math.random() * GENRES.length)];
    res = http.get(`${BASE}/genres/${g}/top?limit=10&cache=${cache}`, { tags: { name: 'GET /genres/:genre/top' } });
    check(res, { 'top 200': (x) => x.status === 200 });
  } else if (r < 0.95) {
    res = http.get(`${BASE}/genres?cache=${cache}`, { tags: { name: 'GET /genres' } });
    check(res, { 'genres 200': (x) => x.status === 200 });
  } else if (r < 0.985) {
    const body = JSON.stringify({ rating: 1 + Math.floor(Math.random() * 5), text: 'k6 load test' });
    res = http.post(`${BASE}/books/${bookId()}/reviews`, body,
      { headers: { 'Content-Type': 'application/json' }, tags: { name: 'POST /books/:id/reviews' } });
    check(res, { 'review 201': (x) => x.status === 201 });
  } else {
    const body = JSON.stringify({ price: Math.round((5 + Math.random() * 95) * 100) / 100 });
    res = http.put(`${BASE}/books/${bookId()}/price`, body,
      { headers: { 'Content-Type': 'application/json' }, tags: { name: 'PUT /books/:id/price' } });
    check(res, { 'price 200': (x) => x.status === 200 });
  }
  trackCacheResult(res);
}

export function handleSummary(data) {
  const m = (name) => (data.metrics[name] ? data.metrics[name].values : {});
  const ms = (v) => (v === undefined ? '-' : v.toFixed(1).padStart(8));
  const rows = ['with_cache', 'without_cache'].map((s) => {
    const d = m(`http_req_duration{scenario:${s}}`);
    const f = m(`http_req_failed{scenario:${s}}`);
    const dropped = m(`dropped_iterations{scenario:${s}}`).count || 0;
    return `${s.padEnd(14)} ${ms(d.avg)} ${ms(d['p(50)'])} ${ms(d['p(95)'])} ${ms(d['p(99)'])} ${ms(d.max)}` +
      `   ${((f.rate || 0) * 100).toFixed(2).padStart(6)}%   ${String(dropped).padStart(7)}`;
  });
  const table = [
    '',
    `Target rate: ${RATE} req/s for ${DURATION} per scenario (after a ${RAMP} ramp-up)`,
    'scenario            avg      p50      p95      p99      max   (ms)   failed   dropped',
    ...rows,
    '',
  ].join('\n');
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  return {
    stdout: table,
    [`/scripts/results/summary-${stamp}.json`]: JSON.stringify(data, null, 2),
    [`/scripts/results/summary-${stamp}.txt`]: table,
  };
}
