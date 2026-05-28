"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Globe,
  GitBranch,
  Loader2,
  Eye,
  StopCircle,
  RefreshCw,
  Trash2,
  ShieldCheck,
  Server,
  Cpu,
  Shield,
  Activity,
  BarChart3,
  ArrowRight,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
import { StaggerContainer, StaggerItem } from "@/components/animations/StaggerContainer";
import SkeletonLoader from "@/components/ui-custom/SkeletonLoader";
import type { Engagement } from "@/hooks/useEngagements";
import { statusConfig } from "@/hooks/useEngagements";

interface EngagementListProps {
  liveEngagements: Engagement[];
  liveLoading: boolean;
  stoppingId: string | null;
  rescannings: Set<string>;
  analyticsData: Array<{ name: string; findings: number; critical: number }>;
  onStop: (id: string) => void;
  onRescan: (id: string) => void;
  onDelete: (id: string) => void;
  getScanProgress: (status: string) => number;
}

export default function EngagementList({
  liveEngagements,
  liveLoading,
  stoppingId,
  rescannings,
  analyticsData,
  onStop,
  onRescan,
  onDelete,
  getScanProgress,
}: EngagementListProps) {
  const router = useRouter();

  return (
    <>
      {/* ── Live Engagements ── */}
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.5, delay: 0.3 }}
        className="col-span-12 lg:col-span-5 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 transition-all duration-300 hover:border-primary/20"
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Activity size={18} className="text-primary" />
            <h2 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">
              Live Engagements
            </h2>
          </div>
          {liveLoading && (
            <div className="flex items-center gap-2 text-[10px] text-on-surface-variant dark:text-[#8A8A9E]">
              <Loader2 size={12} className="animate-spin" />
              Refreshing...
            </div>
          )}
        </div>

        <div className="space-y-3 max-h-[540px] overflow-y-auto pr-1 custom-scrollbar">
          {liveEngagements.length === 0 && !liveLoading ? (
            <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
              <Shield size={28} />
              <p className="text-[11px] font-mono uppercase tracking-widest">No engagements yet</p>
              <p className="text-[10px]">Launch your first scan to see it here</p>
            </div>
          ) : (
            liveEngagements.map((eng, idx) => {
              const config = statusConfig[eng.status] || statusConfig.created;
              const progress = getScanProgress(eng.status);

              return (
                <motion.div
                  key={eng.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: idx * 0.05 }}
                  className="p-4 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg transition-all duration-300 hover:border-primary/30 hover:shadow-glow group"
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2.5">
                      {eng.scan_type === "repo" ? (
                        <GitBranch size={16} className="text-primary shrink-0" />
                      ) : (
                        <Globe size={16} className="text-primary shrink-0" />
                      )}
                      <div>
                        <p className="text-xs font-mono text-on-surface dark:text-[#F0F0F5] break-all">{eng.target_url}</p>
                        <p className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] mt-0.5">
                          {new Date(eng.created_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md ${config.bg} ${config.color}`}>
                      {config.label}
                    </span>
                  </div>

                  <div className="mt-3">
                    <div className="flex items-center justify-between text-[9px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1">
                      <span>Progress</span>
                      <span>{progress}%</span>
                    </div>
                    <div className="h-1.5 w-full bg-surface-container-high dark:bg-[#1A1A24] rounded-full overflow-hidden">
                      <motion.div
                        className="h-full bg-primary rounded-full"
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.6, ease: "easeOut" }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-outline-variant dark:border-[#ffffff08]">
                    <div className="flex gap-3 text-[10px] font-mono">
                      <span className="text-on-surface-variant dark:text-[#8A8A9E]">{eng.findings_count} findings</span>
                      {eng.critical_count > 0 && (
                        <span className="text-error">{eng.critical_count} critical</span>
                      )}
                    </div>
                    <div className="flex gap-1">
                      <button
                        onClick={() => router.push(`/dashboard?engagement=${eng.id}`)}
                        className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-primary transition-all duration-300 rounded-md hover:bg-primary/5"
                        title="Monitor"
                      >
                        <Eye size={14} />
                      </button>
                      {eng.status !== "complete" && eng.status !== "failed" && eng.status !== "paused" && (
                        <button
                          onClick={() => onStop(eng.id)}
                          disabled={stoppingId === eng.id}
                          className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-error transition-all duration-300 rounded-md hover:bg-error/5 disabled:opacity-40"
                          title="Stop scan"
                        >
                          {stoppingId === eng.id ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <StopCircle size={14} />
                          )}
                        </button>
                      )}
                      {["complete", "failed", "paused"].includes(eng.status) && (
                        <button
                          onClick={() => onRescan(eng.id)}
                          disabled={rescannings.has(eng.id)}
                          className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-primary transition-all duration-300 rounded-md hover:bg-primary/5 disabled:opacity-40"
                          title="Rescan"
                        >
                          {rescannings.has(eng.id) ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <RefreshCw size={14} />
                          )}
                        </button>
                      )}
                      <button
                        onClick={() => onDelete(eng.id)}
                        className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-error transition-all duration-300 rounded-md hover:bg-error/5"
                        title="Delete"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </motion.div>
              );
            })
          )}
        </div>
      </motion.div>

      {/* ── Meta Info ── */}
      <ScrollReveal direction="up" delay={0.15}>
        <StaggerContainer className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-6" staggerDelay={0.06}>
          <StaggerItem>
            <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Server size={18} className="text-primary" />
                </div>
                <div>
                  <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">VPC Tunneling</div>
                  <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">Active • us-east-1</div>
                </div>
              </div>
            </motion.div>
          </StaggerItem>
          <StaggerItem>
            <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Cpu size={18} className="text-primary" />
                </div>
                <div>
                  <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">Model Version</div>
                  <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">Argus v1.0.0</div>
                </div>
              </div>
            </motion.div>
          </StaggerItem>
          <StaggerItem>
            <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Shield size={18} className="text-primary" />
                </div>
                <div>
                  <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">Total Scans</div>
                  <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">{liveEngagements.length} engagements</div>
                </div>
              </div>
            </motion.div>
          </StaggerItem>
          <StaggerItem>
            <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Activity size={18} className="text-primary" />
                </div>
                <div>
                  <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">Active Scans</div>
                  <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">
                    {liveEngagements.filter((e) => ["scanning", "analyzing", "recon", "reporting"].includes(e.status)).length} running
                  </div>
                </div>
              </div>
            </motion.div>
          </StaggerItem>
        </StaggerContainer>
      </ScrollReveal>

      {/* ── Analytics Preview ── */}
      <ScrollReveal direction="up" delay={0.15}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          whileHover={{ y: -3, transition: { duration: 0.25 } }}
          className="mt-6 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 transition-all duration-300 hover:border-primary/20"
        >
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-6 gap-4">
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-primary" />
              <h3 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">Engagement Analytics</h3>
            </div>
            <button
              onClick={() => router.push("/reports")}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-on-primary text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all duration-300 shadow-glow rounded-lg font-body"
            >
              View Reports
              <ArrowRight size={14} />
            </button>
          </div>

          {analyticsData.length > 0 ? (
            <div className="h-[220px] w-full">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={analyticsData} barCategoryGap="20%">
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(122, 116, 137, 0.15)" />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 11, fill: "#7A7489" }}
                    axisLine={{ stroke: "rgba(122, 116, 137, 0.2)" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#7A7489" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#FFFFFF",
                      border: "1px solid #CAC3DA",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                    cursor={{ fill: "rgba(103, 32, 255, 0.05)" }}
                  />
                  <Bar dataKey="findings" fill="#6720FF" radius={[4, 4, 0, 0]} name="Findings" />
                  <Bar dataKey="critical" fill="#BA1A1A" radius={[4, 4, 0, 0]} name="Critical" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-[220px] flex flex-col items-center justify-center text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
              <BarChart3 size={28} />
              <p className="text-[11px] font-mono uppercase tracking-widest">No analytics data available</p>
            </div>
          )}
        </motion.div>
      </ScrollReveal>
    </>
  );
}
