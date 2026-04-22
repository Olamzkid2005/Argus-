import { render, screen } from "@testing-library/react";
import { StaggerContainer, StaggerItem } from "@/components/animations/StaggerContainer";

describe("StaggerContainer", () => {
  it("renders children with stagger animation", () => {
    render(
      <StaggerContainer staggerDelay={0.1} initialDelay={0.2}>
        <StaggerItem>
          <div data-testid="item-1">Item 1</div>
        </StaggerItem>
        <StaggerItem>
          <div data-testid="item-2">Item 2</div>
        </StaggerItem>
        <StaggerItem direction="left">
          <div data-testid="item-3">Item 3</div>
        </StaggerItem>
      </StaggerContainer>
    );

    expect(screen.getByTestId("item-1")).toBeInTheDocument();
    expect(screen.getByTestId("item-2")).toBeInTheDocument();
    expect(screen.getByTestId("item-3")).toBeInTheDocument();
  });
});
