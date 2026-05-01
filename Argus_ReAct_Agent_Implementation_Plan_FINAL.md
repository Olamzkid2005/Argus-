**ARGUS**

ReAct Agent Integration

LLM-Driven Dynamic Pipeline — 30-Step Implementation Plan (with Risk Mitigations)

 **Goal** | Replace the deterministic tool pipeline with a fully LLM-driven ReAct agent loop: recon runs, the LLM reads results and selects scan tools dynamically, and the LLM presides over all findings to produce the final report. |

 **Total Steps** | 30 steps across 5 phases | ~4–6 weeks of focused development |

 **Model** | gpt-4o-mini (or claude-haiku-4-5 via OpenRouter) for tool selection and synthesis. Change via LLM\_AGENT\_MODEL env var. |

# **Architecture: Before vs After**

## **Current (Deterministic Pipeline)**

 run\_recon task

└─ execute\_recon\_tools() ← flat sequential: httpx, katana, ffuf, amass, ...

└─ always all 10 tools, fixed order, no feedback

run\_scan task

└─ execute\_scan\_tools() ← flat sequential: nuclei, dalfox, sqlmap, ...

└─ always all 7 tools, no awareness of recon results

run\_analysis task

└─ IntelligenceEngine.evaluate() ← rule-based heuristics, no LLM

run\_report task

└─ ComplianceReportGenerator ← Jinja2 templates only |

## **Target (LLM ReAct Agent Loop)**

 run\_recon task

└─ execute\_recon\_tools() ← unchanged (recon is always full surface scan)

└─ returns ReconContext: endpoints, ports, tech stack, subdomains

run\_scan task ← receives ReconContext

└─ CoordinatorAgent.run\_phase('scan', recon\_context)

└─ ReActAgent loop:

1\. LLM receives: recon findings summary + all MCP tool schemas

2\. LLM returns JSON: { tool, arguments, reasoning }

3\. ToolRunner executes the tool

4\. Result fed back to LLM as observation

5\. LLM decides: call another tool OR stop

(fallback to deterministic if LLM unavailable)

run\_analysis task

└─ IntelligenceEngine.evaluate() (existing scoring/FP detection)

└─ LLM synthesizes scored findings into executive narrative

run\_report task

└─ LLM generates: exec summary, technical findings, remediation plan

└─ Streamed to frontend via SSE / Redis pub-sub |

# **Phase Overview**

 **Phase** | **Description** | **Steps** | **Key Output** | **Est. Time** |

 1 — Foundation | Dataclass, prompts, JSON schema, fallback logic | 1–6 | LLM tool selector working in isolation | 4–5 days |

 2 — Agent Wiring | ReActAgent uses LLM, Orchestrator uses Agent | 7–12 | Dynamic scan driven by recon results | 5–6 days |

 3 — LLM Synthesis | LLM presides over findings and writes reports | 13–18 | AI-generated report streamed to user | 4–5 days |

 4 — Safety & Budget | Scope guard, cost cap, token limits, decision log | 19–24 | Safe, bounded, observable agent | 3–4 days |

 5 — Frontend & E2E | UI wiring, integration + E2E tests, health metrics | 25–30 | Fully tested, production-ready system | 4–5 days |

**PHASE 1 — Foundation: LLM Tool Selector (Steps 1–6)**

 **1** | **Add ReconContext Dataclass** | Foundation | ~2 hrs |

 **File** | argus-workers/models/recon\_context.py (create new) |

Create a dataclass that distills raw recon findings into a structured summary the LLM can reason about without being overwhelmed by thousands of raw lines.

### **What to create**

 from dataclasses import dataclass, field

from typing import List, Dict

@dataclass

class ReconContext:

target\_url: str

live\_endpoints: List\[str\] # from httpx

subdomains: List\[str\] # from amass, subfinder

open\_ports: List\[Dict\] # from naabu: \[{port, service}\]

tech\_stack: List\[str\] # from whatweb: \['WordPress 6.4', 'PHP 8.1'\]

crawled\_paths: List\[str\] # from katana: top 50 paths

parameter\_bearing\_urls: List\[str\] # URLs with ?param= from gau/wayback

auth\_endpoints: List\[str\] # /login, /api/auth, /oauth

api\_endpoints: List\[str\] # /api/\*, /v1/\*, /graphql

findings\_count: int # total raw recon findings

has\_login\_page: bool

has\_api: bool

has\_file\_upload: bool

def to\_llm\_summary(self) -> str:

'''Compact text summary for LLM context window.'''

\# max 800 tokens, truncate lists to top 20 items

... |

### **to\_llm\_summary() must produce**

A plain-text block under 800 tokens covering: target, live endpoints count, subdomains found, open ports and services, tech stack, whether auth/API/upload endpoints were detected, and top 10 most interesting crawled paths.

### **Test**

 **Test File** | argus-workers/tests/test\_recon\_context.py |

-   test\_to\_llm\_summary\_stays\_under\_token\_limit — use tiktoken or len()/4 estimate
-   test\_auth\_detection\_from\_crawled\_paths — verify /login triggers has\_login\_page=True
-   test\_api\_detection — verify /api/v1/users triggers has\_api=True

 **2** | **Build \_summarize\_recon\_findings() Helper** | Foundation | ~1.5 hrs |

 **File** | argus-workers/orchestrator\_pkg/recon.py (add at bottom) |

Write a function that converts the raw list of findings returned by execute\_recon\_tools() into a populated ReconContext object.

### **What to add**

 def summarize\_recon\_findings(target: str, findings: List\[Dict\]) -> ReconContext:

'''

Convert raw recon findings list into ReconContext.

Called at end of execute\_recon\_tools() before returning.

'''

live\_endpoints = \[f\['endpoint'\] for f in findings if f.get('source\_tool') == 'httpx'\]

subdomains = \[f\['endpoint'\] for f in findings if f.get('source\_tool') in ('amass','subfinder')\]

open\_ports = \[f.get('evidence',{}) for f in findings if f.get('source\_tool') == 'naabu'\]

tech\_stack = \[t for f in findings if f.get('source\_tool') == 'whatweb'

for t in f.get('evidence',{}).get('technologies', \[\])\]

crawled\_paths = \[f\['endpoint'\] for f in findings if f.get('source\_tool') in ('katana','ffuf')\]\[:50\]

param\_urls = \[f\['endpoint'\] for f in findings

if '?' in f.get('endpoint','') and f.get('source\_tool') in ('gau','waybackurls')\]

auth\_kw = ('login','signin','auth','oauth','sso','password','reset')

api\_kw = ('/api/','/v1/','/v2/','/graphql','/rest/')

upload\_kw = ('upload','file','attach','media')

all\_paths = \[f.get('endpoint','').lower() for f in findings\]

return ReconContext(

target\_url=target,

live\_endpoints=list(set(live\_endpoints))\[:100\],

subdomains=list(set(subdomains))\[:50\],

open\_ports=open\_ports\[:20\],

tech\_stack=list(set(tech\_stack))\[:20\],

crawled\_paths=crawled\_paths,

parameter\_bearing\_urls=param\_urls\[:30\],

auth\_endpoints=\[p for p in crawled\_paths if any(k in p.lower() for k in auth\_kw)\],

api\_endpoints=\[p for p in crawled\_paths if any(k in p.lower() for k in api\_kw)\],

findings\_count=len(findings),

has\_login\_page=any(any(k in p for k in auth\_kw) for p in all\_paths),

has\_api=any(any(k in p for k in api\_kw) for p in all\_paths),

has\_file\_upload=any(any(k in p for k in upload\_kw) for p in all\_paths),

) |

### **Also modify execute\_recon\_tools() return value**

Add 2 lines at the end of execute\_recon\_tools() so it returns a tuple: (findings, recon\_context). The Orchestrator.run\_recon() call will be updated in Step 9 to handle the tuple.

### **Test**

-   test\_summarize\_empty\_findings — empty list returns zero-count ReconContext
-   test\_summarize\_detects\_auth — findings with /login endpoint sets has\_login\_page
-   test\_summarize\_counts\_subdomains — amass findings correctly populate subdomains

 **3** | **Build the LLM Tool Selection Prompt** | Foundation | ~2 hrs |

 **File** | argus-workers/agent\_loop.py (add method to ReActAgent) |

This is the most critical design step. Write the system and user prompts that tell the LLM: here is what recon found, here are the available tools and their schemas, pick the best next tool to call.

### **System prompt structure**

 TOOL\_SELECTION\_SYSTEM\_PROMPT = '''

You are an expert penetration tester deciding which security tool to run next.

You have already completed reconnaissance. Your job is to select ONE tool from

the provided list that will yield the highest-value findings given what was discovered.

Rules:

\- Return ONLY valid JSON. No markdown. No explanation outside the JSON.

\- Select tools in logical order: parameter discovery before injection testing.

\- Do NOT re-run a tool already in tried\_tools.

\- If you believe no further tools are needed, set 'tool' to '\_\_done\_\_'.

\- Set 'arguments' to match the tool's parameter schema exactly.

\- Put your reasoning in the 'reasoning' field (max 100 words).

Response format (JSON only):

{

"tool": "<tool\_name>",

"arguments": { "target": "<url>", ... },

"reasoning": "<why this tool, why these args>"

}

''' |

### **User prompt structure**

 def \_build\_tool\_selection\_prompt(self, recon\_context: str,

available\_tools: List\[Dict\],

tried\_tools: set,

observation\_history: str) -> str:

tools\_json = json.dumps(\[

{

'name': t\['name'\],

'description': t\['description'\],

'parameters': \[{'name': p.name, 'type': p.type, 'required': p.required,

'description': p.description}

for p in t.get('parameters', \[\])\]

}

for t in available\_tools

if t\['name'\] not in tried\_tools

\], indent=2)

return f'''

\=== RECON SUMMARY ===

{recon\_context}

\=== ALREADY RAN ===

{', '.join(tried\_tools) or 'none'}

\=== OBSERVATIONS SO FAR ===

{observation\_history or 'No observations yet.'}

\=== AVAILABLE TOOLS ===

{tools\_json}

Select the single best tool to run next. Return JSON only.

''' |

### **Test**

-   test\_prompt\_excludes\_tried\_tools — tried\_tools set removes tools from the available list
-   test\_prompt\_under\_4k\_tokens — ensure combined prompt stays under 4096 tokens for cheap models
-   test\_prompt\_format\_valid\_json\_structure — prompt instructs JSON-only response correctly

 **4** | **Replace plan\_next\_action() with LLM-Backed Version** | Foundation | ~3 hrs |

 **File** | argus-workers/agent\_loop.py (replace ReActAgent.plan\_next\_action method) |

This is the core wiring step. Replace the iterator loop inside plan\_next\_action() with an actual LLM call. The LLM\_client.chat\_sync() method is already available and working.

### **New plan\_next\_action() signature**

 def plan\_next\_action(

self,

task: str,

context: str,

tried\_tools: set = None,

recon\_context: 'ReconContext' = None, # NEW

llm\_client: 'LLMClient' = None, # NEW

) -> Optional\[AgentAction\]: |

### **LLM branch logic**

 if llm\_client and llm\_client.is\_available() and recon\_context:

try:

messages = \[

{'role': 'system', 'content': TOOL\_SELECTION\_SYSTEM\_PROMPT},

{'role': 'user', 'content': self.\_build\_tool\_selection\_prompt(

recon\_context.to\_llm\_summary(),

self.registry.list\_tools(),

tried\_tools,

context

)}

\]

raw = llm\_client.chat\_sync(

messages,

temperature=0.1, # low temp for deterministic tool selection

max\_tokens=300,

response\_format={'type': 'json\_object'},

)

decision = json.loads(raw)

tool\_name = decision.get('tool')

if tool\_name == '\_\_done\_\_':

return None

if not self.registry.get\_tool(tool\_name):

logger.warning(f'LLM selected unknown tool {tool\_name}, falling back')

raise ValueError(f'Unknown tool: {tool\_name}')

return AgentAction(

tool=tool\_name,

arguments=decision.get('arguments', {}),

reasoning=decision.get('reasoning', ''),

)

except Exception as e:

logger.warning(f'LLM tool selection failed: {e}. Using deterministic fallback.')

\# FALL THROUGH to deterministic iterator below |

### **Fallback (below LLM branch, unchanged)**

The existing deterministic PHASE\_TOOLS iterator remains verbatim below the LLM branch. If LLM is unavailable or raises any exception, execution falls through to it automatically. This ensures zero regression.

### **Test**

-   test\_plan\_next\_action\_with\_mock\_llm — mock chat\_sync returns valid JSON, verify correct AgentAction returned
-   test\_plan\_next\_action\_llm\_done — LLM returns \_\_done\_\_, verify None returned
-   test\_plan\_next\_action\_llm\_unknown\_tool — LLM returns unregistered tool, verify deterministic fallback used
-   test\_plan\_next\_action\_llm\_exception — chat\_sync raises exception, verify deterministic fallback used
-   test\_plan\_next\_action\_no\_llm — llm\_client=None, verify deterministic path used directly

 **5** | **Add LLM Agent Constants and Config** | Foundation | ~1 hr |

 **File** | argus-workers/config/constants.py (add new constants block) |

Add all configuration constants needed by the LLM agent system. Everything should be overridable via environment variable or Redis setting.

### **Constants to add**

 \# ── LLM Agent (ReAct Loop) ──────────────────────────────────────────────

LLM\_AGENT\_ENABLED = True

LLM\_AGENT\_MODEL = os.getenv('LLM\_AGENT\_MODEL', 'gpt-4o-mini')

LLM\_AGENT\_MAX\_ITERATIONS = int(os.getenv('LLM\_AGENT\_MAX\_ITERATIONS', '10'))

LLM\_AGENT\_TEMPERATURE = float(os.getenv('LLM\_AGENT\_TEMPERATURE', '0.1'))

LLM\_AGENT\_MAX\_TOKENS\_PLAN = 300 # tokens per tool selection call

LLM\_AGENT\_MAX\_TOKENS\_SYNTH = 2000 # tokens for findings synthesis

LLM\_AGENT\_MAX\_TOKENS\_REPORT= 3000 # tokens for final report

LLM\_AGENT\_CONTEXT\_MAX\_TOKENS = 3500 # max context passed to LLM

\# ── LLM Agent Cost Guard ────────────────────────────────────────────────

LLM\_AGENT\_MAX\_COST\_USD = float(os.getenv('LLM\_AGENT\_MAX\_COST\_USD', '0.25'))

\# gpt-4o-mini: $0.000150/1K input, $0.000600/1K output (as of 2025)

LLM\_AGENT\_COST\_PER\_1K\_INPUT = 0.000150

LLM\_AGENT\_COST\_PER\_1K\_OUTPUT = 0.000600

\# ── Mitigations: Timeout & Retry ───────────────────────────────────────

LLM\_AGENT\_TIMEOUT\_SECONDS = int(os.getenv('LLM\_AGENT\_TIMEOUT\_SECONDS', '30'))

LLM\_AGENT\_MAX\_RETRIES = int(os.getenv('LLM\_AGENT\_MAX\_RETRIES', '2'))

LLM\_AGENT\_ZERO\_FINDING\_STOP = int(os.getenv('LLM\_AGENT\_ZERO\_FINDING\_STOP', '2')) |

 **Note** | import os at the top of constants.py if not already present. These can also be managed via Redis settings:\*:llm\_agent\_\* keys consistent with the existing load\_llm\_setting() pattern. |

### **Test**

-   test\_constants\_defaults\_exist — import all new constants, verify they are the correct type
-   test\_env\_override — set LLM\_AGENT\_MODEL env var, verify constant picks it up

 **6** | **Add LLM Agent Decision Log to Database** | Foundation | ~2 hrs |

 **File 1** | argus-platform/db/migrations/add\_agent\_decision\_log.sql (new migration) |

 **File 2** | argus-workers/database/repositories/agent\_decision\_repository.py (new file) |

Every LLM tool selection decision must be persisted so it's auditable and visible in the frontend. This is also the data source for debugging when the agent makes bad choices.

### **Migration SQL**

 CREATE TABLE agent\_decisions (

id UUID PRIMARY KEY DEFAULT uuid\_generate\_v4(),

engagement\_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,

phase VARCHAR(50) NOT NULL, -- 'scan', 'recon'

iteration INTEGER NOT NULL,

tool\_selected VARCHAR(100) NOT NULL,

arguments JSONB NOT NULL DEFAULT '{}',

reasoning TEXT,

was\_fallback BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE if LLM failed and deterministic ran

input\_tokens INTEGER,

output\_tokens INTEGER,

cost\_usd DECIMAL(8, 6),

created\_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT\_TIMESTAMP

);

CREATE INDEX idx\_agent\_decisions\_engagement ON agent\_decisions(engagement\_id, created\_at); |

### **AgentDecisionRepository**

 class AgentDecisionRepository:

def log\_decision(self, engagement\_id, phase, iteration,

tool\_selected, arguments, reasoning,

was\_fallback, input\_tokens, output\_tokens) -> str:

'''Insert one row into agent\_decisions. Returns decision id.'''

cost = self.\_estimate\_cost(input\_tokens, output\_tokens)

...

def get\_decisions(self, engagement\_id) -> List\[Dict\]:

'''Fetch all decisions for an engagement, ordered by created\_at.'''

...

def get\_total\_cost(self, engagement\_id) -> float:

'''Sum cost\_usd for all decisions in this engagement.'''

... |

Call AgentDecisionRepository.log\_decision() inside ReActAgent.run() after every iteration, whether LLM or fallback. Pass was\_fallback=True when the deterministic path ran.

### **Test**

-   test\_log\_decision\_inserts\_row — mock DB, verify INSERT called with correct params
-   test\_get\_total\_cost — multiple rows, verify sum is correct
-   test\_was\_fallback\_logged\_on\_exception — simulate LLM exception, verify was\_fallback=True in DB

**PHASE 2 — Agent Wiring: Dynamic Scan Pipeline (Steps 7–12)**

 **7** | **Inject LLMClient into ReActAgent** | Wiring | ~1.5 hrs |

 **File** | argus-workers/agent\_loop.py (modify ReActAgent.\_\_init\_\_ and create\_phase\_agent) |

The ReActAgent needs to hold a reference to LLMClient and AgentDecisionRepository so it can make and log decisions. Both are optional to preserve backward compatibility.

### **Update ReActAgent.\_\_init\_\_()**

 def \_\_init\_\_(self, registry: ToolRegistry, max\_iterations: int = 20,

llm\_client: 'LLMClient' = None,

decision\_repo: 'AgentDecisionRepository' = None,

engagement\_id: str = None,

phase: str = 'scan'):

self.registry = registry

self.max\_iterations = max\_iterations

self.llm\_client = llm\_client

self.decision\_repo = decision\_repo

self.engagement\_id = engagement\_id

self.phase = phase

self.history: List\[Dict\] = \[\]

self.\_phase = phase |

### **Update create\_phase\_agent() signature**

 def create\_phase\_agent(

phase: str,

tool\_runner=None,

engagement\_id: str = None,

llm\_client=None, # NEW

decision\_repo=None, # NEW

) -> ReActAgent:

registry = ToolRegistry()

\# ... existing tool registration ...

agent = ReActAgent(

registry,

llm\_client=llm\_client,

decision\_repo=decision\_repo,

engagement\_id=engagement\_id,

phase=phase,

)

agent.set\_phase(phase)

return agent |

### **Update ReActAgent.run() to log decisions**

After each call to plan\_next\_action(), call self.decision\_repo.log\_decision() if decision\_repo is set. Capture input/output token counts from the LLMClient response if available.

### **Test**

-   test\_agent\_created\_with\_llm\_client — verify llm\_client stored as instance var
-   test\_agent\_logs\_each\_decision — mock decision\_repo, run 3 iterations, verify log\_decision called 3x

 **8** | **Add run\_with\_agent() Method to Orchestrator** | Wiring | ~3 hrs |

 **File** | argus-workers/orchestrator\_pkg/orchestrator.py (add new method) |

Add a new method run\_scan\_with\_agent() that creates a CoordinatorAgent, injects the ReconContext, and runs the LLM-driven scan phase. This replaces the call to execute\_scan\_tools() when LLM is available.

### **New method**

 def run\_scan\_with\_agent(self, targets: List\[str\],

recon\_context: 'ReconContext',

aggressiveness: str = DEFAULT\_AGGRESSIVENESS) -> List\[Dict\]:

'''

Run the scan phase using the LLM ReAct agent.

Falls back to execute\_scan\_tools() if agent raises.

'''

from agent\_loop import create\_phase\_agent, CoordinatorAgent

from database.repositories.agent\_decision\_repository import AgentDecisionRepository

db\_conn = os.getenv('DATABASE\_URL')

decision\_repo = AgentDecisionRepository(db\_conn) if db\_conn else None

all\_findings = \[\]

for target in targets:

try:

agent = create\_phase\_agent(

phase='scan',

tool\_runner=self.tool\_runner,

engagement\_id=self.engagement\_id,

llm\_client=self.llm\_client,

decision\_repo=decision\_repo,

)

\# Build initial context from ReconContext

initial\_context = {'recon\_context': recon\_context, 'target': target}

emit\_thinking(self.engagement\_id,

f'LLM agent selecting scan tools for {target}...')

results = agent.run(

task=f'scan: {target}',

initial\_context=initial\_context,

recon\_context=recon\_context, # passed through to plan\_next\_action

)

\# Normalize AgentResults back to finding dicts

for r in results:

if r.success and r.output:

parsed = self.parser.parse(r.tool, r.output)

for p in parsed:

norm = self.\_normalize\_finding(p, r.tool)

if norm:

all\_findings.append(norm)

except Exception as e:

logger.warning(f'Agent scan failed for {target}: {e}. Falling back.')

fallback = execute\_scan\_tools(self, \[target\], {}, aggressiveness)

all\_findings.extend(fallback)

return all\_findings |

### **Test**

-   test\_run\_scan\_with\_agent\_calls\_llm — mock agent.run, verify it is called with recon\_context
-   test\_run\_scan\_with\_agent\_fallback — agent.run raises, verify execute\_scan\_tools called
-   test\_run\_scan\_with\_agent\_normalizes\_findings — agent returns mock stdout, verify parser called

 **9** | **Update Orchestrator.run\_recon() to Return ReconContext** | Wiring | ~1.5 hrs |

 **File** | argus-workers/orchestrator\_pkg/orchestrator.py (modify run\_recon method) |

run\_recon() currently returns a plain dict with findings\_count. It needs to also return the ReconContext so the scan phase can use it.

### **Modified run\_recon() return**

 \# After: findings = execute\_recon\_tools(self, target, ...)

\# execute\_recon\_tools now returns (findings\_list, recon\_context) tuple

findings, recon\_context = execute\_recon\_tools(self, target, ...)

\# Save recon context to Redis for cross-task access

import json

redis\_client = get\_redis() # existing redis connection in orchestrator

redis\_client.setex(

f'recon\_context:{self.engagement\_id}',

3600, # TTL 1 hour

json.dumps({

'target\_url': recon\_context.target\_url,

'live\_endpoints': recon\_context.live\_endpoints,

'subdomains': recon\_context.subdomains,

'open\_ports': recon\_context.open\_ports,

'tech\_stack': recon\_context.tech\_stack,

'crawled\_paths': recon\_context.crawled\_paths,

'parameter\_bearing\_urls': recon\_context.parameter\_bearing\_urls,

'auth\_endpoints': recon\_context.auth\_endpoints,

'api\_endpoints': recon\_context.api\_endpoints,

'findings\_count': recon\_context.findings\_count,

'has\_login\_page': recon\_context.has\_login\_page,

'has\_api': recon\_context.has\_api,

'has\_file\_upload': recon\_context.has\_file\_upload,

})

)

return {

'phase': 'recon',

'status': 'completed',

'findings\_count': len(findings),

'next\_state': 'scanning',

'recon\_context': recon\_context, # NEW

'trace\_id': get\_trace\_id(),

} |

 **Why Redis?** | Celery tasks are separate processes. The recon context must cross the process boundary between tasks.recon.run\_recon and tasks.scan.run\_scan via Redis, not memory. |

### **Test**

-   test\_run\_recon\_saves\_context\_to\_redis — mock redis, verify setex called with correct key and TTL
-   test\_run\_recon\_returns\_recon\_context — mock execute\_recon\_tools, verify context in return dict

 **10** | **Update Orchestrator.run\_scan() to Use Agent** | Wiring | ~2 hrs |

 **File** | argus-workers/orchestrator\_pkg/orchestrator.py (modify run\_scan method) |

Modify run\_scan() to: load ReconContext from Redis, check if LLM is available, and dispatch to run\_scan\_with\_agent() or execute\_scan\_tools() accordingly.

### **Updated run\_scan() dispatch logic**

 def run\_scan(self, job: Dict) -> Dict:

...

\# Load recon context from Redis

recon\_context = None

try:

raw = redis\_client.get(f'recon\_context:{self.engagement\_id}')

if raw:

data = json.loads(raw)

recon\_context = ReconContext(\*\*data)

except Exception as e:

logger.warning(f'Could not load recon context from Redis: {e}')

\# Check agent mode feature flag

from llm\_client import load\_llm\_setting

agent\_mode\_enabled = load\_llm\_setting('llm\_agent\_mode\_enabled', 'true') == 'true'

\# Dispatch

if (agent\_mode\_enabled

and recon\_context

and self.llm\_client

and self.llm\_client.is\_available()):

emit\_thinking(self.engagement\_id, 'LLM agent mode active — analyzing recon results...')

findings = self.run\_scan\_with\_agent(targets, recon\_context, aggressiveness)

else:

logger.info('Running deterministic scan (agent mode off or LLM unavailable)')

findings = execute\_scan\_tools(self, targets, job.get('budget',{}), aggressiveness)

... |

### **Test**

-   test\_run\_scan\_uses\_agent\_when\_available — recon\_context in Redis + LLM available = run\_scan\_with\_agent called
-   test\_run\_scan\_uses\_deterministic\_no\_context — no Redis key = execute\_scan\_tools called
-   test\_run\_scan\_uses\_deterministic\_flag\_off — agent flag = false = execute\_scan\_tools called

 **11** | **Update ReActAgent.run() to Accept and Pass ReconContext** | Wiring | ~1.5 hrs |

 **File** | argus-workers/agent\_loop.py (modify ReActAgent.run method) |

The run() method needs to receive the ReconContext and pass it into every call to plan\_next\_action(), so the LLM has full context for every iteration.

### **Updated run() signature**

 def run(self, task: str,

initial\_context: Dict = None,

recon\_context: 'ReconContext' = None) -> List\[AgentResult\]:

self.history = \[\]

results = \[\]

tried\_tools = set()

self.add\_to\_history('system', f'Task: {task}')

for iteration in range(self.max\_iterations):

action = self.plan\_next\_action(

task,

self.get\_context(),

tried\_tools=tried\_tools,

recon\_context=recon\_context, # PASS THROUGH

llm\_client=self.llm\_client, # PASS THROUGH

)

if action is None:

break

tried\_tools.add(action.tool)

emit\_thinking(self.engagement\_id,

f'\[Iteration {iteration+1}\] LLM selected: {action.tool} — {action.reasoning\[:80\]}')

result = self.registry.call(action.tool, \*\*action.arguments)

results.append(result)

self.add\_to\_history('observation',

f'Tool {action.tool}: {"succeeded" if result.success else "failed"}')

if self.decision\_repo:

self.decision\_repo.log\_decision(

engagement\_id=self.engagement\_id,

phase=self.\_phase,

iteration=iteration,

tool\_selected=action.tool,

arguments=action.arguments,

reasoning=action.reasoning,

was\_fallback=False,

input\_tokens=None, # TODO Step 23

output\_tokens=None,

)

return results |

### **Test**

-   test\_run\_passes\_recon\_context\_to\_plan — spy on plan\_next\_action, verify recon\_context passed
-   test\_run\_respects\_max\_iterations — mock plan to always return action, verify loop stops at max
-   test\_run\_stops\_on\_none\_action — plan returns None on iteration 2, verify results has 1 entry

 **12** | **Wire ReconContext Through Celery Task Chain** | Wiring | ~2 hrs |

 **File** | argus-workers/tasks/recon.py and tasks/scan.py (update both task functions) |

The ReconContext travels recon → scan via Redis (set in Step 9). The scan task loads it from Redis. Both tasks need a helper to load/save via the same key pattern.

### **Add helpers to tasks/utils.py (create if not exists)**

 RECON\_CONTEXT\_KEY = 'recon\_context:{engagement\_id}'

RECON\_CONTEXT\_TTL = 3600 # 1 hour

def save\_recon\_context(engagement\_id: str, ctx: ReconContext, redis\_url: str):

r = redis.from\_url(redis\_url)

r.setex(RECON\_CONTEXT\_KEY.format(engagement\_id=engagement\_id),

RECON\_CONTEXT\_TTL,

json.dumps(dataclasses.asdict(ctx)))

def load\_recon\_context(engagement\_id: str, redis\_url: str) -> Optional\[ReconContext\]:

r = redis.from\_url(redis\_url)

raw = r.get(RECON\_CONTEXT\_KEY.format(engagement\_id=engagement\_id))

return ReconContext(\*\*json.loads(raw)) if raw else None |

### **In tasks/recon.py run\_recon()**

After orchestrator.run\_recon(job) returns, call save\_recon\_context(engagement\_id, result\['recon\_context'\], redis\_url) before enqueuing the scan task.

### **In tasks/scan.py run\_scan()**

At top of the task function, call load\_recon\_context(engagement\_id, redis\_url). Add it to the job dict as job\['recon\_context'\] so Orchestrator.run\_scan() can use it. The Orchestrator will also attempt to load from Redis directly (double-load is safe and idempotent).

### **Test**

-   test\_recon\_task\_saves\_context — mock Redis, run\_recon, verify save\_recon\_context called
-   test\_scan\_task\_loads\_context — mock Redis with stored context, verify load\_recon\_context called
-   test\_context\_not\_found\_gracefully — Redis returns None, verify scan proceeds in deterministic mode

**PHASE 3 — LLM Synthesis: Findings & Final Report (Steps 13–18)**

 **13** | **Build LLM Findings Synthesizer** | Synthesis | ~3 hrs |

 **File** | argus-workers/llm\_synthesizer.py (create new) |

Create a new class responsible for the LLM presiding over all scored findings. This is separate from IntelligenceEngine (which does rule-based scoring) — the LLM adds narrative reasoning on top of the already-scored data.

### **LLMSynthesizer class**

 class LLMSynthesizer:

SYNTHESIS\_SYSTEM\_PROMPT = '''

You are a senior penetration tester writing the analysis section of a security report.

You will receive a list of scored, de-duplicated findings from automated tools.

Your job is to:

1\. Identify attack chains (findings that compound each other)

2\. Prioritize findings by real-world exploitability, not just CVSS

3\. Write a 3-5 sentence executive summary in plain English

4\. List the top 5 most critical findings with your reasoning

5\. Note any false-positive candidates the analyst should verify

Return ONLY valid JSON matching the schema provided.

'''

def synthesize(self, scored\_findings: List\[Dict\],

attack\_paths: List\[Dict\],

recon\_context: ReconContext) -> Dict:

'''

Call LLM to synthesize findings into structured analysis.

Returns: {executive\_summary, priority\_findings, attack\_chains,

fp\_candidates, risk\_level, analyst\_notes}

'''

prompt = self.\_build\_synthesis\_prompt(

scored\_findings, attack\_paths, recon\_context)

raw = self.llm\_client.chat\_sync(

messages=\[

{'role': 'system', 'content': self.SYNTHESIS\_SYSTEM\_PROMPT},

{'role': 'user', 'content': prompt}

\],

temperature=0.3,

max\_tokens=LLM\_AGENT\_MAX\_TOKENS\_SYNTH,

response\_format={'type': 'json\_object'},

)

return json.loads(raw) |

### **JSON output schema**

 {

'executive\_summary': 'string (3-5 sentences)',

'risk\_level': 'critical|high|medium|low',

'priority\_findings': \[

{'finding\_id': '...', 'why\_critical': '...', 'real\_world\_impact': '...'}

\],

'attack\_chains': \[

{'chain\_description': '...', 'finding\_ids': \['...'\], 'combined\_risk': 'critical|high'}

\],

'fp\_candidates': \[

{'finding\_id': '...', 'reason': '...'}

\],

'analyst\_notes': 'string'

} |

### **Test**

-   test\_synthesize\_returns\_schema\_keys — mock LLM response, verify all required keys present
-   test\_synthesize\_handles\_empty\_findings — empty list, verify graceful JSON response
-   test\_synthesize\_llm\_error\_returns\_fallback — LLM raises, verify fallback dict returned

 **14** | **Integrate Synthesizer into run\_analysis()** | Synthesis | ~2 hrs |

 **File** | argus-workers/orchestrator\_pkg/orchestrator.py (modify run\_analysis) |

After IntelligenceEngine.evaluate() runs, call LLMSynthesizer.synthesize() and attach the result to the analysis output. Store the synthesis in the decision\_snapshots table.

### **Updated run\_analysis() tail**

 \# existing: evaluation = engine.evaluate(snapshot)

\# NEW: LLM synthesis pass

synthesis = {}

if self.llm\_client and self.llm\_client.is\_available():

try:

from llm\_synthesizer import LLMSynthesizer

recon\_context = load\_recon\_context(self.engagement\_id, redis\_url)

synthesizer = LLMSynthesizer(self.llm\_client)

synthesis = synthesizer.synthesize(

scored\_findings=evaluation.get('scored\_findings', \[\]),

attack\_paths=snapshot.get('attack\_graph', {}).get('paths', \[\]),

recon\_context=recon\_context,

)

emit\_thinking(self.engagement\_id,

f'LLM analysis: {synthesis.get("risk\_level","unknown")} risk — '

f'{synthesis.get("executive\_summary","")\[:100\]}...')

except Exception as e:

logger.warning(f'LLM synthesis failed (non-fatal): {e}')

return {

'phase': 'analyze',

'status': 'completed',

'actions': actions,

'scored\_findings': evaluation.get('scored\_findings', \[\]),

'reasoning': evaluation.get('reasoning', ''),

'synthesis': synthesis, # NEW

'next\_state': next\_state,

'trace\_id': get\_trace\_id(),

} |

### **Test**

-   test\_run\_analysis\_calls\_synthesizer — mock LLMSynthesizer, verify synthesize called with findings
-   test\_run\_analysis\_synthesis\_in\_return — verify 'synthesis' key in return dict
-   test\_run\_analysis\_synthesis\_failure\_nonfatal — synthesizer raises, verify analysis still completes

 **15** | **Build LLM Report Generator** | Synthesis | ~3 hrs |

 **File** | argus-workers/llm\_report\_generator.py (create new) |

Create a class that calls the LLM to write the final human-readable report: executive summary, technical findings with remediation steps, and CVSS-prioritized action items.

### **LLMReportGenerator class**

 class LLMReportGenerator:

REPORT\_SYSTEM\_PROMPT = '''

You are writing a professional penetration test report for a technical audience.

Structure your report with these sections:

1\. Executive Summary (non-technical, 2-3 paragraphs)

2\. Scope and Methodology

3\. Findings Summary Table (severity, finding name, affected endpoint)

4\. Detailed Findings (one entry per finding: description, evidence, impact, remediation)

5\. Remediation Roadmap (prioritized action items by severity)

6\. Conclusion

Return as structured JSON matching the schema provided.

Use professional security report language. Be specific about evidence.

'''

def generate\_report(self, synthesis: Dict,

scored\_findings: List\[Dict\],

engagement: Dict,

recon\_context: 'ReconContext') -> Dict:

...

def stream\_report(self, ...) -> Generator\[str, None, None\]:

'''Stream report generation token by token via SSE.'''

... |

### **Test**

-   test\_generate\_report\_returns\_all\_sections — mock LLM, verify 6 section keys in output
-   test\_generate\_report\_includes\_findings — findings in input appear in output
-   test\_generate\_report\_handles\_zero\_findings — clean report with no findings

 **16** | **Add Reports Table and Store LLM Report** | Synthesis | ~2 hrs |

 **File 1** | argus-platform/db/migrations/add\_reports\_table.sql |

 **File 2** | argus-workers/database/repositories/report\_repository.py |

### **Migration SQL**

 CREATE TABLE reports (

id UUID PRIMARY KEY DEFAULT uuid\_generate\_v4(),

engagement\_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,

generated\_by VARCHAR(50) NOT NULL DEFAULT 'llm', -- 'llm' or 'template'

executive\_summary TEXT,

full\_report\_json JSONB NOT NULL DEFAULT '{}',

risk\_level VARCHAR(20),

total\_findings INTEGER DEFAULT 0,

critical\_count INTEGER DEFAULT 0,

high\_count INTEGER DEFAULT 0,

medium\_count INTEGER DEFAULT 0,

low\_count INTEGER DEFAULT 0,

model\_used VARCHAR(100),

created\_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT\_TIMESTAMP

);

CREATE UNIQUE INDEX idx\_reports\_engagement ON reports(engagement\_id); |

### **Modify tasks/report.py generate\_report() task**

After ComplianceReportGenerator runs, call LLMReportGenerator.generate\_report(), then call ReportRepository.upsert\_report() to store it. Emit a 'report\_ready' WebSocket event with the engagement\_id.

### **Test**

-   test\_report\_saved\_to\_db — mock DB, run task, verify INSERT into reports
-   test\_report\_upserts\_on\_rerun — run twice, verify only one row (UPSERT)

 **17** | **Add /api/reports/\[id\] API Route on Frontend** | Synthesis | ~2 hrs |

 **File** | argus-platform/src/app/api/reports/\[id\]/route.ts (create new) |

Create a Next.js API route that serves the LLM-generated report for an engagement. Also update the existing reports page to fetch and render it.

### **Route handler**

 // GET /api/reports/\[id\]

export async function GET(req, { params }) {

const { id } = await params;

const { rows } = await pool.query(

\`SELECT \* FROM reports WHERE engagement\_id = $1 LIMIT 1\`, \[id\]

);

if (!rows.length) return NextResponse.json({ error: 'Not found' }, { status: 404 });

return NextResponse.json({ report: rows\[0\] });

} |

### **Update reports page**

In argus-platform/src/app/reports/page.tsx, add a section that fetches the LLM report and renders: executive\_summary as a card, risk\_level badge, findings\_count breakdown table, and a collapsible full\_report\_json viewer.

### **Test**

-   GET /api/reports/\[existing-id\] — returns 200 with report JSON
-   GET /api/reports/\[non-existent\] — returns 404
-   Frontend renders executive\_summary text and risk badge correctly

 **18** | **Stream Report Generation to Frontend via SSE** | Synthesis | ~3 hrs |

 **File 1** | argus-workers/streaming.py (add REPORT\_CHUNK event type) |

 **File 2** | argus-platform/src/app/api/ws/\[id\]/route.ts (update WebSocket handler) |

As the LLM generates the report, stream each token/sentence to the frontend so the user sees the report being written in real time rather than waiting for completion.

### **Add to StreamEventType enum**

 REPORT\_CHUNK = 'report\_chunk' # incremental report text

REPORT\_COMPLETE = 'report\_complete' # final report ready, includes summary |

### **In LLMReportGenerator**

Add a stream\_report() method that uses the streaming parameter of chat\_sync (if provider supports it) or falls back to emitting the full report as a single REPORT\_COMPLETE event. Call emit\_report\_chunk() for each token/sentence received.

### **In tasks/report.py**

Replace generate\_report() body with stream\_report() call. Each emitted chunk is published via WebSocketEventPublisher.publish\_event() with type REPORT\_CHUNK and payload {text, engagement\_id}.

### **Test**

-   test\_stream\_emits\_chunks — mock LLM streaming, verify multiple REPORT\_CHUNK events emitted
-   test\_stream\_fallback\_single\_chunk — non-streaming provider, verify REPORT\_COMPLETE emitted
-   Frontend: report section shows typing animation as chunks arrive

**PHASE 4 — Safety, Budget & Observability (Steps 19–24)**

 **19** | **Add Token Counting and Cost Tracking to LLMClient** | Safety | ~2 hrs |

 **File** | argus-workers/llm\_client.py (add token tracking to chat\_sync and chat) |

Modify LLMClient to return token usage alongside the response text, and accumulate cost per engagement. This feeds into the cost guard in Step 20.

### **Modified chat\_sync() return**

 \# Return a named tuple / dataclass instead of raw string

@dataclass

class LLMResponse:

text: str

input\_tokens: int = 0

output\_tokens: int = 0

cost\_usd: float = 0.0

\# In chat\_sync() success branch:

usage = response.usage # from OpenAI SDK

cost = (usage.prompt\_tokens / 1000 \* LLM\_AGENT\_COST\_PER\_1K\_INPUT +

usage.completion\_tokens / 1000 \* LLM\_AGENT\_COST\_PER\_1K\_OUTPUT)

return LLMResponse(

text=response.choices\[0\].message.content,

input\_tokens=usage.prompt\_tokens,

output\_tokens=usage.completion\_tokens,

cost\_usd=cost,

) |

 **Backward Compat** | All existing callers use .text attribute. Update all call sites in agent\_loop.py, llm\_synthesizer.py, and llm\_report\_generator.py to access response.text instead of treating the return value as a string directly. |

### **Test**

-   test\_chat\_sync\_returns\_lllm\_response — verify return is LLMResponse with text, tokens, cost
-   test\_cost\_calculation — 1000 input + 500 output tokens = expected USD amount

 **20** | **Add LLM Cost Guard to ReActAgent Loop** | Safety | ~2 hrs |

 **File** | argus-workers/agent\_loop.py (modify ReActAgent.run) |

Track cumulative LLM cost across iterations. If cost exceeds LLM\_AGENT\_MAX\_COST\_USD, abort the LLM loop and fall through to deterministic mode for remaining tools.

### **Cost tracking in run()**

 total\_cost\_usd = 0.0

for iteration in range(self.max\_iterations):

action = self.plan\_next\_action(...) # returns AgentAction + cost\_usd

total\_cost\_usd += action.cost\_usd if hasattr(action, 'cost\_usd') else 0

if total\_cost\_usd > LLM\_AGENT\_MAX\_COST\_USD:

logger.warning(

f'Cost guard: ${total\_cost\_usd:.4f} exceeds ${LLM\_AGENT\_MAX\_COST\_USD}. '

f'Switching to deterministic for remaining tools.'

)

emit\_thinking(self.engagement\_id,

f'LLM cost cap reached — completing scan with deterministic tools')

\# Run remaining untried tools deterministically

phase\_tools = self.PHASE\_TOOLS.get(self.\_phase, \[\])

for tool\_name in phase\_tools:

if tool\_name not in tried\_tools:

result = self.registry.call(tool\_name, target=initial\_target)

results.append(result)

break |

### **Test**

-   test\_cost\_guard\_triggers — mock LLMClient to return cost=999 USD on first call, verify deterministic fallback
-   test\_cost\_guard\_logs\_warning — verify logger.warning called when limit hit
-   test\_cost\_accumulates\_across\_iterations — 3 calls at $0.10 each with $0.25 limit, verify stops at iteration 3

 **21** | **Add Scope Validation Inside Agent Loop** | Safety | ~1.5 hrs |

 **File** | argus-workers/agent\_loop.py (modify ReActAgent.registry.call wrapper) |

Before executing any LLM-selected tool, validate that the target argument is within the engagement's authorized scope. This prevents the LLM from being tricked (via prompt injection in tool output) into scanning unauthorized targets.

### **Wrap registry.call() in Orchestrator**

 \# In run\_scan\_with\_agent(), wrap the ToolRegistry.call:

from tools.scope\_validator import ScopeValidator, ScopeViolationError

authorized\_scope = json.loads(engagement\_row\['authorized\_scope'\])

scope\_validator = ScopeValidator(self.engagement\_id, authorized\_scope)

original\_call = agent.registry.call

def scoped\_call(name, \*\*kwargs):

target = kwargs.get('target', '')

if target:

try:

scope\_validator.validate\_target(target)

except ScopeViolationError as e:

logger.warning(f'Scope violation blocked: {e}')

emit\_thinking(self.engagement\_id, f'Blocked: {target} is out of scope')

return AgentResult(tool=name, success=False,

error=f'Scope violation: {str(e)}')

return original\_call(name, \*\*kwargs)

agent.registry.call = scoped\_call |

### **Test**

-   test\_scope\_violation\_blocked — LLM selects tool with out-of-scope target, verify AgentResult(success=False)
-   test\_scope\_valid\_passes — in-scope target, verify original call executed
-   test\_scope\_validation\_logged — violation, verify emit\_thinking called with 'Blocked' message

 **22** | **Add Context Window Management** | Safety | ~2 hrs |

 **File** | argus-workers/agent\_loop.py (add to \_build\_tool\_selection\_prompt) |

As iterations accumulate, the observation history grows. Without trimming, it will exceed the LLM's context window and start failing or hallucinating. Add a windowed context builder that keeps the most recent and most relevant observations.

### **get\_context() update**

 def get\_context(self, max\_tokens: int = LLM\_AGENT\_CONTEXT\_MAX\_TOKENS) -> str:

'''Build context string. Trims history to stay under token budget.'''

\# Always keep: system message + last 5 observations

recent = self.history\[-5:\]

parts = \[f'\[{e\["role"\]}\]: {e\["content"\]}' for e in recent\]

context = chr(10).join(parts)

\# Rough token estimate: len/4

if len(context) / 4 > max\_tokens:

\# Hard-trim to last 2 observations if still over

parts = \[f'\[{e\["role"\]}\]: {e\["content"\]}' for e in self.history\[-2:\]\]

context = chr(10).join(parts)

return context |

### **Recon context trimming**

In ReconContext.to\_llm\_summary(), ensure lists are capped: live\_endpoints\[:20\], subdomains\[:15\], crawled\_paths\[:10\], parameter\_bearing\_urls\[:10\]. The total summary should never exceed 800 tokens (estimate: 3200 chars).

### **Test**

-   test\_context\_trimmed\_when\_over\_limit — add 20 history entries, verify get\_context returns <= max\_tokens estimate
-   test\_recon\_summary\_under\_800\_tokens — large ReconContext, verify to\_llm\_summary() is under 3200 chars

 **23** | **Publish Agent Decision Events to Frontend** | Safety | ~2 hrs |

 **File 1** | argus-workers/websocket\_events.py (add publish\_agent\_decision method) |

 **File 2** | argus-workers/agent\_loop.py (call publisher in run()) |

The frontend should be able to show in real-time which tool the LLM just chose and why. Add a new WebSocket event type and publish it on every agent decision.

### **Add to WebSocketEventPublisher**

 EVENT\_AGENT\_DECISION = 'agent\_decision'

def publish\_agent\_decision(self, engagement\_id: str, iteration: int,

tool: str, reasoning: str, was\_fallback: bool):

self.\_publish(engagement\_id, {

'type': self.EVENT\_AGENT\_DECISION,

'iteration': iteration,

'tool': tool,

'reasoning': reasoning,

'was\_fallback': was\_fallback,

}) |

### **In ReActAgent.run()**

After each action is determined and before registry.call(), if self.engagement\_id exists, publish the agent\_decision event. Import get\_websocket\_publisher lazily to avoid circular deps.

### **Test**

-   test\_agent\_decision\_event\_published — run 2 iterations, verify publish\_agent\_decision called twice
-   test\_fallback\_decision\_marked — LLM fails, fallback runs, verify was\_fallback=True in event

 **24** | **Add Agent Decision Viewer to System Health Page** | Safety | ~2 hrs |

 **File** | argus-platform/src/app/system/page.tsx (add agent decisions section) |

The System Health page already exists. Add a new section showing: total agent decisions made, LLM vs fallback ratio, total cost spent, and the last 10 decisions with their reasoning.

### **New API route**

 // GET /api/system/agent-stats

// Query: SELECT COUNT(\*), SUM(cost\_usd), SUM(CASE WHEN was\_fallback THEN 1 ELSE 0 END)

// FROM agent\_decisions WHERE created\_at > NOW() - INTERVAL '24 hours'

// Returns: { total\_decisions, total\_cost\_usd, fallback\_count, llm\_count } |

### **System health card content**

Render a card with: LLM Decisions (24h), Cost Spent (24h), Fallback Rate %. Below it, a table of recent decisions: timestamp, engagement\_id (truncated), tool\_selected, was\_fallback, cost\_usd, reasoning (first 80 chars).

### **Test**

-   GET /api/system/agent-stats returns correct counts
-   Frontend renders agent stats card without crashing on empty data

**PHASE 5 — Frontend, Integration Tests & End-to-End (Steps 25–30)**

 **25** | **Add Agent Mode Toggle to Engagement Creation** | Frontend | ~2 hrs |

 **File 1** | argus-platform/src/app/engagements/page.tsx (add toggle) |

 **File 2** | argus-platform/db/schema.sql (add column to engagements) |

Add an agent\_mode boolean column to engagements and a toggle in the creation form. When agent\_mode=false, the engagement always uses the deterministic pipeline regardless of LLM availability.

### **Schema change**

 ALTER TABLE engagements ADD COLUMN agent\_mode BOOLEAN NOT NULL DEFAULT TRUE;

\-- TRUE = LLM-driven agent loop (new default)

\-- FALSE = deterministic pipeline (legacy mode) |

### **Form addition**

In the engagement creation form, add a Switch component (Radix UI Switch already in deps) labeled 'AI Agent Mode' with a tooltip: 'Uses LLM to dynamically select scan tools based on recon results. Disable for fixed, reproducible scans.' Default: on.

### **Pass to worker**

Include agent\_mode in the job dict dispatched to tasks/recon.py. In Orchestrator.run\_scan(), check job.get('agent\_mode', True) alongside the LLM availability check before dispatching to run\_scan\_with\_agent().

### **Test**

-   test\_agent\_mode\_false\_uses\_deterministic — create engagement with agent\_mode=false, verify execute\_scan\_tools used
-   Frontend toggle saves agent\_mode to DB correctly

 **26** | **Live Agent Reasoning Feed in Engagement Detail Page** | Frontend | ~3 hrs |

 **File** | argus-platform/src/app/engagements/\[id\]/page.tsx (add agent feed section) |

During an active scan, show a real-time feed of LLM decisions: which tool was selected, why, and whether it was a fallback. This appears in the engagement detail page alongside the existing scanner activity log.

### **Component to build: AgentReasoningFeed**

 // Subscribes to WebSocket events of type 'agent\_decision'

// Renders a scrollable list:

// \[#3\] nuclei — 'High-value endpoints found on /api/v1, targeting for CVE scanning'

// \[#2\] arjun — 'Parameter-bearing URLs detected, discovering hidden params first'

// \[#1\] jwt\_tool — 'Auth endpoint /api/auth found, testing JWT security'

// Fallback decisions shown in grey with a tag: \[deterministic fallback\] |

### **WebSocket subscription**

Listen on the existing /api/ws/\[id\] endpoint that is already implemented. Filter incoming events for type === 'agent\_decision' and prepend to a React state array (max 50 entries). Use framer-motion for smooth entry animation. Show timestamp relative to scan start.

### **Test**

-   test\_agent\_feed\_renders\_decision — mock WebSocket message, verify decision appears in DOM
-   test\_agent\_feed\_marks\_fallback — was\_fallback=true event, verify grey styling applied
-   test\_agent\_feed\_max\_50\_entries — send 60 events, verify only 50 in state

 **27** | **Write Full Integration Test Suite for Agent Pipeline** | Testing | ~4 hrs |

 **File** | argus-workers/tests/test\_agent\_pipeline\_integration.py (new test file) |

Write end-to-end integration tests for the full agent pipeline with mocked LLM responses and mocked tool execution. These tests verify the complete flow without needing a live target or API key.

### **Test fixture: mock\_llm\_responses**

 MOCK\_SCAN\_DECISIONS = \[

\# Iteration 1

'{"tool": "arjun", "arguments": {"target": "http://test.local"}, "reasoning": "API found"}',

\# Iteration 2

'{"tool": "nuclei", "arguments": {"target": "http://test.local"}, "reasoning": "Scan endpoints"}',

\# Iteration 3 (done)

'{"tool": "\_\_done\_\_", "arguments": {}, "reasoning": "Sufficient coverage"}'

\] |

### **Required test cases**

-   test\_full\_agent\_scan\_calls\_llm\_selected\_tools — mock chat\_sync with MOCK\_SCAN\_DECISIONS, mock tool\_runner.run, verify arjun and nuclei called but not sqlmap (since LLM said done before it)
-   test\_full\_agent\_scan\_fallback\_on\_llm\_error — chat\_sync always raises, verify all PHASE\_TOOLS called deterministically
-   test\_full\_pipeline\_recon\_to\_report — mock entire chain: execute\_recon\_tools → ReconContext → LLM decisions → synthesis → report generation, verify final report contains executive\_summary
-   test\_agent\_respects\_budget — max\_iterations=2 constant, verify only 2 LLM calls made
-   test\_scope\_violation\_skips\_tool — LLM returns out-of-scope target, verify tool not executed, verify AgentResult(success=False)

 **28** | **Write Fallback and Regression Tests** | Testing | ~3 hrs |

 **File** | argus-workers/tests/test\_agent\_fallback\_regression.py (new test file) |

Verify that the system behaves identically to before this entire feature when agent mode is disabled or LLM is unavailable. No regression is acceptable on the deterministic path.

### **Required test cases**

-   test\_no\_llm\_key\_uses\_deterministic\_fully — set OPENAI\_API\_KEY='', run scan, verify execute\_scan\_tools called, verify no agent\_decision rows in DB
-   test\_agent\_mode\_false\_bypass\_all\_agent\_code — engagement.agent\_mode=False, verify LLMClient never instantiated for tool selection
-   test\_missing\_recon\_context\_falls\_through — Redis returns None for recon context, verify deterministic scan runs
-   test\_llm\_timeout\_falls\_through — chat\_sync raises httpx.TimeoutException, verify fallback within 1 second
-   test\_existing\_pipeline\_executor\_unchanged — import PipelineExecutor, run execute\_recon\_tools, verify returns same finding structure as before changes
-   test\_state\_machine\_transitions\_unchanged — run full scan with agent, verify state machine still goes created → recon → scanning → analyzing → reporting → complete

 **29** | **Live End-to-End Test Against Real Vulnerable Target** | Testing | ~4 hrs |

 **Target** | testphp.vulnweb.com (Acunetix legal test site) OR local DVWA Docker instance |

 **Prerequisite** | Real LLM API key configured in .env.local (OpenRouter sk-or-\* or OpenAI sk-\*) |

Run one complete engagement end-to-end with agent mode enabled. Observe and verify each phase manually against expected behavior.

### **Checklist**

1.  Start full stack: docker-compose up (postgres, redis, worker, platform)
2.  Create engagement: target=http://testphp.vulnweb.com, agent\_mode=ON, aggressiveness=default
3.  Observe recon phase complete — verify ReconContext saved in Redis (redis-cli GET recon\_context:{id})
4.  Observe scan phase — verify AgentReasoningFeed shows LLM decisions in UI
5.  Check agent\_decisions table — verify rows created with was\_fallback=FALSE for at least 1 iteration
6.  Verify LLM chose different tools than the full deterministic set (not all 7 scan tools)
7.  Observe analysis phase — verify synthesis.executive\_summary populated
8.  Observe report phase — verify report streams to frontend and REPORT\_COMPLETE event fires
9.  Check reports table — verify row with full\_report\_json and executive\_summary
10.  Check total cost — verify agent\_decisions.SUM(cost\_usd) < LLM\_AGENT\_MAX\_COST\_USD
11.  Run again with agent\_mode=OFF — verify identical findings structure, no agent\_decision rows
12.  Compare findings: agent mode vs deterministic — document any differences

### **DVWA local setup (if preferred over external target)**

 docker run --name dvwa -d -p 8080:80 vulnerables/web-dvwa

\# Wait for container to start, then:

\# Visit http://localhost:8080/setup.php and click 'Create / Reset Database'

\# Use http://localhost:8080 as the engagement target

\# DVWA has: SQL injection, XSS, CSRF, File Inclusion, Command Injection |

 **30** | **Final Hardening: Error Handling, Docs, and CI Updates** | Hardening | ~3 hrs |

 **Files** | Multiple — see checklist below |

Final cleanup pass before treating the feature as production-ready.

### **Checklist**

1.  Add LLM\_AGENT\_MODEL and LLM\_AGENT\_MAX\_COST\_USD to .env.example with comments
2.  Add new DB migrations to argus-platform/db/migrations/ README listing them in apply order
3.  Add 'llm\_agent\_mode\_enabled' Redis key to UI Settings page (Settings > AI Features toggle)
4.  Update FINAL-ARCHITECTURE.md: mark ReAct agent loop as IMPLEMENTED, update architecture diagram
5.  Update README.md: add Agent Mode section under Features with example expected output
6.  Update GitHub Actions CI: add test\_agent\_pipeline\_integration.py and test\_agent\_fallback\_regression.py to pytest run
7.  Add pytest markers: @pytest.mark.agent for all agent tests, @pytest.mark.llm\_required for tests needing real key
8.  Add SKIP condition: if not os.getenv('OPENAI\_API\_KEY'): pytest.skip('LLM key required') for live API tests
9.  Run full test suite: pytest argus-workers/tests/ -v -- verify all existing tests still pass
10.  Review agent\_decisions table for any data quality issues from E2E test run

 **Done** | The Argus ReAct agent loop is fully implemented: recon completes, LLM reads results, selects tools dynamically, presides over findings, and generates the final report. All existing functionality is preserved via fallback. |

# **Mitigations for Identified Risks & Gaps**

The following additional safeguards address potential issues identified during the design review. These are implemented alongside the 30-step plan.

## **1\. Mitigation: LLM Latency & Iteration Timeout**

 **Risk** | LLM calls may take >5–10 seconds, delaying scan completion. |

\*\*Solution:\*\* Add a per‑iteration timeout (default 30s). If the LLM does not respond within the timeout, the agent falls back to deterministic mode for the remaining tools.

 \# In ReActAgent.run()

import asyncio

try:

action = await asyncio.wait\_for(

self.plan\_next\_action\_async(...),

timeout=LLM\_AGENT\_TIMEOUT\_SECONDS

)

except asyncio.TimeoutError:

logger.warning(f'LLM iteration {iteration} timed out, falling back')

\# force deterministic fallback for this engagement

self.llm\_client = None # disable further LLM calls

action = self.\_deterministic\_plan(...) |

## **2\. Mitigation: Extend Cost Guard to ALL LLM Phases**

 **Risk** | The original plan only capped cost during the scan phase, leaving analysis and report generation unbounded. |

\*\*Solution:\*\* Wrap \`LLMSynthesizer.synthesize()\` and \`LLMReportGenerator.generate\_report()\` with the same cost tracker. If total engagement cost exceeds \`LLM\_AGENT\_MAX\_COST\_USD\`, skip LLM steps and use fallback templates.

 \# In run\_analysis() and generate\_report()

total\_cost = decision\_repo.get\_total\_cost(engagement\_id)

if total\_cost > LLM\_AGENT\_MAX\_COST\_USD:

logger.warning(f'Cost cap reached (${total\_cost}), using template analysis/report')

synthesis = {} # empty, IntelligenceEngine already ran

report = ComplianceReportGenerator().generate(...) # fallback to Jinja2

else:

synthesis = synthesizer.synthesize(...)

report = llm\_report\_generator.generate\_report(...) |

## **3\. Mitigation: Exponential Backoff for Transient LLM Errors**

 **Risk** | A network hiccup or rate limit error immediately triggers fallback, which may be overly aggressive. |

\*\*Solution:\*\* Retry failed LLM calls with exponential backoff (2 retries, delays 1s and 3s). Only after retries exhausted do we fall to deterministic.

 def chat\_with\_retry(llm\_client, messages, max\_retries=2):

for attempt in range(max\_retries + 1):

try:

return llm\_client.chat\_sync(messages)

except (httpx.TimeoutException, openai.RateLimitError) as e:

if attempt == max\_retries: raise

wait = (2 \*\* attempt) \* 0.5 # 0.5, 1, 2 seconds

time.sleep(wait)

logger.warning(f'LLM retry {attempt+1} after {e}')

return None # fallback |

## **4\. Mitigation: WebSocket Reconnection & Historical Decisions**

 **Risk** | If the frontend WebSocket disconnects, the user misses agent decisions and report streaming. |

\*\*Solution:\*\* Redis‑backed buffer of last 10 decisions per engagement. On reconnection, the frontend requests \`/api/agent-decisions/history?engagement\_id=...\` to replay missed events.

 \# In backend, after each decision:

redis\_client.lpush(f'agent\_decisions:{engagement\_id}', json.dumps(decision))

redis\_client.ltrim(f'agent\_decisions:{engagement\_id}', 0, 9) # keep last 10

redis\_client.expire(f'agent\_decisions:{engagement\_id}', 3600)

\# New API endpoint:

GET /api/engagements/:id/agent-decisions

→ returns list of last 10 decisions |

## **5\. Mitigation: Tool Argument Validation & Hallucination Guard**

 **Risk** | LLM may hallucinate a parameter not in the schema, causing runtime errors. |

\*\*Solution:\*\* Before calling any tool, validate the arguments against the tool's JSON schema. If invalid, log the error and ask the LLM to retry (once). If still invalid, skip the tool and mark it as \`tried\_tools\`.

 from jsonschema import validate, ValidationError

try:

validate(instance=action.arguments, schema=tool\_schema)

except ValidationError as e:

logger.warning(f'LLM provided invalid args for {action.tool}: {e}')

\# Give LLM one chance to correct

corrected = self.\_ask\_llm\_to\_fix\_args(action, e.message)

if corrected:

action.arguments = corrected

else:

\# skip this tool – add to tried\_tools so it's not retried

tried\_tools.add(action.tool)

continue # go to next iteration |

## **6\. Mitigation: Automatic Stop on Low Finding Yield**

 **Risk** | LLM may never return \`\_\_done\_\_\`, wasting budget by iterating until \`max\_iterations\`. |

\*\*Solution:\*\* After each tool execution, check the number of new findings. If two consecutive tools produce zero new findings, automatically stop the agent loop and proceed to analysis.

 new\_findings\_count = len(result.findings)

if new\_findings\_count == 0:

zero\_finding\_consecutive += 1

else:

zero\_finding\_consecutive = 0

if zero\_finding\_consecutive >= 2:

logger.info('Two consecutive tools found nothing – stopping agent early')

emit\_thinking(engagement\_id, 'No new findings from last two tools. Moving to analysis.')

break |

 **Summary of Mitigations** | All mitigations are additive, non‑breaking, and can be toggled via environment variables (e.g., \`LLM\_AGENT\_TIMEOUT\_SECONDS=30\`, \`LLM\_AGENT\_ZERO\_FINDING\_STOP=2\`). They are integrated into the existing 30‑step plan as recommended additions. |

# **Quick Reference: Files Changed / Created**

 **#** | **File** | **Action** | **Step(s)** |

 1 | argus-workers/models/recon\_context.py | CREATE | Step 1 |

 2 | argus-workers/orchestrator\_pkg/recon.py | MODIFY | Steps 2, 9 |

 3 | argus-workers/agent\_loop.py | MODIFY | Steps 3, 4, 7, 11, 20, 21, 22, 23 |

 4 | argus-workers/config/constants.py | MODIFY | Step 5 |

 5 | argus-platform/db/migrations/add\_agent\_decision\_log.sql | CREATE | Step 6 |

 6 | argus-workers/database/repositories/agent\_decision\_repository.py | CREATE | Step 6 |

 7 | argus-workers/orchestrator\_pkg/orchestrator.py | MODIFY | Steps 8, 9, 10, 14 |

 8 | argus-workers/llm\_client.py | MODIFY | Step 19 |

 9 | argus-workers/tasks/utils.py | CREATE | Step 12 |

 10 | argus-workers/tasks/recon.py | MODIFY | Step 12 |

 11 | argus-workers/tasks/scan.py | MODIFY | Steps 10, 12, 25 |

 12 | argus-workers/llm\_synthesizer.py | CREATE | Step 13 |

 13 | argus-workers/llm\_report\_generator.py | CREATE | Steps 15, 18 |

 14 | argus-platform/db/migrations/add\_reports\_table.sql | CREATE | Step 16 |

 15 | argus-workers/database/repositories/report\_repository.py | CREATE | Step 16 |

 16 | argus-workers/tasks/report.py | MODIFY | Steps 16, 18 |

 17 | argus-platform/src/app/api/reports/\[id\]/route.ts | CREATE | Step 17 |

 18 | argus-platform/src/app/reports/page.tsx | MODIFY | Step 17 |

 19 | argus-workers/streaming.py | MODIFY | Step 18 |

 20 | argus-workers/websocket\_events.py | MODIFY | Step 23 |

 21 | argus-platform/src/app/system/page.tsx | MODIFY | Step 24 |

 22 | argus-platform/db/schema.sql (engagements table) | MODIFY | Step 25 |

 23 | argus-platform/src/app/engagements/page.tsx | MODIFY | Steps 25, 26 |

 24 | argus-platform/src/app/engagements/\[id\]/page.tsx | MODIFY | Step 26 |

 25 | argus-workers/tests/test\_recon\_context.py | CREATE | Step 1 |

 26 | argus-workers/tests/test\_agent\_pipeline\_integration.py | CREATE | Step 27 |

 27 | argus-workers/tests/test\_agent\_fallback\_regression.py | CREATE | Step 28 |

 28 | .env.example | MODIFY | Step 30 |

 29 | FINAL-ARCHITECTURE.md | MODIFY | Step 30 |

 30 | .github/workflows/\*.yml (CI) | MODIFY | Step 30 |