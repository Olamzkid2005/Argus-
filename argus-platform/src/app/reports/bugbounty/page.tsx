"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion } from "framer-motion";
import { log } from "@/lib/logger";
import {
  Bug,
  Download,
  Loader2,
  ChevronRight,
  Globe,
  Shield,
} from "lucide-react";

interface Platform {
  id: string;
  name: string;
  description: string;
}

export default function BugBountyPage() {
  useEffect(() => {
    log.pageMount("BugBounty");
    return () => log.pageUnmount("BugBounty");
  }, []);

  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [engagements, setEngagements] = useState<any[]>([]);
  const [selectedEngagement, setSelectedEngagement] = useState("");
  const [selectedPlatform, setSelectedPlatform] = useState("hackerone");
  const [isExporting, setIsExporting] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated") return;

    // Fetch available platforms
    fetch("/api/reports/bugbounty")
      .then((r) => r.json())
      .then((data) => setPlatforms(data.platforms || []))
      .catch(() => {});

    // Fetch completed engagements
    fetch("/api/engagements?limit=50")
      .then((r) => r.json())
      .then((data) => {
        const completed = (data.engagements || []).filter(
          (e: any) => e.status !== "created" && e.status !== "recon"
        );
        setEngagements(completed);
        if (completed.length > 0) {
          setSelectedEngagement(completed[0].id);
        }
      })
      .catch(() => {});
  }, [status]);

  const handleExport = async () => {
    if (!selectedEngagement) {
      showToast("error", "Please select an engagement");
      return;
    }

    setIsExporting(true);
    try {
      const response = await fetch("/api/reports/bugbounty", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          engagement_id: selectedEngagement,
          platform: selectedPlatform,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        showToast("success", `Bug bounty report generation started for ${selectedPlatform}`);
      } else {
        const error = await response.json();
        showToast("error", error.error || "Failed to start report generation");
      }
    } catch (err) {
      showToast("error", "Failed to generate bug bounty report");
    } finally {
      setIsExporting(false);
    }
  };

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <div className="flex items-center gap-3 mb-2">
          <Bug size={24} className="text-amber-500" />
          <h1 className="text-2xl font-bold tracking-tight text-on-surface">
            Bug Bounty Report Export
          </h1>
        </div>
        <p className="text-on-surface-variant/70 text-sm font-body">
          Export findings as submission-ready bug bounty reports for HackerOne,
          Bugcrowd, Intigriti, and YesWeHack
        </p>
      </motion.div>

      {/* Platform Selection */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8"
      >
        {platforms.map((platform) => (
          <button
            key={platform.id}
            onClick={() => setSelectedPlatform(platform.id)}
            className={`p-4 rounded-xl border text-left transition-all duration-300 ${
              selectedPlatform === platform.id
                ? "border-amber-500 bg-amber-500/10 shadow-glow-amber"
                : "border-outline-variant dark:border-outline/30 bg-surface dark:bg-surface-container-low hover:border-amber-500/50"
            }`}
          >
            <div className="flex items-center gap-2 mb-2">
              <Globe
                size={16}
                className={
                  selectedPlatform === platform.id
                    ? "text-amber-500"
                    : "text-on-surface-variant"
                }
              />
              <span
                className={`text-sm font-bold ${
                  selectedPlatform === platform.id
                    ? "text-amber-500"
                    : "text-on-surface"
                }`}
              >
                {platform.name}
              </span>
            </div>
            <p className="text-[11px] text-on-surface-variant/70 font-body leading-relaxed">
              {platform.description}
            </p>
          </button>
        ))}
      </motion.div>

      {/* Engagement Selection */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6 mb-6"
      >
        <div className="flex items-center gap-2 mb-4">
          <Shield size={16} className="text-primary" />
          <h2 className="text-sm font-bold uppercase tracking-widest text-on-surface">
            Select Engagement
          </h2>
        </div>

        <select
          value={selectedEngagement}
          onChange={(e) => setSelectedEngagement(e.target.value)}
          className="w-full px-4 py-3 bg-surface dark:bg-surface-container-high border border-outline-variant dark:border-outline/30 rounded-lg text-sm text-on-surface outline-none focus:border-primary focus:shadow-glow transition-all duration-300"
        >
          <option value="">-- Select an engagement --</option>
          {engagements.map((eng: any) => (
            <option key={eng.id} value={eng.id}>
              {eng.target_url || eng.id} ({eng.status})
            </option>
          ))}
        </select>

        {engagements.length === 0 && (
          <p className="mt-3 text-xs text-on-surface-variant/60 italic">
            No completed engagements found. Complete a scan first to generate bug bounty reports.
          </p>
        )}
      </motion.div>

      {/* Export Button */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="flex items-center gap-4"
      >
        <button
          onClick={handleExport}
          disabled={isExporting || !selectedEngagement}
          className="flex items-center gap-3 px-6 py-3 bg-amber-500 text-black font-bold text-xs tracking-widest uppercase hover:bg-amber-400 transition-all duration-300 rounded-xl disabled:opacity-50 disabled:cursor-not-allowed shadow-glow"
        >
          {isExporting ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Download size={16} />
          )}
          {isExporting ? "Generating Report..." : "Export Bug Bounty Report"}
          <ChevronRight size={16} />
        </button>

        <p className="text-[11px] text-on-surface-variant/50 font-body">
          Bug-Reaper methodology applied: findings filtered by Bug-Reaper audit rules
          (confidence &ge; 0.65, severity &ge; Medium, false positives excluded)
        </p>
      </motion.div>
    </div>
  );
}
