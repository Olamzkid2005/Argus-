// Shared job message contract between frontend and workers
// Must stay in sync with argus-workers/job_schema.py

export type JobType =
  | "recon" | "scan" | "analyze" | "report" | "repo_scan"
  | "compliance_report" | "full_report" | "asset_discovery" | "asset_risk_scoring"
  | "bugbounty_report";

export const TASK_NAME_MAP: Record<JobType, string> = {
  recon: "tasks.recon.run_recon",
  scan: "tasks.scan.run_scan",
  analyze: "tasks.analyze.run_analysis",
  report: "tasks.report.generate_report",
  repo_scan: "tasks.repo_scan.run_repo_scan",
  compliance_report: "tasks.report.generate_compliance_report",
  full_report: "tasks.report.generate_full_report",
  asset_discovery: "tasks.asset_discovery.run_asset_discovery",
  asset_risk_scoring: "tasks.asset_discovery.update_asset_risk_scores",
  bugbounty_report: "tasks.bugbounty.generate_bugbounty_report",
};

export interface JobMessage {
  type: JobType;
  engagement_id: string;
  target: string;
  repo_url?: string;
  standard?: string;
  report_id?: string;
  org_id?: string;
  budget: {
    max_cycles: number;
    max_depth: number;
  };
  aggressiveness?: string;
  agent_mode?: boolean;
  trace_id: string;
  created_at: string;
}
