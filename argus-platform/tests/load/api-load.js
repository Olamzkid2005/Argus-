import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const apiLatency = new Trend('api_latency');

// Configuration
const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';

export const options = {
  stages: [
    { duration: '30s', target: 5 },   // Ramp up
    { duration: '1m', target: 10 },    // Stay at 10 users
    { duration: '30s', target: 20 },   // Peak
    { duration: '1m', target: 20 },    // Stay at peak
    { duration: '30s', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<2000'],  // 95% of requests under 2s
    errors: ['rate<0.1'],                // Error rate under 10%
    api_latency: ['p(90)<1500'],         // 90th percentile under 1.5s
  },
};

export default function () {
  const endpoints = [
    { name: 'Landing Page', url: `${BASE_URL}/`, method: 'GET' },
    { name: 'Dashboard', url: `${BASE_URL}/dashboard`, method: 'GET' },
    { name: 'Engagements List', url: `${BASE_URL}/api/engagements`, method: 'GET' },
    { name: 'Findings List', url: `${BASE_URL}/api/findings?page=1&limit=10`, method: 'GET' },
    { name: 'Analytics Trends', url: `${BASE_URL}/api/analytics/trends`, method: 'GET' },
    { name: 'Reports List', url: `${BASE_URL}/api/reports`, method: 'GET' },
    { name: 'Settings', url: `${BASE_URL}/api/settings`, method: 'GET' },
    { name: 'Assets', url: `${BASE_URL}/api/assets`, method: 'GET' },
  ];

  // Randomly select an endpoint
  const endpoint = endpoints[Math.floor(Math.random() * endpoints.length)];

  const startTime = Date.now();
  const response = http.get(endpoint.url, {
    headers: { 'Accept': 'application/json' },
    timeout: '10s',
  });
  const latency = Date.now() - startTime;

  apiLatency.add(latency);
  errorRate.add(response.status >= 500);

  check(response, {
    [`${endpoint.name} - status is ok`]: (r) => r.status < 500,
    [`${endpoint.name} - response time < 5s`]: () => latency < 5000,
  });

  sleep(Math.random() * 2 + 1); // 1-3s think time
}
