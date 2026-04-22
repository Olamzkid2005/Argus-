import { render, screen, waitFor } from "@testing-library/react";

const mockPush = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "test@argus.io" } }, status: "authenticated" }),
  signOut: jest.fn(),
}));

jest.mock("@/lib/use-engagement-events", () => ({
  useEngagementEvents: () => ({
    events: [],
    currentState: "created",
    isConnected: false,
    reconnect: jest.fn(),
    clearEvents: jest.fn(),
  }),
}));

jest.mock("@/lib/use-scanner-activities", () => ({
  useScannerActivities: () => ({ activities: [] }),
}));

jest.mock("@/components/effects/MatrixDataRain", () => () => <div data-testid="matrix-rain" />);
jest.mock("@/components/effects/SurveillanceEye", () => () => <div data-testid="surveillance-eye" />);
jest.mock("@/components/ui-custom/ScannerActivityPanel", () => ({
  __esModule: true,
  default: ({ activities }: any) => (
    <div data-testid="scanner-panel">Scanner Activities: {activities.length}</div>
  ),
}));
jest.mock("@/components/ui-custom/AIStatus", () => ({
  AIStatusBadge: () => <div data-testid="ai-status">AI Online</div>,
}));

jest.mock("@/components/ui-custom/AttackPathGraph", () => () => <div data-testid="attack-path-graph" />);
jest.mock("@/components/ui-custom/ExecutionTimeline", () => () => <div data-testid="execution-timeline" />);
jest.mock("@/components/ui-custom/ToolPerformanceMetrics", () => () => <div data-testid="tool-metrics" />);

global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: async () => ({
      findings: { total_findings: 1245, critical: 18, verified: 42 },
      engagements: { total_engagements: 42 },
      recent_engagements: [],
    }),
  })
);

import DashboardPage from "@/app/dashboard/page";

describe("Dashboard Page", () => {
  it("renders dashboard title and stats", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Main Intelligence Hub")).toBeInTheDocument();
    });
    expect(screen.getAllByText(/total findings/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Engagements")).toBeInTheDocument();
    expect(screen.getAllByText(/critical/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders engagement input and monitor button", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/engagement id/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /monitor/i })).toBeInTheDocument();
  });

  it("renders network intelligence feed", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Network Intelligence Feed")).toBeInTheDocument();
    });
  });

  it("renders scanner activity panel", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Scanner Activity")).toBeInTheDocument();
    });
  });
});
