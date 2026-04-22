import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "test@argus.io" } }, status: "authenticated" }),
}));

jest.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div data-testid="recharts-container">{children}</div>,
  AreaChart: ({ children }: any) => <div data-testid="area-chart">{children}</div>,
  Area: () => <div data-testid="area" />,
  PieChart: ({ children }: any) => <div data-testid="pie-chart">{children}</div>,
  Pie: () => <div data-testid="pie" />,
  Cell: () => <div data-testid="cell" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  Legend: () => <div data-testid="legend" />,
  BarChart: ({ children }: any) => <div data-testid="bar-chart">{children}</div>,
  Bar: () => <div data-testid="bar" />,
}));

global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: async () => ({
      trends: [
        { date: "2024-01-01", critical: 2, high: 5, medium: 8, low: 3 },
        { date: "2024-01-02", critical: 1, high: 3, medium: 6, low: 2 },
      ],
      comparisons: [],
    }),
  })
);

import AnalyticsPage from "@/app/analytics/page";

describe("Analytics Page", () => {
  it("renders analytics header", async () => {
    render(<AnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByText("Analytics")).toBeInTheDocument();
    });
  });

  it("renders date range filters", async () => {
    render(<AnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByText(/7 days/i)).toBeInTheDocument();
      expect(screen.getByText(/30 days/i)).toBeInTheDocument();
      expect(screen.getByText(/90 days/i)).toBeInTheDocument();
    });
  });

  it("renders charts container", async () => {
    render(<AnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("recharts-container")).toBeInTheDocument();
    });
  });

  it("renders scheduled reports section", async () => {
    render(<AnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByText(/scheduled reports/i)).toBeInTheDocument();
    });
  });
});
