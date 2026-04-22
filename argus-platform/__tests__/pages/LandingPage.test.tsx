import { render, screen, waitFor } from "@testing-library/react";
import LandingPage from "@/app/page";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: jest.fn(),
}));

describe("Landing Page", () => {
  it("renders the Argus brand and headline", async () => {
    render(<LandingPage />);

    await waitFor(() => {
      expect(screen.getByText(/build\. tune\. scale\./i)).toBeInTheDocument();
    });
  });

  it("renders primary CTA buttons", async () => {
    render(<LandingPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /get started/i })).toBeInTheDocument();
    });
  });

  it("renders capabilities section", async () => {
    render(<LandingPage />);

    await waitFor(() => {
      expect(screen.getByText(/infrastructure scan/i)).toBeInTheDocument();
    });
  });

  it("renders footer", async () => {
    render(<LandingPage />);

    await waitFor(() => {
      expect(screen.getByText(/© 2026 argus systems/i)).toBeInTheDocument();
    });
  });
});
