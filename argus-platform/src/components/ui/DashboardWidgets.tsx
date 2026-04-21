"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  Activity,
  Shield,
  AlertTriangle,
  CheckCircle,
  Clock,
  TrendingUp,
  Target,
  Zap,
} from "lucide-react";

interface DashboardStats {
  engagements?: {
    total_engagements: number;
    completed: number;
    failed: number;
    in_progress: number;
  };
  findings?: {
    total_findings: number;
    critical: number;
    high: number;
    medium: number;
    verified: number;
  };
  recent_engagements?: Array<{
    id: string;
    target_url: string;
    status: string;
    created_at: string;
    findings_count: number;
  }>;
}

export function DashboardWidgets() {
  const { data: session, status } = useSession();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchStats = async () => {
      try {
        const res = await fetch("/api/dashboard/stats");
        if (res.ok) {
          const data = await res.json();
          setStats(data);
        }
      } catch (err) {
        console.error("Failed to fetch stats:", err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchStats();
  }, [status]);

  if (status === "loading" || isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-[120px] rounded-xl" />
        ))}
      </div>
    );
  }

  const widgets = [
    {
      title: "Total Engagements",
      value: stats?.engagements?.total_engagements || 0,
      icon: Target,
      color: "text-blue-400",
      bg: "bg-blue-500/10",
    },
    {
      title: "In Progress",
      value: stats?.engagements?.in_progress || 0,
      icon: Zap,
      color: "text-yellow-400",
      bg: "bg-yellow-500/10",
    },
    {
      title: "Critical Findings",
      value: stats?.findings?.critical || 0,
      icon: AlertTriangle,
      color: "text-red-400",
      bg: "bg-red-500/10",
    },
    {
      title: "Completed",
      value: stats?.engagements?.completed || 0,
      icon: CheckCircle,
      color: "text-green-400",
      bg: "bg-green-500/10",
    },
    {
      title: "Total Findings",
      value: stats?.findings?.total_findings || 0,
      icon: Shield,
      color: "text-purple-400",
      bg: "bg-purple-500/10",
    },
    {
      title: "Verified",
      value: stats?.findings?.verified || 0,
      icon: Activity,
      color: "text-cyan-400",
      bg: "bg-cyan-500/10",
    },
    {
      title: "Failed",
      value: stats?.engagements?.failed || 0,
      icon: Clock,
      color: "text-gray-400",
      bg: "bg-gray-500/10",
    },
    {
      title: "High Priority",
      value: stats?.findings?.high || 0,
      icon: TrendingUp,
      color: "text-orange-400",
      bg: "bg-orange-500/10",
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {widgets.map((widget) => (
        <div
          key={widget.title}
          className={`p-4 rounded-xl border border-border ${widget.bg}`}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-muted-foreground">{widget.title}</p>
              <p className="text-3xl font-bold mt-1">{widget.value}</p>
            </div>
            <widget.icon className={`h-8 w-8 ${widget.color}`} />
          </div>
        </div>
      ))}
    </div>
  );
}
