"use client";

import { useEffect } from "react";
import { useSession, signIn } from "next-auth/react";
import { motion } from "framer-motion";
import { ShieldCheck, Loader2 } from "lucide-react";
import { log } from "@/lib/logger";
import { useEngagements } from "@/hooks/useEngagements";
import EngagementForm from "@/components/ui-custom/EngagementForm";
import EngagementList from "@/components/ui-custom/EngagementList";
import SkeletonLoader from "@/components/ui-custom/SkeletonLoader";

export default function EngagementsPage() {
  useEffect(() => {
    log.pageMount("Engagements");
    return () => log.pageUnmount("Engagements");
  }, []);

  const { data: session, status } = useSession();

  const {
    // Form state
    scanType, setScanType,
    target, setTarget,
    scanAggressiveness, setScanAggressiveness,
    agentMode, setAgentMode,
    scanMode, setScanMode,
    bugBounty, setBugBounty,
    priorityVulnClasses, setPriorityVulnClasses,
    isLoading,
    progressStep,
    error,
    settingsLoading,

    // NL state
    configMode, setConfigMode,
    nlIntent, setNlIntent,
    nlLoading,
    nlError, setNlError,
    nlResult, setNlResult,
    nlIsFallback,

    // Auth wizard
    authConfig, setAuthConfig,
    dualAuthConfig, setDualAuthConfig,
    showAuthWizard, setShowAuthWizard,

    // Templates
    templates,
    templatesLoading,
    selectedTemplateId, setSelectedTemplateId,

    // History
    history,
    showAllHistory, setShowAllHistory,
    removeFromHistory, clearHistory,

    // Engagements
    liveEngagements,
    liveLoading,

    // Computed
    analyticsData,

    // Handlers
    handleSubmit,
    handleDelete,
    handleStop,
    handleRescan,
    handleParseIntent,
    handleNlStartScan,
    handleNlEditDetails,
    getScanProgress,
    stoppingId,
    rescannings,
    templateVariables, setTemplateVariables,
    showVariablePrompt, setShowVariablePrompt,
    pendingTemplateConfig, setPendingTemplateConfig,
  } = useEngagements();

  if (status === "loading") {
    return <SkeletonLoader className="min-h-screen" />;
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-background dark:bg-[#0A0A0F] matrix-grid">
      <style jsx>{`
        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        .shimmer {
          background: linear-gradient(90deg, transparent 0%, rgba(103, 32, 255, 0.08) 50%, transparent 100%);
          background-size: 200% 100%;
          animation: shimmer 1.5s infinite;
        }
      `}</style>
      <div className="max-w-[1440px] mx-auto px-4 sm:px-6 py-8">
        {/* ── Header ── */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-8"
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <ShieldCheck size={18} className="text-primary" />
            </div>
            <span className="text-xs font-body text-on-surface-variant dark:text-[#8A8A9E] tracking-widest uppercase">
              Operations Center
            </span>
          </div>
          <h1 className="text-4xl font-headline font-semibold text-gray-900 dark:text-[#F0F0F5] tracking-tight">
            Security Engagements
          </h1>
          <p className="text-sm font-body text-on-surface-variant dark:text-[#8A8A9E] mt-1">
            Launch penetration tests and monitor active security operations
          </p>
        </motion.div>

        {/* ── Bento Grid ── */}
        <div className="grid grid-cols-12 gap-6">
          {/* Left Column: Form */}
          <EngagementForm
            scanType={scanType}
            target={target}
            scanAggressiveness={scanAggressiveness}
            agentMode={agentMode}
            scanMode={scanMode}
            bugBounty={bugBounty}
            priorityVulnClasses={priorityVulnClasses}
            isLoading={isLoading}
            progressStep={progressStep}
            error={error}
            settingsLoading={settingsLoading}
            configMode={configMode}
            nlIntent={nlIntent}
            nlLoading={nlLoading}
            nlError={nlError}
            nlResult={nlResult}
            nlIsFallback={nlIsFallback}
            authConfig={authConfig}
            dualAuthConfig={dualAuthConfig}
            showAuthWizard={showAuthWizard}
            templates={templates}
            templatesLoading={templatesLoading}
            selectedTemplateId={selectedTemplateId}
            history={history}
            showAllHistory={showAllHistory}
            onScanTypeChange={setScanType}
            onTargetChange={setTarget}
            onScanAggressivenessChange={setScanAggressiveness}
            onAgentModeChange={setAgentMode}
            onScanModeChange={setScanMode}
            onBugBountyChange={setBugBounty}
            onPriorityVulnClassesChange={setPriorityVulnClasses}
            onConfigModeChange={setConfigMode}
            onNlIntentChange={setNlIntent}
            onNlResultChange={setNlResult}
            onNlErrorChange={setNlError}
            onShowAllHistoryChange={setShowAllHistory}
            onAuthConfigChange={setAuthConfig}
            onDualAuthConfigChange={setDualAuthConfig}
            onShowAuthWizardChange={setShowAuthWizard}
            onSelectedTemplateChange={setSelectedTemplateId}
            onParseIntent={handleParseIntent}
            onNlStartScan={handleNlStartScan}
            onNlEditDetails={handleNlEditDetails}
            onSubmit={handleSubmit}
            onRemoveHistory={removeFromHistory}
            onClearHistory={clearHistory}
            templateVariables={templateVariables}
            onTemplateVariablesChange={setTemplateVariables}
            showVariablePrompt={showVariablePrompt}
            onShowVariablePromptChange={setShowVariablePrompt}
            pendingTemplateConfig={pendingTemplateConfig}
            onPendingTemplateConfigChange={setPendingTemplateConfig}
          />

          {/* Right Column: Engagement List */}
          <EngagementList
            liveEngagements={liveEngagements}
            liveLoading={liveLoading}
            stoppingId={stoppingId}
            rescannings={rescannings}
            analyticsData={analyticsData}
            onStop={handleStop}
            onRescan={handleRescan}
            onDelete={handleDelete}
            getScanProgress={getScanProgress}
          />
        </div>
      </div>
    </div>
  );
}
