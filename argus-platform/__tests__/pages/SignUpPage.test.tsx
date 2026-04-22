import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

  it("renders signup form with all fields", () => {
    render(<SignUpPage />);
    expect(screen.getByPlaceholderText(/you@company.com/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
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

    const emailInput = screen.getByPlaceholderText(/you@company.com/i);
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    const submitButton = screen.getByRole("button", { name: /create account/i });

    await userEvent.type(emailInput, "newuser@argus.io");
    fireEvent.change(passwordInputs[0], { target: { value: "SecurePass123!" } });
    fireEvent.change(passwordInputs[1], { target: { value: "SecurePass123!" } });
    fireEvent.click(submitButton);

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

    const emailInput = screen.getByPlaceholderText(/you@company.com/i);
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    const submitButton = screen.getByRole("button", { name: /create account/i });

    await userEvent.type(emailInput, "newuser@argus.io");
    fireEvent.change(passwordInputs[0], { target: { value: "Password1" } });
    fireEvent.change(passwordInputs[1], { target: { value: "Password2" } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    });
  });
});
