"use client";

import { useEffect, useState } from "react";
import { getRatingColor, getRatingLabel } from "@/lib/security-rating";

interface SecurityRatingProps {
  engagementId?: string;
  className?: string;
  showDetails?: boolean;
}

interface SecurityRatingData {
  rating: number;
  label: string;
  color: string;
  total_findings: number;
  actionable_findings: number;
  severity_counts: {
    CRITICAL: number;
    HIGH: number;
    MEDIUM: number;
    LOW: number;
    INFO: number;
  };
}

export default function SecurityRating({
  engagementId,
  className = "",
  showDetails = true,
}: SecurityRatingProps) {
  const [data, setData] = useState<SecurityRatingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSecurityRating();
  }, [engagementId]);

  async function fetchSecurityRating() {
    try {
      setLoading(true);
      const url = new URL(
        "/api/security-rating",
        window.location.origin
      );
      if (engagementId && engagementId !== "all") {
        url.searchParams.set("engagement_id", engagementId);
      }

      const res = await fetch(url.toString());
      if (!res.ok) throw new Error("Failed to fetch security rating");

      const result = await res.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className={`animate-pulse ${className}`}>
        <div className="flex items-center justify-center p-8">
          <div className="h-32 w-32 rounded-full bg-gray-200 dark:bg-gray-700"></div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className={`text-red-500 ${className}`}>
        Error loading security rating
      </div>
    );
  }

  const { rating, label, color, severity_counts } = data;

  // Calculate stroke-dasharray for circular progress
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const strokeDasharray = circumference;
  const strokeDashoffset = circumference - (rating / 100) * circumference;

  return (
    <div className={`${className}`}>
      <div className="flex flex-col items-center space-y-4">
        {/* Circular Gauge */}
        <div className="relative inline-flex items-center justify-center">
          <svg width="160" height="160" className="-rotate-90">
            {/* Background circle */}
            <circle
              cx="80"
              cy="80"
              r={radius}
              fill="none"
              stroke="#e5e7eb"
              strokeWidth="12"
              className="dark:stroke-gray-700"
            />
            {/* Progress circle */}
            <circle
              cx="80"
              cy="80"
              r={radius}
              fill="none"
              stroke={color}
              strokeWidth="12"
              strokeDasharray={strokeDasharray}
              strokeDashoffset={strokeDashoffset}
              strokeLinecap="round"
              style={{
                transition: "stroke-dashoffset 1s ease-in-out",
              }}
            />
          </svg>
          {/* Center content */}
          <div className="absolute flex flex-col items-center justify-center">
            <span
              className="text-4xl font-bold"
              style={{ color }}
            >
              {rating}%
            </span>
            <span
              className="text-sm font-medium"
              style={{ color }}
            >
              {label}
            </span>
          </div>
        </div>

        {/* Details Section */}
        {showDetails && (
          <div className="w-full max-w-sm">
            {/* Severity Breakdown */}
            <div className="space-y-2">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                  Vulnerability Breakdown
                </h4>
                <div className="relative group">
                  <button
                    type="button"
                    aria-label="Security rating scoring rules"
                    className="h-5 w-5 rounded-full border border-gray-300 dark:border-gray-600 text-[11px] font-bold text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                  >
                    ?
                  </button>
                  <div className="pointer-events-none absolute right-0 z-20 mt-2 w-72 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-[11px] leading-relaxed text-gray-700 dark:text-gray-200 opacity-0 shadow-lg transition-opacity duration-75 group-hover:opacity-100 group-focus-within:opacity-100">
                    Scoring starts at 100%. Deductions per finding: Critical -10%,
                    High -5%, Medium -2%, Low -1%, Info -0.25%.
                  </div>
                </div>
              </div>
              <SeverityBar
                label="Critical"
                count={severity_counts.CRITICAL}
                color="#EF4444"
              />
              <SeverityBar
                label="High"
                count={severity_counts.HIGH}
                color="#F97316"
              />
              <SeverityBar
                label="Medium"
                count={severity_counts.MEDIUM}
                color="#F59E0B"
              />
              <SeverityBar
                label="Low"
                count={severity_counts.LOW}
                color="#10B981"
              />
              <SeverityBar
                label="Info"
                count={severity_counts.INFO}
                color="#6720FF"
              />
            </div>

            {/* Stats */}
            <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="text-gray-600 dark:text-gray-400">
                  Total Findings:
                </div>
                <div className="font-semibold text-right">
                  {data.total_findings}
                </div>
                <div className="text-gray-600 dark:text-gray-400">
                  Actionable:
                </div>
                <div className="font-semibold text-right">
                  {data.actionable_findings}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SeverityBar({
  label,
  count,
  color,
}: {
  label: string;
  count: number;
  color: string;
}) {
  if (count === 0) return null;

  return (
    <div className="flex items-center justify-between text-sm">
      <div className="flex items-center space-x-2">
        <div
          className="w-3 h-3 rounded-full"
          style={{ backgroundColor: color }}
        />
        <span className="text-gray-700 dark:text-gray-300">{label}</span>
      </div>
      <span className="font-semibold" style={{ color }}>
        {count}
      </span>
    </div>
  );
}
