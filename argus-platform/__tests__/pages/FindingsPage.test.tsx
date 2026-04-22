import { render, screen, waitFor } from "@testing-library/react";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "test@argus.io" } }, status: "authenticated" }),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/findings",
}));

jest.mock("@/components/effects/ScannerReveal", () => ({ text }: any) => <span>{text}</span>);
jest.mock("@/components/ui-custom/AIStatus", () => ({
  AIStatusBadge: () => <div data-testid="ai-status">AI</div>,
}));
jest.mock("@/components/ui-custom/MarkdownRenderer", () => ({ content }: any) => <div>{content}</div>);

global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: async () => ({ findings: [], engagements: [], configured: true }),
  })
);

import FindingsPage from "@/app/findings/page";

describe("Findings Page", () => {
  it("renders findings header", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("Findings")).toBeInTheDocument();
    });
  });

  it("renders severity filter buttons", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByText("CRITICAL")).toBeInTheDocument();
      expect(screen.getByText("HIGH")).toBeInTheDocument();
      expect(screen.getByText("MEDIUM")).toBeInTheDocument();
    });
  });

  it("renders search input", async () => {
    render(<FindingsPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search findings/i)).toBeInTheDocument();
    });
  });
});
