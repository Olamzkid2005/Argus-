# CortexAI Architecture Analysis & Rebuild Blueprint

## 1. System Overview

**Problem Solved:** CortexAI is an autonomous AI-powered penetration testing orchestrator that conducts security assessments like a senior security consultant. Unlike traditional tools that require manual operation, CortexAI reasons about objectives, orchestrates tools, explains decisions, and continuously improves its approach.

**Main Components:**
- **AI Agent Core** - Azure OpenAI-powered reasoning engine
- **Plugin System** - Extensible tool architecture with dynamic loading
- **Project Management** - SQLite-based engagement tracking with scope management
- **Tool Registry** - Central orchestration system for all capabilities
- **Audit System** - Comprehensive logging and evidence collection

**Key Differentiator:** This is an autonomous agent, not a workflow tool. You give it objectives ("assess this target"), not step-by-step instructions.

---

## 2. Execution Flow

```
User Input → AI Agent → Tool Selection → Tool Execution → Result Analysis → Evidence Storage → Next Action Planning
     ↓
Project Context (SQLite DB) ← Scope Rules ← Vulnerability Tracking ← HTTP Evidence
```

**Detailed Flow:**
1. **User provides high-level objective** ("Run security assessment on example.com")
2. **AI Agent analyzes context** using dynamic system prompt with project state
3. **Agent selects appropriate tools** from registry based on objective
4. **Tools execute** (web requests, content discovery, vulnerability scanning)
5. **Results are analyzed** and classified (OWASP mapping, severity rating)
6. **Evidence is stored** in project database with full HTTP request/response
7. **Agent plans next steps** based on findings and continues autonomously
8. **Comprehensive audit trail** maintained in separate terminal window

---

## 3. Key Components

### Core Agent (agent.js)
- **Azure OpenAI Integration** - GPT-4 powered reasoning
- **Dynamic System Prompt** - Context-aware prompts with project state
- **Tool Orchestration** - Manages tool calling and result processing
- **Terminal Formatting** - Rich markdown output with security-specific highlighting
- **Conversation Loop** - Handles multi-turn interactions with tool calling

### Plugin System
- **PluginLoader** - Scans and loads plugins from filesystem
- **Plugin Manifest** - JSON-based plugin definitions with tool declarations
- **Dynamic Registration** - Tools auto-register at startup without core changes
- **Tool Categories** - Web, filesystem, command execution, analysis, encoding

### Project Management Engine
- **ProjectManager** - SQLite database per engagement
- **ScopeManager** - URL/CIDR/regex-based scope enforcement
- **IssueManager** - OWASP-classified vulnerability tracking
- **Evidence Storage** - Immutable HTTP request/response chains
- **Site Mapping** - Hierarchical asset discovery and organization

### Tool Registry
- **Central Orchestration** - Maps tool names to handlers
- **OpenAI Function Calling** - Converts tools to function calling format
- **Handler Abstraction** - Unified interface for all tool types
- **Statistics Tracking** - Tool usage and performance metrics

---

## 4. Tool Integration Pattern

**Clean Pattern:**
```
Tool Definition (OpenAI Format) → Handler Function → Registry → AI Agent
```

**Tool Lifecycle:**
1. **Plugin declares tools** in plugin.json manifest
2. **Plugin exports init()** function that registers tools with registry
3. **Registry stores** tool definitions and handler functions
4. **AI Agent receives** tool list in OpenAI function calling format
5. **Tool execution** routed through registry to appropriate handler
6. **Results returned** in standardized JSON format

**Example Tool Structure:**
```javascript
// Tool Definition
{
  type: "function",
  function: {
    name: "web_request",
    description: "Make HTTP requests for security testing",
    parameters: { /* OpenAI schema */ }
  }
}

// Handler Function
async function webRequestHandler(args) {
  // Execute tool logic
  return JSON.stringify({ success: true, data: result });
}

// Registration
toolRegistry.register(toolDefinition, webRequestHandler);
```

---

## 5. Decision Logic

**Hybrid AI + Rule-Based System:**

**AI-Driven Decisions:**
- Tool selection based on context and objectives
- Vulnerability severity assessment
- Next step planning and strategy adaptation
- Error recovery and alternative approaches

**Rule-Based Components:**
- Scope enforcement (URL/CIDR matching)
- OWASP classification mapping
- Evidence storage requirements
- Security header analysis

**Decision Flow:**
1. **Context Analysis** - Current project state, previous findings, scope rules
2. **Objective Decomposition** - Break high-level goals into actionable steps
3. **Tool Selection** - Choose appropriate tools based on current phase
4. **Execution Monitoring** - Adapt strategy based on tool results
5. **Evidence Classification** - Automatically categorize and store findings

---

## 6. Data Flow & Memory

**Project-Centric Architecture:**
```
Project Database (SQLite)
├── Sites & Assets (discovered URLs, status codes, content types)
├── Vulnerabilities (OWASP-classified findings with severity)
├── HTTP Evidence (full request/response pairs)
├── Scope Rules (include/exclude patterns)
└── Scan History (audit trail of all activities)
```

**Memory Management:**
- **Conversation History** - Maintained in-memory for context
- **Project State** - Persisted in SQLite database
- **Tool Results** - Cached during conversation, stored as evidence
- **Scope Context** - Loaded at startup, enforced during execution

**State Tracking:**
- Current project loaded in memory
- Active scope rules applied to all requests
- Vulnerability findings automatically logged
- Site map built incrementally during discovery

---

## 7. Limitations

**Critical Issues:**
- **Single-threaded execution** - No parallel tool execution
- **Memory leaks** - Conversation history grows unbounded
- **No rate limiting** - Can overwhelm targets
- **Limited error recovery** - Tool failures can break flow
- **Azure OpenAI dependency** - No fallback providers

**Architectural Weaknesses:**
- **Monolithic agent.js** - 87k lines, hard to maintain
- **Plugin coupling** - Core tools mixed with plugin system
- **Database per project** - No multi-user support
- **No authentication** - Direct database access
- **Limited scalability** - Single process, single user

**Production Concerns:**
- **No input validation** - SQL injection risks in project names
- **Hardcoded paths** - ~/.cortexai directory assumptions
- **No backup strategy** - Project data loss risk
- **Terminal dependency** - Requires interactive shell
- **No API interface** - CLI-only operation

---

## 8. Rebuild Blueprint

### Minimal MVP Architecture

**Core Services:**
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   API Gateway   │    │  Agent Engine   │    │ Tool Executor   │
│                 │    │                 │    │                 │
│ - Authentication│    │ - LLM Interface │    │ - Plugin System │
│ - Rate Limiting │    │ - Context Mgmt  │    │ - Tool Registry │
│ - Request Queue │    │ - Decision Logic│    │ - Result Parser │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │ Data Layer      │
                    │                 │
                    │ - Projects DB   │
                    │ - Evidence Store│
                    │ - Audit Logs    │
                    └─────────────────┘
```

### Essential Modules to Build

**1. Agent Orchestrator**
```python
class AgentOrchestrator:
    def __init__(self, llm_client, tool_registry):
        self.llm = llm_client
        self.tools = tool_registry
        self.context = ConversationContext()
    
    async def process_objective(self, objective, project_context):
        # Build dynamic prompt with project state
        # Call LLM with tool definitions
        # Execute selected tools
        # Store results and plan next steps
        pass
```

**2. Tool Registry**
```python
class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.handlers = {}
    
    def register(self, tool_def, handler):
        # Store OpenAI function calling definition
        # Map to handler function
        pass
    
    def execute(self, tool_name, args):
        # Route to appropriate handler
        # Return standardized result
        pass
```

**3. Project Manager**
```python
class ProjectManager:
    def __init__(self, db_connection):
        self.db = db_connection
    
    async def create_project(self, name, config):
        # Create project database
        # Initialize scope rules
        # Set up evidence storage
        pass
    
    async def log_finding(self, vulnerability):
        # Store vulnerability with OWASP mapping
        # Save HTTP evidence
        # Update project statistics
        pass
```

**4. Plugin System**
```python
class PluginLoader:
    def __init__(self, tool_registry):
        self.registry = tool_registry
    
    async def load_plugins(self, plugin_dir):
        # Scan for plugin.json manifests
        # Import plugin modules
        # Register tools with registry
        pass
```

### Clean Execution Pipeline

**Security Assessment Pipeline:**
```python
async def security_assessment_pipeline(target_url, project_id):
    # Phase 1: Reconnaissance
    await content_discovery(target_url)
    await technology_fingerprinting(target_url)
    await javascript_analysis(target_url)
    
    # Phase 2: Vulnerability Scanning
    await owasp_top10_scan(discovered_assets)
    await custom_payload_testing(input_fields)
    
    # Phase 3: Evidence Collection
    await store_http_evidence(all_requests)
    await classify_vulnerabilities(findings)
    
    # Phase 4: Reporting
    await generate_report(project_id)
    return assessment_summary
```

**Tool Execution Pattern:**
```python
async def execute_tool_chain(tools, context):
    results = []
    for tool_name, args in tools:
        # Execute tool
        result = await tool_registry.execute(tool_name, args)
        
        # Store evidence
        await evidence_store.save(result)
        
        # Update context for next tool
        context.update(result)
        results.append(result)
    
    return results
```

---

## 9. Keep vs Ignore

### KEEP (Valuable Patterns)

**Core Architecture:**
- ✅ **Plugin-based tool system** - Extensible and maintainable
- ✅ **Project-centric data model** - Proper engagement tracking
- ✅ **SQLite for evidence storage** - Immutable audit trails
- ✅ **OpenAI function calling integration** - Clean LLM tool interface
- ✅ **Scope management system** - Essential for security testing
- ✅ **OWASP vulnerability classification** - Industry standard
- ✅ **HTTP evidence collection** - Critical for proof of concept

**Tool Patterns:**
- ✅ **Web request abstraction** - Handles security testing requirements
- ✅ **Content discovery logic** - Automated asset enumeration
- ✅ **JavaScript analysis** - API endpoint extraction
- ✅ **Vulnerability logging** - Structured finding storage

### IGNORE (Over-engineered/Problematic)

**Implementation Issues:**
- ❌ **Monolithic agent.js** - Split into focused modules
- ❌ **Terminal-only interface** - Build API-first
- ❌ **Hardcoded Azure OpenAI** - Abstract LLM providers
- ❌ **Single-user design** - Plan for multi-tenancy
- ❌ **No input validation** - Security vulnerability
- ❌ **Synchronous execution** - Implement async/parallel processing
- ❌ **Memory management** - Conversation history grows unbounded

**Unnecessary Complexity:**
- ❌ **Terminal formatting system** - Focus on API responses
- ❌ **Puppeteer fallback logic** - Use headless browser consistently
- ❌ **Multiple database viewers** - Provide web interface
- ❌ **Complex logging system** - Use structured logging library

---

## 10. Integration Strategy

**For SaaS Integration:**

1. **Extract Core Logic** - Agent orchestration, tool registry, project management
2. **Build API Layer** - REST/GraphQL interface for web frontend
3. **Add Authentication** - Multi-tenant user management
4. **Implement Queuing** - Background job processing for long-running scans
5. **Add Monitoring** - Real-time scan progress and results
6. **Scale Database** - PostgreSQL for multi-user, Redis for caching
7. **Containerize** - Docker for deployment and scaling

**Key Reusable Components:**
- Tool registry pattern for extensibility
- Project-based data model for engagement tracking
- OWASP vulnerability classification system
- HTTP evidence collection and storage
- Scope management for security testing
- Plugin architecture for tool integration

This architecture provides a solid foundation for building an autonomous security testing platform while avoiding the implementation pitfalls of the original codebase.