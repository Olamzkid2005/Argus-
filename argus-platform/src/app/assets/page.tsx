"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion, AnimatePresence } from "framer-motion";
import { log } from "@/lib/logger";
import {
  Loader2,
  Server,
  Globe,
  Database,
  Code2,
  Box,
  Network,
  Cloud,
  Plus,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Clock,
  TrendingUp,
  Activity,
} from "lucide-react";

interface Asset {
  id: string;
  asset_type: string;
  identifier: string;
  display_name: string;
  description: string;
  risk_score: number;
  risk_level: string;
  criticality: string;
  lifecycle_status: string;
  discovered_at: string;
  last_scanned_at: string;
  verified: boolean;
}

const assetTypeIcons: Record<string, React.ElementType> = {
  domain: Globe,
  ip: Network,
  endpoint: Code2,
  repository: Database,
  container: Box,
  api: Code2,
  network: Network,
  cloud_resource: Cloud,
};

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

const tableRowVariants = {
  hidden: { opacity: 0, x: -10 },
  show: { opacity: 1, x: 0, transition: { duration: 0.3 } },
};

export default function AssetsPage() {
  useEffect(() => {
    log.pageMount("Assets");
    return () => log.pageUnmount("Assets");
  }, []);

  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [assets, setAssets] = useState<Asset[]>([]);
  const [stats, setStats] = useState({ total: 0, critical: 0, high: 0, active: 0 });
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("all");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [newAsset, setNewAsset] = useState({
    asset_type: "domain",
    identifier: "",
    display_name: "",
    description: "",
    criticality: "medium",
  });

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/auth/signin");
    }
  }, [status, router]);

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/assets?type=${typeFilter}`);
      if (res.ok) {
        const data = await res.json();
        setAssets(data.assets || []);
        setStats(data.stats || { total: 0, critical: 0, high: 0, active: 0 });
      } else {
        const data = await res.json();
        showToast("error", data.error || "Failed to fetch assets");
      }
    } catch (e) {
      console.error("Failed to fetch assets:", e);
    } finally {
      setLoading(false);
    }
  }, [typeFilter]);

  useEffect(() => {
    if (status !== "authenticated") return;
    fetchAssets();
  }, [status, typeFilter, fetchAssets]);

  const createAsset = async () => {
    if (!newAsset.identifier.trim()) {
      showToast("error", "Identifier is required");
      return;
    }
    setIsCreating(true);
    try {
      const res = await fetch("/api/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newAsset),
      });
      if (res.ok) {
        showToast("success", "Asset added successfully");
        setShowCreateModal(false);
        setNewAsset({
          asset_type: "domain",
          identifier: "",
          display_name: "",
          description: "",
          criticality: "medium",
        });
        fetchAssets();
      } else {
        const data = await res.json();
        showToast("error", data.error || "Failed to add asset");
      }
    } catch (e) {
      showToast("error", "Failed to add asset");
    } finally {
      setIsCreating(false);
    }
  };

  const getRiskColor = (level: string) => {
    switch (level.toUpperCase()) {
      case "CRITICAL": return "#FF4444";
      case "HIGH": return "#FF8800";
      case "MEDIUM": return "#F59E0B";
      case "LOW": return "#00CED1";
      default: return "#888";
    }
  };

  const getLifecycleIcon = (status: string) => {
    switch (status) {
      case "active": return <CheckCircle2 size={12} className="text-green-400" />;
      case "inactive": return <Clock size={12} className="text-prism-cream" />;
      case "decommissioned": return <AlertTriangle size={12} className="text-text-secondary" />;
      default: return <Activity size={12} className="text-text-secondary" />;
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
              Asset Inventory
            </h1>
            <p className="font-body text-xs text-outline dark:text-[#8A8A9E] mt-1">
              Manage and monitor discovered assets
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2.5 primary-gradient text-white text-xs font-bold uppercase tracking-widest rounded-xl hover:shadow-glow transition-all duration-300 self-start"
          >
            <Plus size={14} />
            Add Asset
          </button>
        </motion.div>

        {/* Stats */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8"
        >
          {[
            { label: "Total Assets", value: stats.total, icon: Server, color: "#6720FF" },
            { label: "Critical Risk", value: stats.critical, icon: ShieldAlert, color: "#BA1A1A" },
            { label: "High Risk", value: stats.high, icon: AlertTriangle, color: "#FF8800" },
            { label: "Active", value: stats.active, icon: CheckCircle2, color: "#00C853" },
          ].map((s) => (
            <motion.div
              key={s.label}
              variants={itemVariants}
              className="bg-white dark:bg-[#12121A] border border-outline-variant dark:border-white/[0.08] rounded-xl p-5 hover:shadow-md transition-all duration-300"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="w-10 h-10 rounded-lg bg-surface-container dark:bg-[#1A1A24] flex items-center justify-center border border-outline-variant dark:border-white/[0.08]">
                  <s.icon size={18} style={{ color: s.color }} />
                </div>
                <TrendingUp size={14} className="text-outline dark:text-[#8A8A9E]" />
              </div>
              <div className="text-2xl font-semibold text-on-surface dark:text-[#F0F0F5] tracking-tight font-headline">
                {s.value}
              </div>
              <div className="text-xs text-outline dark:text-[#8A8A9E] mt-1 tracking-wide uppercase font-label">
                {s.label}
              </div>
            </motion.div>
          ))}
        </motion.div>

        {/* Filters */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className="flex flex-wrap items-center gap-2 mb-6"
        >
          {["all", "domain", "ip", "endpoint", "repository", "container", "api", "network", "cloud_resource"].map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-4 py-1.5 text-[11px] font-label uppercase tracking-wider rounded-full border transition-all duration-300 ${
                typeFilter === t
                  ? "primary-gradient text-white border-transparent shadow-glow"
                  : "bg-transparent border-outline-variant dark:border-white/[0.08] text-outline dark:text-[#8A8A9E] hover:border-primary hover:text-primary"
              }`}
            >
              {t}
            </button>
          ))}
        </motion.div>

        {/* Assets Table */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="bg-white dark:bg-[#12121A] rounded-xl border border-outline-variant dark:border-white/[0.08] overflow-hidden shadow-xs"
        >
          <div className="grid grid-cols-12 gap-4 px-5 py-3 bg-surface-container-high dark:bg-[#1A1A24] border-b border-outline-variant dark:border-white/[0.08] text-[10px] font-label uppercase tracking-wider text-outline dark:text-[#8A8A9E]">
            <div className="col-span-3">Asset</div>
            <div className="col-span-2">Type</div>
            <div className="col-span-2">Risk</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-2">Last Scanned</div>
            <div className="col-span-1">Verified</div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : assets.length === 0 ? (
            <div className="py-12 text-center">
              <Server size={32} className="text-outline dark:text-[#8A8A9E] mx-auto mb-4" />
              <h3 className="text-sm text-on-surface dark:text-[#F0F0F5] font-medium mb-2 font-headline">
                No assets found
              </h3>
              <p className="text-xs text-outline dark:text-[#8A8A9E] font-body">
                Add assets manually or run an engagement to discover them automatically
              </p>
            </div>
          ) : (
            <motion.div variants={containerVariants} initial="hidden" animate="show">
              {assets.map((asset) => {
                const Icon = assetTypeIcons[asset.asset_type] || Server;
                return (
                  <motion.div
                    key={asset.id}
                    variants={tableRowVariants}
                    className="grid grid-cols-12 gap-4 px-5 py-3 border-b border-outline-variant dark:border-white/[0.08] last:border-b-0 hover:bg-surface-container dark:hover:bg-[#1A1A24]/50 transition-all duration-300 items-center"
                  >
                    <div className="col-span-3 min-w-0">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-md bg-surface-container dark:bg-[#1A1A24] flex items-center justify-center border border-outline-variant dark:border-white/[0.08] shrink-0">
                          <Icon size={14} className="text-primary" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-xs text-on-surface dark:text-[#F0F0F5] truncate font-medium">
                            {asset.display_name || asset.identifier}
                          </div>
                          <div className="text-[10px] text-outline dark:text-[#8A8A9E] font-label truncate">
                            {asset.identifier}
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="col-span-2">
                      <span className="text-[10px] font-label uppercase border border-outline-variant dark:border-white/[0.08] px-2 py-0.5 rounded-md bg-surface-container dark:bg-[#1A1A24] text-outline dark:text-[#8A8A9E]">
                        {asset.asset_type}
                      </span>
                    </div>
                    <div className="col-span-2">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-surface-container dark:bg-[#1A1A24] rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.min(100, (asset.risk_score || 0) * 10)}%`,
                              backgroundColor: getRiskColor(asset.risk_level),
                            }}
                          />
                        </div>
                        <span
                          className="text-[10px] font-label"
                          style={{ color: getRiskColor(asset.risk_level) }}
                        >
                          {asset.risk_level}
                        </span>
                      </div>
                    </div>
                    <div className="col-span-2">
                      <span className="flex items-center gap-1.5 text-[10px] font-label text-outline dark:text-[#8A8A9E]">
                        {getLifecycleIcon(asset.lifecycle_status)}
                        {asset.lifecycle_status}
                      </span>
                    </div>
                    <div className="col-span-2 text-[10px] font-label text-outline dark:text-[#8A8A9E]">
                      {asset.last_scanned_at
                        ? new Date(asset.last_scanned_at).toLocaleDateString()
                        : "Never"}
                    </div>
                    <div className="col-span-1">
                      {asset.verified ? (
                        <CheckCircle2 size={14} className="text-green-400" />
                      ) : (
                        <span className="text-[10px] text-outline dark:text-[#8A8A9E]">—</span>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </motion.div>
      </div>

      {/* Create Asset Modal */}
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
              className="bg-white dark:bg-[#12121A] w-full max-w-lg rounded-xl border border-outline-variant dark:border-white/[0.08] shadow-glow overflow-hidden"
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant dark:border-white/[0.08]">
                <h2 className="font-headline text-sm font-medium text-on-surface dark:text-[#F0F0F5] uppercase tracking-wider">
                  Add Asset
                </h2>
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="text-outline dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5] transition-colors text-xs font-label"
                >
                  Close
                </button>
              </div>
              <div className="p-6 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                      Asset Type
                    </label>
                    <select
                      value={newAsset.asset_type}
                      onChange={(e) => setNewAsset({ ...newAsset, asset_type: e.target.value })}
                      className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    >
                      <option value="domain">Domain</option>
                      <option value="ip">IP Address</option>
                      <option value="endpoint">Endpoint</option>
                      <option value="repository">Repository</option>
                      <option value="container">Container</option>
                      <option value="api">API</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                      Criticality
                    </label>
                    <select
                      value={newAsset.criticality}
                      onChange={(e) => setNewAsset({ ...newAsset, criticality: e.target.value })}
                      className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    >
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="critical">Critical</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                    Identifier
                  </label>
                  <input
                    type="text"
                    value={newAsset.identifier}
                    onChange={(e) => setNewAsset({ ...newAsset, identifier: e.target.value })}
                    className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    placeholder="e.g., example.com or 192.168.1.1"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                    Display Name
                  </label>
                  <input
                    type="text"
                    value={newAsset.display_name}
                    onChange={(e) => setNewAsset({ ...newAsset, display_name: e.target.value })}
                    className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300"
                    placeholder="Optional display name"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-label text-outline dark:text-[#8A8A9E] uppercase tracking-wider block mb-1.5">
                    Description
                  </label>
                  <textarea
                    value={newAsset.description}
                    onChange={(e) => setNewAsset({ ...newAsset, description: e.target.value })}
                    rows={3}
                    className="w-full px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-white/[0.08] text-xs text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 rounded-lg transition-all duration-300 resize-none"
                    placeholder="Optional description"
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
                    onClick={createAsset}
                    disabled={isCreating}
                    className="px-4 py-2 primary-gradient text-white text-xs font-bold uppercase tracking-widest hover:shadow-glow rounded-xl transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isCreating ? (
                      <span className="flex items-center gap-2">
                        <Loader2 size={14} className="animate-spin" />
                        Adding...
                      </span>
                    ) : (
                      "Add Asset"
                    )}
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
