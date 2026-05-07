"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { log } from "@/lib/logger";
import {
  Users,
  MessageSquare,
  ClipboardList,
  CheckSquare,
  Activity,
  Bell,
  Loader2,
  Shield,
  Mail,
  Trash2,
  Plus,
  Send,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  UserPlus,
} from "lucide-react";

// ── Types ──
interface TeamMember {
  id: string;
  user_id: string;
  email: string;
  name: string;
  team_role: string;
  invitation_status: string;
  created_at: string;
}

interface FindingComment {
  id: string;
  content: string;
  parent_id: string | null;
  created_at: string;
  user_name: string;
  user_email: string;
}

interface Assignment {
  id: string;
  finding_id: string;
  finding_type: string;
  severity: string;
  endpoint: string;
  status: string;
  priority: string;
  due_date: string;
  assigned_to_name: string;
  assigned_to_email: string;
  assigned_by_email: string;
}

interface ApprovalRequest {
  id: string;
  workflow_name: string;
  workflow_type: string;
  status: string;
  requester_name: string;
  engagement_target: string;
  created_at: string;
  notes: string;
}

interface ActivityItem {
  id: string;
  activity_type: string;
  entity_type: string;
  entity_id: string;
  metadata: any;
  created_at: string;
  user_name: string;
}

interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

const TABS = [
  { id: "team", label: "Team", icon: Users },
  { id: "comments", label: "Comments", icon: MessageSquare },
  { id: "assignments", label: "Assignments", icon: ClipboardList },
  { id: "approvals", label: "Approvals", icon: CheckSquare },
  { id: "activity", label: "Activity", icon: Activity },
];

export default function CollaborationPage() {
  useEffect(() => {
    log.pageMount("Collaboration");
    return () => log.pageUnmount("Collaboration");
  }, []);

  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [activeTab, setActiveTab] = useState("team");
  const [isLoading, setIsLoading] = useState(true);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [comments, setComments] = useState<FindingComment[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequest[]>([]);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [newComment, setNewComment] = useState("");
  const [selectedFindingId, setSelectedFindingId] = useState("");
  const [showInviteForm, setShowInviteForm] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");

  useEffect(() => {
    if (status === "unauthenticated") signIn();
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchData = async () => {
      setIsLoading(true);
      try {
        const [teamRes, assignmentsRes, approvalsRes, activityRes] = await Promise.all([
          fetch("/api/collaboration/team"),
          fetch("/api/collaboration/assignments"),
          fetch("/api/collaboration/approvals"),
          fetch("/api/collaboration/activity"),
        ]);

        if (teamRes.ok) {
          const data = await teamRes.json();
          setTeamMembers(data.members || []);
        }
        if (assignmentsRes.ok) {
          const data = await assignmentsRes.json();
          setAssignments(data.assignments || []);
        }
        if (approvalsRes.ok) {
          const data = await approvalsRes.json();
          setApprovalRequests(data.requests || []);
        }
        if (activityRes.ok) {
          const data = await activityRes.json();
          setActivities(data.activities || []);
          setNotifications(data.notifications || []);
          setUnreadCount(data.unread_count || 0);
        }
      } catch (err) {
        console.error("Failed to fetch collaboration data:", err);
      } finally {
        setIsLoading(false);
      }
    };
    fetchData();
  }, [status]);

  const fetchComments = async (findingId: string) => {
    if (!findingId) return;
    try {
      const res = await fetch(`/api/collaboration/comments?finding_id=${findingId}`);
      if (res.ok) {
        const data = await res.json();
        setComments(data.comments || []);
      }
    } catch (err) {
      console.error("Failed to fetch comments:", err);
    }
  };

  const handleAddComment = async () => {
    if (!newComment.trim() || !selectedFindingId) return;
    try {
      const res = await fetch("/api/collaboration/comments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ finding_id: selectedFindingId, content: newComment }),
      });
      if (res.ok) {
        setNewComment("");
        fetchComments(selectedFindingId);
        showToast("success", "Comment added");
      }
    } catch (err) {
      showToast("error", "Failed to add comment");
    }
  };

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    try {
      const res = await fetch("/api/collaboration/team", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: inviteEmail, team_role: inviteRole }),
      });
      if (res.ok) {
        setInviteEmail("");
        setShowInviteForm(false);
        showToast("success", "Team member added");
        const teamRes = await fetch("/api/collaboration/team");
        if (teamRes.ok) {
          const data = await teamRes.json();
          setTeamMembers(data.members || []);
        }
      } else {
        showToast("error", "Failed to add team member");
      }
    } catch (err) {
      showToast("error", "Failed to add team member");
    }
  };

  const handleRemoveMember = async (id: string) => {
    if (!confirm("Remove this team member?")) return;
    try {
      const res = await fetch(`/api/collaboration/team?id=${id}`, { method: "DELETE" });
      if (res.ok) {
        setTeamMembers((prev) => prev.filter((m) => m.id !== id));
        showToast("success", "Team member removed");
      }
    } catch (err) {
      showToast("error", "Failed to remove team member");
    }
  };

  const handleApproveRequest = async (id: string, action: "approve" | "reject") => {
    try {
      const res = await fetch("/api/collaboration/approvals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, request_id: id }),
      });
      if (res.ok) {
        showToast("success", `Request ${action}d`);
        setApprovalRequests((prev) =>
          prev.map((r) => (r.id === id ? { ...r, status: action === "approve" ? "approved" : "rejected" } : r))
        );
      }
    } catch (err) {
      showToast("error", "Failed to process approval");
    }
  };

  const handleMarkAllRead = async () => {
    try {
      const res = await fetch("/api/collaboration/activity", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mark_all_read: true }),
      });
      if (res.ok) {
        setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
        setUnreadCount(0);
        showToast("success", "Notifications marked as read");
      }
    } catch (err) {
      showToast("error", "Failed to mark notifications as read");
    }
  };

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <Loader2 className="h-8 w-8 animate-spin text-on-surface" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen px-8 py-8 bg-surface">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-2">
          <Users size={18} className="text-on-surface" />
          <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">Collaboration Center</span>
          {unreadCount > 0 && (
            <span className="ml-2 text-[10px] font-mono px-1.5 py-0.5 bg-red-500/20 text-red-400 border border-red-500/30">
              {unreadCount} unread
            </span>
          )}
        </div>
        <h1 className="text-4xl font-semibold text-on-surface tracking-tight">COLLABORATION</h1>
        <p className="text-sm text-on-surface-variant mt-2">
          Team coordination, finding assignments, and approval workflows
        </p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 mb-6 border-b border-outline-variant">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-5 py-3 text-[10px] font-bold uppercase tracking-widest transition-all border-b-2 ${
              activeTab === tab.id
                ? "border-prism-cream text-on-surface bg-surface/30"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <tab.icon size={14} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Team Tab */}
      {activeTab === "team" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase">Team Members</h2>
            <button
              onClick={() => setShowInviteForm(!showInviteForm)}
              className="flex items-center gap-2 px-4 py-2 bg-prism-cream text-void text-[10px] font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow"
            >
              {showInviteForm ? <XCircle size={12} /> : <UserPlus size={12} />}
              {showInviteForm ? "Cancel" : "Invite Member"}
            </button>
          </div>

          {showInviteForm && (
            <div className="border border-outline-variant bg-surface/30 p-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="user@company.com"
                  className="px-3 py-2 bg-surface/50 border border-outline-variant text-xs text-on-surface outline-none focus:border-prism-cream transition-colors font-mono"
                />
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="px-3 py-2 bg-surface/50 border border-outline-variant text-xs text-on-surface outline-none focus:border-prism-cream transition-colors font-mono"
                >
                  <option value="admin">Admin</option>
                  <option value="member">Member</option>
                  <option value="viewer">Viewer</option>
                </select>
              </div>
              <button
                onClick={handleInvite}
                className="px-5 py-2 bg-prism-cream text-void text-[10px] font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow"
              >
                Add to Team
              </button>
            </div>
          )}

          <div className="border border-outline-variant bg-surface/20">
            <div className="grid grid-cols-[1fr_120px_120px_100px_40px] gap-4 px-5 py-3 border-b border-outline-variant text-[11px] font-mono text-on-surface-variant tracking-wider uppercase">
              <span>User</span>
              <span>Role</span>
              <span>Status</span>
              <span>Joined</span>
              <span></span>
            </div>
            {teamMembers.map((member) => (
              <div
                key={member.id}
                className="grid grid-cols-[1fr_120px_120px_100px_40px] gap-4 px-5 py-3 items-center border-b border-outline-variant last:border-b-0 hover:bg-surface/10 transition-colors"
              >
                <div>
                  <div className="text-sm text-on-surface">{member.name || member.email}</div>
                  <div className="text-[10px] text-on-surface-variant font-mono">{member.email}</div>
                </div>
                <span className="text-[10px] font-mono font-bold uppercase px-2 py-0.5 border border-outline-variant w-fit" style={{ color: "var(--prism-cream)" }}>
                  {member.team_role}
                </span>
                <span className="text-[10px] font-mono uppercase" style={{ color: member.invitation_status === "active" ? "#00FF88" : "var(--text-secondary)" }}>
                  {member.invitation_status}
                </span>
                <span className="text-[10px] font-mono text-on-surface-variant">
                  {new Date(member.created_at).toLocaleDateString()}
                </span>
                <button
                  onClick={() => handleRemoveMember(member.id)}
                  className="p-1.5 text-on-surface-variant hover:text-red-500 transition-colors"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            {teamMembers.length === 0 && (
              <div className="px-5 py-12 text-center text-on-surface-variant/40 italic text-sm tracking-widest uppercase">
                No team members yet
              </div>
            )}
          </div>
        </div>
      )}

      {/* Comments Tab */}
      {activeTab === "comments" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={selectedFindingId}
              onChange={(e) => {
                setSelectedFindingId(e.target.value);
                fetchComments(e.target.value);
              }}
              placeholder="Enter Finding ID to view comments..."
              className="flex-1 px-3 py-2 bg-surface/50 border border-outline-variant text-xs text-on-surface outline-none focus:border-prism-cream transition-colors font-mono"
            />
          </div>

          {selectedFindingId && (
            <>
              <div className="border border-outline-variant bg-surface/20 max-h-[400px] overflow-y-auto space-y-2 p-4">
                {comments.length === 0 ? (
                  <p className="text-[10px] font-mono text-on-surface-variant/40 uppercase tracking-widest text-center py-8">No comments yet</p>
                ) : (
                  comments.map((comment) => (
                    <div key={comment.id} className="border border-outline-variant bg-surface/10 p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] font-bold text-on-surface">{comment.user_name || comment.user_email}</span>
                        <span className="text-[9px] font-mono text-on-surface-variant">{new Date(comment.created_at).toLocaleString()}</span>
                      </div>
                      <p className="text-xs text-on-surface-variant">{comment.content}</p>
                    </div>
                  ))
                )}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddComment()}
                  placeholder="Add a comment..."
                  className="flex-1 px-3 py-2 bg-surface/50 border border-outline-variant text-xs text-on-surface outline-none focus:border-prism-cream transition-colors"
                />
                <button
                  onClick={handleAddComment}
                  className="px-4 py-2 bg-prism-cream text-void text-[10px] font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow"
                >
                  <Send size={12} />
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Assignments Tab */}
      {activeTab === "assignments" && (
        <div className="border border-outline-variant bg-surface/20">
          <div className="grid grid-cols-[1fr_120px_100px_100px_120px_40px] gap-4 px-5 py-3 border-b border-outline-variant text-[11px] font-mono text-on-surface-variant tracking-wider uppercase">
            <span>Finding</span>
            <span>Assigned To</span>
            <span>Status</span>
            <span>Priority</span>
            <span>Due</span>
            <span></span>
          </div>
          {assignments.map((a) => (
            <div key={a.id} className="grid grid-cols-[1fr_120px_100px_100px_120px_40px] gap-4 px-5 py-3 items-center border-b border-outline-variant last:border-b-0 hover:bg-surface/10 transition-colors">
              <div>
                <div className="text-xs text-on-surface font-mono">{a.finding_type}</div>
                <div className="text-[9px] text-on-surface-variant truncate">{a.endpoint}</div>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">{a.assigned_to_name || a.assigned_to_email}</div>
              <span className="text-[10px] font-mono uppercase" style={{ color: a.status === "resolved" ? "#00FF88" : a.status === "in_progress" ? "var(--prism-cyan)" : "var(--prism-cream)" }}>
                {a.status}
              </span>
              <span className="text-[10px] font-mono uppercase" style={{ color: a.priority === "urgent" ? "#FF4444" : a.priority === "high" ? "#FF8800" : "var(--text-secondary)" }}>
                {a.priority}
              </span>
              <span className="text-[10px] font-mono text-on-surface-variant">
                {a.due_date ? new Date(a.due_date).toLocaleDateString() : "—"}
              </span>
              <button
                onClick={async () => {
                  try {
                    const res = await fetch("/api/collaboration/assignments", {
                      method: "PATCH",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ id: a.id, status: a.status === "resolved" ? "closed" : "resolved" }),
                    });
                    if (res.ok) {
                      setAssignments((prev) => prev.map((x) => (x.id === a.id ? { ...x, status: a.status === "resolved" ? "closed" : "resolved" } : x)));
                      showToast("success", "Assignment updated");
                    }
                  } catch (err) {
                    showToast("error", "Failed to update assignment");
                  }
                }}
                className="p-1.5 text-on-surface-variant hover:text-prism-cyan transition-colors"
              >
                <CheckSquare size={12} />
              </button>
            </div>
          ))}
          {assignments.length === 0 && (
            <div className="px-5 py-12 text-center text-on-surface-variant/40 italic text-sm tracking-widest uppercase">
              No assignments yet
            </div>
          )}
        </div>
      )}

      {/* Approvals Tab */}
      {activeTab === "approvals" && (
        <div className="space-y-4">
          {approvalRequests.map((req) => (
            <div key={req.id} className="border border-outline-variant bg-surface/20 p-5">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <CheckSquare size={14} className="text-on-surface" />
                    <span className="text-sm font-medium text-on-surface">{req.workflow_name}</span>
                    <span className="text-[10px] font-mono px-2 py-0.5 border border-outline-variant" style={{ color: req.status === "approved" ? "#00FF88" : req.status === "rejected" ? "#FF4444" : "var(--prism-cyan)" }}>
                      {req.status}
                    </span>
                  </div>
                  <p className="text-[11px] text-on-surface-variant font-mono">
                    Requested by {req.requester_name} · {req.engagement_target || "N/A"}
                  </p>
                </div>
                <span className="text-[10px] font-mono text-on-surface-variant">{new Date(req.created_at).toLocaleDateString()}</span>
              </div>
              {req.notes && <p className="text-xs text-on-surface-variant mb-3">{req.notes}</p>}
              {req.status === "pending" && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => handleApproveRequest(req.id, "approve")}
                    className="flex items-center gap-2 px-4 py-2 bg-prism-cream text-void text-[10px] font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow"
                  >
                    <CheckCircle2 size={12} />
                    Approve
                  </button>
                  <button
                    onClick={() => handleApproveRequest(req.id, "reject")}
                    className="flex items-center gap-2 px-4 py-2 border border-red-500/30 text-red-400 text-[10px] font-bold uppercase tracking-widest hover:bg-red-500/10 transition-all"
                  >
                    <XCircle size={12} />
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
          {approvalRequests.length === 0 && (
            <div className="px-5 py-12 text-center text-on-surface-variant/40 italic text-sm tracking-widest uppercase border border-outline-variant">
              No approval requests
            </div>
          )}
        </div>
      )}

      {/* Activity Tab */}
      {activeTab === "activity" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase">Activity Feed</h2>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="text-[10px] font-mono text-prism-cyan hover:underline uppercase tracking-widest"
              >
                Mark all read ({unreadCount})
              </button>
            )}
          </div>

          {/* Notifications */}
          {notifications.length > 0 && (
            <div className="border border-outline-variant bg-surface/20 mb-4">
              <div className="px-5 py-3 border-b border-outline-variant text-[11px] font-mono text-on-surface-variant tracking-wider uppercase">
                Notifications
              </div>
              {notifications.map((n) => (
                <div key={n.id} className={`px-5 py-3 border-b border-outline-variant last:border-b-0 hover:bg-surface/10 transition-colors ${!n.is_read ? "bg-prism-cyan/5" : ""}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <Bell size={12} className={n.is_read ? "text-on-surface-variant" : "text-prism-cyan"} />
                    <span className="text-xs font-bold text-on-surface">{n.title}</span>
                    {!n.is_read && <div className="w-1.5 h-1.5 rounded-full bg-prism-cyan" />}
                  </div>
                  <p className="text-[11px] text-on-surface-variant">{n.message}</p>
                </div>
              ))}
            </div>
          )}

          {/* Activities */}
          <div className="border border-outline-variant bg-surface/20">
            <div className="px-5 py-3 border-b border-outline-variant text-[11px] font-mono text-on-surface-variant tracking-wider uppercase">
              Recent Activity
            </div>
            {activities.map((activity) => (
              <div key={activity.id} className="px-5 py-3 border-b border-outline-variant last:border-b-0 hover:bg-surface/10 transition-colors">
                <div className="flex items-center gap-2 mb-1">
                  <Activity size={12} className="text-on-surface-variant" />
                  <span className="text-[10px] font-mono uppercase text-on-surface">{activity.activity_type}</span>
                  <span className="text-[9px] font-mono text-on-surface-variant">{new Date(activity.created_at).toLocaleString()}</span>
                </div>
                <p className="text-[11px] text-on-surface-variant">
                  {activity.user_name || "System"} · {activity.entity_type} · {activity.entity_id.split("-")[0]}
                </p>
              </div>
            ))}
            {activities.length === 0 && (
              <div className="px-5 py-12 text-center text-on-surface-variant/40 italic text-sm tracking-widest uppercase">
                No recent activity
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
