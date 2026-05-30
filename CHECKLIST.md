# Argus Near-Infinite E2E Test

Comprehensive self-healing end-to-end test for the Argus AI-powered pentest platform.

## Codebase Status (May 2026)

### Infrastructure (all running locally, no Docker)
| Service | Status | Details |
|---------|--------|---------|
| PostgreSQL 15.17 | ✅ Running | port 5432, MacPorts daemon (`/opt/local/lib/postgresql15/bin/psql`) |
| Redis 8.6.2 | ✅ Running | port 6379, Homebrew |
| Node.js v24.14.1 | ✅ Available | npm 11.11.0 |
| Python 3.14.4 | ✅ Available | system + venv at `argus-workers/venv/` |
| Next.js 14 | ✅ Starts | `cd argus-platform && npm run dev` |
| Celery workers | ✅ Starts | `celery -A celery_app worker` |

### Security Tools (all on PATH after `./run.sh`)
| Source | Tools | Status |
|--------|-------|--------|
| `~/go/bin/` | nuclei, httpx, katana, amass, naabu, gau, waybackurls, dalfox, gospider, subfinder, alterx | ✅ 11 tools |
| `/usr/local/bin/` | ffuf, nikto, semgrep, gitleaks, trivy, bandit, nmap | ✅ 7 tools |
| `argus-workers/venv/bin/` | sqlmap, arjun, pip-audit, whatweb, wafw00f | ✅ 5 tools |
| ~~Broken symlinks~~ | jwt_tool, commix, testssl | ❌ Removed (pointed to deleted `/tmp/` files) |

### Database Schema (`schema.sql` updated)
All missing columns and tables discovered during testing have been added to `schema.sql`:

| Table | Column | Fix |
|-------|--------|-----|
| `engagement_states` | `trace_id` | ✅ Added |
| `attack_paths` | `chain_exploit_script` | ✅ Added |
| `findings` | `chain_exploit_script`, `updated_at` | ✅ Added |
| `agent_decision_log` | Full table + `checkpoint_id`, `execution_result` | ✅ Created |
| `agent_decisions` | Full table + `tool_selected`, `arguments`, `was_fallback` | ✅ Created |
| `webhooks` | Full table + `webhook_url` | ✅ Created |
| `reports` | `generated_by`, `executive_summary` | ✅ Added |

### LLM
- **API key**: `OPENAI_API_KEY` detected (OpenRouter, `sk-or-v1-...` 73 chars)
- **Status**: ⚠️ Returns `402 Payment Required` — account needs credits
- **Fallback**: System gracefully degrades to deterministic mode via circuit breaker
- **Fix**: Add credits to the OpenRouter account associated with the key

### Pipeline (verified: automated test passes all 4 phases)
| Phase | Status | Details |
|-------|--------|---------|
| RECON | ✅ OK | 5 findings via mock recon tools |
| SCAN | ✅ OK | 13 findings via real `web_scanner` (HTTP to example.com) |
| ANALYZE | ✅ OK | IntelligenceEngine evaluated all findings |
| REPORT | ✅ OK | Engagement transitions to "complete" |
| **End-to-end** | ✅ | **All 4 phases pass. Status: complete** |

### Bugs Fixed
- `ScanLogger.info()` — now accepts printf-style `*args` (was crashing analyze phase)
- `MCPToolBridge` initialization — proper fake module (MagicMock broke Python imports)
- Mock tool results — added `success`, `run_streaming()`, proper dicts for JSON serialization
- Tool PATH — `venv/bin` added to PATH so tools are findable by MCP bridge
- `mcp_server` mock — provides `MCPServer`, `ToolDefinition`, `ToolSchema`, `get_mcp_server`

### Known Non-Blocking Warnings
- `EngagementRepository.get_engagement()` not implemented — non-fatal
- `post_finding_hooks` webhook query — non-fatal (column name fixed)
- LLM circuit breaker opens on 402 — expected with no credits
- No parser for `wafw00f` — tool runs, findings use generic path

---

## Test Checklist

> Use `browser-use-direct` CLI for all browser interactions.
> Screenshots saved to `/tmp/argus-e2e-screenshots/`.

### SECTION 1 — AUTHENTICATION

Navigate to http://localhost:3000

#### 1.1 Sign-in page loads
- `browser-use-direct open http://localhost:3000/auth/signin`
- Verify the sign-in form renders (email field, password field, Sign In button)
- ✅/❌ Sign-in page renders

#### 1.2 Invalid credentials rejected
- `browser-use-direct input <email_index> wrong@example.com`
- `browser-use-direct input <password_index> wrongpassword`
- `browser-use-direct click <submit_button_index>`
- Verify error message appears
- ✅/❌ Invalid credentials rejected

#### 1.3 Valid sign-in
- `browser-use-direct input <email_index> davidolamijulo2005@gmail.com`
- `browser-use-direct input <password_index> Olamzkid123$`
- `browser-use-direct click <submit_index>`
- Verify redirect to /dashboard
- ✅/❌ Valid sign-in works

#### 1.4 Session persistence
- `browser-use-direct eval "location.reload()"`
- Verify still logged in
- ✅/❌ Session persists across refresh

#### 1.5 Signup page loads
- Navigate to http://localhost:3000/auth/signup
- Verify signup form renders (email, password, confirm password, org name fields)
- ✅/❌ Signup page renders

#### 1.6 Forgot password flow
- Navigate to sign-in, click "Forgot password"
- Verify reset page loads at /auth/reset-password
- ✅/❌ Forgot password page accessible

### SECTION 2 — DASHBOARD

Navigate to http://localhost:3000/dashboard

#### 2.1 Dashboard loads
- `browser-use-direct open http://localhost:3000/dashboard`
- Verify page loads without error
- ✅/❌ Dashboard loads

#### 2.2 Statistics cards
- Verify stat cards show numbers (engagements, findings, critical count)
- Note values for comparison after scan
- ✅/❌ Stat cards render with numbers

#### 2.3 Security rating widget
- Verify security rating/score widget visible
- ✅/❌ Security rating widget present

#### 2.4 Chart renders
- Verify at least one chart/graph renders (not loading spinner)
- ✅/❌ Chart renders

#### 2.5 Navigation sidebar
- Verify all nav links: Dashboard, Engagements, Findings, Analytics, Assets, Reports, Rules, Collaboration, Monitoring, System, Settings
- Click each, verify no 404
- ✅/❌ All nav links present and navigable
- `browser-use-direct screenshot dashboard`

### SECTION 3 — ENGAGEMENTS: CREATE

Navigate to http://localhost:3000/engagements

#### 3.1 Engagements list loads
- ✅/❌ Engagements list loads

#### 3.2 Standard engagement
- Click "New Engagement" or "Create Engagement"
- Fill in:
  - Target URL: https://vulnbank.org/
  - Authorization: "Testing authorization confirmed"
  - Scan Type: URL
  - Aggressiveness: Default
  - Agent Mode: ON
  - Scan Mode: Agent
- Click Create/Submit
- Verify engagement appears with status "created" or "recon"
- Note the engagement ID
- ✅/❌ Standard engagement created successfully

#### 3.3 Natural Language tab
- Click "New Engagement" → "Natural Language" tab
- Type: "Scan https://vulnbank.org/ for SQL injection and XSS. No authentication needed. Focus on parameter injection."
- Click "Parse Intent"
- Verify preview card shows target URL, vulnerability priorities, intent summary
- ✅/❌ Natural language tab exists
- ✅/❌ Parse Intent returns preview card
- ✅/❌ Preview shows correct target and summary
- Close without creating (to avoid duplicate)

### SECTION 4 — ENGAGEMENT DETAIL

Click into the engagement from 3.2.

#### 4.1 Detail page loads
- Verify URL: /engagements/[id]
- Verify: status badge, target URL, scan type, phase indicator
- ✅/❌ Engagement detail page loads

#### 4.2 Live status updates
- Watch status badge for 60s
- Verify updates from "created" → "recon" without page reload
- ✅/❌ Status updates in real-time

#### 4.3 Agent Reasoning Feed
- During "scanning", find "AI Agent Decisions" or "Agent Reasoning" section
- Verify tool selections with reasoning text and LLM/DETERMINISTIC badges
- ✅/❌ Agent reasoning feed visible during scan

#### 4.4 Timeline
- Find Timeline or Activities section
- Verify timestamped events appear
- ✅/❌ Timeline shows events

#### 4.5 Stop button
- Verify "Stop" button visible during scan (do NOT click)
- ✅/❌ Stop button present while scanning

#### 4.6 Attack Paths tab
- Find "Attack Paths" or "Attack Graph" section on the detail page
- Verify it shows risk-scored paths (if any findings exist)
- Click to expand/highlight a path
- ✅/❌ Attack paths tab visible
- ✅/❌ Attack paths show chain relationships

#### 4.7 Wait for completion
- Wait for "complete" status (up to 30 min)
- If "failed", note error and continue
- ✅/❌ Engagement reaches complete/failed status
- `browser-use-direct screenshot engagement-complete`

#### 4.8 Rescan button
- Verify "Rescan" button appears after completion
- Click it and verify a new engagement is created for the same target
- ✅/❌ Rescan button present after completion
- ✅/❌ Rescan creates new engagement

#### 4.9 Explainability
- Find "AI Explanation" or "Explainability" section/button
- Click it — verify LLM-generated plain-English explanation
- ✅/❌ Engagement explainability works

### SECTION 5 — FINDINGS

Navigate to http://localhost:3000/findings

#### 5.1 Findings list loads
- Verify findings from engagement appear
- Note total count and severity breakdown
- ✅/❌ Findings list loads with data
- `browser-use-direct screenshot findings-list`

#### 5.2 Severity filter
- Click "Critical" filter, verify only Critical shown. Clear filter.
- ✅/❌ Severity filter works

#### 5.3 Engagement filter
- Filter by engagement from 3.2, verify only its findings shown
- ✅/❌ Engagement filter works

#### 5.4 Finding detail page
- Click any finding, verify URL: /findings/[id]
- Verify: severity badge, type label, endpoint, source tool
- ✅/❌ Finding detail page loads

#### 5.5 Evidence tab
- Find Evidence tab, verify request/response/payload content
- ✅/❌ Evidence tab renders content

#### 5.6 Classification
- Verify CVSS score, OWASP category, CWE ID shown
- ✅/❌ Classification data displayed

#### 5.7 Repro steps
- Verify repro_steps displayed as numbered list (or "No reproduction steps recorded")
- ✅/❌ Repro steps section present

#### 5.8 PoC tab (if HIGH/CRITICAL finding)
- Find HIGH/CRITICAL finding, look for "Proof of Concept" tab
- Verify LLM-generated PoC fields (curl_command, manual_steps, etc.)
- Verify copy buttons work
- If poc_generated is null: click "Generate PoC" button
- ✅/❌ PoC tab exists on HIGH/CRITICAL finding
- ✅/❌ PoC content populated
- ✅/❌ Generate PoC button works

#### 5.9 Developer Fix tab
- On same HIGH/CRITICAL finding, click "Developer Fix" tab
- Verify Before/After code blocks with red/green tints
- If remediation_fix is null: verify "Generate Fix" button
- ✅/❌ Developer Fix tab shows before/after code
- ✅/❌ Generate Fix button exists

#### 5.10 Verify finding
- Click "Verify" button, verify badge changes to "Verified"
- ✅/❌ Finding verification works

#### 5.11 AI Explain
- Click "Explain with AI", verify LLM explanation loads (5-10s)
- ✅/❌ AI explain generates explanation

#### 5.12 Chain Exploits
- On a HIGH/CRITICAL finding that is part of a chain, look for "Chain Exploits" or "Exploit Chaining" section
- Verify it shows chained vulnerabilities with risk scores
- If a chain exploit script exists, verify it's displayed
- ✅/❌ Chain exploits visualization present

#### 5.13 False positive
- On LOW/INFO finding, click "Mark as False Positive"
- Verify status changes
- ✅/❌ False positive marking works

### SECTION 6 — REPORTS

Navigate to http://localhost:3000/reports

#### 6.1 Reports list
- Verify report for completed engagement appears
- ✅/❌ Report appears in list

#### 6.2 LLM report view
- Click report, verify: Executive Summary, Risk Level badge, findings count table
- ✅/❌ LLM report view loads
- ✅/❌ Executive summary non-empty and specific
- `browser-use-direct screenshot llm-report`

#### 6.3 Report download
- Find download button (PDF or JSON), click it
- Verify download starts or new tab opens
- ✅/❌ Report download works

#### 6.4 Manual report generation
- Find "Generate Report" or "Regenerate" button, click it
- Verify loading state or success toast
- ✅/❌ Manual report generation works

#### 6.5 Compliance page
- Navigate to /reports/compliance
- Verify compliance framework options (OWASP, PCI DSS, SOC 2)
- ✅/❌ Compliance reports page loads

#### 6.6 Generate compliance report
- Select OWASP Top 10, click Generate
- Verify compliance report created with OWASP category mappings
- ✅/❌ OWASP compliance report generated

#### 6.7 Bug Bounty page
- Navigate to /reports/bugbounty
- Verify platform selector: HackerOne, Bugcrowd, Intigriti, YesWeHack
- Select HackerOne, select completed engagement, click Generate
- Verify HackerOne-formatted markdown produced
- ✅/❌ Bug bounty report page loads
- ✅/❌ HackerOne report generated

#### 6.8 Email report
- Find "Email Report" button, click it
- Enter email if prompted, verify success
- ✅/❌ Email report button exists and triggers

#### 6.9 Full audit report
- Navigate to reports, look for "Generate Full Report" or "Full Security Audit" option
- Click it — verify the audit report is generated with all findings, security score, and SBOM
- ✅/❌ Full audit report generation works

#### 6.10 Compliance Posture page
- Navigate to /reports/compliance or find Compliance Posture section
- Verify posture scores (0-100) for frameworks: OWASP, PCI DSS, SOC 2, NIST, HIPAA, ISO 27001
- Verify score trend indicator (improving/declining)
- ✅/❌ Compliance posture page loads with framework scores
- ✅/❌ Posture trend indicators visible

#### 6.11 Scheduled reports
- Navigate to Settings → Scheduled Reports (or Reports → Scheduled)
- Verify any scheduled report schedules appear
- Note: tested in Settings section for creation

### SECTION 7 — ANALYTICS

Navigate to http://localhost:3000/analytics

#### 7.1 Analytics page loads
- ✅/❌ Analytics page loads

#### 7.2 Charts render
- Verify 2+ charts render with data (engagement findings, severity breakdown)
- ✅/❌ Charts render with data

#### 7.3 Vulnerability trends
- Look for time-series chart of findings over time
- ✅/❌ Vulnerability trend chart present

#### 7.4 Tool performance
- Find per-tool stats (execution times, success rates)
- ✅/❌ Tool performance data visible

### SECTION 8 — ASSETS

Navigate to http://localhost:3000/assets

#### 8.1 Assets page loads
- ✅/❌ Assets page loads

#### 8.2 Discovered assets listed
- Verify assets from completed engagement appear
- ✅/❌ Assets populated from scan

#### 8.3 Asset detail
- Click asset, verify associated findings and metadata
- ✅/❌ Asset detail with findings works

### SECTION 9 — RULES

Navigate to http://localhost:3000/rules

#### 9.1 Rules page loads
- ✅/❌ Rules page loads

#### 9.2 Create rule manually
- Click "New Rule" → "Manual" mode
- Name: "Test SQLi Pattern", Severity: HIGH, YAML: at least one `pattern:` entry
- Click Create, verify rule in list
- ✅/❌ Manual rule creation works

#### 9.3 AI rule generation
- Click "New Rule" → "AI" mode
- Prompt: "Detect SQL injection patterns in URL query parameters with classic payloads like ' OR 1=1"
- Click Generate, verify LLM returns filled-in YAML
- ✅/❌ AI rule generation produces valid YAML

#### 9.4 Edit rule
- Edit rule from 9.2, change severity to MEDIUM, save
- Verify list shows MEDIUM
- ✅/❌ Rule edit works

#### 9.5 Delete rule
- Delete test rule from 9.2, verify it disappears
- ✅/❌ Rule deletion works

### SECTION 10 — MONITORING

Navigate to http://localhost:3000/monitoring

#### 10.1 Monitoring page loads
- ✅/❌ Monitoring page loads

#### 10.2 Target profile visible
- Verify target from Section 3 appears with last scan date, total scans
- ✅/❌ Target profile card visible

#### 10.3 Diff summary
- Click target or "View Diff"
- Verify: new findings, fixed findings, regressed, persistent counts
- ✅/❌ Diff summary data loads

#### 10.4 Target intelligence
- Verify: best_tools, noisy_tools, confirmed_finding_types shown
- ✅/❌ Target intelligence data populated

### SECTION 11 — SETTINGS

Navigate to http://localhost:3000/settings

#### 11.1 Settings page loads
- ✅/❌ Settings page loads
- `browser-use-direct screenshot settings`

#### 11.2 LLM API key field
- Find OpenRouter API Key field, verify masked key shown if configured
- ✅/❌ LLM API key field present

#### 11.3 Model selector
- Find LLM model dropdown, verify options (gpt-4o-mini, claude, etc.)
- ✅/❌ Model selector works

#### 11.4 AI feature toggles
- Toggle LLM Review Enabled off → save → on → save
- Verify toast confirmation
- ✅/❌ AI feature toggles save correctly

#### 11.5 Webhook creation
- Find Webhooks section, click "Add Webhook"
- URL: https://webhook.site/test
- Events: "finding.critical"
- Save, verify webhook in list
- ✅/❌ Webhook creation works

#### 11.6 Delete webhook
- Delete test webhook, verify it disappears
- ✅/❌ Webhook deletion works

#### 11.7 Scheduled scans
- Find "Scheduled Scans", click "Add Schedule"
- Target: http://testphp.vulnweb.com
- Frequency: Weekly
- Aggressiveness: Default
- Save, verify next_run_at date
- ✅/❌ Scheduled scan creation works

#### 11.8 Delete scheduled scan
- Delete schedule, verify disappears
- ✅/❌ Scheduled scan deletion works

### SECTION 12 — SYSTEM HEALTH

Navigate to http://localhost:3000/system

#### 12.1 System health page loads
- ✅/❌ System health page loads
- `browser-use-direct screenshot system-health`

#### 12.2 Infrastructure health
- Verify Database, Worker, Redis all green/healthy
- ✅/❌ Database healthy
- ✅/❌ Worker healthy
- ✅/❌ Redis healthy

#### 12.3 Circuit breaker panel
- Find Circuit Breakers section, verify tools listed with circuit state
- ✅/❌ Circuit breaker panel present

#### 12.4 LLM usage stats
- Find LLM Usage section, verify token counts, cost, model name
- ✅/❌ LLM usage stats visible

#### 12.5 Agent decisions panel
- Find Agent Decisions section
- Verify: total decisions, LLM vs fallback ratio, cost per engagement
- Verify last 10 decisions table populated
- ✅/❌ Agent decisions panel populated

#### 12.6 Tool performance metrics
- Find tool performance section
- Verify per-tool rows: tool name, avg duration, success rate
- ✅/❌ Tool performance metrics present

#### 12.7 Threat enrichment status
- Find enrichment or NVD/EPSS status section
- ✅/❌ Enrichment status visible

### SECTION 13 — ADVANCED FEATURES

Return to completed engagement from Section 3.

#### 13.1 Swarm mode scan
- Click "New Engagement" → Standard tab
- Target: http://testphp.vulnweb.com
- Scan Mode: Swarm (if option exists)
- Create, verify detail page shows parallel agent columns
- ✅/❌ Swarm mode option exists
- ✅/❌ Swarm engagement shows specialist agents

#### 13.2 Repository scan
- Click "New Engagement", Scan Type: Repository
- Target: https://github.com/vulnbank/vulnbank.git
- Create, verify recon starts and processes repo scan
- ✅/❌ Repository scan type works
- ✅/❌ Repo scan reaches scanning phase

#### 13.3 Bug Bounty mode
- Click "New Engagement", Scan Type: URL
- Enable "Bug Bounty Mode" toggle if exists, Agent Mode: ON
- Create
- ✅/❌ Bug bounty mode toggle exists
- ✅/❌ Engagement created in bug bounty mode

### SECTION 14 — API SMOKE TEST

Test endpoints directly (navigate or check response):

#### 14.1 OpenAPI spec
- `/api/openapi` → 200 with JSON/YAML schema
- ✅/❌ OpenAPI spec accessible

#### 14.2 Dashboard stats API
- `/api/dashboard/stats` → JSON with engagement/finding counts
- ✅/❌ Dashboard stats API returns data

#### 14.3 Analytics API
- `/api/analytics` → JSON
- ✅/❌ Analytics API returns data

#### 14.4 System health API
- `/api/system/health` → JSON with database, worker, redis health
- ✅/❌ System health API returns data

#### 14.5 Tool performance API
- `/api/tools/performance` → per-tool metrics JSON
- ✅/❌ Tool performance API returns data

#### 14.6 Security rating API
- `/api/security-rating` → score/rating JSON
- ✅/❌ Security rating API returns data

#### 14.7 Engagement API
- `/api/engagements` → list of engagements with status
- `/api/engagement/[id]` → single engagement detail
- `/api/engagement/[id]/activities` → activity feed
- `/api/engagement/[id]/timeline` → timeline events
- `/api/engagement/[id]/attack-paths` → attack graph paths
- `/api/engagement/[id]/findings` → engagement-scoped findings
- ✅/❌ Engagements list API returns data
- ✅/❌ Engagement detail API returns data
- ✅/❌ Activities API returns events
- ✅/❌ Timeline API returns events
- ✅/❌ Attack paths API returns graph data
- ✅/❌ Engagement findings API returns scoped findings

#### 14.8 Findings API
- `/api/findings` → all findings with filters
- `/api/findings/[id]` → single finding detail
- `/api/findings/[id]/verify` → verify/cancel verification
- `/api/ai/explain` → AI explanation for a finding
- ✅/❌ Findings list API supports severity/engagement filters
- ✅/❌ Finding detail API returns evidence + classification
- ✅/❌ Finding verify API changes verified status
- ✅/❌ AI explain API returns explanation text

#### 14.9 Reports API
- `/api/reports` → list of reports
- `/api/reports/[id]` → single report detail
- `/api/reports/[id]/download` → download as PDF/JSON
- `/api/reports/generate` → trigger manual report generation
- `/api/reports/email` → email a report
- `/api/reports/compliance` → compliance report list
- `/api/reports/compliance/[id]` → single compliance report
- `/api/compliance/posture` → compliance posture scores
- ✅/❌ Reports list API returns data
- ✅/❌ Report download API triggers download
- ✅/❌ Report generate API triggers generation
- ✅/❌ Email report API sends (or validates)
- ✅/❌ Compliance reports API returns reports
- ✅/❌ Compliance posture API returns scores

#### 14.10 System & Monitoring APIs
- `/api/health/db` → database health check
- `/api/health/worker` → worker health check
- `/api/system/agent-stats` → agent decision metrics
- `/api/system/circuit-breaker` → circuit breaker states
- `/api/system/enrichment` → threat enrichment status
- `/api/system/llm-usage` → LLM token/cost usage
- `/api/monitoring/diff/[id]` → scan diff data
- ✅/❌ DB health API returns healthy status
- ✅/❌ Worker health API returns status
- ✅/❌ Agent stats API returns decision metrics
- ✅/❌ Circuit breaker API returns tool states
- ✅/❌ Enrichment API returns status
- ✅/❌ LLM usage API returns token/cost data
- ✅/❌ Monitoring diff API returns diff data

#### 14.11 Settings & Rules APIs
- `/api/settings` → get/update settings
- `/api/rules` → list/create rules
- `/api/rules/[id]` → get/update/delete rule
- `/api/webhooks` → list/create webhooks
- `/api/ai/generate-rule` → AI rule generation
- ✅/❌ Settings API returns configuration
- ✅/❌ Rules CRUD API works (create/read/update/delete)
- ✅/❌ Webhooks API lists webhooks
- ✅/❌ AI generate-rule API produces YAML

#### 14.12 Auth APIs
- `/api/auth/signup` → create account
- `/api/auth/forgot-password` → request reset
- `/api/auth/reset-password` → complete reset
- `/api/auth/verify-email` → verify email address
- ✅/❌ Signup API creates user (or returns appropriate error)
- ✅/❌ Forgot password API sends reset email (or validates)
- ✅/❌ Reset password API completes (or validates)
- ✅/❌ Email verification API works (or validates)

### FINAL CHECKLIST SUMMARY

Print the complete checklist in this exact format:

```
AUTHENTICATION
  ✅/❌ Sign-in page renders
  ✅/❌ Invalid credentials rejected
  ✅/❌ Valid sign-in works
  ✅/❌ Session persists across refresh
  ✅/❌ Signup page renders
  ✅/❌ Forgot password page accessible

DASHBOARD
  ✅/❌ Dashboard loads
  ✅/❌ Stat cards render with numbers
  ✅/❌ Security rating widget present
  ✅/❌ Chart renders
  ✅/❌ All nav links present and navigable

ENGAGEMENTS
  ✅/❌ Engagements list loads
  ✅/❌ Standard engagement created successfully
  ✅/❌ Natural language tab exists
  ✅/❌ Parse Intent returns preview card
  ✅/❌ Preview shows correct target and summary
  ✅/❌ Engagement detail page loads
  ✅/❌ Status updates in real-time
  ✅/❌ Agent reasoning feed visible during scan
  ✅/❌ Timeline shows events
  ✅/❌ Stop button present while scanning
  ✅/❌ Attack paths tab visible
  ✅/❌ Attack paths show chain relationships
  ✅/❌ Engagement reaches complete status
  ✅/❌ Rescan button present after completion
  ✅/❌ Rescan creates new engagement
  ✅/❌ Engagement explainability works

FINDINGS
  ✅/❌ Findings list loads with data
  ✅/❌ Severity filter works
  ✅/❌ Engagement filter works
  ✅/❌ Finding detail page loads
  ✅/❌ Evidence tab renders content
  ✅/❌ Classification data displayed
  ✅/❌ Repro steps section present
  ✅/❌ PoC tab exists on HIGH/CRITICAL finding
  ✅/❌ PoC content populated
  ✅/❌ Generate PoC button works when not generated
  ✅/❌ Developer Fix tab shows before/after code
  ✅/❌ Generate Fix button exists when not generated
  ✅/❌ Finding verification works
  ✅/❌ AI explain generates explanation
  ✅/❌ Chain exploits visualization present
  ✅/❌ False positive marking works

REPORTS
  ✅/❌ Report appears in list after scan completion
  ✅/❌ LLM report view loads
  ✅/❌ Executive summary text is non-empty
  ✅/❌ Report download works
  ✅/❌ Manual report generation works
  ✅/❌ Compliance reports page loads
  ✅/❌ OWASP compliance report generated
  ✅/❌ Bug bounty report page loads
  ✅/❌ HackerOne report generated
  ✅/❌ Email report button exists and triggers
  ✅/❌ Full audit report generation works
  ✅/❌ Compliance posture page loads with framework scores
  ✅/❌ Posture trend indicators visible
  ✅/❌ Scheduled reports section present

ANALYTICS
  ✅/❌ Analytics page loads
  ✅/❌ Charts render with data
  ✅/❌ Vulnerability trend chart present
  ✅/❌ Tool performance data visible

ASSETS
  ✅/❌ Assets page loads
  ✅/❌ Assets populated from scan
  ✅/❌ Asset detail with findings works

RULES
  ✅/❌ Rules page loads
  ✅/❌ Manual rule creation works
  ✅/❌ AI rule generation produces valid YAML
  ✅/❌ Rule edit works
  ✅/❌ Rule deletion works

MONITORING
  ✅/❌ Monitoring page loads
  ✅/❌ Target profile card visible
  ✅/❌ Diff summary data loads
  ✅/❌ Target intelligence data populated

SETTINGS
  ✅/❌ Settings page loads
  ✅/❌ LLM API key field present
  ✅/❌ Model selector works
  ✅/❌ AI feature toggles save correctly
  ✅/❌ Webhook creation works
  ✅/❌ Webhook deletion works
  ✅/❌ Scheduled scan creation works
  ✅/❌ Scheduled scan deletion works

SYSTEM HEALTH
  ✅/❌ System health page loads
  ✅/❌ Database healthy
  ✅/❌ Worker healthy
  ✅/❌ Redis healthy
  ✅/❌ Circuit breaker panel present
  ✅/❌ LLM usage stats visible
  ✅/❌ Agent decisions panel populated
  ✅/❌ Tool performance metrics present
  ✅/❌ Enrichment status visible

ADVANCED FEATURES
  ✅/❌ Swarm mode option exists
  ✅/❌ Swarm engagement created and shows specialist agents
  ✅/❌ Repository scan type works
  ✅/❌ Repo scan reaches scanning phase
  ✅/❌ Bug bounty mode toggle exists
  ✅/❌ Engagement created in bug bounty mode

API ROUTES
  ✅/❌ OpenAPI spec accessible
  ✅/❌ Dashboard stats API returns data
  ✅/❌ Analytics API returns data
  ✅/❌ System health API returns data
  ✅/❌ Tool performance API returns data
  ✅/❌ Security rating API returns data
  ✅/❌ Engagements list API returns data
  ✅/❌ Engagement detail API returns data
  ✅/❌ Activities API returns events
  ✅/❌ Timeline API returns events
  ✅/❌ Attack paths API returns graph data
  ✅/❌ Engagement findings API returns scoped findings
  ✅/❌ Findings list API supports severity/engagement filters
  ✅/❌ Finding detail API returns evidence + classification
  ✅/❌ Finding verify API changes verified status
  ✅/❌ AI explain API returns explanation text
  ✅/❌ Reports list API returns data
  ✅/❌ Report download API triggers download
  ✅/❌ Report generate API triggers generation
  ✅/❌ Email report API sends (or validates)
  ✅/❌ Compliance reports API returns reports
  ✅/❌ Compliance posture API returns scores
  ✅/❌ DB health API returns healthy status
  ✅/❌ Worker health API returns status
  ✅/❌ Agent stats API returns decision metrics
  ✅/❌ Circuit breaker API returns tool states
  ✅/❌ Enrichment API returns status
  ✅/❌ LLM usage API returns token/cost data
  ✅/❌ Monitoring diff API returns diff data
  ✅/❌ Settings API returns configuration
  ✅/❌ Rules CRUD API works (create/read/update/delete)
  ✅/❌ Webhooks API lists webhooks
  ✅/❌ AI generate-rule API produces YAML
  ✅/❌ Signup API creates user (or returns appropriate error)
  ✅/❌ Forgot password API sends reset email (or validates)
  ✅/❌ Reset password API completes (or validates)
  ✅/❌ Email verification API works (or validates)

TOTAL: X/115 passed
```

### IMPORTANT NOTES
1. Start the system: `./start-argus.sh` (stops existing, restarts clean)
2. Stop the system: `./stop-argus.sh`
3. Run automated pipeline test: `cd argus-workers && source venv/bin/activate && pytest tests/near_infinite/test_e2e_full.py -v --timeout=600`
4. The scan must reach "complete" before testing Sections 5-8
5. Check `/system` for Worker health before Section 3
6. PoC/DevFix tabs only populate for HIGH/CRITICAL with confidence ≥ 0.75
7. Monitoring populates after scan completes AND report step finishes
8. Screenshots mandatory after: Section 2, 4.6, 5, 6.2, 11, 12
