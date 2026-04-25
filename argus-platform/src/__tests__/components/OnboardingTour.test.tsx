import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import OnboardingTour, {
  useOnboarding,
  STORAGE_KEY,
} from "@/components/ui-custom/OnboardingTour";

const mockGetItem = jest.fn();
const mockSetItem = jest.fn();
const mockRemoveItem = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  (window.localStorage.getItem as jest.Mock).mockImplementation(mockGetItem);
  (window.localStorage.setItem as jest.Mock).mockImplementation(mockSetItem);
  (window.localStorage.removeItem as jest.Mock).mockImplementation(
    mockRemoveItem
  );
});

describe("OnboardingTour - First-time detection", () => {
  it("opens the tour for first-time users", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => {
      expect(screen.getByTestId("onboarding-tour")).toBeInTheDocument();
    });
  });

  it("does not open the tour for returning users", async () => {
    mockGetItem.mockReturnValue("true");
    render(<OnboardingTour />);
    await waitFor(() => {
      expect(screen.queryByTestId("onboarding-tour")).not.toBeInTheDocument();
    });
  });
});

describe("OnboardingTour - Step progression", () => {
  const TOTAL_STEPS = 13;

  it("shows step 1 initially", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => screen.getByTestId("onboarding-tour"));
    expect(screen.getByTestId("step-counter")).toHaveTextContent(`1 of ${TOTAL_STEPS}`);
  });

  it("advances to next step when Next is clicked", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => screen.getByTestId("onboarding-tour"));

    fireEvent.click(screen.getByTestId("next-step-btn"));
    expect(screen.getByTestId("step-counter")).toHaveTextContent(`2 of ${TOTAL_STEPS}`);
  });

  it("goes back to previous step when Back is clicked", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => screen.getByTestId("onboarding-tour"));

    fireEvent.click(screen.getByTestId("next-step-btn"));
    expect(screen.getByTestId("step-counter")).toHaveTextContent(`2 of ${TOTAL_STEPS}`);

    fireEvent.click(screen.getByTestId("prev-step-btn"));
    expect(screen.getByTestId("step-counter")).toHaveTextContent(`1 of ${TOTAL_STEPS}`);
  });

  it("shows the Done button on the last step", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => screen.getByTestId("onboarding-tour"));

    // Advance to last step (12 clicks to get from step 1 to step 13)
    for (let i = 0; i < TOTAL_STEPS - 1; i++) {
      fireEvent.click(screen.getByTestId("next-step-btn"));
    }

    expect(screen.getByTestId("step-counter")).toHaveTextContent(`${TOTAL_STEPS} of ${TOTAL_STEPS}`);
    expect(screen.getByTestId("done-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("next-step-btn")).not.toBeInTheDocument();
  });

  it("does not show Back button on the first step", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => screen.getByTestId("onboarding-tour"));

    expect(screen.queryByTestId("prev-step-btn")).not.toBeInTheDocument();
  });
});

describe("OnboardingTour - Completion", () => {
  const TOTAL_STEPS = 13;

  it("sets localStorage flag when Done is clicked", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => screen.getByTestId("onboarding-tour"));

    // Advance to last step
    for (let i = 0; i < TOTAL_STEPS - 1; i++) {
      fireEvent.click(screen.getByTestId("next-step-btn"));
    }

    fireEvent.click(screen.getByTestId("done-btn"));

    expect(mockSetItem).toHaveBeenCalledWith(STORAGE_KEY, "true");
    await waitFor(() => {
      expect(screen.queryByTestId("onboarding-tour")).not.toBeInTheDocument();
    });
  });
});

describe("OnboardingTour - Skip functionality", () => {
  it("sets localStorage flag and closes when Skip is clicked", async () => {
    mockGetItem.mockReturnValue(null);
    render(<OnboardingTour />);
    await waitFor(() => screen.getByTestId("onboarding-tour"));

    fireEvent.click(screen.getByTestId("skip-tour-btn"));

    expect(mockSetItem).toHaveBeenCalledWith(STORAGE_KEY, "true");
    await waitFor(() => {
      expect(screen.queryByTestId("onboarding-tour")).not.toBeInTheDocument();
    });
  });

  it("allows restarting the tour via useOnboarding hook", async () => {
    mockGetItem.mockReturnValue("true");

    function TestComponent() {
      const { startTour, isOpen } = useOnboarding();
      return (
        <div>
          <button onClick={startTour} data-testid="restart-btn">
            Restart
          </button>
          {isOpen && <div data-testid="tour-open">Tour Open</div>}
        </div>
      );
    }

    render(<TestComponent />);
    await waitFor(() => {
      expect(screen.queryByTestId("tour-open")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("restart-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("tour-open")).toBeInTheDocument();
    });

    expect(mockRemoveItem).toHaveBeenCalledWith(STORAGE_KEY);
  });

  it("responds to the custom restart event by showing the overview grid", async () => {
    mockGetItem.mockReturnValue("true");
    render(<OnboardingTour />);
    await waitFor(() => {
      expect(screen.queryByTestId("onboarding-tour")).not.toBeInTheDocument();
    });

    act(() => {
      window.dispatchEvent(new CustomEvent("argus:restart-onboarding"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("onboarding-tour")).toBeInTheDocument();
    });
    // Restart shows the "All Steps Overview" grid with "Complete Tour" heading
    expect(screen.getByText("Complete Tour")).toBeInTheDocument();
    expect(screen.getByText("Start Interactive Tour")).toBeInTheDocument();
  });
});
