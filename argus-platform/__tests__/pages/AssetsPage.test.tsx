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
    json: async () => ({
      assets: [],
      stats: { total: 0, critical: 0, high: 0, active: 0 },
    }),
  })
);

import AssetsPage from "@/app/assets/page";

describe("Assets Page", () => {
  it("renders assets header", async () => {
    render(<AssetsPage />);

    await waitFor(() => {
      expect(screen.getByText("Asset Inventory")).toBeInTheDocument();
    });
  });

  it("renders stats cards", async () => {
    render(<AssetsPage />);

    await waitFor(() => {
      expect(screen.getByText("Total Assets")).toBeInTheDocument();
      expect(screen.getByText("Critical Risk")).toBeInTheDocument();
    });
  });

  it("renders type filter buttons", async () => {
    render(<AssetsPage />);

    await waitFor(() => {
      expect(screen.getByText("all")).toBeInTheDocument();
      expect(screen.getByText("domain")).toBeInTheDocument();
    });
  });

  it("renders add asset button", async () => {
    render(<AssetsPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /add asset/i })).toBeInTheDocument();
    });
  });
});
