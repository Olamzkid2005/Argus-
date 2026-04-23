"use client";

import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ShieldAlert, Target, Lock, Bug, Crosshair } from "lucide-react";

interface AttackPathNode {
  id: string;
  type: "entry" | "exploit" | "privilege" | "target";
  label: string;
  description?: string;
  cvss?: number | null;
  confidence?: number | null;
}

interface AttackPathEdge {
  source: string;
  target: string;
  label?: string;
}

interface AttackPathGraphProps {
  nodes: AttackPathNode[];
  edges: AttackPathEdge[];
}

const NODE_ICONS: Record<string, React.ElementType> = {
  entry: Target,
  exploit: Bug,
  privilege: Lock,
  target: Crosshair,
};

const NODE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  entry: { bg: "rgba(233,255,255,0.08)", border: "var(--prism-cyan)", text: "var(--prism-cyan)" },
  exploit: { bg: "rgba(255,136,0,0.08)", border: "#FF8800", text: "#FF8800" },
  privilege: { bg: "rgba(255,255,208,0.08)", border: "var(--prism-cream)", text: "var(--prism-cream)" },
  target: { bg: "rgba(255,68,68,0.08)", border: "#FF4444", text: "#FF4444" },
};

interface AttackNodeData {
  label: string;
  description?: string;
  cvss?: number | null;
  confidence?: number | null;
  type: string;
}

function parseOptionalNumber(value: unknown): number | null {
  if (value == null) return null;
  const normalized = typeof value === "number" ? value : Number(value);
  return Number.isFinite(normalized) ? normalized : null;
}

function formatCvss(value: number): string {
  const roundedTenth = Math.round(value * 10) / 10;
  return String(roundedTenth);
}

function AttackNode({ data }: { data: AttackNodeData }) {
  if (!data) {
    return null;
  }

  const Icon = NODE_ICONS[data.type] || ShieldAlert;
  const colors = NODE_COLORS[data.type] || NODE_COLORS.exploit;

  const cvssValue = parseOptionalNumber(data.cvss);
  const cvssDisplay = cvssValue !== null ? (
    <span className="text-[9px] font-mono" style={{ color: colors.text }}>
      CVSS: {formatCvss(cvssValue)}
    </span>
  ) : null;

  const confidenceValue = parseOptionalNumber(data.confidence);
  const confidenceDisplay = confidenceValue !== null ? (
    <span className="text-[9px] font-mono text-text-secondary">
      {Math.round(confidenceValue * 100)}%
    </span>
  ) : null;

  return (
    <div
      className="px-4 py-3 min-w-[160px] border"
      style={{
        backgroundColor: colors.bg,
        borderColor: colors.border,
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: colors.border, width: 8, height: 8 }} />
      <div className="flex items-center gap-2 mb-1">
        <Icon size={14} style={{ color: colors.text }} />
        <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.text }}>
          {data.label}
        </span>
      </div>
      {data.description && (
        <p className="text-[10px] text-text-secondary truncate">{data.description}</p>
      )}
      <div className="flex items-center gap-3 mt-2">
        {cvssDisplay}
        {confidenceDisplay}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: colors.border, width: 8, height: 8 }} />
    </div>
  );
}

const TYPE_ORDER = ["entry", "exploit", "privilege", "target"] as const;

const nodeTypes = { attackNode: AttackNode } as const;

export default function AttackPathGraph({ nodes = [], edges = [] }: AttackPathGraphProps) {
  const flowNodes: Node[] = useMemo(() => {
    const sorted = [...nodes].sort(
      (a, b) => TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type)
    );
    const seenByType: Record<string, number> = {};

    return sorted.map((n) => {
      const typeIndex = Math.max(0, TYPE_ORDER.indexOf(n.type));
      const rowIndex = seenByType[n.type] ?? 0;
      seenByType[n.type] = rowIndex + 1;

      return {
        id: n.id,
        type: "attackNode",
        // Render as a left-to-right path map grouped by attack stage.
        position: { x: 70 + typeIndex * 240, y: 40 + rowIndex * 140 },
        data: { label: n.label, description: n.description, cvss: n.cvss, confidence: n.confidence, type: n.type },
      };
    });
  }, [nodes]);

  const flowEdges: Edge[] = useMemo(() => {
    return edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      label: e.label,
      style: { stroke: "var(--prism-cream)", strokeWidth: 1.5 },
      labelStyle: { fill: "var(--text-secondary)", fontSize: 10, fontFamily: "monospace" },
      animated: true,
    }));
  }, [edges]);

  const proOptions = { hideAttribution: true };

  return (
    <div className="w-full h-[420px] bg-surface/20 border border-structural">
      {flowNodes.length === 0 ? (
        <div className="w-full h-full flex items-center justify-center text-xs text-text-secondary font-mono">
          No attack path data yet. Run a scan or wait for findings.
        </div>
      ) : null}
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        proOptions={proOptions}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background color="var(--border-structural)" gap={20} size={1} />
        <Controls style={{ background: "var(--bg-surface)", borderColor: "var(--border-structural)" }} />
      </ReactFlow>
    </div>
  );
}
