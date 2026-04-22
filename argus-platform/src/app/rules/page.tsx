"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2,
  ShieldCheck,
  Plus,
  FileCode2,
  GitCommit,
  Layers,
  Globe,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Info,
} from "lucide-react";

interface CustomRule {
  id: string;
  name: string;
  description: string;
  severity: string;
  category: string;
  status: string;
  version: number;
  is_community_shared: boolean;
  created_at: string;
}

const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.08 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" as const } },
};

export default function RulesPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [rules, setRules] = useState<CustomRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("active");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newRule, setNewRule] = useState({
    name: "",
    description: "",
    rule_yaml: "rules:\n  - id: custom-rule-001\n    severity: MEDIUM\n    message: \"Custom vulnerability pattern detected\"\n    patterns:\n      - pattern: \"dangerous_function()\"\n",
    severity: "MEDIUM",
    category: "custom",
  });

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/auth/signin");
    }
  }, [status, router]);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/rules?status=${statusFilter}`);
      if (res.ok) {
        const data = await res.json();
        setRules(data.rules || []);
      }
    } catch (e) {
      console.error("Failed to fetch rules:", e);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    if (status !== "authenticated") return;
    fetchRules();
  }, [status, statusFilter, fetchRules]);

  const createRule = async () => {
    try {
      const res = await fetch("/api/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newRule),
      });
      if (res.ok) {
        showToast("success", "Rule created successfully");
        setShowCreateModal(false);
        fetchRules();
      } else {
        const data = await res.json();
        showToast("error", data.error || "Failed to create rule");
      }
    } catch (e) {
      showToast("error", "Failed to create rule");
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity.toUpperCase()) {
      case "CRITICAL": return "#FF4444";
      case "HIGH": return "#FF8800";
      case "MEDIUM": return "var(--prism-cream)";
      case "LOW": return "var(--prism-cyan)";
      default: return "var(--text-secondary)";
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "active": return <CheckCircle2 size={14} className="text-green-400" />;
      case "draft": return <Clock size={14} className="text-prism-cream" />;
      default: return <AlertTriangle size={14} className="text-text-secondary" />;
    }
  };

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface dark:bg-[#0A0A0F]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-surface dark:bg-[#0A0A0F] font-body">
      <div className="px-8 py-8 max-w-7xl mx-auto">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8"
        >
          <div>
            <h1 className="font-headline text-2xl font-semibold text-on-surface dark:text-[#F0F0F5] tracking-tight">
              Custom Rule Engine
            </h1>
            <p className="font-body text-xs text-outline dark:text-[#8A8A9E] mt-1">
              Build, validate, and share vulnerability detection rules
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2.5 primary-gradient text-white text-xs font-bold uppercase tracking-widest rounded-xl hover:shadow-glow transition-all duration-300 self-start"
          >
            <Plus size={14} />
            New Rule
          </button>
        </motion.div>

        {/* Filters */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className="flex flex-wrap items-center gap-2 mb-6"
        >
          {["all", "active", "draft", "deprecated"].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-4 py-1.5 text-[11px] font-label uppercase tracking-wider rounded-full border transition-all duration-300 ${
                statusFilter === s
                  ? "primary-gradient text-white border-transparent shadow-glow"
                  : "bg-transparent border-outline-variant dark:border-white/[0.08] text-outline dark:text-[#8A8A9E] hover:border-primary hover:text-primary"
              }`}
            >
              {s}
            </button>
          ))}
        </motion.div>

        {/* Rules Grid */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : rules.length === 0 ? (
          <div className="bg-white dark:bg-[#12121A] border border-outline-variant dark:border-white/[0.08] rounded-xl p-12 text-center">
            <FileCode2 size={32} className="text-outline dark:text-[#8A8A9E] mx-auto mb-4" />
            <h3 className="text-sm text-on-surface dark:text-[#F0F0F5] font-medium mb-2 font-headline">
              No rules found
            </h3>
            <p className="text-xs text-outline dark:text-[#8A8A9E] font-body">
              Create your first custom vulnerability detection rule
            </p>
          </div>
        ) : (
          <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="show"
            className="grid grid-cols-1 gap-4"
          >
            {rules.map((rule) => (
              <motion.div
                key={rule.id}
                variants={itemVariants}
                className="bg-white dark:bg-[#12121A] border border-outline-variant dark:border-white/[0.08] rounded-xl p-5 hover:shadow-md hover:border-primary/30 transition-all duration-300 group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-lg bg-surface-container dark:bg-[#1A1A24] flex items-center justify-center border border-outline-variant dark:border-white/[0.08] shrink-0">
                      <ShieldCheck size={16} className="text-primary" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-3 mb-1">
                        <h3 className="text-sm font-medium text-on-surface dark:text-[#F0F0F5] font-headline">
                          {rule.name}
                        </h3>
                        <span
                          className="text-[10px] font-label px-2 py-0.5 border rounded-md"
                          style={{
                            color: getSeverityColor(rule.severity),
                            borderColor: getSeverityColor(rule.severity),
                          }}
                        >
                          {rule.severity}
                        </span>
                        <span className="text-[10px] font-label text-outline dark:text-[#8A8A9E] border border-outline-variant dark:border-white/[0.08] px-2 py-0.5 rounded-md">
                          v{rule.version}
                        </span>
                        {rule.is_community_shared && (
                          <span className="text-[10px] font-label text-primary border border-primary/30 px-2 py-0.5 rounded-md bg-primary/5">
                            COMMUNITY
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-outline dark:text-[#8A8A9E] mb-2 font-body">
                        {rule.description}
                      </p>
                      <div className="flex flex-wrap items-center gap-4 text-[10px] font-label text-outline/60 dark:text-[#8A8A9E]/60">
                        <span className="flex items-center gap-1">
                          {getStatusIcon(rule.status)}
                          {rule.status}
                        </span>
                        <span className="flex items-center gap-1">
                          <Layers size={10} />
                          {rule.category}
                        </span>
                        <span className="flex items-center gap-1">
                          <GitCommit size={10} />
                          {new Date(rule.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>
        )}
      </div>

      {/* Create Rule Modal */}
      <AnimatePresence>
        {showCreateModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-md"
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 20 }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
              className="bg-white dark:bg-[#12121A] w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-outline-variant dark:border-white/[0.08] shadow-glow"
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant dark:border-white/[0.08]">
                <h2 className="font-headline text-sm font-medium text-on-surface dark:text-[#F0F0F5] uppercase tracking-wider">
                  Create Custom Rule
                </h2>
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="text-outline dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5] transition-colors text-xs font-label"
                >
                  Close
                </button>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                    Rule Name
                  </label>
                  <input
                    type="text"
                    value={newRule.name}
                    onChange={(e) => setNewRule({ ...newRule, name: e.target.value })}
                    className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    placeholder="e.g., SQL Injection Detection"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                    Description
                  </label>
                  <input
                    type="text"
                    value={newRule.description}
                    onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
                    className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    placeholder="Brief description of what this rule detects"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                      Severity
                    </label>
                    <select
                      value={newRule.severity}
                      onChange={(e) => setNewRule({ ...newRule, severity: e.target.value })}
                      className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    >
                      <option value="INFO">INFO</option>
                      <option value="LOW">LOW</option>
                      <option value="MEDIUM">MEDIUM</option>
                      <option value="HIGH">HIGH</option>
                      <option value="CRITICAL">CRITICAL</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                      Category
                    </label>
                    <select
                      value={newRule.category}
                      onChange={(e) => setNewRule({ ...newRule, category: e.target.value })}
                      className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    >
                      <option value="custom">Custom</option>
                      <option value="injection">Injection</option>
                      <option value="auth">Authentication</option>
                      <option value="crypto">Cryptography</option>
                      <option value="secrets">Secrets</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                    Rule YAML
                  </label>
                  <textarea
                    value={newRule.rule_yaml}
                    onChange={(e) => setNewRule({ ...newRule, rule_yaml: e.target.value })}
                    rows={12}
                    className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] font-mono outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300 resize-none"
                  />
                </div>
                <div className="flex justify-end gap-3 pt-2">
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="px-4 py-2 border border-outline-variant dark:border-white/[0.08] text-outline dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5] hover:border-on-surface dark:hover:border-[#F0F0F5] text-xs font-bold uppercase tracking-widest rounded-xl transition-all duration-300"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={createRule}
                    className="px-4 py-2 primary-gradient text-white text-xs font-bold uppercase tracking-widest hover:shadow-glow rounded-xl transition-all duration-300"
                  >
                    Create Rule
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
