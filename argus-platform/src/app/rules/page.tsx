"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
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

  useEffect(() => {
    if (status !== "authenticated") return;
    fetchRules();
  }, [status, statusFilter]);

  const fetchRules = async () => {
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
  };

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
      <div className="min-h-screen flex items-center justify-center bg-void">
        <Loader2 className="h-8 w-8 animate-spin text-prism-cream" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-void">
      <div className="px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-text-primary tracking-tight">
              CUSTOM RULE ENGINE
            </h1>
            <p className="text-xs text-text-secondary mt-1 font-mono uppercase tracking-wider">
              Build, validate, and share vulnerability detection rules
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-prism-cream text-void text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow-cream"
          >
            <Plus size={14} />
            New Rule
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mb-6">
          {["all", "active", "draft", "deprecated"].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider border transition-all ${
                statusFilter === s
                  ? "border-prism-cream text-prism-cream bg-prism-cream/10"
                  : "border-structural text-text-secondary hover:text-text-primary hover:border-text-secondary/40"
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Rules Grid */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-prism-cream" />
          </div>
        ) : rules.length === 0 ? (
          <div className="border border-structural bg-surface/30 p-12 text-center">
            <FileCode2 size={32} className="text-text-secondary mx-auto mb-4" />
            <h3 className="text-sm text-text-primary font-medium mb-2">No rules found</h3>
            <p className="text-xs text-text-secondary font-mono">
              Create your first custom vulnerability detection rule
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3">
            {rules.map((rule) => (
              <div
                key={rule.id}
                className="border border-structural bg-surface/30 p-5 hover:border-prism-cream/20 transition-all group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-4">
                    <div className="w-9 h-9 flex items-center justify-center border border-structural bg-surface/10 shrink-0">
                      <ShieldCheck size={16} className="text-prism-cyan" />
                    </div>
                    <div>
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="text-sm font-medium text-text-primary">{rule.name}</h3>
                        <span
                          className="text-[10px] font-mono px-2 py-0.5 border"
                          style={{
                            color: getSeverityColor(rule.severity),
                            borderColor: "var(--border-structural)",
                          }}
                        >
                          {rule.severity}
                        </span>
                        <span className="text-[10px] font-mono text-text-secondary border border-structural px-2 py-0.5">
                          v{rule.version}
                        </span>
                        {rule.is_community_shared && (
                          <span className="text-[10px] font-mono text-prism-cyan border border-prism-cyan/30 px-2 py-0.5">
                            COMMUNITY
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-text-secondary mb-2">{rule.description}</p>
                      <div className="flex items-center gap-4 text-[10px] font-mono text-text-secondary/60">
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
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Rule Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="border border-structural bg-surface w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-structural">
              <h2 className="text-sm font-medium text-text-primary uppercase tracking-wider">
                Create Custom Rule
              </h2>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-text-secondary hover:text-text-primary transition-colors"
              >
                Close
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                  Rule Name
                </label>
                <input
                  type="text"
                  value={newRule.name}
                  onChange={(e) => setNewRule({ ...newRule, name: e.target.value })}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
                  placeholder="e.g., SQL Injection Detection"
                />
              </div>
              <div>
                <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                  Description
                </label>
                <input
                  type="text"
                  value={newRule.description}
                  onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
                  placeholder="Brief description of what this rule detects"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                    Severity
                  </label>
                  <select
                    value={newRule.severity}
                    onChange={(e) => setNewRule({ ...newRule, severity: e.target.value })}
                    className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
                  >
                    <option value="INFO">INFO</option>
                    <option value="LOW">LOW</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="HIGH">HIGH</option>
                    <option value="CRITICAL">CRITICAL</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                    Category
                  </label>
                  <select
                    value={newRule.category}
                    onChange={(e) => setNewRule({ ...newRule, category: e.target.value })}
                    className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
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
                <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                  Rule YAML
                </label>
                <textarea
                  value={newRule.rule_yaml}
                  onChange={(e) => setNewRule({ ...newRule, rule_yaml: e.target.value })}
                  rows={12}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary font-mono outline-none focus:border-prism-cream transition-colors resize-none"
                />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 border border-structural text-text-secondary hover:text-text-primary text-xs font-bold uppercase tracking-widest transition-all"
                >
                  Cancel
                </button>
                <button
                  onClick={createRule}
                  className="px-4 py-2 bg-prism-cream text-void text-xs font-bold uppercase tracking-widest hover:opacity-90 shadow-glow-cream transition-all"
                >
                  Create Rule
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
