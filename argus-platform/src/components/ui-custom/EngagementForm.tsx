"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Target,
  Loader2,
  Globe,
  GitBranch,
  ChevronDown,
  ChevronUp,
  X,
  History,
  Trash2,
  Zap,
  Shield,
  MessageSquare,
  Brain,
  AlertTriangle,
  CheckCircle,
  Edit3,
} from "lucide-react";
import AuthWizard from "@/components/ui-custom/AuthWizard";
import ScanModeHelp from "@/components/ui-custom/ScanModeHelp";
import NaturalLanguageConfig from "@/components/ui-custom/NaturalLanguageConfig";
import type { Engagement } from "@/hooks/useEngagements";

interface URLHistoryItem {
  url: string;
  timestamp: number;
  scanType: "url" | "repo";
}

interface Template {
  id: string;
  name: string;
  description: string;
  config: Record<string, unknown>;
}

interface EngagementFormProps {
  // Form state
  scanType: "url" | "repo";
  target: string;
  scanAggressiveness: string;
  agentMode: boolean;
  scanMode: "agent" | "swarm";
  bugBounty: boolean;
  priorityVulnClasses: string[];
  isLoading: boolean;
  progressStep: string;
  error: string;
  settingsLoading: boolean;

  // NL state
  configMode: "standard" | "nl";
  nlIntent: string;
  nlLoading: boolean;
  nlError: string;
  nlResult: Record<string, string | boolean | string[]> | null;
  nlIsFallback: boolean;

  // Auth wizard
  authConfig: Record<string, unknown> | null;
  dualAuthConfig: Record<string, unknown> | null;
  showAuthWizard: boolean;

  // Templates
  templates: Template[];
  templatesLoading: boolean;
  selectedTemplateId: string;

  // History
  history: URLHistoryItem[];
  showAllHistory: boolean;

  // Setters
  onScanTypeChange: (val: "url" | "repo") => void;
  onTargetChange: (val: string) => void;
  onScanAggressivenessChange: (val: string) => void;
  onAgentModeChange: (val: boolean) => void;
  onScanModeChange: (val: "agent" | "swarm") => void;
  onBugBountyChange: (val: boolean) => void;
  onPriorityVulnClassesChange: (val: string[]) => void;
  onConfigModeChange: (val: "standard" | "nl") => void;
  onNlIntentChange: (val: string) => void;
  onNlResultChange: (val: Record<string, string | boolean | string[]> | null) => void;
  onNlErrorChange: (val: string) => void;
  onShowAllHistoryChange: (val: boolean) => void;
  onAuthConfigChange: (val: Record<string, unknown> | null) => void;
  onDualAuthConfigChange: (val: Record<string, unknown> | null) => void;
  onShowAuthWizardChange: (val: boolean) => void;
  onSelectedTemplateChange: (val: string) => void;

  // Handlers
  onParseIntent: () => void;
  onNlStartScan: () => void;
  onNlEditDetails: () => void;
  onSubmit: (e: React.FormEvent) => void;
  onRemoveHistory: (url: string) => void;
  onClearHistory: () => void;

  // Refs for template variable UI
  templateVariables: Record<string, string>;
  onTemplateVariablesChange: (val: Record<string, string>) => void;
  showVariablePrompt: boolean;
  onShowVariablePromptChange: (val: boolean) => void;
  pendingTemplateConfig: Record<string, unknown> | null;
  onPendingTemplateConfigChange: (val: Record<string, unknown> | null) => void;
}

const VULN_CLASSES = [
  "SQL Injection",
  "XSS",
  "IDOR",
  "SSRF",
  "RCE",
  "Authentication Bypass",
  "Authorization Bypass",
  "CSRF",
  "Open Redirect",
  "SSTI",
  "LFI",
  "NoSQL Injection",
] as const;

export default function EngagementForm({
  scanType, target, scanAggressiveness, agentMode, scanMode, bugBounty, priorityVulnClasses,
  isLoading, progressStep, error, settingsLoading,
  configMode, nlIntent, nlLoading, nlError, nlResult, nlIsFallback,
  authConfig, dualAuthConfig, showAuthWizard,
  templates, templatesLoading, selectedTemplateId,
  history, showAllHistory,
  onScanTypeChange, onTargetChange, onScanAggressivenessChange, onAgentModeChange,
  onScanModeChange, onBugBountyChange, onPriorityVulnClassesChange,
  onConfigModeChange, onNlIntentChange, onNlResultChange, onNlErrorChange,
  onShowAllHistoryChange, onAuthConfigChange, onDualAuthConfigChange,
  onShowAuthWizardChange, onSelectedTemplateChange,
  onParseIntent, onNlStartScan, onNlEditDetails, onSubmit,
  onRemoveHistory, onClearHistory,
  templateVariables, onTemplateVariablesChange, showVariablePrompt, onShowVariablePromptChange,
  pendingTemplateConfig, onPendingTemplateConfigChange,
}: EngagementFormProps) {
  const [focusedField, setFocusedField] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const vulnToggle = (vuln: string) => {
    if (priorityVulnClasses.includes(vuln)) {
      onPriorityVulnClassesChange(priorityVulnClasses.filter((v) => v !== vuln));
    } else {
      onPriorityVulnClassesChange([...priorityVulnClasses, vuln]);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, delay: 0.1 }}
      className="col-span-12 lg:col-span-7 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 transition-all duration-300 hover:border-primary/20"
    >
      <div className="flex items-center gap-2 mb-6">
        <Target size={18} className="text-primary" />
        <h2 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">New Scan Engagement</h2>
      </div>

      {/* Configuration Mode Toggle */}
      <div className="flex gap-2 mb-6 p-1 bg-surface-container dark:bg-[#1A1A24] rounded-lg">
        <button
          type="button"
          onClick={() => { onConfigModeChange("standard"); onNlResultChange(null); onNlErrorChange(""); }}
          className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider rounded-md transition-all duration-300 font-body ${
            configMode === "standard"
              ? "bg-primary text-on-primary shadow-glow"
              : "text-on-surface-variant dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5]"
          }`}
        >
          Standard
        </button>
        <button
          type="button"
          onClick={() => onConfigModeChange("nl")}
          className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider rounded-md transition-all duration-300 font-body flex items-center justify-center gap-1.5 ${
            configMode === "nl"
              ? "bg-primary text-on-primary shadow-glow"
              : "text-on-surface-variant dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5]"
          }`}
        >
          <MessageSquare size={13} />
          Natural Language
        </button>
      </div>

      {/* Natural Language Mode */}
      {configMode === "nl" ? (
        <NaturalLanguageConfig
          nlIntent={nlIntent}
          nlLoading={nlLoading}
          nlError={nlError}
          nlResult={nlResult}
          nlIsFallback={nlIsFallback}
          onIntentChange={onNlIntentChange}
          onParseIntent={onParseIntent}
          onStartScan={onNlStartScan}
          onEditDetails={onNlEditDetails}
        />
      ) : (
        <form onSubmit={onSubmit} className="space-y-5">
          {/* Target Input with History */}
          <div>
            <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
              Target
            </label>
            <div className="relative">
              <div className="absolute left-3 top-1/2 -translate-y-1/2 flex items-center gap-1">
                {scanType === "url" ? (
                  <Globe size={14} className="text-primary" />
                ) : (
                  <GitBranch size={14} className="text-primary" />
                )}
              </div>
              <input
                type="text"
                value={target}
                onChange={(e) => onTargetChange(e.target.value)}
                onFocus={() => setFocusedField("target")}
                onBlur={() => setFocusedField(null)}
                placeholder={scanType === "url" ? "https://example.com" : "https://github.com/org/repo"}
                disabled={isLoading}
                className={`w-full pl-10 pr-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] rounded-lg text-sm font-body text-on-surface dark:text-[#F0F0F5] outline-none transition-all duration-200 placeholder:text-on-surface-variant/40 dark:placeholder:text-[#8A8A9E]/40 border ${
                  focusedField === "target"
                    ? "border-primary ring-2 ring-primary/10"
                    : "border-transparent"
                } disabled:opacity-50`}
              />
            </div>
          </div>

          {/* Scan Type Toggle */}
          <div>
            <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
              Scan Type
            </label>
            <div className="flex gap-2 p-1 bg-surface-container dark:bg-[#1A1A24] rounded-lg">
              <button
                type="button"
                onClick={() => onScanTypeChange("url")}
                className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold uppercase tracking-wider rounded-md transition-all duration-300 font-body ${
                  scanType === "url"
                    ? "bg-primary text-on-primary shadow-glow"
                    : "text-on-surface-variant dark:text-[#8A8A9E]"
                }`}
              >
                <Globe size={14} />
                Web App
              </button>
              <button
                type="button"
                onClick={() => onScanTypeChange("repo")}
                className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold uppercase tracking-wider rounded-md transition-all duration-300 font-body ${
                  scanType === "repo"
                    ? "bg-primary text-on-primary shadow-glow"
                    : "text-on-surface-variant dark:text-[#8A8A9E]"
                }`}
              >
                <GitBranch size={14} />
                Repository
              </button>
            </div>
          </div>

          {/* Scan Mode Row */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                Scan Mode
              </label>
              <select
                value={scanMode}
                onChange={(e) => onScanModeChange(e.target.value as "agent" | "swarm")}
                disabled={isLoading}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] rounded-lg text-sm font-body text-on-surface dark:text-[#F0F0F5] outline-none border border-transparent focus:border-primary transition-all duration-200 disabled:opacity-50"
              >
                <option value="agent">🤖 Agent Mode</option>
                <option value="swarm">🐝 Swarm Mode</option>
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                Aggressiveness
              </label>
              <select
                value={scanAggressiveness}
                onChange={(e) => onScanAggressivenessChange(e.target.value)}
                disabled={isLoading}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] rounded-lg text-sm font-body text-on-surface dark:text-[#F0F0F5] outline-none border border-transparent focus:border-primary transition-all duration-200 disabled:opacity-50"
              >
                <option value="default">Default</option>
                <option value="high">High</option>
                <option value="extreme">Extreme</option>
              </select>
            </div>
          </div>

          {/* Agent Mode Toggle */}
          <div className="flex items-center justify-between p-3 bg-surface-container dark:bg-[#1A1A24] rounded-lg">
            <div className="flex items-center gap-2">
              <Zap size={14} className="text-primary" />
              <div>
                <span className="text-xs font-semibold text-on-surface dark:text-[#F0F0F5]">AI Agent Mode</span>
                <p className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E]">Let AI drive scan decisions adaptively</p>
              </div>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={agentMode}
                onChange={(e) => onAgentModeChange(e.target.checked)}
                disabled={isLoading}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-surface-container-high dark:bg-[#2A2A3A] rounded-full peer peer-checked:bg-primary peer-focus:ring-2 peer-focus:ring-primary/30 after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
            </label>
          </div>

          {/* Template Selector (if available) */}
          {templates.length > 0 && (
            <div>
              <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                Engagement Template
              </label>
              <select
                value={selectedTemplateId}
                onChange={(e) => onSelectedTemplateChange(e.target.value)}
                disabled={isLoading || templatesLoading}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] rounded-lg text-sm font-body text-on-surface dark:text-[#F0F0F5] outline-none border border-transparent focus:border-primary transition-all duration-200 disabled:opacity-50"
              >
                <option value="">No template (manual config)</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Auth Wizard */}
          <div>
            <button
              type="button"
              onClick={() => onShowAuthWizardChange(!showAuthWizard)}
              className="flex items-center gap-2 text-xs font-semibold text-primary hover:text-primary/80 transition-colors"
            >
              <Shield size={14} />
              {authConfig ? "Edit Auth Configuration" : "Configure Authentication"}
              {authConfig && <CheckCircle size={12} className="text-green-500" />}
            </button>
            {showAuthWizard && (
              <div className="mt-3">
                <AuthWizard
                  targetUrl={target}
                  onComplete={(config) => { onAuthConfigChange(config as unknown as Record<string, unknown> | null); onShowAuthWizardChange(false); }}
                  onSkip={() => onShowAuthWizardChange(false)}
                />
              </div>
            )}
          </div>

          {/* ScanModeHelp for scanning mode explanation */}
          <ScanModeHelp />

          {/* Advanced Settings Toggle */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-2 text-xs font-semibold text-on-surface-variant dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5] transition-colors"
          >
            {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            Advanced Settings
          </button>

          {showAdvanced && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-4"
            >
              {/* Bug Bounty Mode */}
              <div className="flex items-center justify-between p-3 bg-surface-container dark:bg-[#1A1A24] rounded-lg">
                <div className="flex items-center gap-2">
                  <Shield size={14} className="text-amber-500" />
                  <div>
                    <span className="text-xs font-semibold text-on-surface dark:text-[#F0F0F5]">Bug Bounty Mode</span>
                    <p className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E]">Limit scanning to safe checks only</p>
                  </div>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={bugBounty}
                    onChange={(e) => onBugBountyChange(e.target.checked)}
                    disabled={isLoading}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-surface-container-high dark:bg-[#2A2A3A] rounded-full peer peer-checked:bg-amber-500 peer-focus:ring-2 peer-focus:ring-amber-500/30 after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
                </label>
              </div>

              {/* Priority Vulnerability Classes */}
              <div>
                <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                  Priority Vulnerability Classes
                </label>
                <div className="flex flex-wrap gap-2">
                  {VULN_CLASSES.map((vuln) => (
                    <button
                      key={vuln}
                      type="button"
                      onClick={() => vulnToggle(vuln)}
                      disabled={isLoading}
                      className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full transition-all duration-200 font-body ${
                        priorityVulnClasses.includes(vuln)
                          ? "bg-primary/20 text-primary border border-primary/40"
                          : "bg-surface-container dark:bg-[#1A1A24] text-on-surface-variant dark:text-[#8A8A9E] border border-transparent hover:border-outline-variant dark:hover:border-[#ffffff10]"
                      } disabled:opacity-50`}
                    >
                      {vuln}
                    </button>
                  ))}
                </div>
              </div>
            </motion.div>
          )}

          {/* URL History */}
          {history.length > 0 && (
            <div className="pt-2">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <History size={12} className="text-on-surface-variant dark:text-[#8A8A9E]" />
                  <span className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">Recent Targets</span>
                </div>
                <button
                  type="button"
                  onClick={onClearHistory}
                  className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] hover:text-error transition-colors"
                >
                  Clear
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(showAllHistory ? history : history.slice(0, 3)).map((item) => (
                  <button
                    key={item.url + item.timestamp}
                    type="button"
                    onClick={() => onTargetChange(item.url)}
                    className="group flex items-center gap-1.5 px-2 py-1 bg-surface-container dark:bg-[#1A1A24] rounded-md text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] hover:bg-primary/10 hover:text-primary transition-all duration-200"
                  >
                    {item.scanType === "repo" ? <GitBranch size={10} /> : <Globe size={10} />}
                    <span className="max-w-[120px] truncate">{item.url}</span>
                    <X
                      size={10}
                      onClick={(e) => { e.stopPropagation(); onRemoveHistory(item.url); }}
                      className="opacity-0 group-hover:opacity-100 hover:text-error transition-all"
                    />
                  </button>
                ))}
                {history.length > 3 && !showAllHistory && (
                  <button
                    type="button"
                    onClick={() => onShowAllHistoryChange(true)}
                    className="text-[10px] text-primary hover:text-primary/80 px-2"
                  >
                    +{history.length - 3} more
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Error message */}
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-start gap-2 p-3 bg-error/5 border border-error/20 rounded-lg"
            >
              <AlertTriangle size={14} className="text-error shrink-0 mt-0.5" />
              <span className="text-xs text-error">{error}</span>
            </motion.div>
          )}

          {/* Loading state with progress */}
          {isLoading && progressStep && (
            <div className="flex items-center gap-3 p-3 bg-primary/5 border border-primary/20 rounded-lg">
              <Loader2 size={14} className="animate-spin text-primary" />
              <span className="text-xs text-primary">{progressStep}</span>
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={isLoading || !target.trim()}
            className="w-full flex items-center justify-center gap-2 py-3 bg-primary text-on-primary text-xs font-bold uppercase tracking-[0.2em] rounded-lg hover:opacity-90 transition-all duration-300 shadow-glow font-body disabled:opacity-50"
          >
            {isLoading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                {progressStep || "Launching..."}
              </>
            ) : (
              <>
                <Zap size={14} />
                Launch Engagement
              </>
            )}
          </button>
        </form>
      )}
    </motion.div>
  );
}
