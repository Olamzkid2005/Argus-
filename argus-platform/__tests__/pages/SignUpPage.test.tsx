import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SignUpPage from "@/app/auth/signup/page";

const mockPush = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

global.fetch = jest.fn();

describe("SignUp Page", () => {
  beforeEach(() => {
    mockPush.mockClear();
    (global.fetch as jest.Mock).mockClear();
  });

  it("renders signup form with all fields", () => {
    render(<SignUpPage />);

    expect(screen.getByPlaceholderText(/name@company.com/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i) || screen.getByPlaceholderText(/••••••••/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
  });

  it("renders social signup buttons", () => {
    render(<SignUpPage />);

    expect(screen.getByText(/google/i)).toBeInTheDocument();
    expect(screen.getByText(/github/i)).toBeInTheDocument();
    expect(screen.getByText(/linkedin/i)).toBeInTheDocument();
  });

  it("renders login link for existing users", () => {
    render(<SignUpPage />);
    expect(screen.getByText(/already have an account/i)).toBeInTheDocument();
    expect(screen.getByText(/login/i)).toBeInTheDocument();
  });

  it("submits form with user data", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });

    render(<SignUpPage />);

    const emailInput = screen.getByPlaceholderText(/name@company.com/i);
    const passwordInputs = screen.getAllByPlaceholderText(/••••••••/i);
    const submitButton = screen.getByRole("button", { name: /create account/i });

    await userEvent.type(emailInput, "newuser@argus.io");
    await userEvent.type(passwordInputs[0], "SecurePass123!");
    await userEvent.type(passwordInputs[1], "SecurePass123!");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/auth/signup",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: expect.stringContaining("newuser@argus.io"),
        })
      );
    });
  });

  it("shows error when passwords do not match", async () => {
    render(<SignUpPage />);

    const emailInput = screen.getByPlaceholderText(/name@company.com/i);
    const passwordInputs = screen.getAllByPlaceholderText(/••••••••/i);
    const submitButton = screen.getByRole("button", { name: /create account/i });

    await userEvent.type(emailInput, "newuser@argus.io");
    await userEvent.type(passwordInputs[0], "Password1");
    await userEvent.type(passwordInputs[1], "Password2");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    });
  });

  it("shows success state and redirects after signup", async () => {
    jest.useFakeTimers();
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });

    render(<SignUpPage />);

    const emailInput = screen.getByPlaceholderText(/name@company.com/i);
    const passwordInputs = screen.getAllByPlaceholderText(/••••••••/i);
    const submitButton = screen.getByRole("button", { name: /create account/i });

    await userEvent.type(emailInput, "newuser@argus.io");
    await userEvent.type(passwordInputs[0], "SecurePass123!");
    await userEvent.type(passwordInputs[1], "SecurePass123!");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/account created/i)).toBeInTheDocument();
    });

    jest.advanceTimersByTime(2500);
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/auth/signin?registered=true");
    });

    jest.useRealTimers();
  });
});
