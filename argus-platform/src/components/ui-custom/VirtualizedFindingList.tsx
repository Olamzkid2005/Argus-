"use client";

import { useState, useRef } from "react";
import { FindingCard } from "@/components/ui/FindingCard";

interface Finding {
  id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  endpoint: string;
  evidence?: Record<string, unknown>;
  source_tool: string;
  repro_steps?: string[];
  cvss_score?: number;
  cwe_id?: string;
  owasp_category?: string;
  verified: boolean;
  confidence?: number;
  created_at: string;
}

interface VirtualizedFindingListProps {
  findings: Finding[];
}

const ITEM_HEIGHT = 120;
const CONTAINER_HEIGHT = 600;
const BUFFER = 5;

export default function VirtualizedFindingList({ findings }: VirtualizedFindingListProps) {
  const [scrollTop, setScrollTop] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const totalHeight = findings.length * ITEM_HEIGHT;
  const startIndex = Math.max(0, Math.floor(scrollTop / ITEM_HEIGHT) - BUFFER);
  const endIndex = Math.min(
    findings.length,
    Math.ceil((scrollTop + CONTAINER_HEIGHT) / ITEM_HEIGHT) + BUFFER
  );

  const visibleFindings = findings.slice(startIndex, endIndex);
  const offsetY = startIndex * ITEM_HEIGHT;

  return (
    <div
      ref={containerRef}
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      className="h-[600px] overflow-auto"
    >
      <div style={{ height: totalHeight, position: "relative" }}>
        <div style={{ transform: `translateY(${offsetY}px)` }}>
          {visibleFindings.map((finding) => (
            <div key={finding.id} style={{ height: ITEM_HEIGHT }} className="px-1 py-1">
              <FindingCard finding={finding} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
