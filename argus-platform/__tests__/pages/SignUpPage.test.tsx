import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockPush = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/auth/signup",
}));

jest.mock("next-auth/react", () => ({
  signIn: jest.fn(),
}));

jest.mock("@/components/effects/MatrixDataRain", () => () => <div data-testid="matrix-rain" />);

global.fetch = jest.fn();

import SignUpPage from "@/app/auth/signup/page";

describe("SignUp Page", () => {
  beforeEach(() => {
    mockPush.mockClear();
    (global.fetch as jest.Mock).mockClear();
  });

  it("renders signup form with email field", () => {
    render(<SignUpPage />);
    expect(screen.getByPlaceholderText(/name@company.com/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeInTheDocument();
  });

  it("renders social signup buttons", () => {
    render(<SignUpPage />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(4);
  });

  it("submits form with user data", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });

    render(<SignUpPage />);

    // Step 1: Enter email and click Next
    const emailInput = screen.getByPlaceholderText(/name@company.com/i);
    fireEvent.change(emailInput, { target: { value: "newuser@argus.io" } });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    // Step 2: Fill in details and submit
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
    });

    const passwordInputs = document.querySelectorAll('input[type="password"]');
    const submitButton = screen.getByRole("button", { name: /create account/i });
    const form = submitButton.closest("form") as HTMLFormElement;

    fireEvent.change(passwordInputs[0], { target: { value: "SecurePass123!" } });
    fireEvent.change(passwordInputs[1], { target: { value: "SecurePass123!" } });
    fireEvent.submit(form);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/auth/signup",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );
    });
  });

  it("shows error when passwords do not match", async () => {
    render(<SignUpPage />);

    // Step 1: Enter email and click Next
    const emailInput = screen.getByPlaceholderText(/name@company.com/i);
    fireEvent.change(emailInput, { target: { value: "newuser@argus.io" } });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    // Step 2: Fill in mismatched passwords and submit
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
    });

    const passwordInputs = document.querySelectorAll('input[type="password"]');
    const submitButton = screen.getByRole("button", { name: /create account/i });
    const form = submitButton.closest("form") as HTMLFormElement;

    fireEvent.change(passwordInputs[0], { target: { value: "Password1" } });
    fireEvent.change(passwordInputs[1], { target: { value: "Password2" } });
    fireEvent.submit(form);

    await waitFor(() => {
      expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    });
  });
});
