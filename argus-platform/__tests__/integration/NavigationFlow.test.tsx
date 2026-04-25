import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import Sidebar from "@/components/ui-custom/Sidebar";

const mockUsePathname = jest.fn();
jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

jest.mock("next-themes", () => ({
  useTheme: () => ({
    theme: "light",
    setTheme: jest.fn(),
    resolvedTheme: "light",
  }),
}));

jest.mock("@/components/ui-custom/AIStatus", () => ({
  AIStatusIndicator: () => <div data-testid="ai-status">AI</div>,
}));

describe("Navigation Integration", () => {
  it("renders all navigation links in sidebar", () => {
    mockUsePathname.mockReturnValue("/dashboard");
    render(<Sidebar onOpenCommandPalette={jest.fn()} />);

    const navLinks = [
      "Dashboard",
      "Engagements",
      "Findings",
      "Assets",
      "Rules",
      "Reports",
      "Settings",
    ];

    navLinks.forEach((link) => {
      expect(screen.getByText(link)).toBeInTheDocument();
    });
  });

  it("highlights the active page", () => {
    mockUsePathname.mockReturnValue("/findings");
    render(<Sidebar onOpenCommandPalette={jest.fn()} />);

    const findingsLink = screen.getByText("Findings").closest("a");
    expect(findingsLink).toHaveClass("bg-[#6720FF]/10");
  });

  it("does not highlight inactive pages", () => {
    mockUsePathname.mockReturnValue("/dashboard");
    render(<Sidebar onOpenCommandPalette={jest.fn()} />);

    const findingsLink = screen.getByText("Findings").closest("a");
    expect(findingsLink).not.toHaveClass("bg-[#6720FF]/10");
  });
});
