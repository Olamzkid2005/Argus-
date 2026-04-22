import { render, screen } from "@testing-library/react";
import { PageTransition, FadeIn, SlideUp } from "@/components/animations/PageTransition";

describe("Animation Components", () => {
  it("PageTransition renders children", () => {
    render(
      <PageTransition>
        <div data-testid="child">Content</div>
      </PageTransition>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("FadeIn renders children", () => {
    render(
      <FadeIn delay={0.2}>
        <div data-testid="fade-child">Faded Content</div>
      </FadeIn>
    );
    expect(screen.getByTestId("fade-child")).toBeInTheDocument();
  });

  it("SlideUp renders children", () => {
    render(
      <SlideUp delay={0.1} y={30}>
        <div data-testid="slide-child">Slid Content</div>
      </SlideUp>
    );
    expect(screen.getByTestId("slide-child")).toBeInTheDocument();
  });
});
