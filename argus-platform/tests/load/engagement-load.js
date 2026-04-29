import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');
const creationRate = new Rate('successful_creations');
const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';

export const options = {
  stages: [
    { duration: '30s', target: 2 },
    { duration: '1m', target: 3 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    errors: ['rate<0.2'],
    http_req_duration: ['p(95)<5000'],
  },
};

export default function () {
  const payload = JSON.stringify({
    targetUrl: `https://test-${Date.now()}.example.com`,
    scanType: 'url',
    scanAggressiveness: 'default',
    authorization: 'LOAD TEST - AUTHORIZED',
    authorizedScope: { domains: ['example.com'], ipRanges: [] },
  });

  const response = http.post(`${BASE_URL}/api/engagement/create`, payload, {
    headers: { 'Content-Type': 'application/json' },
    timeout: '10s',
  });

  errorRate.add(response.status >= 500);
  creationRate.add(response.status === 200 || response.status === 201);

  check(response, {
    'engagement created': (r) => r.status < 400 || r.status === 401,
    'response time ok': (r) => r.timings.duration < 5000,
  });

  sleep(5); // Don't overwhelm
}
