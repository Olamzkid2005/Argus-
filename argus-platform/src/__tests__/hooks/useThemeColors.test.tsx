import { render, screen } from "@testing-library/react";
import { useThemeColors } from "@/hooks/useThemeColors";

// Mock getComputedStyle
const mockGetComputedStyle = jest.fn();
Object.defineProperty(window, "getComputedStyle", {
  value: mockGetComputedStyle,
});

describe("useThemeColors", () => {
  it("should export the hook", () => {
    const hookModule = require("@/hooks/useThemeColors");
    expect(hookModule).toHaveProperty("useThemeColors");
  });

  it("should return theme colors", () => {
    mockGetComputedStyle.mockReturnValue({
      getPropertyValue: (prop: string) => {
        const values: Record<string, string> = {
          "--color-primary": "#6720FF",
          "--color-background": "#ffffff",
          "--color-surface": "#f5f5f5",
          "--color-text": "#171717",
          "--color-border": "#e5e5e5",
          "--color-success": "#10B981",
          "--color-error": "#EF4444",
          "--color-warning": "#F59E0B",
          "--color-info": "#3B82F6",
        };
        return values[prop] || "";
      },
    });

    let colors: any;
    const TestComponent = () => {
      colors = useThemeColors();
      return null;
    };

    render(<TestComponent />);
    expect(colors).toBeDefined();
    expect(colors.primary).toBe("#6720FF");
    expect(colors.background).toBe("#ffffff");
  });

  it("should update colors on theme change", () => {
    mockGetComputedStyle.mockReturnValue({
      getPropertyValue: (prop: string) => {
        const values: Record<string, string> = {
          "--color-primary": "#000000",
          "--color-background": "#000000",
          "--color-surface": "#111111",
          "--color-text": "#ffffff",
          "--color-border": "#333333",
          "--color-success": "#10B981",
          "--color-error": "#EF4444",
          "--color-warning": "#F59E0B",
          "--color-info": "#3B82F6",
        };
        return values[prop] || "";
      },
    });

    let colors: any;
    const TestComponent = () => {
      colors = useThemeColors();
      return null;
    };

    render(<TestComponent />);
    expect(colors.primary).toBe("#000000");
    expect(colors.background).toBe("#000000");
  });
});
