"use client";

/**
 * Dashboard Page with Real-Time Engagement Updates
 * 
 * Demonstrates WebSocket connection and real-time UI updates.
 * 
 * Requirements: 31.5
 */

import { useState } from "react";
import { useEngagementEvents } from "@/lib/use-engagement-events";
import { WebSocketEvent } from "@/lib/websocket-events";

export default function DashboardPage() {
  const [engagementId, setEngagementId] = useState<string>("");
  const [isConnected, setIsConnected] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [approveSuccess, setApproveSuccess] = useState<string | null>(null);

  const {
    events,
    currentState,
    isConnected: wsConnected,
    error,
    reconnect,
    clearEvents,
  } = useEngagementEvents({
    engagementId,
    enabled: isConnected && !!engagementId,
    pollingInterval: 2000,
    onEvent: (event: WebSocketEvent) => {
      console.log("Received event:", event);
    },
    onError: (err: Error) => {
      console.error("WebSocket error:", err);
    },
  });

  // Handle approve findings
  const handleApprove = async () => {
    if (!engagementId) return;

    setIsApproving(true);
    setApproveError(null);
    setApproveSuccess(null);

    try {
      const response = await fetch(`/api/engagement/${engagementId}/approve`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to approve engagement");
      }

      setApproveSuccess("Findings approved! Scan job has been queued.");
    } catch (err) {
      const error = err as Error;
      setApproveError(error.message);
    } finally {
      setIsApproving(false);
    }
  };

  // Group events by type
  const eventsByType = events.reduce(
    (acc, event) => {
      const type = event.type;
      if (!acc[type]) {
        acc[type] = [];
      }
      acc[type].push(event);
      return acc;
    },
    {} as Record<string, WebSocketEvent[]>
  );

  // Get severity color
  const getSeverityColor = (severity: string): string => {
    switch (severity.toUpperCase()) {
      case "CRITICAL":
        return "text-red-500";
      case "HIGH":
        return "text-orange-500";
      case "MEDIUM":
        return "text-yellow-500";
      case "LOW":
        return "text-blue-500";
      default:
        return "text-gray-400";
    }
  };

  // Get event type badge color
  const getEventBadgeColor = (type: string): string => {
    switch (type) {
      case "finding_discovered":
        return "bg-red-900/50 text-red-300";
      case "state_transition":
        return "bg-blue-900/50 text-blue-300";
      case "rate_limit_event":
        return "bg-yellow-900/50 text-yellow-300";
      case "tool_executed":
        return "bg-purple-900/50 text-purple-300";
      case "job_started":
        return "bg-green-900/50 text-green-300";
      case "job_completed":
        return "bg-gray-700 text-gray-300";
      case "error":
        return "bg-red-900 text-red-200";
      default:
        return "bg-gray-700 text-gray-300";
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Header */}
      <header className="border-b border-slate-700 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Argus Dashboard</h1>
            <p className="text-slate-400 text-sm">
              Real-Time Engagement Monitoring
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${wsConnected ? "bg-green-500" : "bg-red-500"}`}
              />
              <span className="text-sm text-slate-400">
                {wsConnected ? "Connected" : "Disconnected"}
              </span>
            </div>
            {engagementId && (
              <a
                href={`/findings/${engagementId}`}
                className="px-4 py-2 bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors text-sm"
              >
                View Findings
              </a>
            )}
            <a
              href="/"
              className="px-4 py-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors text-sm"
            >
              Home
            </a>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Connection Controls */}
        <div className="mb-8 p-6 bg-slate-800 rounded-lg border border-slate-700">
          <h2 className="text-lg font-semibold mb-4">Connect to Engagement</h2>
          <div className="flex gap-4">
            <input
              type="text"
              placeholder="Enter Engagement ID"
              value={engagementId}
              onChange={(e) => setEngagementId(e.target.value)}
              className="flex-1 px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={() => setIsConnected(!isConnected)}
              disabled={!engagementId}
              className={`px-6 py-2 rounded-lg font-medium transition-colors ${
                isConnected
                  ? "bg-red-600 hover:bg-red-700"
                  : "bg-blue-600 hover:bg-blue-700"
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {isConnected ? "Disconnect" : "Connect"}
            </button>
            <button
              onClick={reconnect}
              disabled={!engagementId}
              className="px-4 py-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Reconnect
            </button>
            <button
              onClick={clearEvents}
              disabled={events.length === 0}
              className="px-4 py-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Clear
            </button>
          </div>
          {error && (
            <p className="mt-4 text-red-400 text-sm">
              Error: {error.message}
            </p>
          )}
        </div>

        {/* Current State and Approve Button */}
        {currentState && (
          <div className="mb-6 p-4 bg-slate-800 rounded-lg border border-slate-700">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-slate-400">Current State:</span>
                <span className="px-3 py-1 bg-blue-900/50 text-blue-300 rounded-full text-sm font-medium">
                  {currentState}
                </span>
              </div>
              {currentState === "awaiting_approval" && (
                <button
                  onClick={handleApprove}
                  disabled={isApproving}
                  className="px-6 py-2 bg-green-600 hover:bg-green-700 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isApproving ? "Approving..." : "Approve Findings"}
                </button>
              )}
            </div>
            {approveSuccess && (
              <div className="mt-3 p-3 bg-green-900/30 border border-green-700 rounded text-green-300 text-sm">
                {approveSuccess}
              </div>
            )}
            {approveError && (
              <div className="mt-3 p-3 bg-red-900/30 border border-red-700 rounded text-red-300 text-sm">
                {approveError}
              </div>
            )}
          </div>
        )}

        {/* Event Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <p className="text-slate-400 text-sm">Total Events</p>
            <p className="text-2xl font-bold">{events.length}</p>
          </div>
          <div className="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <p className="text-slate-400 text-sm">Findings</p>
            <p className="text-2xl font-bold">
              {eventsByType["finding_discovered"]?.length || 0}
            </p>
          </div>
          <div className="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <p className="text-slate-400 text-sm">State Changes</p>
            <p className="text-2xl font-bold">
              {eventsByType["state_transition"]?.length || 0}
            </p>
          </div>
          <div className="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <p className="text-slate-400 text-sm">Tools Executed</p>
            <p className="text-2xl font-bold">
              {eventsByType["tool_executed"]?.length || 0}
            </p>
          </div>
        </div>

        {/* Events List */}
        <div className="bg-slate-800 rounded-lg border border-slate-700">
          <div className="px-6 py-4 border-b border-slate-700">
            <h2 className="text-lg font-semibold">Recent Events</h2>
          </div>
          <div className="divide-y divide-slate-700 max-h-[600px] overflow-y-auto">
            {events.length === 0 ? (
              <div className="px-6 py-12 text-center text-slate-400">
                {engagementId
                  ? "No events yet. Waiting for real-time updates..."
                  : "Enter an Engagement ID to start monitoring."}
              </div>
            ) : (
              events.map((event, index) => (
                <div key={`${event.type}-${index}`} className="px-6 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-medium ${getEventBadgeColor(event.type)}`}
                        >
                          {event.type.replace(/_/g, " ")}
                        </span>
                        <span className="text-xs text-slate-500">
                          {new Date(event.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      <EventDetails event={event} getSeverityColor={getSeverityColor} />
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

/**
 * Event details component
 */
function EventDetails({
  event,
  getSeverityColor,
}: {
  event: WebSocketEvent;
  getSeverityColor: (severity: string) => string;
}) {
  switch (event.type) {
    case "finding_discovered":
      return (
        <div className="text-sm">
          <p>
            <span className={getSeverityColor(event.data.severity as string)}>
              {event.data.severity as string}
            </span>
            {" - "}
            <span className="text-white">{event.data.finding_type as string}</span>
          </p>
          <p className="text-slate-400 text-xs mt-1 truncate">
            {event.data.endpoint as string}
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Confidence: {((event.data.confidence as number) * 100).toFixed(0)}% | Tool: {event.data.source_tool as string}
          </p>
        </div>
      );

    case "state_transition":
      return (
        <div className="text-sm">
          <p>
            <span className="text-slate-400">{event.data.from_state as string}</span>
            <span className="mx-2">→</span>
            <span className="text-blue-300">{event.data.to_state as string}</span>
          </p>
          {(event.data.reason as string | null) && (
            <p className="text-slate-500 text-xs mt-1">
              Reason: {event.data.reason as string}
            </p>
          )}
        </div>
      );

    case "rate_limit_event":
      return (
        <div className="text-sm">
          <p>
            Domain: <span className="text-white">{event.data.domain as string}</span>
          </p>
          <p className="text-slate-400 text-xs mt-1">
            {event.data.message as string} | RPS: {(event.data.current_rps as number).toFixed(1)}
          </p>
        </div>
      );

    case "tool_executed":
      return (
        <div className="text-sm">
          <p>
            Tool: <span className="text-purple-300">{event.data.tool_name as string}</span>
            {" | "}
            <span className={event.data.success ? "text-green-400" : "text-red-400"}>
              {event.data.success ? "Success" : "Failed"}
            </span>
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Duration: {event.data.duration_ms as number}ms | Findings: {event.data.findings_count as number}
          </p>
        </div>
      );

    case "job_started":
      return (
        <div className="text-sm">
          <p>
            Job: <span className="text-green-300">{event.data.job_type as string}</span>
          </p>
          {(event.data.target as string | null) && (
            <p className="text-slate-400 text-xs mt-1 truncate">
              Target: {event.data.target as string}
            </p>
          )}
        </div>
      );

    case "job_completed":
      return (
        <div className="text-sm">
          <p>
            Job: <span className="text-gray-300">{event.data.job_type as string}</span>
            {" | "}
            <span className={event.data.status === "success" ? "text-green-400" : "text-red-400"}>
              {event.data.status as string}
            </span>
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Duration: {event.data.duration_ms as number}ms | Findings: {event.data.findings_count as number}
          </p>
        </div>
      );

    case "error":
      return (
        <div className="text-sm">
          <p className="text-red-400">{event.data.error_message as string}</p>
          <p className="text-slate-500 text-xs mt-1">
            Code: {event.data.error_code as string}
          </p>
        </div>
      );

    default:
      return (
        <pre className="text-xs text-slate-400">
          {JSON.stringify(event.data, null, 2)}
        </pre>
      );
  }
}
