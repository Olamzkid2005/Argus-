import { render, screen, waitFor } from "@testing-library/react";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: jest.fn(),
}));

jest.mock("@/components/effects/MatrixDataRain", () => () => <div data-testid="matrix-rain" />);
jest.mock("@/components/effects/SurveillanceEye", () => () => <div data-testid="surveillance-eye" />);

import LandingPage from "@/app/page";

describe("Landing Page", () => {
  it("renders the Argus brand", async () => {
    render(<LandingPage />);
    await waitFor(() => {
      expect(screen.getAllByText("Argus").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders CTA buttons", async () => {
    render(<LandingPage />);
    await waitFor(() => {
      expect(screen.getAllByRole("link", { name: /get started/i }).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole("link", { name: /login/i })).toBeInTheDocument();
    });
  });

  it("renders capabilities section with feature cards", async () => {
    render(<LandingPage />);
    await waitFor(() => {
      expect(screen.getByText(/Code Assistance/i)).toBeInTheDocument();
    });
  });

  it("renders footer", async () => {
    render(<LandingPage />);
    await waitFor(() => {
      expect(screen.getByText(/© 2026 argus systems/i)).toBeInTheDocument();
    });
  });
});
