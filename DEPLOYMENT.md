# Argus Pentest Platform - Deployment Guide

## Overview

This guide covers deploying the Argus Pentest Platform to Railway (or similar PaaS platforms).

## Architecture

- **Next.js Web Service**: Frontend and API layer
- **PostgreSQL Database**: Data persistence with pgvector extension
- **Redis Instance**: Job queue and distributed locking
- **Python Workers**: Celery workers for background processing

## Prerequisites

- Railway account (or similar PaaS)
- GitHub repository with code
- Environment variables configured

## Required Environment Variables

### Next.js Web Service

```bash
# Database
DATABASE_URL=postgresql://user:password@host:port/database

# Redis
REDIS_URL=redis://host:port

# Authentication
NEXTAUTH_URL=https://your-domain.com
NEXTAUTH_SECRET=<generate-with-openssl-rand-base64-32>
JWT_SECRET=<generate-with-openssl-rand-base64-32>

# Node Environment
NODE_ENV=production
```

### Python Workers

```bash
# Database
DATABASE_URL=postgresql://user:password@host:port/database

# Redis (Celery broker)
CELERY_BROKER_URL=redis://host:port/0
CELERY_RESULT_BACKEND=redis://host:port/1

# Optional: AI Explainer
OPENAI_API_KEY=<your-openai-api-key>

# Python Environment
PYTHONUNBUFFERED=1
```

## Railway Deployment Steps

### 1. Create New Project

1. Go to Railway dashboard
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Connect your repository

### 2. Add PostgreSQL Database

1. Click "New" → "Database" → "PostgreSQL"
2. Railway will provision a PostgreSQL instance
3. Note the `DATABASE_URL` connection string
4. Enable pgvector extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

### 3. Add Redis Instance

1. Click "New" → "Database" → "Redis"
2. Railway will provision a Redis instance
3. Note the `REDIS_URL` connection string

### 4. Configure Next.js Service

1. Click on your web service
2. Go to "Settings" → "Environment"
3. Add all Next.js environment variables
4. Set build command: `cd argus-platform && npm install && npm run build`
5. Set start command: `cd argus-platform && npm start`
6. Set root directory: `/`

### 5. Add Python Worker Service

1. Click "New" → "Empty Service"
2. Connect to same GitHub repo
3. Go to "Settings" → "Environment"
4. Add all Python worker environment variables
5. Set build command: `cd argus-workers && pip install -r requirements.txt`
6. Set start command: `cd argus-workers && celery -A celery_app worker --loglevel=info`
7. Set root directory: `/`

### 6. Run Database Migrations

1. Connect to PostgreSQL instance
2. Run schema creation script:
   ```bash
   psql $DATABASE_URL < argus-platform/db/schema.sql
   ```

### 7. Verify Deployment

1. Check Next.js service logs for startup
2. Check Python worker logs for Celery connection
3. Visit your deployment URL
4. Test authentication and engagement creation

## Testing Against OWASP Juice Shop

### Local Testing

1. Run OWASP Juice Shop locally:
   ```bash
   docker run -p 3000:3000 bkimminich/juice-shop
   ```

2. Create engagement targeting `http://localhost:3000`

3. Configure authorized scope:
   ```json
   {
     "domains": ["localhost"],
     "ipRanges": ["127.0.0.1/32"]
   }
   ```

4. Monitor dashboard for real-time findings

### Expected Findings

- SQL Injection vulnerabilities
- XSS vulnerabilities
- Authentication bypasses
- IDOR vulnerabilities
- Directory traversal

## Production Considerations

### Security

1. **Enable HTTPS**: Railway provides automatic HTTPS
2. **Rotate Secrets**: Regularly rotate JWT_SECRET and NEXTAUTH_SECRET
3. **Database Backups**: Enable automated backups in Railway
4. **Rate Limiting**: Configure appropriate rate limits for production
5. **Container Isolation**: Use Docker for tool execution (not subprocess)

### Scaling

1. **Horizontal Scaling**: Add more Python workers for increased throughput
2. **Database Connection Pooling**: Configure appropriate pool size
3. **Redis Memory**: Monitor Redis memory usage and scale as needed
4. **Worker Concurrency**: Adjust Celery concurrency based on load

### Monitoring

1. **Application Logs**: Monitor Railway logs for errors
2. **Database Performance**: Track query performance and slow queries
3. **Worker Health**: Monitor Celery worker status and task queue length
4. **Rate Limit Events**: Track rate limiting activity

## Troubleshooting

### Workers Not Processing Jobs

1. Check Redis connection: `redis-cli -u $REDIS_URL ping`
2. Verify Celery broker URL matches Redis URL
3. Check worker logs for connection errors
4. Ensure workers are running: `celery -A celery_app inspect active`

### Database Connection Errors

1. Verify DATABASE_URL is correct
2. Check PostgreSQL is running
3. Verify network connectivity
4. Check connection pool settings

### Tool Execution Failures

1. Verify security tools are installed in worker container
2. Check tool execution timeouts
3. Review tool execution logs
4. Verify scope validation is working

## Demo Video Script

### 1. Introduction (30 seconds)

- Show landing page
- Explain platform purpose
- Highlight key features

### 2. Engagement Creation (1 minute)

- Create new engagement
- Configure target URL (Juice Shop)
- Set authorized scope
- Configure rate limits
- Submit engagement

### 3. Real-Time Monitoring (2 minutes)

- Connect to engagement in dashboard
- Show real-time events appearing
- Highlight different event types:
  - Job started
  - Tool executed
  - Findings discovered
  - State transitions
- Show findings grouped by severity

### 4. Approval Workflow (1 minute)

- Wait for "awaiting_approval" state
- Review reconnaissance findings
- Click "Approve Findings" button
- Show scan job queued

### 5. Intelligence-Driven Iteration (1 minute)

- Show state transitions
- Explain intelligence engine decisions
- Show loop budget tracking
- Demonstrate adaptive scanning

### 6. Final Report (1 minute)

- Navigate to findings page
- Show findings grouped by severity
- Display confidence scores
- Show AI-generated explanations
- Highlight fix guidance

### 7. Conclusion (30 seconds)

- Recap key features
- Show execution timeline
- Highlight real-time updates
- Call to action

## Support

For issues or questions:
- Check logs in Railway dashboard
- Review error messages in application
- Consult requirements and design documents
- Contact platform maintainers

## Requirements Satisfied

- Requirement 37: Production Deployment
- Requirement 38: Security Tool Integration
- All requirements: End-to-end testing
