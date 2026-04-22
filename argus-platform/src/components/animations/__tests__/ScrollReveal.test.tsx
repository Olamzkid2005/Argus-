import { render, screen } from "@testing-library/react";
import { ScrollReveal } from "@/components/animations/ScrollReveal";

describe("ScrollReveal", () => {
  it("renders children", () => {
    render(
      <ScrollReveal direction="up" delay={0.2}>
        <div data-testid="scroll-child">Revealed Content</div>
      </ScrollReveal>
    );
    expect(screen.getByTestId("scroll-child")).toBeInTheDocument();
  });

  it("renders with different directions", () => {
    const { rerender } = render(
      <ScrollReveal direction="left">
        <div data-testid="dir-child">Left</div>
      </ScrollReveal>
    );
    expect(screen.getByTestId("dir-child")).toBeInTheDocument();

    rerender(
      <ScrollReveal direction="right">
        <div data-testid="dir-child">Right</div>
      </ScrollReveal>
    );
    expect(screen.getByTestId("dir-child")).toBeInTheDocument();

    rerender(
      <ScrollReveal direction="down">
        <div data-testid="dir-child">Down</div>
      </ScrollReveal>
    );
    expect(screen.getByTestId("dir-child")).toBeInTheDocument();
  });
});
