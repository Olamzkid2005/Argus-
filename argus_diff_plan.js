const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  LevelFormat, PageBreak
} = require('docx');
const fs = require('fs');

// ─── Color palette ────────────────────────────────────────────────────────────
const C = {
  navy: "1B2F4E", blue: "2563EB", lblue: "EFF6FF", mblue: "BFDBFE",
  white: "FFFFFF", grey: "F8FAFC", dgrey: "64748B",
  green: "166534", gbg: "DCFCE7",
  orange: "C2410C", obg: "FFF7ED",
  red: "991B1B", rbg: "FEF2F2",
  purple: "5B21B6", pbg: "EDE9FE",
  teal: "0F766E", tbg: "CCFBF1",
  border: "CBD5E1", code: "0F1117", codeFg: "A5F3FC"
};

const b = { style: BorderStyle.SINGLE, size: 1, color: C.border };
const bs = { top: b, bottom: b, left: b, right: b };
const nb = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const nbs = { top: nb, bottom: nb, left: nb, right: nb };
const sp = (before=80, after=80) => ({ spacing: { before, after } });

function f(text, opts={}) { return new TextRun({ text, font: "Arial", size: 20, ...opts }); }
function fm(text, opts={}) { return new TextRun({ text, font: "Courier New", size: 17, ...opts }); }
function spacer() { return new Paragraph({ ...sp(80,80), children: [f("")] }); }
function pageBreak() { return new Paragraph({ children: [new PageBreak()] }); }

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1, ...sp(360,160),
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.blue, space: 6 } },
    children: [new TextRun({ text, font: "Arial", size: 30, bold: true, color: C.navy })]
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2, ...sp(280,100),
    children: [new TextRun({ text, font: "Arial", size: 24, bold: true, color: C.blue })]
  });
}
function h3(text, color=C.orange) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3, ...sp(200,80),
    children: [new TextRun({ text, font: "Arial", size: 20, bold: true, color })]
  });
}
function body(text) {
  return new Paragraph({ ...sp(60,60), children: [f(text)] });
}
function bullet(text, level=0) {
  return new Paragraph({
    numbering: { reference: "bullets", level }, ...sp(40,40),
    children: [f(text)]
  });
}
function num(text, level=0) {
  return new Paragraph({
    numbering: { reference: "numbers", level }, ...sp(40,40),
    children: [f(text)]
  });
}

function banner(text, fill=C.navy) {
  return new Paragraph({
    ...sp(400,200),
    shading: { fill, type: ShadingType.CLEAR },
    children: [new TextRun({ text: `  ${text}`, font: "Arial", size: 26, bold: true, color: C.white })]
  });
}

function infoBox(label, value, labelFill=C.blue, valueFill=C.lblue) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: [1800, 7560],
    rows: [new TableRow({ children: [
      new TableCell({
        borders: bs, width: { size: 1800, type: WidthType.DXA },
        shading: { fill: labelFill, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({ children: [new TextRun({ text: label, font: "Arial", size: 18, bold: true, color: C.white })] })]
      }),
      new TableCell({
        borders: bs, width: { size: 7560, type: WidthType.DXA },
        shading: { fill: valueFill, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({ children: [f(value, { size: 18 })] })]
      })
    ]})]
  });
}

function codeBlock(lines) {
  var cell = new TableCell({
    borders: bs,
    width: { size: 9360, type: WidthType.DXA },
    shading: { fill: C.code, type: ShadingType.CLEAR },
    margins: { top: 120, bottom: 120, left: 200, right: 200 },
    children: lines.map(function(l) {
      return new Paragraph({
        spacing: { before: 16, after: 16 },
        children: [fm(l, { color: C.codeFg })]
      });
    })
  });
  return new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: [9360],
    rows: [new TableRow({ children: [cell] })]
  });
}

function stepHeader(num, title, phase, effort, impact) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [600, 4560, 1200, 1440, 1560],
    rows: [new TableRow({ children: [
      new TableCell({
        borders: bs, width: { size: 600, type: WidthType.DXA },
        shading: { fill: C.navy, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 100, right: 100 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: String(num), font: "Arial", size: 22, bold: true, color: C.white })] })]
      }),
      new TableCell({
        borders: bs, width: { size: 4560, type: WidthType.DXA },
        shading: { fill: C.lblue, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({ children: [new TextRun({ text: title, font: "Arial", size: 20, bold: true, color: C.navy })] })]
      }),
      new TableCell({
        borders: bs, width: { size: 1200, type: WidthType.DXA },
        shading: { fill: C.grey, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 80, right: 80 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [f(phase, { size: 15, color: C.dgrey })] })]
      }),
      new TableCell({
        borders: bs, width: { size: 1440, type: WidthType.DXA },
        shading: { fill: C.grey, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 80, right: 80 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [f(effort, { size: 15, color: C.dgrey })] })]
      }),
      new TableCell({
        borders: bs, width: { size: 1560, type: WidthType.DXA },
        shading: { fill: C.gbg, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 80, right: 80 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [f(impact, { size: 15, color: C.green })] })]
      })
    ]})]
  });
}

// ─────────────────────────────────────────────────────────────────────────────
const children = [];

// COVER
children.push(
  new Paragraph({ ...sp(1440,0), children: [new TextRun({ text: "ARGUS", font: "Arial", size: 80, bold: true, color: C.navy })] }),
  new Paragraph({ ...sp(0,80), children: [new TextRun({ text: "Differentiation Implementation Plan", font: "Arial", size: 40, color: C.blue })] }),
  new Paragraph({ ...sp(0,400), children: [new TextRun({ text: "7 Features That Make Argus Different From Everything Else — 25 Steps, Fully Grounded in the Codebase", font: "Arial", size: 22, color: C.dgrey })] }),
  spacer(),
  infoBox("Core thesis", "Every scanner on the market treats each scan as a disposable event. Argus will be the first that remembers, learns, and improves with every scan it runs."),
  spacer(),
  infoBox("What this builds", "Target Memory · Self-Calibrating Confidence · Continuous Monitoring · Live PoC Generator · Natural Language Config · Developer Fix Assistant · Multi-Agent Swarm"),
  spacer(),
  infoBox("Total effort", "~18 days of focused development across 25 steps. Each step is independently testable and delivers value on its own."),
  pageBreak()
);

// OVERVIEW TABLE
children.push(
  h1("Feature Overview"),
  spacer(),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [480, 2400, 1800, 3000, 1680],
    rows: [
      new TableRow({ children: ["#","Feature","Steps","What it does","Effort"].map(function(t,i) {
        return new TableCell({
          borders: bs, width: { size:[480,2400,1800,3000,1680][i], type:WidthType.DXA },
          shading: { fill:C.navy, type:ShadingType.CLEAR },
          margins:{top:80,bottom:80,left:80,right:80},
          children:[new Paragraph({children:[new TextRun({text:t,font:"Arial",size:17,bold:true,color:C.white})]})]
        });
      })}),
      ...([
        ["A","Self-Calibrating Confidence","1–3","Feedback loop closes — FP verdicts feed back into next scan's confidence","2 days"],
        ["B","Target Memory","4–8","Per-target intelligence profile builds over time — agent gets smarter per rescan","3 days"],
        ["C","Continuous Monitoring Diff","9–11","Catch regressions, auto-close fixed findings, alert on new vulns","2 days"],
        ["D","Live PoC Generator","12–14","Confirmed findings get weaponised PoC + curl command automatically","2 days"],
        ["E","Natural Language Scan Config","15–17","Analyst types intent in English — LLM translates to scan configuration","2 days"],
        ["F","Developer Fix Assistant","18–21","Finding → exact code fix tailored to the detected tech stack","3 days"],
        ["G","Multi-Agent Specialist Swarm","22–25","IDOR Agent + Auth Agent + API Agent run in parallel, Coordinator merges","4 days"],
      ]).map(function(row,i) {
        return new TableRow({ children: row.map(function(cell,j) {
          return new TableCell({
            borders:bs, width:{size:[480,2400,1800,3000,1680][j],type:WidthType.DXA},
            shading:{fill:i%2===0?C.white:C.grey,type:ShadingType.CLEAR},
            margins:{top:60,bottom:60,left:80,right:80},
            children:[new Paragraph({children:[new TextRun({text:cell,font:"Arial",size:16})]})]
          });
        })});
      })
    ]
  }),
  pageBreak()
);

// ─────────────────────────────────────────────────────────────────────────────
// FEATURE A — Self-Calibrating Confidence
// ─────────────────────────────────────────────────────────────────────────────
children.push(banner("FEATURE A — Self-Calibrating Confidence (Steps 1–3)"), spacer());

children.push(
  body("The FeedbackLearningLoop in models/feedback.py already collects analyst verdicts and stores per-tool FP rates. The intelligence_engine.py uses a hardcoded fp_likelihood of 0.2 as the default. The gap: the stored FP rate never feeds back into the next scan. This feature closes that loop in 3 steps with zero new infrastructure."),
  spacer(),

  stepHeader(1, "Add tool_accuracy table to track per-tool FP rates", "A", "3 hrs", "Foundation"),
  spacer(),
  infoBox("New file", "argus-platform/db/migrations/035_tool_accuracy.sql"),
  spacer(),
  h3("Migration SQL"),
  codeBlock([
    "CREATE TABLE tool_accuracy (",
    "    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),",
    "    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,",
    "    source_tool     VARCHAR(100) NOT NULL,",
    "    total_verdicts  INTEGER NOT NULL DEFAULT 0,",
    "    true_positives  INTEGER NOT NULL DEFAULT 0,",
    "    false_positives INTEGER NOT NULL DEFAULT 0,",
    "    fp_rate         DECIMAL(4,3) NOT NULL DEFAULT 0.200, -- 0.000 to 1.000",
    "    last_updated    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,",
    "    UNIQUE (org_id, source_tool)",
    ");",
    "",
    "-- Pre-seed with neutral defaults for all known tools",
    "-- (fp_rate 0.2 = same as current hardcoded default, no regression)",
    "INSERT INTO tool_accuracy (org_id, source_tool, fp_rate)",
    "SELECT DISTINCT o.id, t.tool, 0.200",
    "FROM organizations o",
    "CROSS JOIN (VALUES",
    "    ('nuclei'), ('nikto'), ('dalfox'), ('sqlmap'), ('arjun'),",
    "    ('whatweb'), ('httpx'), ('katana'), ('naabu'), ('gau'),",
    "    ('web_scanner'), ('jwt_tool'), ('commix'), ('testssl')",
    ") t(tool);",
    "",
    "CREATE INDEX idx_tool_accuracy_org_tool ON tool_accuracy(org_id, source_tool);",
  ]),
  spacer(),
  h3("Test"),
  bullet("Migration runs cleanly on existing DB"),
  bullet("All tools seeded with fp_rate=0.200"),
  bullet("UNIQUE constraint prevents duplicate rows per org+tool"),
  spacer(),

  stepHeader(2, "Wire FeedbackLearningLoop to update tool_accuracy table", "A", "2 hrs", "Core logic"),
  spacer(),
  infoBox("Edit file", "argus-workers/models/feedback.py — modify _update_tool_accuracy()"),
  spacer(),
  h3("Replace the current _update_tool_accuracy() with a version that writes to the DB"),
  codeBlock([
    "def _update_tool_accuracy(self, feedback: FindingFeedback) -> bool:",
    "    source_tool = self._get_finding_source_tool(feedback.finding_id)",
    "    if not source_tool: return False",
    "",
    "    conn = None; cursor = None",
    "    try:",
    "        conn = get_db().get_connection()",
    "        cursor = conn.cursor()",
    "        # Atomically increment counters and recalculate fp_rate",
    "        cursor.execute(",
    "            '''",
    "            INSERT INTO tool_accuracy (",
    "                org_id, source_tool, total_verdicts,",
    "                true_positives, false_positives, fp_rate",
    "            )",
    "            SELECT e.org_id, %s, 1,",
    "                CASE WHEN %s THEN 1 ELSE 0 END,",
    "                CASE WHEN %s THEN 0 ELSE 1 END,",
    "                CASE WHEN %s THEN 0.0 ELSE 1.0 END",
    "            FROM findings f JOIN engagements e ON f.engagement_id = e.id",
    "            WHERE f.id = %s",
    "            ON CONFLICT (org_id, source_tool) DO UPDATE SET",
    "                total_verdicts  = tool_accuracy.total_verdicts + 1,",
    "                true_positives  = tool_accuracy.true_positives + EXCLUDED.true_positives,",
    "                false_positives = tool_accuracy.false_positives + EXCLUDED.false_positives,",
    "                -- Recalculate fp_rate from totals, not incremental averages",
    "                fp_rate = (tool_accuracy.false_positives + EXCLUDED.false_positives)::decimal",
    "                        / NULLIF(tool_accuracy.total_verdicts + 1, 0),",
    "                last_updated = NOW()",
    "            ''',",
    "            (source_tool, feedback.is_true_positive, feedback.is_true_positive,",
    "             feedback.is_true_positive, feedback.is_true_positive, feedback.finding_id)",
    "        )",
    "        conn.commit()",
    "        return True",
    "    except Exception as e:",
    "        logger.error('tool_accuracy update failed: %s', e)",
    "        if conn: conn.rollback()",
    "        return False",
    "    finally:",
    "        if cursor: cursor.close()",
    "        if conn: get_db().release_connection(conn)",
  ]),
  spacer(),
  h3("Test"),
  bullet("Submit 5 FP verdicts for nuclei → fp_rate should approach 1.0"),
  bullet("Submit 5 TP verdicts for nuclei → fp_rate should approach 0.0"),
  bullet("Mix of verdicts → fp_rate tracks ratio accurately"),
  spacer(),

  stepHeader(3, "Feed tool_accuracy.fp_rate into IntelligenceEngine.assign_confidence_scores()", "A", "2 hrs", "Closing the loop"),
  spacer(),
  infoBox("Edit file", "argus-workers/intelligence_engine.py — modify assign_confidence_scores()"),
  spacer(),
  h3("Add org-aware fp_rate lookup at the start of assign_confidence_scores"),
  codeBlock([
    "def assign_confidence_scores(self, findings: list[dict],",
    "                              org_id: str = None) -> list[dict]:",
    "    # Load per-tool FP rates for this org from tool_accuracy table",
    "    tool_fp_rates = {}  # {source_tool: fp_rate}",
    "    if org_id and self.connection_string:",
    "        try:",
    "            conn = connect(self.connection_string)",
    "            cursor = conn.cursor()",
    "            cursor.execute(",
    "                'SELECT source_tool, fp_rate FROM tool_accuracy WHERE org_id = %s',",
    "                (org_id,)",
    "            )",
    "            tool_fp_rates = {row[0]: float(row[1]) for row in cursor.fetchall()}",
    "            cursor.close(); conn.close()",
    "        except Exception as e:",
    "            logger.warning('Could not load tool_accuracy: %s', e)",
    "            # Fallback: use hardcoded defaults — no regression",
    "",
    "    # ... existing grouping code unchanged ...",
    "",
    "    for finding in group:",
    "        evidence_strength = self._get_evidence_strength(finding)",
    "",
    "        # Use org-specific learned FP rate if available, else stored value, else default",
    "        source_tool = finding.get('source_tool', '')",
    "        learned_fp = tool_fp_rates.get(source_tool)",
    "        stored_fp  = finding.get('fp_likelihood', None)",
    "",
    "        if learned_fp is not None and stored_fp is not None:",
    "            # Weighted blend: 60% learned from history, 40% stored from scanner",
    "            fp_likelihood = 0.6 * learned_fp + 0.4 * float(stored_fp)",
    "        elif learned_fp is not None:",
    "            fp_likelihood = learned_fp",
    "        elif stored_fp is not None:",
    "            fp_likelihood = float(stored_fp)",
    "        else:",
    "            fp_likelihood = 0.2  # unchanged default",
    "",
    "        confidence = (tool_agreement * evidence_strength) / (1 + fp_likelihood)",
    "        # ... rest unchanged ...",
  ]),
  spacer(),
  h3("Also: pass org_id from Orchestrator.run_analysis()"),
  body("In orchestrator_pkg/orchestrator.py, the IntelligenceEngine.evaluate(snapshot) call must pass self.org_id (already available from the engagement row) so the org-specific rates load correctly."),
  spacer(),
  h3("Test"),
  bullet("Verify nikto findings with 80% org FP rate get confidence ≈ 0.35 (heavily discounted)"),
  bullet("Verify nuclei findings with 5% org FP rate get confidence ≈ 0.66 (slightly discounted)"),
  bullet("Verify no regression when tool_accuracy row missing (falls back to 0.2 default)"),
  bullet("Verify different orgs get different confidence scores for same finding type"),
  spacer(),

  pageBreak()
);

// ─────────────────────────────────────────────────────────────────────────────
// FEATURE B — Target Memory
// ─────────────────────────────────────────────────────────────────────────────
children.push(banner("FEATURE B — Target Memory (Steps 4–8)"), spacer());

children.push(
  body("Every scanner starts from zero on each rescan. Target Memory builds a persistent intelligence profile per domain — which tools work, which endpoints exist, which finding types appear, how the attack surface changes over time. The LLM agent reads this profile before selecting tools, so scan #5 is dramatically smarter than scan #1."),
  spacer(),

  stepHeader(4, "Create target_profiles table and TargetProfileRepository", "B", "3 hrs", "Foundation"),
  spacer(),
  infoBox("New files", "migrations/036_target_profiles.sql · database/repositories/target_profile_repository.py"),
  spacer(),
  h3("Migration SQL"),
  codeBlock([
    "CREATE TABLE target_profiles (",
    "    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),",
    "    org_id                UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,",
    "    target_domain         VARCHAR(512) NOT NULL,",
    "    -- Surface knowledge",
    "    known_endpoints       JSONB NOT NULL DEFAULT '[]',   -- top 100 seen endpoints",
    "    known_tech_stack      JSONB NOT NULL DEFAULT '[]',   -- stable tech fingerprint",
    "    known_open_ports      JSONB NOT NULL DEFAULT '[]',",
    "    known_subdomains      JSONB NOT NULL DEFAULT '[]',",
    "    -- Finding history",
    "    confirmed_finding_types JSONB DEFAULT '[]', -- types confirmed as TP in past scans",
    "    false_positive_types    JSONB DEFAULT '[]', -- types that were always FP here",
    "    high_value_endpoints    JSONB DEFAULT '[]', -- endpoints that had findings",
    "    -- Tool performance",
    "    best_tools            JSONB DEFAULT '[]',   -- [{tool, finding_rate, last_seen}]",
    "    noisy_tools           JSONB DEFAULT '[]',   -- tools with >50% FP on this target",
    "    -- Scan history",
    "    total_scans           INTEGER NOT NULL DEFAULT 0,",
    "    last_scan_at          TIMESTAMP WITH TIME ZONE,",
    "    last_findings_count   INTEGER DEFAULT 0,",
    "    scan_ids              JSONB DEFAULT '[]',   -- list of engagement IDs",
    "    -- Regression tracking",
    "    fixed_findings        JSONB DEFAULT '[]',   -- finding IDs marked fixed",
    "    regressed_findings    JSONB DEFAULT '[]',   -- finding IDs that came back",
    "    created_at            TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,",
    "    updated_at            TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,",
    "    UNIQUE (org_id, target_domain)",
    ");",
    "CREATE INDEX idx_target_profiles_domain ON target_profiles(org_id, target_domain);",
  ]),
  spacer(),
  h3("TargetProfileRepository key methods"),
  codeBlock([
    "class TargetProfileRepository:",
    "    def upsert_from_engagement(self, org_id, target_url, engagement_id,",
    "                                recon_context, findings) -> dict:",
    "        '''Called at end of each scan to update the profile.'''",
    "",
    "    def get_profile(self, org_id, target_domain) -> dict | None:",
    "        '''Returns the profile dict, or None if first scan.'''",
    "",
    "    def to_llm_context(self, profile: dict) -> str:",
    "        '''Returns a compact string for the agent prompt section",
    "        '=== WHAT WE KNOW ABOUT THIS TARGET ==='",
    "        Max 800 tokens. Focuses on actionable intel:',",
    "        - Which tools found real issues here",
    "        - Which tools were noisy",
    "        - Which endpoints had confirmed findings",
    "        - What changed since last scan",
    "        '''",
  ]),
  spacer(),

  stepHeader(5, "Update target profile after each completed scan", "B", "2 hrs", "Data collection"),
  spacer(),
  infoBox("Edit file", "argus-workers/orchestrator_pkg/orchestrator.py — end of run_report()"),
  spacer(),
  codeBlock([
    "# In run_report(), after findings are saved and report generated:",
    "try:",
    "    from database.repositories.target_profile_repository import TargetProfileRepository",
    "    from urllib.parse import urlparse",
    "",
    "    target_domain = urlparse(self.target_url).netloc",
    "    profile_repo = TargetProfileRepository(self.db_conn)",
    "",
    "    # Load findings from this engagement",
    "    all_findings, _ = self.finding_repo.get_findings_by_engagement(self.engagement_id)",
    "",
    "    profile_repo.upsert_from_engagement(",
    "        org_id=self.org_id,",
    "        target_url=self.target_url,",
    "        engagement_id=self.engagement_id,",
    "        recon_context=recon_context,  # from Redis or passed through",
    "        findings=all_findings,",
    "    )",
    "    logger.info('Target profile updated for %s', target_domain)",
    "except Exception as e:",
    "    logger.warning('Target profile update failed (non-fatal): %s', e)",
    "    # Never fail the report task for a profile update",
  ]),
  spacer(),

  stepHeader(6, "Add target_profile field to ReconContext", "B", "1 hr", "Schema extension"),
  spacer(),
  infoBox("Edit file", "argus-workers/models/recon_context.py — add one optional field"),
  spacer(),
  codeBlock([
    "# In ReconContext dataclass, add after existing fields:",
    "target_profile: dict | None = None  # Populated from target_profiles table if prior scans exist",
    "",
    "# In to_llm_structured(), add profile section if present:",
    "def to_llm_structured(self) -> str:",
    "    data = { ...existing fields... }",
    "    if self.target_profile:",
    "        p = self.target_profile",
    "        data['PREVIOUS_SCANS'] = {",
    "            'scan_count': p.get('total_scans', 0),",
    "            'best_tools': p.get('best_tools', [])[:5],",
    "            'noisy_tools': p.get('noisy_tools', [])[:5],",
    "            'confirmed_finding_types': p.get('confirmed_finding_types', [])[:10],",
    "            'high_value_endpoints': p.get('high_value_endpoints', [])[:10],",
    "        }",
    "    return json.dumps(data, indent=2)",
  ]),
  spacer(),

  stepHeader(7, "Load target profile in execute_recon_tools() before summarizing context", "B", "1 hr", "Agent wiring"),
  spacer(),
  infoBox("Edit file", "argus-workers/orchestrator_pkg/recon.py — end of execute_recon_tools()"),
  spacer(),
  codeBlock([
    "# At end of execute_recon_tools(), before return (findings, recon_context):",
    "try:",
    "    from urllib.parse import urlparse",
    "    from database.repositories.target_profile_repository import TargetProfileRepository",
    "",
    "    domain = urlparse(target).netloc",
    "    org_id = ctx.tool_runner.engagement.get('org_id') if hasattr(ctx.tool_runner, 'engagement') else None",
    "    if org_id and domain:",
    "        profile_repo = TargetProfileRepository(ctx.tool_runner.db_conn)",
    "        existing_profile = profile_repo.get_profile(org_id, domain)",
    "        if existing_profile:",
    "            recon_context.target_profile = existing_profile",
    "            logger.info('Loaded target profile for %s (%d prior scans)',",
    "                        domain, existing_profile.get('total_scans', 0))",
    "except Exception as e:",
    "    logger.warning('Could not load target profile (non-fatal): %s', e)",
  ]),
  spacer(),

  stepHeader(8, "Add '=== WHAT WE KNOW ABOUT THIS TARGET ===' section to agent prompt", "B", "2 hrs", "Agent intelligence"),
  spacer(),
  infoBox("Edit file", "argus-workers/agent/agent_prompts.py — build_tool_selection_prompt()"),
  spacer(),
  h3("Add as the first section of the user prompt when target_profile is present"),
  codeBlock([
    "def build_tool_selection_prompt(recon_context, available_tools, tried_tools,",
    "                                 observation_history, mode=None, bugbounty_context=''):",
    "    prompt = ''",
    "",
    "    # Section 0: Target memory — what we already know about this domain",
    "    profile = getattr(recon_context, 'target_profile', None)",
    "    if profile and profile.get('total_scans', 0) > 0:",
    "        best = profile.get('best_tools', [])[:4]",
    "        noisy = profile.get('noisy_tools', [])[:4]",
    "        finding_types = profile.get('confirmed_finding_types', [])[:6]",
    "        hot_endpoints = profile.get('high_value_endpoints', [])[:5]",
    "",
    "        prompt += f'''",
    "=== WHAT WE KNOW ABOUT THIS TARGET ({profile.get('total_scans')} prior scans) ===",
    "Tools that found real issues here: {', '.join(t['tool'] for t in best) or 'none yet'}",
    "Tools that were noisy/FP here: {', '.join(noisy) or 'none'}",
    "Confirmed vulnerability types: {', '.join(finding_types) or 'none confirmed'}",
    "Previously vulnerable endpoints: {chr(10).join('  - ' + e for e in hot_endpoints) or '  none'}",
    "",
    "INSTRUCTION: Prioritise tools that worked before. Skip tools marked noisy unless",
    "all better options are exhausted.",
    "'''",
    "",
    "    # Section 1: Structured recon data",
    "    prompt += f'\\n=== RECON FINDINGS (STRUCTURED) ===\\n{recon_context.to_llm_structured()}\\n'",
    "    # ... rest of prompt unchanged ...",
  ]),
  spacer(),
  h3("Test"),
  bullet("First scan of a domain: prompt has no target memory section"),
  bullet("Second scan: prompt shows 'Tools that found real issues: nuclei'"),
  bullet("After 5 scans of noisy target: prompt correctly warns against nikto"),
  spacer(),
  pageBreak()
);

// ─────────────────────────────────────────────────────────────────────────────
// FEATURE C — Continuous Monitoring Diff Engine
// ─────────────────────────────────────────────────────────────────────────────
children.push(banner("FEATURE C — Continuous Monitoring Diff Engine (Steps 9–11)"), spacer());

children.push(
  body("Scheduled engagements already run every N days. What's missing: comparing each new scan to the previous and surfacing only what changed. New finding = alert. Fixed finding that re-appeared = regression. Finding that's gone = auto-close. This turns Argus from a scanner into a continuous security posture monitor."),
  spacer(),

  stepHeader(9, "Build ScanDiffEngine that compares findings across engagements", "C", "3 hrs", "Core engine"),
  spacer(),
  infoBox("New file", "argus-workers/scan_diff_engine.py"),
  spacer(),
  h3("Key method: diff(previous_engagement_id, current_engagement_id)"),
  codeBlock([
    "class ScanDiffEngine:",
    "    '''Compares findings between two scans of the same target.'''",
    "",
    "    NEW_FINDING     = 'new'       # Appeared in current, not in previous",
    "    FIXED_FINDING   = 'fixed'     # Was in previous, gone in current",
    "    REGRESSED       = 'regressed' # Was fixed, now back",
    "    PERSISTENT      = 'persistent'# Present in both",
    "    SEVERITY_CHANGE = 'severity_changed'",
    "",
    "    def diff(self, prev_id: str, curr_id: str) -> dict:",
    "        prev = self._load_findings(prev_id)  # {fingerprint: finding}",
    "        curr = self._load_findings(curr_id)",
    "        fixed_ids = self._load_fixed_findings(prev_id) # from target_profile",
    "",
    "        result = {",
    "            'new':              [],",
    "            'fixed':            [],",
    "            'regressed':        [],",
    "            'persistent':       [],",
    "            'severity_changed': [],",
    "            'summary': {}",
    "        }",
    "",
    "        curr_fps = set(curr.keys())",
    "        prev_fps = set(prev.keys())",
    "",
    "        for fp in curr_fps - prev_fps:",
    "            if fp in fixed_ids:",
    "                result['regressed'].append(curr[fp])",
    "            else:",
    "                result['new'].append(curr[fp])",
    "",
    "        for fp in prev_fps - curr_fps:",
    "            result['fixed'].append(prev[fp])",
    "",
    "        for fp in curr_fps & prev_fps:",
    "            if curr[fp]['severity'] != prev[fp]['severity']:",
    "                result['severity_changed'].append({",
    "                    'finding': curr[fp],",
    "                    'old_severity': prev[fp]['severity'],",
    "                    'new_severity': curr[fp]['severity'],",
    "                })",
    "            else:",
    "                result['persistent'].append(curr[fp])",
    "",
    "        result['summary'] = {",
    "            'new_count': len(result['new']),",
    "            'fixed_count': len(result['fixed']),",
    "            'regressed_count': len(result['regressed']),",
    "            'action_required': len(result['new']) + len(result['regressed']) > 0",
    "        }",
    "        return result",
    "",
    "    def _fingerprint(self, finding: dict) -> str:",
    "        '''Stable fingerprint for matching findings across scans.'''",
    "        import hashlib",
    "        key = f\"{finding['type']}:{finding['endpoint']}\"",
    "        return hashlib.sha256(key.encode()).hexdigest()[:16]",
  ]),
  spacer(),

  stepHeader(10, "Run diff engine after each scheduled scan completes", "C", "2 hrs", "Automation"),
  spacer(),
  infoBox("Edit file", "argus-workers/tasks/scheduled.py — after scan is dispatched"),
  spacer(),
  codeBlock([
    "# In run_due_scans(), after a new engagement is created and scanned:",
    "# (Run as a Celery chord: scan chain → then diff task)",
    "",
    "from celery import chord",
    "from tasks.diff import run_scan_diff  # new task",
    "",
    "# After scan completes (via chord callback):",
    "@app.task(name='tasks.diff.run_scan_diff')",
    "def run_scan_diff(_, new_engagement_id, prev_engagement_id, org_id):",
    "    '''Called after a scheduled scan completes.'''",
    "    if not prev_engagement_id:",
    "        return  # First scan — no diff possible",
    "",
    "    from scan_diff_engine import ScanDiffEngine",
    "    engine = ScanDiffEngine(db_url=os.getenv('DATABASE_URL'))",
    "    diff = engine.diff(prev_engagement_id, new_engagement_id)",
    "",
    "    # Auto-close fixed findings in the DB",
    "    for finding in diff['fixed']:",
    "        engine.mark_fixed(finding['id'], new_engagement_id)",
    "",
    "    # Fire webhooks for new + regressed findings",
    "    if diff['summary']['action_required']:",
    "        from post_finding_hooks import fire_diff_webhooks",
    "        fire_diff_webhooks(diff, org_id, new_engagement_id)",
    "",
    "    # Store diff in target_profile",
    "    engine.store_diff_in_profile(org_id, diff)",
    "",
    "    logger.info('Diff complete: %d new, %d fixed, %d regressed',",
    "                diff['summary']['new_count'],",
    "                diff['summary']['fixed_count'],",
    "                diff['summary']['regressed_count'])",
  ]),
  spacer(),

  stepHeader(11, "Add Diff Timeline to Engagement Detail and Monitoring Dashboard page", "C", "3 hrs", "Frontend"),
  spacer(),
  infoBox("New files", "argus-platform/src/app/monitoring/page.tsx · /api/monitoring/diff/[id]/route.ts"),
  spacer(),
  body("A new Monitoring page shows all targets under continuous monitoring with their diff history. Each row: target domain, last scan date, new findings (red), fixed findings (green), regressions (orange), and a Scan Now button. Clicking a row shows the full diff timeline — a vertical timeline with one entry per scan, showing what changed."),
  spacer(),
  h3("GET /api/monitoring/diff/[engagement_id]"),
  codeBlock([
    "// Returns the diff between this engagement and the previous one for same target",
    "// Response:",
    "{",
    "  new:              [{ id, type, severity, endpoint }],",
    "  fixed:            [{ id, type, severity, endpoint }],",
    "  regressed:        [{ id, type, severity, endpoint }],",
    "  persistent_count: 14,",
    "  summary:          { new_count, fixed_count, regressed_count, action_required }",
    "}",
  ]),
  spacer(),
  pageBreak()
);

// ─────────────────────────────────────────────────────────────────────────────
// FEATURE D — Live PoC Generator
// ─────────────────────────────────────────────────────────────────────────────
children.push(banner("FEATURE D — Live PoC Generator (Steps 12–14)"), spacer());

children.push(
  body("Detection is a commodity. Argus is the only tool with an LLM already integrated that can take a confirmed HIGH/CRITICAL finding with evidence and generate the weaponised demonstration — a curl command, a browser paste, and a developer-facing explanation — automatically. No analyst effort required."),
  spacer(),

  stepHeader(12, "Build PoCGenerator class", "D", "3 hrs", "Core logic"),
  spacer(),
  infoBox("New file", "argus-workers/poc_generator.py"),
  spacer(),
  codeBlock([
    "POC_SYSTEM_PROMPT = '''",
    "You are a senior penetration tester generating proof-of-concept demonstrations.",
    "Given a confirmed security finding with evidence, produce a weaponised PoC.",
    "Output valid JSON with exactly these fields.",
    "All output must be specific to the actual finding — never generic.",
    "'''",
    "",
    "POC_TEMPLATES = {",
    "    'XSS': {",
    "        'fields': ['curl_command', 'browser_poc', 'blind_xss_payload',",
    "                   'impact_demo', 'developer_fix_hint'],",
    "        'instruction': 'Generate a reflected XSS PoC using the detected payload and endpoint.'",
    "    },",
    "    'SQL_INJECTION': {",
    "        'fields': ['curl_command', 'sqlmap_command', 'manual_payload',",
    "                   'data_extraction_query', 'developer_fix_hint'],",
    "        'instruction': 'Generate SQLi PoC with extraction example using the parameter.'",
    "    },",
    "    'SSRF': {",
    "        'fields': ['curl_command', 'imds_test', 'internal_scan_example',",
    "                   'oob_detection_url', 'developer_fix_hint'],",
    "        'instruction': 'Generate SSRF PoC targeting cloud IMDS and internal services.'",
    "    },",
    "    'IDOR': {",
    "        'fields': ['account_a_request', 'account_b_request',",
    "                   'expected_403_vs_actual', 'automation_script', 'developer_fix_hint'],",
    "        'instruction': 'Generate two-account IDOR PoC showing cross-user data access.'",
    "    },",
    "    'CORS_MISCONFIGURATION': {",
    "        'fields': ['attacker_page_html', 'curl_command', 'data_stolen', 'developer_fix_hint'],",
    "        'instruction': 'Generate CORS exploit showing credential read from attacker origin.'",
    "    },",
    "}",
    "DEFAULT_TEMPLATE = {'fields': ['curl_command', 'manual_steps', 'developer_fix_hint'],",
    "                    'instruction': 'Generate a generic PoC for this security finding.'}",
    "",
    "class PoCGenerator:",
    "    def generate(self, finding: dict, llm_service) -> dict | None:",
    "        if finding.get('confidence', 0) < 0.75:",
    "            return None  # Only generate PoC for high-confidence findings",
    "        if finding.get('severity') not in ('CRITICAL', 'HIGH'):",
    "            return None  # Only HIGH and CRITICAL findings warrant PoC",
    "",
    "        vuln_type = finding.get('type', 'UNKNOWN').upper()",
    "        template = POC_TEMPLATES.get(vuln_type, DEFAULT_TEMPLATE)",
    "",
    "        evidence = finding.get('evidence', {})",
    "        user_prompt = f'''",
    "Finding: {vuln_type}",
    "Endpoint: {finding['endpoint']}",
    "Severity: {finding['severity']}",
    "Evidence:",
    "  Request:  {str(evidence.get('request', ''))[:400]}",
    "  Response: {str(evidence.get('response', ''))[:300]}",
    "  Payload:  {str(evidence.get('payload', ''))[:200]}",
    "",
    "Instruction: {template['instruction']}",
    "Return JSON with fields: {', '.join(template['fields'])}",
    "'''",
    "        result = llm_service.chat_json(",
    "            system_prompt=POC_SYSTEM_PROMPT,",
    "            user_prompt=user_prompt,",
    "            max_tokens=800,",
    "            temperature=0.1,",
    "        )",
    "        return None if result.get('_fallback') else result",
  ]),
  spacer(),

  stepHeader(13, "Add poc_generated JSONB column to findings and call PoCGenerator post-analysis", "D", "2 hrs", "Integration"),
  spacer(),
  infoBox("New migration", "migrations/037_poc_generated.sql — adds poc_generated JSONB column to findings"),
  spacer(),
  codeBlock([
    "ALTER TABLE findings ADD COLUMN poc_generated JSONB;",
    "ALTER TABLE findings ADD COLUMN poc_generated_at TIMESTAMP WITH TIME ZONE;",
    "",
    "-- Index for fetching findings that have PoC vs those that don't",
    "CREATE INDEX idx_findings_has_poc ON findings((poc_generated IS NOT NULL));",
  ]),
  spacer(),
  body("In orchestrator_pkg/orchestrator.py run_analysis(), after IntelligenceEngine.evaluate() returns scored findings, call PoCGenerator on each HIGH/CRITICAL finding with confidence >= 0.75. Save the result to poc_generated column. This runs during the analysis phase, so by the time the report is generated the PoC is already stored."),
  spacer(),

  stepHeader(14, "Render PoC in finding detail page with copy buttons", "D", "2 hrs", "Frontend"),
  spacer(),
  infoBox("Edit file", "argus-platform/src/app/findings/[id]/page.tsx — add PoC section"),
  spacer(),
  body("Add a new 'Proof of Concept' section below the Evidence tab. Shows the LLM-generated PoC fields in syntax-highlighted, copyable code blocks. Each field has a one-click copy button. Include a warning banner: 'For authorized testing only — use on systems you own or have written permission to test.' If poc_generated is null, show a 'Generate PoC' button that calls POST /api/findings/[id]/poc."),
  spacer(),
  pageBreak()
);

// ─────────────────────────────────────────────────────────────────────────────
// FEATURE E — Natural Language Scan Config
// ─────────────────────────────────────────────────────────────────────────────
children.push(banner("FEATURE E — Natural Language Scan Configuration (Steps 15–17)"), spacer());

children.push(
  body("The engagement creation form has 8+ technical fields. A new analyst stares at 'aggressiveness', 'authorized scope', 'scan type' and has no idea what to put. Natural language configuration lets them type: 'Scan this Node.js API for IDOR and auth bypass. I have a test account.' The LLM translates that into a complete scan configuration with zero form expertise required."),
  spacer(),

  stepHeader(15, "Build IntentParser — LLM that translates free text to scan config", "E", "2 hrs", "Core logic"),
  spacer(),
  infoBox("New file", "argus-workers/intent_parser.py"),
  spacer(),
  codeBlock([
    "INTENT_SYSTEM_PROMPT = '''",
    "You translate a security analyst's intent description into a structured scan configuration.",
    "Extract: target URL, scan type, priority vulnerability classes, aggressiveness,",
    "auth credentials if mentioned, tech stack hints, and any explicit exclusions.",
    "Return valid JSON only. For any field not mentioned, use the default.",
    "'''",
    "",
    "INTENT_SCHEMA = {",
    "    'target_url':         str,   # required",
    "    'scan_type':          str,   # 'url' | 'repo' | 'bug_bounty', default 'url'",
    "    'aggressiveness':     str,   # 'default' | 'high' | 'extreme', default 'default'",
    "    'agent_mode':         bool,  # always True unless 'deterministic' mentioned",
    "    'mode':               str,   # 'bugbounty' | 'standard', default 'standard'",
    "    'priority_classes':   list,  # ['idor', 'auth', 'ssrf', 'xss', 'sqli']",
    "    'skip_vuln_types':    list,  # types to skip",
    "    'tech_stack_hints':   list,  # ['nodejs', 'php', 'react', 'java']",
    "    'auth_config':        dict,  # {type, username, password, login_url} if mentioned",
    "    'severity_filter':    str,   # 'critical_only' | 'high_plus' | 'all'",
    "    'intent_summary':     str,   # 1 sentence summary of what was understood",
    "}",
    "",
    "class IntentParser:",
    "    def parse(self, intent_text: str, llm_service) -> dict:",
    "        result = llm_service.chat_json(",
    "            system_prompt=INTENT_SYSTEM_PROMPT,",
    "            user_prompt=f'Translate this scan request:\\n\\n{intent_text}',",
    "            max_tokens=600,",
    "            temperature=0.1,",
    "        )",
    "        if result.get('_fallback'):",
    "            return {'error': 'Could not parse intent', 'raw': intent_text}",
    "        # Validate target_url is present",
    "        if not result.get('target_url'):",
    "            return {'error': 'No target URL found in your description', 'raw': intent_text}",
    "        return result",
    "",
    "# Example input → output:",
    "# 'Scan this Laravel app at https://app.example.com for SQLi and auth bypass.",
    "#  Test account: admin@example.com / TestPass123'",
    "# → {",
    "#     target_url: 'https://app.example.com',",
    "#     scan_type: 'url',",
    "#     aggressiveness: 'default',",
    "#     priority_classes: ['sqli', 'auth'],",
    "#     tech_stack_hints: ['php', 'laravel'],",
    "#     auth_config: {type:'form', username:'admin@example.com', password:'TestPass123'},",
    "#     intent_summary: 'Authenticated scan of Laravel app for SQLi and auth bypass'",
    "# }",
  ]),
  spacer(),

  stepHeader(16, "Add intent API endpoint and wire priority_classes into agent prompt", "E", "2 hrs", "Backend"),
  spacer(),
  infoBox("New route", "argus-platform/src/app/api/engagements/parse-intent/route.ts"),
  infoBox("Edit", "argus-workers/agent/agent_prompts.py — accept priority_classes parameter"),
  spacer(),
  codeBlock([
    "// POST /api/engagements/parse-intent",
    "// Body: { intent: 'Scan this Node.js API for IDOR...' }",
    "// Response: { target_url, scan_type, aggressiveness, priority_classes, auth_config, intent_summary, ... }",
    "// Used by the engagement creation form to pre-fill all fields",
    "",
    "// In agent_prompts.py, add priority_classes to build_tool_selection_prompt():",
    "// When priority_classes = ['idor', 'auth'], inject at top of user prompt:",
    "// '=== ANALYST PRIORITY ==='",
    "// 'The analyst specifically requested focus on: IDOR, AUTH BYPASS'",
    "// 'Run tools for these classes before all others.'",
  ]),
  spacer(),

  stepHeader(17, "Add intent input field to engagement creation form", "E", "2 hrs", "Frontend"),
  spacer(),
  infoBox("Edit file", "argus-platform/src/app/engagements/page.tsx — add intent mode toggle"),
  spacer(),
  body("Add a 'Natural Language' tab alongside the current 'Standard' form tab. The NL tab has a single large textarea: 'Describe what you want to scan and why.' Below it: 'Parse Intent' button that calls /api/engagements/parse-intent. On response, show a preview card: 'Understood: Authenticated scan of Laravel app for SQLi and auth bypass — High aggressiveness, tech: PHP/Laravel, auth: form login.' With a 'Looks good, start scan' button and an 'Edit details' link that pre-fills the standard form with the parsed values."),
  spacer(),
  pageBreak()
);

// ─────────────────────────────────────────────────────────────────────────────
// FEATURE F — Developer Fix Assistant
// ─────────────────────────────────────────────────────────────────────────────
children.push(banner("FEATURE F — Developer Fix Assistant (Steps 18–21)"), spacer());

children.push(
  body("Every scanner tells developers what's wrong. None of them tell developers exactly how to fix it in their specific tech stack. Argus has the tech stack from recon and the LLM. A Developer Fix Assistant generates a PR-ready remediation: the vulnerable code pattern, the fixed version, a unit test that proves the fix works, and a library recommendation if relevant."),
  spacer(),

  stepHeader(18, "Build DeveloperFixAssistant class", "F", "3 hrs", "Core logic"),
  spacer(),
  infoBox("New file", "argus-workers/developer_fix_assistant.py"),
  spacer(),
  codeBlock([
    "FIX_SYSTEM_PROMPT = '''",
    "You are a senior application security engineer generating developer-ready remediation.",
    "Given a confirmed security finding and the application's tech stack, produce:",
    "1. vulnerable_pattern: The code pattern that caused this (pseudocode or real if evident from evidence)",
    "2. fixed_pattern: The corrected version with security controls applied",
    "3. explanation: Why the fix works (2-3 sentences, developer-friendly)",
    "4. unit_test: A unit test or integration test that would catch this regression",
    "5. library_recommendation: If a library makes this easier/safer, name it",
    "6. additional_contexts: Other places in the codebase this same pattern might exist",
    "Be specific to the tech stack. Never give generic advice.",
    "Return valid JSON only.",
    "'''",
    "",
    "TECH_STACK_PATTERNS = {",
    "    'node': {",
    "        'XSS': 'DOMPurify.sanitize(input) or helmet CSP header',",
    "        'SQL_INJECTION': 'Use parameterized queries: db.query(\"SELECT * FROM users WHERE id = $1\", [userId])',",
    "        'IDOR': 'Add ownership check: if (resource.userId !== req.user.id) throw new ForbiddenError()',",
    "    },",
    "    'php': {",
    "        'SQL_INJECTION': 'Use PDO prepared statements: $stmt = $pdo->prepare(\"SELECT...\"); $stmt->execute([$id])',",
    "        'XSS': 'htmlspecialchars($input, ENT_QUOTES, \"UTF-8\")',",
    "    },",
    "    'python': {",
    "        'SQL_INJECTION': 'Use parameterized queries: cursor.execute(\"SELECT * FROM users WHERE id = %s\", (user_id,))',",
    "        'SSTI': 'Use Environment(autoescape=True) in Jinja2 or render_template_string with Markup()',",
    "    },",
    "    # ... java, go, ruby, etc.",
    "}",
    "",
    "class DeveloperFixAssistant:",
    "    def generate_fix(self, finding: dict, tech_stack: list[str],",
    "                     llm_service) -> dict | None:",
    "        if finding.get('severity') not in ('CRITICAL', 'HIGH', 'MEDIUM'):",
    "            return None",
    "",
    "        stack_str = ', '.join(tech_stack[:5]) if tech_stack else 'unknown'",
    "        hints = self._get_stack_hints(finding.get('type', ''), tech_stack)",
    "",
    "        prompt = f'''",
    "Finding: {finding.get('type')} ({finding.get('severity')})",
    "Endpoint: {finding.get('endpoint')}",
    "Evidence: {str(finding.get('evidence', {}))[:400]}",
    "Tech stack: {stack_str}",
    "Stack-specific hint: {hints}",
    "",
    "Generate developer-ready remediation for this specific finding in this tech stack.",
    "'''",
    "        result = llm_service.chat_json(",
    "            FIX_SYSTEM_PROMPT, prompt, max_tokens=900, temperature=0.1",
    "        )",
    "        return None if result.get('_fallback') else result",
  ]),
  spacer(),

  stepHeader(19, "Add remediation_fix JSONB column to findings", "F", "1 hr", "Schema"),
  spacer(),
  codeBlock([
    "-- migrations/038_remediation_fix.sql",
    "ALTER TABLE findings ADD COLUMN remediation_fix JSONB;",
    "ALTER TABLE findings ADD COLUMN remediation_fix_at TIMESTAMP WITH TIME ZONE;",
    "",
    "-- Schema of remediation_fix JSONB:",
    "-- {",
    "--   vulnerable_pattern: string,",
    "--   fixed_pattern: string,",
    "--   explanation: string,",
    "--   unit_test: string,",
    "--   library_recommendation: string | null,",
    "--   additional_contexts: string[],",
    "--   tech_stack: string[],",
    "--   generated_at: ISO timestamp",
    "-- }",
  ]),
  spacer(),

  stepHeader(20, "Call DeveloperFixAssistant during analysis phase for all MEDIUM+ findings", "F", "2 hrs", "Integration"),
  spacer(),
  body("In orchestrator_pkg/orchestrator.py run_analysis(), after the PoC Generator runs (Step 13), run DeveloperFixAssistant on all MEDIUM/HIGH/CRITICAL scored findings in parallel using ThreadPoolExecutor(max_workers=4). Save results to findings.remediation_fix. This runs async and doesn't block the report generation — if it exceeds 60 seconds, it runs as a separate background task that updates findings after the report is already visible."),
  spacer(),

  stepHeader(21, "Render Developer Fix in finding detail page with GitHub Copilot-style UI", "F", "2 hrs", "Frontend"),
  spacer(),
  body("In the finding detail page, add a 'Developer Fix' tab alongside Evidence and Reproduction Steps. The tab shows: (1) vulnerable_pattern in a red-tinted code block with a 'Before' label, (2) fixed_pattern in a green-tinted code block with an 'After' label, (3) explanation as prose, (4) unit_test in a code block with a 'Test' label and copy button, (5) library_recommendation as a badge with npm/pip install command. If remediation_fix is null, show a 'Generate Fix' button."),
  spacer(),
  pageBreak()
);

// ─────────────────────────────────────────────────────────────────────────────
// FEATURE G — Multi-Agent Specialist Swarm
// ─────────────────────────────────────────────────────────────────────────────
children.push(banner("FEATURE G — Multi-Agent Specialist Swarm (Steps 22–25)"), spacer());

children.push(
  body("The current ReActAgent is a generalist that runs tools sequentially. The next architectural step: a SwarmOrchestrator that spawns specialist sub-agents in parallel. The IDOR Agent, Auth Agent, and API Agent each have deep domain expertise, run concurrently, and report to a Coordinator that deduplicates and merges results. This is how real pentest teams operate."),
  spacer(),

  stepHeader(22, "Build SpecialistAgent base class and 3 specialist implementations", "G", "4 hrs", "Architecture"),
  spacer(),
  infoBox("New file", "argus-workers/agent/swarm.py"),
  spacer(),
  codeBlock([
    "class SpecialistAgent:",
    "    '''Base class for domain-specialist agents.'''",
    "",
    "    DOMAIN = None         # 'idor' | 'auth' | 'api' | 'injection'",
    "    PRIORITY_TOOLS = []   # Ordered list of tools this specialist prioritises",
    "    SYSTEM_PROMPT = ''    # Domain-specific system prompt from bug-reaper knowledge",
    "",
    "    def __init__(self, llm_service, tool_runner, recon_context, engagement_id):",
    "        self.llm_service = llm_service",
    "        self.tool_runner  = tool_runner",
    "        self.recon_context = recon_context",
    "        self.engagement_id = engagement_id",
    "        self.findings: list[dict] = []",
    "",
    "    def should_activate(self) -> bool:",
    "        '''Return True if recon signals suggest this domain is relevant.'''",
    "        raise NotImplementedError",
    "",
    "    def run(self) -> list[dict]:",
    "        '''Run this specialist agent and return its findings.'''",
    "        raise NotImplementedError",
    "",
    "",
    "class IDORAgent(SpecialistAgent):",
    "    DOMAIN = 'idor'",
    "    PRIORITY_TOOLS = ['arjun', 'jwt_tool', 'web_scanner']",
    "",
    "    def should_activate(self) -> bool:",
    "        rc = self.recon_context",
    "        return (len(rc.parameter_bearing_urls) > 0 or",
    "                rc.has_api or len(rc.api_endpoints) > 0)",
    "",
    "    def run(self) -> list[dict]:",
    "        # 1. Discover hidden parameters with arjun",
    "        # 2. Run web_scanner with IDOR-focused checks",
    "        # 3. Ask LLM to identify predictable ID patterns in evidence",
    "        # 4. Return findings tagged source='idor_agent'",
    "        ...",
    "",
    "class AuthAgent(SpecialistAgent):",
    "    DOMAIN = 'auth'",
    "    PRIORITY_TOOLS = ['jwt_tool', 'web_scanner', 'nuclei']",
    "",
    "    def should_activate(self) -> bool:",
    "        rc = self.recon_context",
    "        return rc.has_login_page or len(rc.auth_endpoints) > 0 or rc.has_api",
    "",
    "    def run(self) -> list[dict]:",
    "        # 1. Run jwt_tool on all auth endpoints",
    "        # 2. Run nuclei with auth-related tags",
    "        # 3. Check password reset flow, OAuth state, session fixation",
    "        # 4. Return findings tagged source='auth_agent'",
    "        ...",
    "",
    "class APIAgent(SpecialistAgent):",
    "    DOMAIN = 'api'",
    "    PRIORITY_TOOLS = ['arjun', 'nuclei', 'dalfox', 'sqlmap']",
    "",
    "    def should_activate(self) -> bool:",
    "        rc = self.recon_context",
    "        return rc.has_api or len(rc.api_endpoints) > 5",
    "",
    "    def run(self) -> list[dict]:",
    "        # 1. Discover all API endpoints and parameters with arjun",
    "        # 2. Run nuclei with api-* tags",
    "        # 3. Run dalfox + sqlmap on discovered API params",
    "        # 4. Check GraphQL introspection if /graphql detected",
    "        ...",
  ]),
  spacer(),

  stepHeader(23, "Build SwarmOrchestrator that runs specialists in parallel", "G", "3 hrs", "Orchestration"),
  spacer(),
  infoBox("Edit file", "argus-workers/agent/swarm.py — add SwarmOrchestrator class"),
  spacer(),
  codeBlock([
    "class SwarmOrchestrator:",
    "    '''Runs specialist agents in parallel and merges their findings.'''",
    "",
    "    SPECIALIST_CLASSES = [IDORAgent, AuthAgent, APIAgent]",
    "",
    "    def __init__(self, llm_service, tool_runner, recon_context, engagement_id):",
    "        self.agents = [",
    "            cls(llm_service, tool_runner, recon_context, engagement_id)",
    "            for cls in self.SPECIALIST_CLASSES",
    "        ]",
    "",
    "    def run(self) -> list[dict]:",
    "        # Activate only relevant specialists based on recon signals",
    "        active = [a for a in self.agents if a.should_activate()]",
    "        logger.info('Swarm: activating %d specialist agents: %s',",
    "                    len(active), [a.DOMAIN for a in active])",
    "",
    "        if not active:",
    "            logger.warning('No specialists activated — falling back to single agent')",
    "            return []",
    "",
    "        # Run all active specialists in parallel",
    "        from concurrent.futures import ThreadPoolExecutor, as_completed",
    "        all_findings = []",
    "        with ThreadPoolExecutor(max_workers=len(active)) as pool:",
    "            futures = {pool.submit(agent.run): agent.DOMAIN for agent in active}",
    "            for future in as_completed(futures, timeout=1800):  # 30min max",
    "                domain = futures[future]",
    "                try:",
    "                    findings = future.result()",
    "                    logger.info('Agent %s returned %d findings', domain, len(findings))",
    "                    all_findings.extend(findings)",
    "                except Exception as e:",
    "                    logger.error('Agent %s failed: %s', domain, e)",
    "",
    "        # Deduplicate across agents using fingerprint",
    "        return self._deduplicate(all_findings)",
    "",
    "    def _deduplicate(self, findings: list[dict]) -> list[dict]:",
    "        seen = {}",
    "        for f in findings:",
    "            key = f\"{f.get('type')}:{f.get('endpoint')}\"",
    "            if key not in seen or f.get('confidence',0) > seen[key].get('confidence',0):",
    "                seen[key] = f",
    "        return list(seen.values())",
  ]),
  spacer(),

  stepHeader(24, "Integrate swarm into run_scan() as a third scan mode alongside agent and deterministic", "G", "2 hrs", "Pipeline wiring"),
  spacer(),
  infoBox("Edit file", "argus-workers/orchestrator_pkg/orchestrator.py — modify run_scan()"),
  spacer(),
  codeBlock([
    "# In run_scan(), the dispatch logic becomes three branches:",
    "",
    "scan_mode = job.get('scan_mode', 'agent')  # 'deterministic' | 'agent' | 'swarm'",
    "",
    "if scan_mode == 'swarm' and recon_context and self.llm_client and self.llm_client.is_available():",
    "    emit_thinking(self.engagement_id, 'Multi-agent swarm activating...')",
    "    from agent.swarm import SwarmOrchestrator",
    "    swarm = SwarmOrchestrator(",
    "        llm_service=LLMService(self.llm_client),",
    "        tool_runner=self.tool_runner,",
    "        recon_context=recon_context,",
    "        engagement_id=self.engagement_id",
    "    )",
    "    findings = swarm.run()",
    "    # Safety net still runs for any tool the swarm didn't cover",
    "    swarm_tools = {f.get('source_tool') for f in findings}",
    "    safety_findings = execute_scan_pipeline(",
    "        self, targets, job.get('budget', {}), scan_aggressiveness,",
    "        skip_tools=swarm_tools",
    "    )",
    "    findings.extend(safety_findings)",
    "",
    "elif scan_mode == 'agent' and agent_mode_enabled ...:",
    "    # existing agent path",
    "",
    "else:",
    "    # deterministic path",
  ]),
  spacer(),

  stepHeader(25, "Add swarm mode UI toggle, specialist activity feed, and test suite", "G", "3 hrs", "Frontend + Tests"),
  spacer(),
  h3("Frontend — Swarm Activity Feed"),
  body("When scan_mode='swarm', the engagement detail page shows three parallel columns in the Agent Reasoning Feed section: one per active specialist. Each column updates in real-time with the specialist's tool selections and observations. This makes the swarm visually legible — analysts see IDOR Agent running arjun in the left column while Auth Agent runs jwt_tool in the right column simultaneously."),
  spacer(),
  h3("New WebSocket event types"),
  codeBlock([
    "SWARM_AGENT_STARTED   = 'swarm_agent_started'   # {domain, engagement_id}",
    "SWARM_AGENT_ACTION    = 'swarm_agent_action'    # {domain, tool, reasoning, iteration}",
    "SWARM_AGENT_COMPLETE  = 'swarm_agent_complete'  # {domain, findings_count}",
    "SWARM_MERGE_COMPLETE  = 'swarm_merge_complete'  # {total_findings, dedup_removed}",
  ]),
  spacer(),
  h3("Test suite"),
  codeBlock([
    "# argus-workers/tests/test_swarm.py",
    "def test_idor_agent_activates_when_api_present():",
    "    rc = ReconContext(has_api=True, api_endpoints=['/api/v1/users'])",
    "    agent = IDORAgent(None, None, rc, 'test-id')",
    "    assert agent.should_activate() == True",
    "",
    "def test_auth_agent_skips_when_no_auth_signals():",
    "    rc = ReconContext(has_login_page=False, auth_endpoints=[], has_api=False)",
    "    agent = AuthAgent(None, None, rc, 'test-id')",
    "    assert agent.should_activate() == False",
    "",
    "def test_swarm_deduplicates_cross_agent_findings():",
    "    findings = [",
    "        {'type':'XSS','endpoint':'http://t.com/search','confidence':0.8,'source_tool':'dalfox'},",
    "        {'type':'XSS','endpoint':'http://t.com/search','confidence':0.9,'source_tool':'web_scanner'},",
    "    ]",
    "    swarm = SwarmOrchestrator.__new__(SwarmOrchestrator)",
    "    result = swarm._deduplicate(findings)",
    "    assert len(result) == 1",
    "    assert result[0]['confidence'] == 0.9  # higher confidence wins",
    "",
    "def test_swarm_runs_agents_in_parallel():",
    "    # Verify wall-clock time < sum of individual agent times",
    "    # (both agents sleep 1s → should complete in ~1s, not 2s)",
    "    ...",
  ]),
  spacer(),
  pageBreak()
);

// IMPLEMENTATION TIMELINE
children.push(
  h1("Implementation Timeline"),
  spacer(),
  body("Each week is independent — you can stop after any week and have working, valuable features."),
  spacer(),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [840, 2400, 2400, 3720],
    rows: [
      new TableRow({ children: ["Week","Features","Steps","What you have at end"].map(function(t,i) {
        return new TableCell({
          borders:bs, width:{size:[840,2400,2400,3720][i],type:WidthType.DXA},
          shading:{fill:C.navy,type:ShadingType.CLEAR},
          margins:{top:80,bottom:80,left:100,right:100},
          children:[new Paragraph({children:[new TextRun({text:t,font:"Arial",size:17,bold:true,color:C.white})]})]
        });
      })}),
      ...([
        ["Week 1","A — Self-Calibrating Confidence","Steps 1–3","Confidence scores reflect your org's real analyst verdicts. No other scanner does this."],
        ["Week 2","B — Target Memory","Steps 4–8","LLM agent gets smarter per rescan. First scan #5 where tool selection is informed by 4 prior results."],
        ["Week 3","C — Continuous Monitoring","Steps 9–11","Automated diff on every scheduled scan. Regressions surface instantly. Fixed findings auto-close."],
        ["Week 4","D — Live PoC Generator","Steps 12–14","Every HIGH/CRITICAL finding has a weaponised PoC automatically attached."],
        ["Week 5","E — Natural Language Config","Steps 15–17","Non-technical analysts can configure scans in plain English with zero form expertise."],
        ["Week 6","F — Developer Fix Assistant","Steps 18–21","Findings include PR-ready code fixes tailored to the detected tech stack."],
        ["Week 7","G — Multi-Agent Swarm","Steps 22–25","Parallel specialist agents run concurrently. IDOR + Auth + API hunt simultaneously."],
      ]).map(function(row,i) {
        return new TableRow({children: row.map(function(cell,j) {
          return new TableCell({
            borders:bs, width:{size:[840,2400,2400,3720][j],type:WidthType.DXA},
            shading:{fill:i%2===0?C.white:C.grey,type:ShadingType.CLEAR},
            margins:{top:80,bottom:80,left:100,right:100},
            children:[new Paragraph({children:[new TextRun({text:cell,font:"Arial",size:17})]})]
          });
        })});
      })
    ]
  }),
  spacer(),

  h2("Files Changed / Created — Full Reference"),
  spacer(),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [480, 5280, 1440, 2160],
    rows: [
      new TableRow({ children: ["#","File","Action","Feature"].map(function(t,i) {
        return new TableCell({
          borders:bs, width:{size:[480,5280,1440,2160][i],type:WidthType.DXA},
          shading:{fill:C.navy,type:ShadingType.CLEAR},
          margins:{top:70,bottom:70,left:80,right:80},
          children:[new Paragraph({children:[new TextRun({text:t,font:"Arial",size:16,bold:true,color:C.white})]})]
        });
      })}),
      ...([
        ["1","argus-platform/db/migrations/035_tool_accuracy.sql","CREATE","A"],
        ["2","argus-workers/models/feedback.py","EDIT","A"],
        ["3","argus-workers/intelligence_engine.py","EDIT","A"],
        ["4","argus-platform/db/migrations/036_target_profiles.sql","CREATE","B"],
        ["5","argus-workers/database/repositories/target_profile_repository.py","CREATE","B"],
        ["6","argus-workers/orchestrator_pkg/orchestrator.py","EDIT","B,C,D,F"],
        ["7","argus-workers/models/recon_context.py","EDIT","B"],
        ["8","argus-workers/orchestrator_pkg/recon.py","EDIT","B"],
        ["9","argus-workers/agent/agent_prompts.py","EDIT","B,E,G"],
        ["10","argus-workers/scan_diff_engine.py","CREATE","C"],
        ["11","argus-workers/tasks/diff.py","CREATE","C"],
        ["12","argus-workers/tasks/scheduled.py","EDIT","C"],
        ["13","argus-platform/src/app/monitoring/page.tsx","CREATE","C"],
        ["14","argus-platform/src/app/api/monitoring/diff/[id]/route.ts","CREATE","C"],
        ["15","argus-workers/poc_generator.py","CREATE","D"],
        ["16","argus-platform/db/migrations/037_poc_generated.sql","CREATE","D"],
        ["17","argus-platform/src/app/findings/[id]/page.tsx","EDIT","D,F"],
        ["18","argus-platform/src/app/api/findings/[id]/poc/route.ts","CREATE","D"],
        ["19","argus-workers/intent_parser.py","CREATE","E"],
        ["20","argus-platform/src/app/api/engagements/parse-intent/route.ts","CREATE","E"],
        ["21","argus-platform/src/app/engagements/page.tsx","EDIT","E"],
        ["22","argus-workers/developer_fix_assistant.py","CREATE","F"],
        ["23","argus-platform/db/migrations/038_remediation_fix.sql","CREATE","F"],
        ["24","argus-workers/agent/swarm.py","CREATE","G"],
        ["25","argus-workers/websocket_events.py","EDIT","G"],
        ["26","argus-workers/tests/test_swarm.py","CREATE","G"],
        ["27","argus-workers/tests/test_scan_diff.py","CREATE","C"],
        ["28","argus-workers/tests/test_poc_generator.py","CREATE","D"],
        ["29","argus-workers/tests/test_intent_parser.py","CREATE","E"],
        ["30","argus-workers/tests/test_target_memory.py","CREATE","B"],
      ]).map(function(row,i) {
        return new TableRow({children: row.map(function(cell,j) {
          return new TableCell({
            borders:bs, width:{size:[480,5280,1440,2160][j],type:WidthType.DXA},
            shading:{fill:i%2===0?C.white:C.grey,type:ShadingType.CLEAR},
            margins:{top:55,bottom:55,left:80,right:80},
            children:[new Paragraph({children:[new TextRun({text:cell,font:j===1?"Courier New":"Arial",size:j===1?15:16})]})]
          });
        })});
      })
    ]
  })
);

// Build document
const doc = new Document({
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
  ]},
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, font: "Arial", color: C.navy }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, font: "Arial", color: C.blue }, paragraph: { spacing: { before: 280, after: 100 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 20, bold: true, font: "Arial", color: C.orange }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 } },
    ]
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } } },
    children
  }]
});

Packer.toBuffer(doc).then(function(buf) {
  fs.writeFileSync('/mnt/user-data/outputs/Argus_Differentiation_Plan.docx', buf);
  console.log('Done — ' + buf.length + ' bytes');
});
