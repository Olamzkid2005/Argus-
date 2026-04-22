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
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ShieldAlert, Target, Lock, Bug, Crosshair } from "lucide-react";

interface AttackPathNode {
  id: string;
  type: "entry" | "exploit" | "privilege" | "target";
  label: string;
  description?: string;
  cvss?: number;
  confidence?: number;
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
  cvss?: number;
  confidence?: number;
  type: string;
}

function AttackNode({ data }: { data: AttackNodeData }) {
  const Icon = NODE_ICONS[data.type] || ShieldAlert;
  const colors = NODE_COLORS[data.type] || NODE_COLORS.exploit;

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
        {Number.isFinite(data.cvss) && (
          <span className="text-[9px] font-mono" style={{ color: colors.text }}>
            CVSS: {data.cvss?.toFixed(1)}
          </span>
        )}
        {Number.isFinite(data.confidence) && (
          <span className="text-[9px] font-mono text-text-secondary">
            {Math.round((data.confidence || 0) * 100)}%
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: colors.border, width: 8, height: 8 }} />
    </div>
  );
}

const nodeTypes: any = { attackNode: AttackNode };

export default function AttackPathGraph({ nodes, edges }: AttackPathGraphProps) {
  const flowNodes: Node[] = useMemo(() => {
    return nodes.map((n, i) => ({
      id: n.id,
      type: "attackNode",
      position: { x: 180 + (i % 3) * 220, y: 40 + Math.floor(i / 3) * 140 },
      data: { label: n.label, description: n.description, cvss: n.cvss, confidence: n.confidence, type: n.type },
    }));
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
