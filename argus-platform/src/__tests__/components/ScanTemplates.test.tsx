import { render, screen, fireEvent } from "@testing-library/react";
import { ScanTemplates } from "@/components/ui-custom/ScanTemplates";

// Mock next/router
const mockPush = jest.fn();
jest.mock("next/router", () => ({
  useRouter: () => ({ push: mockPush }),
}));

describe("ScanTemplates", () => {
  const mockTemplates = [
    {
      id: "quick",
      name: "Quick Scan",
      description: "Fast scan with basic checks",
      icon: "⚡",
      settings: { aggressiveness: "default", tools: ["basics"], timeout: 300 },
    },
    {
      id: "full",
      name: "Full Scan",
      description: "Comprehensive security audit",
      icon: "🔍",
      settings: { aggressiveness: "high", tools: ["all"], timeout: 1800 },
    },
  ];

  it("should export ScanTemplates component", () => {
    const templatesModule = require("@/components/ui-custom/ScanTemplates");
    expect(templatesModule).toHaveProperty("ScanTemplates");
  });

  it("should render template cards", () => {
    render(
      <ScanTemplates
        selectedTemplate={null}
        onSelect={() => {}}
      />
    );

    expect(screen.getByText("Quick Scan")).toBeInTheDocument();
    expect(screen.getByText("Full Scan")).toBeInTheDocument();
  });

  it("should call onSelect when template is clicked", () => {
    const mockOnSelect = jest.fn();
    render(
      <ScanTemplates
        selectedTemplate={null}
        onSelect={mockOnSelect}
      />
    );

    const quickScan = screen.getByText("Quick Scan");
    fireEvent.click(quickScan);
    expect(mockOnSelect).toHaveBeenCalledWith("quick");
  });

  it("should highlight selected template", () => {
    render(
      <ScanTemplates
        selectedTemplate="quick"
        onSelect={() => {}}
      />
    );

    // selected template should have different styling
    const quickScanCard = screen.getByText("Quick Scan").closest("button");
    expect(quickScanCard).toBeInTheDocument();
    // Check that the card has the selected styling (bg-primary/5 shadow-glow)
    expect(quickScanCard).toHaveClass("bg-primary/5");
  });

  it("should show template descriptions", () => {
    render(
      <ScanTemplates
        selectedTemplate={null}
        onSelect={() => {}}
      />
    );

    expect(screen.getByText("Fast scan with basic checks")).toBeInTheDocument();
    expect(screen.getByText("Comprehensive security audit")).toBeInTheDocument();
  });
});
