# Contributing to Argus

Thank you for your interest in contributing to Argus! This document provides guidelines for contributing.

## Getting Started

### Prerequisites

- macOS 13+ or Linux
- PostgreSQL 15+ (with pgvector extension)
- Redis
- Python 3.11+
- Node.js 18+
- Go 1.21+ (for security tools)

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/Olamzkid2005/Argus-.git
cd Argus-

# Install everything
make install

# Set up database
make db-setup

# Start development
make dev
```

### Using Docker (Alternative)

```bash
docker-compose up -d
```

## Development Workflow

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes
3. Run linters: `make lint`
4. Run tests: `make test`
5. Commit with a clear message
6. Push and create a Pull Request

## Code Style

### Frontend (TypeScript/Next.js)
- Use TypeScript strict mode
- Follow existing component patterns
- Use Tailwind CSS for styling
- Run `npm run lint` before committing

### Backend (Python)
- Follow PEP 8
- Use type hints
- Use Pydantic models for data validation
- Run `ruff check .` before committing

## Pull Request Process

1. Ensure all tests pass
2. Update documentation if needed
3. One feature per PR
4. Write clear commit messages

## Reporting Issues

Use GitHub Issues with the appropriate label:
- `bug` — something is broken
- `feature` — new functionality request
- `security` — security vulnerability (email for sensitive issues)

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.
