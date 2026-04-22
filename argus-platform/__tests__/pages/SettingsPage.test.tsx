import { render, screen, waitFor } from "@testing-library/react";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "test@argus.io" } }, status: "authenticated" }),
  signOut: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/settings",
}));

jest.mock("@/components/ui-custom/ScanModeHelp", () => ({ trigger }: any) => <span>{trigger}</span>);

global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: async () => ({
      settings: {
        openrouter_api_key: "sk-or-v1-test",
        preferred_ai_model: "anthropic/claude-3.5-sonnet",
        scan_aggressiveness: "high",
      },
    }),
  })
);

import SettingsPage from "@/app/settings/page";

describe("Settings Page", () => {
  it("renders settings header", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText("Settings")).toBeInTheDocument();
    });
  });

  it("renders API key input", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/sk-or-v1/i)).toBeInTheDocument();
    });
  });

  it("renders scan aggressiveness presets", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText("Default")).toBeInTheDocument();
      expect(screen.getByText("High")).toBeInTheDocument();
      expect(screen.getByText("Extreme")).toBeInTheDocument();
    });
  });

  it("renders dark mode toggle", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText(/dark mode/i)).toBeInTheDocument();
    });
  });

  it("renders logout button", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /revoke access/i })).toBeInTheDocument();
    });
  });
});
