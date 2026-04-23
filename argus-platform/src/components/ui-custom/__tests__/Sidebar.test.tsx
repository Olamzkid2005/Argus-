import { render, screen, fireEvent } from "@testing-library/react";
import Sidebar from "@/components/ui-custom/Sidebar";

// Mock usePathname
const mockUsePathname = jest.fn();
jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

// Mock AIStatusIndicator
jest.mock("@/components/ui-custom/AIStatus", () => ({
  AIStatusIndicator: () => <div data-testid="ai-status">AI Status</div>,
}));

// Mock next-themes (jest.setup.tsx also mocks this, but we need setTheme access here)
const mockSetTheme = jest.fn();
jest.mock("next-themes", () => ({
  useTheme: () => ({
    theme: "light",
    setTheme: mockSetTheme,
    resolvedTheme: "light",
  }),
}));

describe("Sidebar", () => {
  const mockOpenCommandPalette = jest.fn();
  const mockOnClose = jest.fn();

  beforeEach(() => {
    mockUsePathname.mockReturnValue("/dashboard");
    mockOpenCommandPalette.mockClear();
    mockSetTheme.mockClear();
    mockOnClose.mockClear();
  });

  it("renders brand and navigation items", () => {
    render(<Sidebar onOpenCommandPalette={mockOpenCommandPalette} onClose={mockOnClose} />);

    expect(screen.getByText("ARGUS")).toBeInTheDocument();
    expect(screen.getByText("SOC Infrastructure")).toBeInTheDocument();

    // Nav items
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Engagements")).toBeInTheDocument();
    expect(screen.getByText("Findings")).toBeInTheDocument();
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText("Rules")).toBeInTheDocument();
    expect(screen.getByText("Reports")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("highlights active nav item based on pathname", () => {
    mockUsePathname.mockReturnValue("/findings");
    render(<Sidebar onOpenCommandPalette={mockOpenCommandPalette} onClose={mockOnClose} />);

    const findingsLink = screen.getByText("Findings").closest("a");
    expect(findingsLink).toHaveClass("bg-white");
  });

  it("triggers command palette on button click", () => {
    render(<Sidebar onOpenCommandPalette={mockOpenCommandPalette} onClose={mockOnClose} />);

    const cmdButton = screen.getByText("Command").closest("button");
    fireEvent.click(cmdButton!);
    expect(mockOpenCommandPalette).toHaveBeenCalledTimes(1);
  });

  it("toggles theme when dark mode button is clicked", () => {
    render(<Sidebar onOpenCommandPalette={mockOpenCommandPalette} onClose={mockOnClose} />);

    const themeButton = screen.getByText("Dark Mode").closest("button");
    fireEvent.click(themeButton!);
    expect(mockSetTheme).toHaveBeenCalledWith("dark");
  });

  it("renders Report Incident button", () => {
    render(<Sidebar onOpenCommandPalette={mockOpenCommandPalette} onClose={mockOnClose} />);
    expect(screen.getByText("Report Incident")).toBeInTheDocument();
  });

  it("renders user profile section", () => {
    render(<Sidebar onOpenCommandPalette={mockOpenCommandPalette} onClose={mockOnClose} />);
    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Admin Level")).toBeInTheDocument();
  });

  it("renders Support and Logs links", () => {
    render(<Sidebar onOpenCommandPalette={mockOpenCommandPalette} onClose={mockOnClose} />);
    expect(screen.getByText("Support")).toBeInTheDocument();
    expect(screen.getByText("Logs")).toBeInTheDocument();
  });
});
