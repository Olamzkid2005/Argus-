import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { email: "test@argus.io" } }, status: "authenticated" }),
}));

jest.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useRouter: () => ({ push: jest.fn() }),
}));

global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: async () => ({ rules: [] }),
  })
);

import RulesPage from "@/app/rules/page";

describe("Rules Page", () => {
  it("renders rules header", async () => {
    render(<RulesPage />);

    await waitFor(() => {
      expect(screen.getByText("Custom Rule Engine")).toBeInTheDocument();
    });
  });

  it("renders status filter buttons", async () => {
    render(<RulesPage />);

    await waitFor(() => {
      expect(screen.getByText("all")).toBeInTheDocument();
      expect(screen.getByText("active")).toBeInTheDocument();
      expect(screen.getByText("draft")).toBeInTheDocument();
    });
  });

  it("renders new rule button", async () => {
    render(<RulesPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /new rule/i })).toBeInTheDocument();
    });
  });

  it("shows empty state when no rules exist", async () => {
    render(<RulesPage />);

    await waitFor(() => {
      expect(screen.getByText(/no rules found/i)).toBeInTheDocument();
    });
  });
});
