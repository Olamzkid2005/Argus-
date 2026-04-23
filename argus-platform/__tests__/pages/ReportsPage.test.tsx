import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "test@argus.io" } }, status: "authenticated" }),
}));

jest.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@/components/effects/ScannerReveal", () => ({ text }: any) => <span>{text}</span>);

(global.fetch as jest.Mock) = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: async () => ({ reports: [] }),
  })
);

import ReportsPage from "@/app/reports/page";

describe("Reports Page", () => {
  it("renders reports header", async () => {
    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByText("Reports")).toBeInTheDocument();
    });
  });

  it("renders generate report button", async () => {
    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /generate report/i })).toBeInTheDocument();
    });
  });

  it("renders type filter tabs", async () => {
    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByText("All")).toBeInTheDocument();
      expect(screen.getByText("Engagement")).toBeInTheDocument();
      expect(screen.getByText("Executive")).toBeInTheDocument();
    });
  });

  it("renders search input", async () => {
    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search reports/i)).toBeInTheDocument();
    });
  });
});
