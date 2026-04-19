# Argus Platform Frontend Tests

Test suite for the Next.js frontend and API routes.

## Test Coverage

### API Routes

- Engagement creation and management
- Authentication and authorization
- Job queue submission

### Library Functions

- Redis job queue operations
- Authorization checks
- Session management

## Running Tests

### Prerequisites

Install test dependencies:

```bash
cd argus-platform
npm install --save-dev jest @testing-library/react @testing-library/jest-dom @types/jest ts-jest
```

### Configure Jest

Create `jest.config.js`:

```javascript
const nextJest = require("next/jest");

const createJestConfig = nextJest({
  dir: "./",
});

const customJestConfig = {
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  testEnvironment: "jest-environment-jsdom",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testMatch: ["**/__tests__/**/*.test.ts", "**/__tests__/**/*.test.tsx"],
};

module.exports = createJestConfig(customJestConfig);
```

### Run Tests

```bash
# Run all tests
npm test

# Run with coverage
npm test -- --coverage

# Run in watch mode
npm test -- --watch

# Run specific test file
npm test -- __tests__/lib/redis.test.ts
```

## Test Structure

```
argus-platform/
├── __tests__/
│   ├── api/
│   │   └── engagement/
│   │       └── create.test.ts
│   ├── lib/
│   │   ├── redis.test.ts
│   │   └── authorization.test.ts
│   └── README.md
├── jest.config.js
└── jest.setup.js
```

## Writing Tests

### API Route Tests

```typescript
import { POST } from "@/app/api/engagement/create/route";

describe("POST /api/engagement/create", () => {
  it("should create engagement with valid data", async () => {
    const request = new Request("http://localhost:3000/api/engagement/create", {
      method: "POST",
      body: JSON.stringify({
        targetUrl: "https://example.com",
        authorization: "Written authorization",
        authorizedScope: {
          domains: ["example.com"],
          ipRanges: [],
        },
      }),
    });

    const response = await POST(request);
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.engagement).toBeDefined();
  });
});
```

### Component Tests

```typescript
import { render, screen } from '@testing-library/react';
import Component from '@/components/Component';

describe('Component', () => {
  it('should render correctly', () => {
    render(<Component />);
    expect(screen.getByText('Expected Text')).toBeInTheDocument();
  });
});
```

## Mocking

### Mock NextAuth Session

```typescript
jest.mock("next-auth", () => ({
  getServerSession: jest.fn(() =>
    Promise.resolve({
      user: {
        id: "user-123",
        email: "test@example.com",
        orgId: "org-123",
      },
    }),
  ),
}));
```

### Mock Database

```typescript
jest.mock("pg", () => ({
  Pool: jest.fn().mockImplementation(() => ({
    query: jest.fn().mockResolvedValue({ rows: [] }),
    connect: jest.fn(),
  })),
}));
```

### Mock Redis

```typescript
jest.mock("ioredis", () => {
  return jest.fn().mockImplementation(() => ({
    get: jest.fn(),
    set: jest.fn(),
    lpush: jest.fn(),
  }));
});
```

## Coverage Goals

- **Overall Coverage:** > 70%
- **API Routes:** > 80%
- **Critical Functions:** > 90%

## Best Practices

1. **Test Behavior, Not Implementation**
   - Focus on what the code does, not how it does it
2. **Use Descriptive Test Names**
   - `it('should create engagement with valid data')`
   - Not: `it('test1')`

3. **Arrange-Act-Assert Pattern**

   ```typescript
   it('should do something', () => {
     // Arrange
     const input = 'test';

     // Act
     const result = function(input);

     // Assert
     expect(result).toBe('expected');
   });
   ```

4. **Mock External Dependencies**
   - Database connections
   - Redis connections
   - External APIs
   - File system operations

5. **Test Edge Cases**
   - Empty inputs
   - Invalid data
   - Error conditions
   - Boundary values

## Continuous Integration

Tests run automatically on:

- Pull requests
- Commits to main branch
- Pre-deployment checks

## Troubleshooting

### Module Resolution Errors

Ensure `tsconfig.json` has correct path mappings:

```json
{
  "compilerOptions": {
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

### Environment Variables

Create `.env.test` for test environment variables:

```bash
DATABASE_URL=postgresql://test:test@localhost:5432/test_db
REDIS_URL=redis://localhost:6379
NEXTAUTH_SECRET=test-secret
```

### Async Test Timeouts

Increase timeout for slow tests:

```typescript
it("should handle slow operation", async () => {
  // test code
}, 10000); // 10 second timeout
```
