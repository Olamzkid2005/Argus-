import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsPage from "@/app/settings/page";

jest.mock("next-auth/react", () => ({
  useSession: () => ({
    data: { user: { email: "test@argus.io" } },
    status: "authenticated",
  }),
  signOut: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

global.fetch = jest.fn();

describe("Settings Page", () => {
  const mockSettings = {
    openrouter_api_key: "sk-or-v1-••••••••••••••••",
    preferred_ai_model: "anthropic/claude-3.5-sonnet",
    scan_aggressiveness: "high",
  };

  beforeEach(() => {
    (global.fetch as jest.Mock).mockImplementation((url: string, options?: any) => {
      if (url === "/api/settings" && (!options || options.method !== "PUT")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ settings: mockSettings }),
        });
      }
      if (url === "/api/settings" && options?.method === "PUT") {
        return Promise.resolve({
          ok: true,
          json: async () => ({ success: true }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  });

  it("renders settings page header", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText("Settings")).toBeInTheDocument();
    });
    expect(screen.getByText(/manage operational parameters/i)).toBeInTheDocument();
  });

  it("renders API key section", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText(/openrouter api key/i)).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/sk-or-v1/i)).toBeInTheDocument();
    });
  });

  it("renders AI model selection", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText(/ai model selection/i)).toBeInTheDocument();
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

  it("allows selecting scan aggressiveness", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText("High")).toBeInTheDocument();
    });

    const defaultPreset = screen.getByText("Default").closest("button");
    fireEvent.click(defaultPreset!);

    await waitFor(() => {
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });

  it("saves settings on button click", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText(/save parameters/i)).toBeInTheDocument();
    });

    const saveButton = screen.getByRole("button", { name: /save parameters/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          method: "PUT",
          headers: { "Content-Type": "application/json" },
        })
      );
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
