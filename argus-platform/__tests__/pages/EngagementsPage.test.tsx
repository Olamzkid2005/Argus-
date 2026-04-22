import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockPush = jest.fn();
jest.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useRouter: () => ({ push: mockPush }),
}));

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "test@argus.io" } }, status: "authenticated" }),
}));

jest.mock("@/components/effects/MatrixDataRain", () => () => <div data-testid="matrix-rain" />);
jest.mock("@/components/ui-custom/ScanModeHelp", () => ({ trigger }: any) => <span>{trigger}</span>);

global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: async () => ({ settings: { scan_aggressiveness: "default" } }),
  })
);

import EngagementsPage from "@/app/engagements/page";

describe("Engagements Page", () => {
  beforeEach(() => {
    mockPush.mockClear();
    (global.fetch as jest.Mock).mockClear();
  });

  it("renders engagement creation form", async () => {
    render(<EngagementsPage />);

    await waitFor(() => {
      expect(screen.getByText("New Scan Engagement")).toBeInTheDocument();
    });
  });

  it("renders scan type toggle buttons", async () => {
    render(<EngagementsPage />);

    await waitFor(() => {
      expect(screen.getByText("Web Application")).toBeInTheDocument();
      expect(screen.getByText("Repository")).toBeInTheDocument();
    });
  });

  it("renders target input and launch button", async () => {
    render(<EngagementsPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/https:\/\/target.com/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /launch engagement/i })).toBeInTheDocument();
  });

  it("renders aggressiveness presets", async () => {
    render(<EngagementsPage />);

    await waitFor(() => {
      expect(screen.getByText("Default")).toBeInTheDocument();
      expect(screen.getByText("High")).toBeInTheDocument();
      expect(screen.getByText("Extreme")).toBeInTheDocument();
    });
  });

  it("submits form to create engagement", async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string, options?: any) => {
      if (url === "/api/settings") {
        return Promise.resolve({ ok: true, json: async () => ({ settings: {} }) });
      }
      if (url === "/api/engagement/create") {
        return Promise.resolve({
          ok: true,
          json: async () => ({ engagement: { id: "eng-123" } }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<EngagementsPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/https:\/\/target.com/i)).toBeInTheDocument();
    });

    const targetInput = screen.getByPlaceholderText(/https:\/\/target.com/i);
    const launchButton = screen.getByRole("button", { name: /launch engagement/i });

    await userEvent.type(targetInput, "https://example.com");
    fireEvent.click(launchButton);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/engagement/create",
        expect.objectContaining({ method: "POST" })
      );
    });
  });
});
