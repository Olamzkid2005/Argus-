import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FindingsPage from "@/app/findings/page";

jest.mock("@/components/effects/ScannerReveal", () => ({ text }: any) => <span>{text}</span>);
jest.mock("@/components/ui-custom/AIStatus", () => ({
  AIStatusBadge: () => <div data-testid="ai-status">AI</div>,
}));
jest.mock("@/components/ui-custom/MarkdownRenderer", () => ({ content }: any) => <div>{content}</div>);

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

global.fetch = jest.fn();

describe("Findings Page", () => {
  const mockFindings = [
    {
      id: "CVE-2024-001",
      type: "SQL Injection",
      severity: "CRITICAL",
      endpoint: "/api/users",
      source_tool: "DeepScan",
      verified: false,
      confidence: 0.98,
      created_at: "2024-01-15T10:00:00Z",
      evidence: "Payload: ' OR 1=1 --",
    },
    {
      id: "CVE-2024-002",
      type: "XSS",
      severity: "HIGH",
      endpoint: "/search",
      source_tool: "Argus Guard",
      verified: true,
      confidence: 0.85,
      created_at: "2024-01-14T08:00:00Z",
    },
  ];

  beforeEach(() => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes("/api/findings")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ findings: mockFindings }),
        });
      }
      if (url.includes("/api/engagements")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ engagements: [] }),
        });
      }
      if (url.includes("/api/ai/explain")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ configured: true }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  });

  it("renders findings page header", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("Findings")).toBeInTheDocument();
    });
    expect(screen.getByText(/vulnerabilities discovered/i)).toBeInTheDocument();
  });

  it("renders severity filter buttons", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("CRITICAL")).toBeInTheDocument();
      expect(screen.getByText("HIGH")).toBeInTheDocument();
      expect(screen.getByText("MEDIUM")).toBeInTheDocument();
      expect(screen.getByText("LOW")).toBeInTheDocument();
      expect(screen.getByText("INFO")).toBeInTheDocument();
    });
  });

  it("renders findings list", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("SQL Injection")).toBeInTheDocument();
      expect(screen.getByText("XSS")).toBeInTheDocument();
    });
  });

  it("filters findings by severity", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("SQL Injection")).toBeInTheDocument();
      expect(screen.getByText("XSS")).toBeInTheDocument();
    });

    const criticalFilter = screen.getByText("CRITICAL");
    fireEvent.click(criticalFilter);

    await waitFor(() => {
      expect(screen.getByText("SQL Injection")).toBeInTheDocument();
    });
  });

  it("searches findings by query", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("SQL Injection")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/search patterns/i);
    await userEvent.type(searchInput, "XSS");

    await waitFor(() => {
      expect(screen.queryByText("SQL Injection")).not.toBeInTheDocument();
      expect(screen.getByText("XSS")).toBeInTheDocument();
    });
  });

  it("expands finding details on click", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("SQL Injection")).toBeInTheDocument();
    });

    const findingRow = screen.getByText("SQL Injection").closest("div");
    fireEvent.click(findingRow!);

    await waitFor(() => {
      expect(screen.getByText(/target endpoint/i)).toBeInTheDocument();
    });
  });

  it("renders AI analysis banner", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText(/ai vulnerability analysis available/i)).toBeInTheDocument();
    });
  });
});
