import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');
const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';

export const options = {
  stages: [
    { duration: '30s', target: 3 },
    { duration: '1m', target: 5 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    errors: ['rate<0.1'],
  },
};

export default function () {
  // Simulate polling pattern (what the frontend does)
  const engagementId = 'test-engagement-id';

  const endpoints = [
    `${BASE_URL}/api/ws/engagement/${engagementId}/poll?since=0&limit=50`,
    `${BASE_URL}/api/engagement/${engagementId}/activities?limit=50`,
    `${BASE_URL}/api/engagement/${engagementId}/findings`,
    `${BASE_URL}/api/engagement/${engagementId}/timeline`,
  ];

  for (const url of endpoints) {
    const response = http.get(url, { timeout: '5s' });
    errorRate.add(response.status >= 500);
    check(response, {
      'status ok': (r) => r.status < 500,
    });
  }

  sleep(2); // Polling interval
}
