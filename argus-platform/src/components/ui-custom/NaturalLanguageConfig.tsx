"use client";

import { motion } from "framer-motion";
import { Brain, Loader2, MessageSquare, AlertTriangle, CheckCircle, Edit3, Zap } from "lucide-react";

interface NaturalLanguageConfigProps {
  nlIntent: string;
  nlLoading: boolean;
  nlError: string;
  nlResult: Record<string, string | boolean | string[]> | null;
  nlIsFallback: boolean;
  onIntentChange: (value: string) => void;
  onParseIntent: () => void;
  onStartScan: () => void;
  onEditDetails: () => void;
}

export default function NaturalLanguageConfig({
  nlIntent,
  nlLoading,
  nlError,
  nlResult,
  nlIsFallback,
  onIntentChange,
  onParseIntent,
  onStartScan,
  onEditDetails,
}: NaturalLanguageConfigProps) {
  return (
    <div className="space-y-5">
      {/* Intent Input */}
      <div>
        <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
          Describe Your Scan Intent
        </label>
        <textarea
          value={nlIntent}
          onChange={(e) => onIntentChange(e.target.value)}
          placeholder={`Describe what you want to scan in plain English...

Examples:
• "Scan https://example.com for IDOR and auth bypass vulnerabilities. Focus on high severity."
• "Run a comprehensive scan of my Node.js API at https://api.example.com. Look for injection flaws."
• "Quick security check of https://shop.example.com — prioritize XSS and CSRF."`}
          rows={5}
          maxLength={5000}
          className="w-full px-4 py-3 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-sm font-body text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-300 placeholder:text-on-surface-variant/40 dark:placeholder:text-[#8A8A9E]/40 resize-none"
        />
        <div className="flex items-center justify-between mt-1">
          <span className="text-[10px] font-mono text-on-surface-variant/50 dark:text-[#8A8A9E]/50">
            {nlIntent.length}/5000
          </span>
        </div>
      </div>

      <button
        type="button"
        onClick={onParseIntent}
        disabled={nlLoading || !nlIntent.trim()}
        className={`w-full flex items-center justify-center gap-2 py-3 text-xs font-bold uppercase tracking-[0.2em] rounded-lg transition-all duration-300 font-body ${
          nlLoading
            ? "bg-transparent text-primary border border-primary/40"
            : "bg-primary text-on-primary hover:opacity-90 shadow-glow"
        } disabled:opacity-50`}
      >
        {nlLoading ? (
          <>
            <Loader2 size={14} className="animate-spin" />
            Parsing Intent...
          </>
        ) : (
          <>
            <Brain size={14} />
            Parse Intent
          </>
        )}
      </button>

      {/* NL Error */}
      {nlError && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-start gap-2 p-3 bg-error/5 border border-error/20 rounded-lg"
        >
          <AlertTriangle size={14} className="text-error shrink-0 mt-0.5" />
          <span className="text-xs text-error">{nlError}</span>
        </motion.div>
      )}

      {/* NL Result */}
      {nlResult && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-4 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg space-y-3"
        >
          <div className="flex items-center gap-2">
            {nlIsFallback ? (
              <AlertTriangle size={14} className="text-amber-500" />
            ) : (
              <CheckCircle size={14} className="text-green-500" />
            )}
            <span className="text-[11px] font-bold text-on-surface dark:text-[#F0F0F5] uppercase tracking-wider">
              {nlIsFallback ? "Partial Parse (fallback)" : "Parsed Configuration"}
            </span>
          </div>

          {nlIsFallback && (
            <p className="text-[10px] text-amber-500">
              Your intent was partially understood. Results may require manual adjustments.
            </p>
          )}

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="text-on-surface-variant dark:text-[#8A8A9E]">Target:</div>
            <div className="text-on-surface dark:text-[#F0F0F5] font-mono">
              {String(nlResult.target_url || "—")}
            </div>
            <div className="text-on-surface-variant dark:text-[#8A8A9E]">Scan Type:</div>
            <div className="text-on-surface dark:text-[#F0F0F5] font-mono">
              {String(nlResult.scan_type || "url")}
            </div>
            <div className="text-on-surface-variant dark:text-[#8A8A9E]">Aggressiveness:</div>
            <div className="text-on-surface dark:text-[#F0F0F5] font-mono">
              {String(nlResult.aggressiveness || "default")}
            </div>
            <div className="text-on-surface-variant dark:text-[#8A8A9E]">Agent Mode:</div>
            <div className="text-on-surface dark:text-[#F0F0F5] font-mono">
              {nlResult.agent_mode ? "Enabled" : "Disabled"}
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onStartScan}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-primary text-on-primary text-xs font-bold uppercase tracking-wider rounded-lg hover:opacity-90 transition-all duration-300 font-body"
            >
              <Zap size={14} />
              Launch Scan
            </button>
            <button
              type="button"
              onClick={onEditDetails}
              className="flex items-center justify-center gap-2 px-4 py-2.5 border border-outline-variant dark:border-[#ffffff10] text-on-surface dark:text-[#F0F0F5] text-xs font-bold uppercase tracking-wider rounded-lg hover:bg-surface-container dark:hover:bg-[#1A1A24] transition-all duration-300 font-body"
            >
              <Edit3 size={14} />
              Edit
            </button>
          </div>
        </motion.div>
      )}
    </div>
  );
}
