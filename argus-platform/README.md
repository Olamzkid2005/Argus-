# Argus Platform — Frontend & API

The Argus frontend provides the user interface for the Argus AI-powered penetration testing platform, including dashboards, findings management, engagement creation, analytics, and API routes.

## Tech Stack

- **Framework:** Next.js 14.2 (App Router)
- **UI:** React 18 + Tailwind CSS + shadcn/ui
- **State:** React context + SSE real-time streaming
- **Auth:** NextAuth.js (Credentials + OAuth providers)
- **Database:** PostgreSQL via node-postgres pool
- **Cache/Queue:** Redis (ioredis)

## Development

```bash
# Install dependencies
npm ci

# Run development server
npm run dev

# Run tests
npx jest --passWithNoTests

# Run E2E tests
npx playwright test

# Lint
npm run lint

# Type check
npx tsc --noEmit
```

## Project Structure

```
src/
├── app/           # Pages (App Router) + API routes
│   ├── api/       # 70+ route handlers (auth, engagements, findings, etc.)
│   ├── auth/      # Sign-in, sign-up, password reset
│   ├── dashboard/ # Main dashboard hub
│   ├── engagements/ # Engagement list, detail, create
│   ├── findings/  # Finding list, detail, AI analysis
│   └── ...
├── components/    # UI components
│   ├── ui/        # shadcn primitives (36 components)
│   ├── ui-custom/ # Composite widgets (19)
│   └── animations/# Framer Motion / Three.js wrappers
├── hooks/         # Custom React hooks (6)
├── lib/           # Utilities (auth, db, cache, rate-limiter, etc.)
└── types/         # TypeScript type definitions
```

## Key Features

- Real-time scan progress via SSE streaming
- AI-powered finding explanations and analysis
- Auth wizard with automatic login form detection
- Compliance posture dashboards (OWASP, PCI DSS, SOC 2, NIST, HIPAA, ISO 27001)
- Verified exploitation chains with step-by-step PoC
- Engagement templates for scan configuration reuse
