import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SignInPage from "@/app/auth/signin/page";

const mockSignIn = jest.fn();
const mockPush = jest.fn();

jest.mock("next-auth/react", () => ({
  signIn: (...args: any[]) => mockSignIn(...args),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
}));

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

  it("renders social login options", () => {
    render(<SignInPage />);
    expect(screen.getByText(/continue with google/i)).toBeInTheDocument();
    expect(screen.getByText(/github/i)).toBeInTheDocument();
    expect(screen.getByText(/linkedin/i)).toBeInTheDocument();
  });

  it("submits credentials and calls signIn", async () => {
    mockSignIn.mockResolvedValue({ error: null });
    render(<SignInPage />);

    const email = screen.getByPlaceholderText(/you@company.com/i);
    const password = screen.getByPlaceholderText(/••••••••/i);
    const submit = screen.getByRole("button", { name: /sign in/i });

    await userEvent.type(email, "test@argus.io");
    await userEvent.type(password, "password123");
    fireEvent.click(submit);

    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalledWith("credentials", expect.objectContaining({
        email: "test@argus.io",
        password: "password123",
        redirect: false,
      }));
    });
  });

  it("displays error on failed signin", async () => {
    mockSignIn.mockResolvedValue({ error: "Invalid credentials" });
    render(<SignInPage />);

    const email = screen.getByPlaceholderText(/you@company.com/i);
    const password = screen.getByPlaceholderText(/••••••••/i);
    const submit = screen.getByRole("button", { name: /sign in/i });

    await userEvent.type(email, "test@argus.io");
    await userEvent.type(password, "wrong");
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });
});
