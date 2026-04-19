"use client";

import { useState, useMemo } from "react";
import { Search, Filter, Download, Trash2, Eye, X } from "lucide-react";

interface Finding {
  id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  endpoint: string;
  source_tool: string;
  verified: boolean;
  created_at: string;
}

interface FindingFiltersProps {
  findings: Finding[];
  onFilter: (filtered: Finding[]) => void;
}

type SeverityFilter = "ALL" | "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
type ToolFilter = "ALL" | string;
type StatusFilter = "ALL" | "VERIFIED" | "UNVERIFIED";

export function FindingFilters({ findings, onFilter }: FindingFiltersProps) {
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState<SeverityFilter>("ALL");
  const [tool, setTool] = useState<ToolFilter>("ALL");
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [sortBy, setSortBy] = useState<"severity" | "date">("severity");

  const uniqueTools = useMemo(() => {
    const tools = new Set(findings.map((f) => f.source_tool));
    return ["ALL", ...Array.from(tools)];
  }, [findings]);

  const filteredFindings = useMemo(() => {
    let result = [...findings];

    // Search filter
    if (search) {
      const searchLower = search.toLowerCase();
      result = result.filter(
        (f) =>
          f.endpoint.toLowerCase().includes(searchLower) ||
          f.type.toLowerCase().includes(searchLower),
      );
    }

    // Severity filter
    if (severity !== "ALL") {
      result = result.filter((f) => f.severity === severity);
    }

    // Tool filter
    if (tool !== "ALL") {
      result = result.filter((f) => f.source_tool === tool);
    }

    // Status filter
    if (status === "VERIFIED") {
      result = result.filter((f) => f.verified);
    } else if (status === "UNVERIFIED") {
      result = result.filter((f) => !f.verified);
    }

    // Sorting
    result.sort((a, b) => {
      if (sortBy === "severity") {
        const severityOrder = {
          CRITICAL: 0,
          HIGH: 1,
          MEDIUM: 2,
          LOW: 3,
          INFO: 4,
        };
        return severityOrder[a.severity] - severityOrder[b.severity];
      }
      return (
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
    });

    return result;
  }, [findings, search, severity, tool, status, sortBy]);

  const handleFilterChange = () => {
    onFilter(filteredFindings);
  };

  const exportToCSV = () => {
    const headers = [
      "ID",
      "Type",
      "Severity",
      "Endpoint",
      "Tool",
      "Verified",
      "Date",
    ];
    const rows = filteredFindings.map((f) => [
      f.id,
      f.type,
      f.severity,
      f.endpoint,
      f.source_tool,
      f.verified ? "Yes" : "No",
      f.created_at,
    ]);

    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `findings-${new Date().toISOString().split("T")[0]}.csv`;
    a.click();
  };

  const exportToJSON = () => {
    const json = JSON.stringify(filteredFindings, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `findings-${new Date().toISOString().split("T")[0]}.json`;
    a.click();
  };

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          type="text"
          placeholder="Search findings..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            handleFilterChange();
          }}
          className="w-full pl-10 pr-4 py-2 rounded-lg bg-background border border-border focus:border-primary focus:ring-1 focus:ring-primary outline-none"
        />
      </div>

      {/* Filters Row */}
      <div className="flex flex-wrap gap-2">
        {/* Severity Filter */}
        <select
          value={severity}
          onChange={(e) => {
            setSeverity(e.target.value as SeverityFilter);
            handleFilterChange();
          }}
          className="px-3 py-2 rounded-lg bg-background border border-border"
        >
          <option value="ALL">All Severity</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
          <option value="LOW">Low</option>
          <option value="INFO">Info</option>
        </select>

        {/* Tool Filter */}
        <select
          value={tool}
          onChange={(e) => {
            setTool(e.target.value);
            handleFilterChange();
          }}
          className="px-3 py-2 rounded-lg bg-background border border-border"
        >
          {uniqueTools.map((t) => (
            <option key={t} value={t}>
              {t === "ALL" ? "All Tools" : t}
            </option>
          ))}
        </select>

        {/* Status Filter */}
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as StatusFilter);
            handleFilterChange();
          }}
          className="px-3 py-2 rounded-lg bg-background border border-border"
        >
          <option value="ALL">All Status</option>
          <option value="VERIFIED">Verified</option>
          <option value="UNVERIFIED">Unverified</option>
        </select>

        {/* Sort */}
        <select
          value={sortBy}
          onChange={(e) => {
            setSortBy(e.target.value as "severity" | "date");
            handleFilterChange();
          }}
          className="px-3 py-2 rounded-lg bg-background border border-border"
        >
          <option value="severity">Sort by Severity</option>
          <option value="date">Sort by Date</option>
        </select>

        {/* Export */}
        <div className="flex gap-2 ml-auto">
          <button
            onClick={exportToCSV}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-background border border-border hover:bg-muted transition-colors"
          >
            <Download className="h-4 w-4" />
            CSV
          </button>
          <button
            onClick={exportToJSON}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-background border border-border hover:bg-muted transition-colors"
          >
            <Download className="h-4 w-4" />
            JSON
          </button>
        </div>
      </div>

      {/* Results Count */}
      <div className="text-sm text-muted-foreground">
        Showing {filteredFindings.length} of {findings.length} findings
      </div>
    </div>
  );
}
