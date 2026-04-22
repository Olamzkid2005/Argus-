import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockSignIn = jest.fn();
const mockPush = jest.fn();

jest.mock("next-auth/react", () => ({
  signIn: (...args: any[]) => mockSignIn(...args),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/auth/signin",
}));

jest.mock("@/components/effects/MatrixDataRain", () => () => <div data-testid="matrix-rain" />);

import SignInPage from "@/app/auth/signin/page";

describe("SignIn Page", () => {
  beforeEach(() => {
    mockSignIn.mockClear();
    mockPush.mockClear();
  });

  it("renders signin form with email and password inputs", () => {
    render(<SignInPage />);
    expect(screen.getByPlaceholderText(/you@company.com/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/••••••••/i)).toBeInTheDocument();
  });

  it("renders social login buttons", () => {
    render(<SignInPage />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(4); // Google, GitHub, LinkedIn, Sign In
  });

  it("submits form with email and password", async () => {
    mockSignIn.mockResolvedValue({ error: null });
    render(<SignInPage />);

    const emailInput = screen.getByPlaceholderText(/you@company.com/i);
    const passwordInput = screen.getByPlaceholderText(/••••••••/i);
    const submitButton = screen.getByRole("button", { name: /sign in/i });

    await userEvent.type(emailInput, "test@argus.io");
    await userEvent.type(passwordInput, "password123");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalledWith("credentials", expect.objectContaining({
        email: "test@argus.io",
        password: "password123",
        redirect: false,
      }));
    });
  });

  it("displays error on invalid credentials", async () => {
    mockSignIn.mockResolvedValue({ error: "Invalid credentials" });
    render(<SignInPage />);

    const emailInput = screen.getByPlaceholderText(/you@company.com/i);
    const passwordInput = screen.getByPlaceholderText(/••••••••/i);
    const submitButton = screen.getByRole("button", { name: /sign in/i });

    await userEvent.type(emailInput, "test@argus.io");
    await userEvent.type(passwordInput, "wrong");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });
});
