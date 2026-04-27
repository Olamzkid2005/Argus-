import { render, screen, fireEvent } from "@testing-library/react";
import { useTheme, ThemeProvider } from "next-themes";

// We test the theme toggle behavior by mocking next-themes
const mockSetTheme = jest.fn();

jest.mock("next-themes", () => ({
  useTheme: () => ({
    theme: "light",
    setTheme: mockSetTheme,
    resolvedTheme: "light",
  }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Import a component that uses the theme
import Sidebar from "@/components/ui-custom/Sidebar";

jest.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

jest.mock("@/components/ui-custom/AIStatus", () => ({
  AIStatusIndicator: () => <div data-testid="ai-status">AI</div>,
}));

describe("Dark Mode Integration", () => {
  beforeEach(() => {
    mockSetTheme.mockClear();
  });

  it("renders in light mode by default", () => {
    render(<Sidebar onOpenCommandPalette={jest.fn()} onClose={() => {}} />);
    expect(screen.getByText("Dark Mode")).toBeInTheDocument();
  });

  it("toggles to dark mode when clicked", () => {
    render(<Sidebar onOpenCommandPalette={jest.fn()} onClose={() => {}} />);

    const themeButton = screen.getByText("Dark Mode").closest("button");
    fireEvent.click(themeButton!);

    expect(mockSetTheme).toHaveBeenCalledWith("dark");
  });
});
