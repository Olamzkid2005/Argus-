"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
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

export default function AssetsPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [assets, setAssets] = useState<Asset[]>([]);
  const [stats, setStats] = useState({ total: 0, critical: 0, high: 0, active: 0 });
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("all");
  const [showCreateModal, setShowCreateModal] = useState(false);
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

  useEffect(() => {
    if (status !== "authenticated") return;
    fetchAssets();
  }, [status, typeFilter]);

  const fetchAssets = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/assets?type=${typeFilter}`);
      if (res.ok) {
        const data = await res.json();
        setAssets(data.assets || []);
        setStats(data.stats || { total: 0, critical: 0, high: 0, active: 0 });
      }
    } catch (e) {
      console.error("Failed to fetch assets:", e);
    } finally {
      setLoading(false);
    }
  };

  const createAsset = async () => {
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
    }
  };

  const getRiskColor = (level: string) => {
    switch (level.toUpperCase()) {
      case "CRITICAL": return "#FF4444";
      case "HIGH": return "#FF8800";
      case "MEDIUM": return "var(--prism-cream)";
      case "LOW": return "var(--prism-cyan)";
      default: return "var(--text-secondary)";
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
              ASSET INVENTORY
            </h1>
            <p className="text-xs text-text-secondary mt-1 font-mono uppercase tracking-wider">
              Manage and monitor discovered assets across engagements
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-prism-cream text-void text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow-cream"
          >
            <Plus size={14} />
            Add Asset
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[
            { label: "Total Assets", value: stats.total, icon: Server, color: "var(--prism-cyan)" },
            { label: "Critical Risk", value: stats.critical, icon: ShieldAlert, color: "#FF4444" },
            { label: "High Risk", value: stats.high, icon: AlertTriangle, color: "#FF8800" },
            { label: "Active", value: stats.active, icon: CheckCircle2, color: "#00FF88" },
          ].map((s, i) => (
            <div key={s.label} className="border border-structural bg-surface/50 p-5">
              <div className="flex items-start justify-between mb-4">
                <div className="w-9 h-9 flex items-center justify-center border border-structural bg-surface/10">
                  <s.icon size={18} style={{ color: s.color }} />
                </div>
                <TrendingUp size={14} className="text-text-secondary" />
              </div>
              <div className="text-2xl font-semibold text-text-primary tracking-tight">{s.value}</div>
              <div className="text-xs text-text-secondary mt-1 tracking-wide uppercase">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mb-6">
          {["all", "domain", "endpoint", "repository", "container", "api"].map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider border transition-all ${
                typeFilter === t
                  ? "border-prism-cream text-prism-cream bg-prism-cream/10"
                  : "border-structural text-text-secondary hover:text-text-primary hover:border-text-secondary/40"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Assets Table */}
        <div className="border border-structural bg-surface/30">
          <div className="grid grid-cols-12 gap-4 px-5 py-3 border-b border-structural text-[10px] font-mono text-text-secondary uppercase tracking-wider">
            <div className="col-span-3">Asset</div>
            <div className="col-span-2">Type</div>
            <div className="col-span-2">Risk</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-2">Last Scanned</div>
            <div className="col-span-1">Verified</div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-prism-cream" />
            </div>
          ) : assets.length === 0 ? (
            <div className="py-12 text-center">
              <Server size={32} className="text-text-secondary mx-auto mb-4" />
              <h3 className="text-sm text-text-primary font-medium mb-2">No assets found</h3>
              <p className="text-xs text-text-secondary font-mono">
                Add assets manually or run an engagement to discover them automatically
              </p>
            </div>
          ) : (
            assets.map((asset) => {
              const Icon = assetTypeIcons[asset.asset_type] || Server;
              return (
                <div
                  key={asset.id}
                  className="grid grid-cols-12 gap-4 px-5 py-3 border-b border-structural last:border-b-0 hover:bg-surface/10 transition-colors items-center"
                >
                  <div className="col-span-3 min-w-0">
                    <div className="flex items-center gap-2">
                      <Icon size={14} className="text-text-secondary shrink-0" />
                      <div className="min-w-0">
                        <div className="text-xs text-text-primary truncate">{asset.display_name || asset.identifier}</div>
                        <div className="text-[10px] text-text-secondary font-mono truncate">{asset.identifier}</div>
                      </div>
                    </div>
                  </div>
                  <div className="col-span-2">
                    <span className="text-[10px] font-mono text-text-secondary uppercase border border-structural px-2 py-0.5">
                      {asset.asset_type}
                    </span>
                  </div>
                  <div className="col-span-2">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1 bg-surface/50 overflow-hidden">
                        <div
                          className="h-full"
                          style={{
                            width: `${Math.min(100, (asset.risk_score || 0) * 10)}%`,
                            backgroundColor: getRiskColor(asset.risk_level),
                          }}
                        />
                      </div>
                      <span
                        className="text-[10px] font-mono"
                        style={{ color: getRiskColor(asset.risk_level) }}
                      >
                        {asset.risk_level}
                      </span>
                    </div>
                  </div>
                  <div className="col-span-2">
                    <span className="flex items-center gap-1.5 text-[10px] font-mono text-text-secondary">
                      {getLifecycleIcon(asset.lifecycle_status)}
                      {asset.lifecycle_status}
                    </span>
                  </div>
                  <div className="col-span-2 text-[10px] font-mono text-text-secondary">
                    {asset.last_scanned_at
                      ? new Date(asset.last_scanned_at).toLocaleDateString()
                      : "Never"}
                  </div>
                  <div className="col-span-1">
                    {asset.verified ? (
                      <CheckCircle2 size={14} className="text-green-400" />
                    ) : (
                      <span className="text-[10px] text-text-secondary">—</span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Create Asset Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="border border-structural bg-surface w-full max-w-lg">
            <div className="flex items-center justify-between px-6 py-4 border-b border-structural">
              <h2 className="text-sm font-medium text-text-primary uppercase tracking-wider">
                Add Asset
              </h2>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-text-secondary hover:text-text-primary transition-colors"
              >
                Close
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                    Asset Type
                  </label>
                  <select
                    value={newAsset.asset_type}
                    onChange={(e) => setNewAsset({ ...newAsset, asset_type: e.target.value })}
                    className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
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
                  <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                    Criticality
                  </label>
                  <select
                    value={newAsset.criticality}
                    onChange={(e) => setNewAsset({ ...newAsset, criticality: e.target.value })}
                    className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                  Identifier
                </label>
                <input
                  type="text"
                  value={newAsset.identifier}
                  onChange={(e) => setNewAsset({ ...newAsset, identifier: e.target.value })}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
                  placeholder="e.g., example.com or 192.168.1.1"
                />
              </div>
              <div>
                <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                  Display Name
                </label>
                <input
                  type="text"
                  value={newAsset.display_name}
                  onChange={(e) => setNewAsset({ ...newAsset, display_name: e.target.value })}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors"
                  placeholder="Optional display name"
                />
              </div>
              <div>
                <label className="text-[10px] font-mono text-text-secondary uppercase tracking-wider block mb-1.5">
                  Description
                </label>
                <textarea
                  value={newAsset.description}
                  onChange={(e) => setNewAsset({ ...newAsset, description: e.target.value })}
                  rows={3}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors resize-none"
                  placeholder="Optional description"
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
                  onClick={createAsset}
                  className="px-4 py-2 bg-prism-cream text-void text-xs font-bold uppercase tracking-widest hover:opacity-90 shadow-glow-cream transition-all"
                >
                  Add Asset
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
