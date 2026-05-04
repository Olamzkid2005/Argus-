"use client";

import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Loader2, Clock, History, Terminal } from "lucide-react";
import { useScanEstimates } from "@/hooks/useScanEstimates";

interface ActiveEngagementPanelProps {
  isConnected: boolean;
  scannerActivities: any[];
  currentState: string;
  engagementStart?: string;
}

function ScanStepTimeline({
  currentState,
  activities,
  engagementStart,
}: {
  currentState: string;
  activities: any[];
  engagementStart?: string;
}) {
  const {
    phaseEstimates,
    getPhaseStatus,
    getPhaseElapsed,
    getPhaseRemaining,
    getPhaseProgress,
    getPhaseCompletionTime,
    phaseHistory,
    formatDuration,
  } = useScanEstimates(currentState, {}, engagementStart);

  const steps = phaseEstimates;

  const completedCount = steps.filter((s) => getPhaseStatus(s.id) === "completed").length;
  const inProgressCount = steps.filter((s) => getPhaseStatus(s.id) === "in_progress").length;
  const progress = steps.length > 0 ? ((completedCount + inProgressCount * 0.5) / steps.length) * 100 : 0;

  const activeActivity = activities.find((a) => a.status === "started" || a.status === "in_progress");

  const getStepIcon = (status: string) => {
    if (status === "completed") {
      return <CheckCircle2 size={14} className="text-primary shrink-0" />;
    }
    if (status === "in_progress") {
      return <Loader2 size={14} className="text-primary animate-spin shrink-0" />;
    }
    return <Clock size={14} className="text-on-surface-variant dark:text-[#8A8A9E] shrink-0" />;
  };

  return (
    <div className="space-y-5">
      <div className="h-2 w-full bg-surface-container dark:bg-[#1A1A24] rounded-full overflow-hidden">
        <motion.div
          className="h-full bg-primary rounded-full"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>

      <div className="space-y-4">
        {steps.map((step, i) => {
          const status = getPhaseStatus(step.id);
          const completionTime = getPhaseCompletionTime(step.id);
          const phaseElapsed = getPhaseElapsed(step.id);
          const phaseRemaining = getPhaseRemaining(step.id);
          const phaseProgress = getPhaseProgress(step.id);

          return (
            <div key={step.id} className="space-y-2">
              <div className="flex items-center gap-3">
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold transition-all duration-300 shrink-0 ${
                    status === "completed"
                      ? "bg-primary text-on-primary"
                      : status === "in_progress"
                      ? "bg-primary/10 text-primary border border-primary"
                      : "bg-surface-container dark:bg-[#1A1A24] text-on-surface-variant dark:text-[#8A8A9E]"
                  }`}
                >
                  {status === "completed" ? <CheckCircle2 size={14} /> : i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-sm font-body transition-colors duration-300 ${
                        status === "completed"
                          ? "text-on-surface dark:text-[#F0F0F5]"
                          : status === "in_progress"
                          ? "text-primary font-medium"
                          : "text-on-surface-variant dark:text-[#8A8A9E]"
                      }`}
                    >
                      {step.label}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {status === "in_progress" && phaseRemaining > 0 && (
                        <span className="text-[10px] font-mono text-primary">
                          {formatDuration(phaseRemaining)} remaining
                        </span>
                      )}
                      {status === "completed" && completionTime && (
                        <span className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E]">
                          {completionTime.toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      )}
                      {getStepIcon(status)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="pl-10">
                <div className="h-1 w-full bg-surface-container dark:bg-[#1A1A24] rounded-full overflow-hidden mb-1">
                  <motion.div
                    className="h-full bg-primary rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${phaseProgress}%` }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                  />
                </div>
                <div className="flex items-center justify-between text-[10px] text-on-surface-variant dark:text-[#8A8A9E] font-mono">
                  <span>
                    {status === "completed"
                      ? `Completed in ${formatDuration(phaseElapsed)}`
                      : status === "in_progress"
                      ? `${phaseProgress}% • ${formatDuration(phaseElapsed)} elapsed`
                      : `Estimated ~${step.estimatedMinutes} min`}
                  </span>
                  <span>
                    {status === "pending" ? `~${step.estimatedMinutes} min` : `${phaseProgress}%`}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {phaseHistory.length > 0 && (
        <div className="pt-3 border-t border-outline-variant dark:border-[#ffffff08]">
          <div className="flex items-center gap-1.5 mb-2">
            <History size={12} className="text-on-surface-variant dark:text-[#8A8A9E]" />
            <span className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">
              Phase History
            </span>
          </div>
          <div className="space-y-1.5">
            {phaseHistory.map((phase) => (
              <div key={phase.id} className="flex items-center gap-2 text-[11px]">
                <CheckCircle2 size={12} className="text-primary shrink-0" />
                <span className="text-on-surface dark:text-[#F0F0F5] font-body">{phase.label}</span>
                <span className="text-on-surface-variant dark:text-[#8A8A9E] font-mono ml-auto">
                  completed at{" "}
                  {phase.completionTime?.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeActivity && (
        <div className="pt-3 border-t border-outline-variant dark:border-[#ffffff08]">
          <div className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1.5">
            Current Operation
          </div>
          <div className="flex items-center gap-2">
            <Loader2 size={12} className="text-primary animate-spin shrink-0" />
            <span className="text-xs font-body text-on-surface dark:text-[#F0F0F5] truncate">
              {activeActivity.tool_name}: {activeActivity.activity}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ActiveEngagementPanel({
  isConnected,
  scannerActivities,
  currentState,
  engagementStart,
}: ActiveEngagementPanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.3 }}
      className="col-span-12 lg:col-span-4 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl overflow-hidden transition-all duration-300 hover:border-primary/20"
    >
      <div className="flex items-center gap-2 px-5 py-4 border-b border-outline-variant dark:border-[#ffffff08]">
        <Terminal size={16} className="text-primary" />
        <h2 className="text-sm font-headline font-medium text-on-surface dark:text-[#F0F0F5] tracking-wide uppercase">Scanner Activity</h2>
        {isConnected && scannerActivities.some((a) => a.status === "started" || a.status === "in_progress") && (
          <div className="ml-auto flex items-center gap-1.5">
            <motion.span
              className="relative flex h-2 w-2"
              animate={{ scale: [1, 1.3, 1], opacity: [1, 0.7, 1] }}
              transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
            >
              <span className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
            </motion.span>
            <span className="text-[10px] font-mono text-primary uppercase">Live</span>
          </div>
        )}
      </div>
      <div className="p-5">
        <AnimatePresence mode="wait">
          {isConnected ? (
            <motion.div
              key="timeline"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3 }}
            >
              <ScanStepTimeline currentState={currentState} activities={scannerActivities} engagementStart={engagementStart} />
            </motion.div>
          ) : (
            <motion.div
              key="empty"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3 }}
              className="flex flex-col items-center justify-center py-10 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3"
            >
              <Terminal size={24} />
              <p className="text-[10px] font-mono uppercase tracking-widest text-center">
                Connect to an engagement to view scanner activity
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
