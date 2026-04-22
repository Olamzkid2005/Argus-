import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DashboardPage from "@/app/dashboard/page";

// Mock hooks and components
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
  useScannerActivities: () => ({
    activities: [],
  }),
}));

jest.mock("@/components/effects/MatrixDataRain", () => () => <div data-testid="matrix-rain" />);
jest.mock("@/components/effects/SurveillanceEye", () => () => <div data-testid="surveillance-eye" />);
jest.mock("@/components/ui-custom/ScannerActivityPanel", () => ({ activities }: any) => (
  <div data-testid="scanner-panel">Scanner Activities: {activities.length}</div>
));
jest.mock("@/components/ui-custom/AIStatus", () => ({
  AIStatusBadge: () => <div data-testid="ai-status">AI Online</div>,
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

global.fetch = jest.fn();

describe("Dashboard Page", () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes("/api/dashboard/stats")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            findings: { total_findings: 1245, critical: 18, verified: 42 },
            engagements: { total_engagements: 42 },
            recent_engagements: [],
          }),
        });
      }
      if (url.includes("/api/tools/performance")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ tools: [] }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  });

  it("renders dashboard title and subtitle", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Main Intelligence Hub")).toBeInTheDocument();
    });
    expect(screen.getByText(/real-time infrastructure oversight/i)).toBeInTheDocument();
  });

  it("renders stats cards", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Findings")).toBeInTheDocument();
      expect(screen.getByText("Engagements")).toBeInTheDocument();
      expect(screen.getByText("Critical")).toBeInTheDocument();
    });
  });

  it("renders engagement input and monitor button", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/engagement id/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /monitor/i })).toBeInTheDocument();
  });

  it("renders network intelligence feed section", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Network Intelligence Feed")).toBeInTheDocument();
    });
  });

  it("renders scanner activity panel", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId("scanner-panel")).toBeInTheDocument();
    });
  });

  it("fetches dashboard stats on mount", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/dashboard/stats");
    });
  });
});
