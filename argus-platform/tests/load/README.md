# Load Tests

## Prerequisites
Install k6: `brew install k6` (macOS) or see https://k6.io/docs/getting-started/installation/

## Running Tests

```bash
# API endpoint load test
k6 run tests/load/api-load.js

# WebSocket polling simulation
k6 run tests/load/websocket-load.js

# Engagement creation stress test
k6 run tests/load/engagement-load.js

# Custom base URL
k6 run -e BASE_URL=https://your-argus-instance.com tests/load/api-load.js
```

## Metrics
- **p(95) < 2s**: 95th percentile response time under 2 seconds
- **Error rate < 10%**: Less than 10% server errors
- **p(90) < 1.5s**: 90th percentile under 1.5 seconds
