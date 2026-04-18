"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { signIn } from "next-auth/react";

interface FormErrors {
  email?: string;
  password?: string;
  passwordConfirm?: string;
  orgName?: string;
  general?: string;
}

export default function SignUp() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [orgName, setOrgName] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isOAuthLoading, setIsOAuthLoading] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleOAuthSignUp = async (provider: "google" | "github") => {
    setIsOAuthLoading(provider);
    try {
      await signIn(provider, { callbackUrl: "/" });
    } catch {
      setErrors({ general: "Failed to sign up with " + provider });
      setIsOAuthLoading(null);
    }
  };

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};

    // Email validation
    if (!email) {
      newErrors.email = "Email is required";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = "Invalid email format";
    }

    // Password validation
    if (!password) {
      newErrors.password = "Password is required";
    } else if (password.length < 8) {
      newErrors.password = "Must be at least 8 characters";
    } else if (!/[A-Z]/.test(password)) {
      newErrors.password = "Must contain an uppercase letter";
    } else if (!/[a-z]/.test(password)) {
      newErrors.password = "Must contain a lowercase letter";
    } else if (!/[0-9]/.test(password)) {
      newErrors.password = "Must contain a number";
    }

    // Password confirmation
    if (!passwordConfirm) {
      newErrors.passwordConfirm = "Please confirm your password";
    } else if (password !== passwordConfirm) {
      newErrors.passwordConfirm = "Passwords do not match";
    }

    // Organization name validation
    if (!orgName) {
      newErrors.orgName = "Organization name is required";
    } else if (orgName.trim().length < 2) {
      newErrors.orgName = "Must be at least 2 characters";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrors({});

    if (!validateForm()) return;

    setIsLoading(true);

    try {
      const response = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.toLowerCase().trim(),
          password,
          passwordConfirm,
          orgName: orgName.trim(),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        if (response.status === 409) {
          setErrors({ email: data.error });
        } else {
          setErrors({ general: data.error });
        }
        return;
      }

      setSuccess(true);
      // Redirect to sign-in after short delay
      setTimeout(() => {
        router.push("/auth/signin?registered=true");
      }, 2000);
    } catch {
      setErrors({ general: "Network error. Please try again." });
    } finally {
      setIsLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0f172a] relative overflow-hidden">
        {/* Geometric background accent */}
        <div className="absolute top-0 right-0 w-96 h-96 bg-cyan-500/10 clip-path-polygon-0" />
        <div className="absolute bottom-0 left-0 w-64 h-64 bg-emerald-500/10 clip-path-polygon-50-0-100-100" />

        <div className="relative z-10 max-w-md w-full mx-4 p-8 bg-[#1e293b] border border-cyan-500/30">
          <div className="text-center space-y-4">
            <div className="w-16 h-16 mx-auto bg-cyan-500/20 rounded-full flex items-center justify-center">
              <svg className="w-8 h-8 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-slate-100">Account Created</h2>
            <p className="text-slate-400">Redirecting you to sign in...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0f172a] relative overflow-hidden">
      {/* Geometric background accents */}
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-gradient-to-br from-cyan-500/5 to-transparent rounded-full blur-3xl" />
      <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-gradient-to-tr from-emerald-500/5 to-transparent rounded-full blur-3xl" />

      {/* Grid pattern overlay */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.03)_1px,transparent_1px)] bg-[size:64px_64px]" />

      <div className="relative z-10 max-w-md w-full mx-4">
        {/* Logo / Brand mark */}
        <div className="text-center mb-8 animate-fade-in">
          <div className="inline-flex items-center justify-center w-12 h-12 mb-4">
            <svg viewBox="0 0 32 32" className="w-10 h-10 text-cyan-400">
              <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="2" />
              <circle cx="16" cy="16" r="6" fill="currentColor" />
              <circle cx="16" cy="16" r="10" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-slate-100 tracking-tight">Argus</h1>
          <p className="text-slate-500 mt-1">Security Intelligence Platform</p>
        </div>

        {/* Main form card */}
        <div className="bg-[#1e293b]/80 backdrop-blur-sm border border-slate-700/50 p-8 animate-slide-up">
          <div className="mb-6">
            <h2 className="text-xl font-semibold text-slate-100">Create your account</h2>
            <p className="text-sm text-slate-500 mt-1">Start your 14-day free trial</p>
          </div>

          {/* OAuth sign up buttons */}
          <div className="space-y-3 mb-6">
            <button
              type="button"
              onClick={() => handleOAuthSignUp("google")}
              disabled={!!isOAuthLoading}
              className="w-full flex items-center justify-center gap-3 px-4 py-2.5 bg-white text-gray-700 font-medium rounded-md hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-500/50 disabled:opacity-50 transition-colors"
            >
              {isOAuthLoading === "google" ? (
                <div className="w-5 h-5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
              ) : (
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                </svg>
              )}
              Sign up with Google
            </button>

            <button
              type="button"
              onClick={() => handleOAuthSignUp("github")}
              disabled={!!isOAuthLoading}
              className="w-full flex items-center justify-center gap-3 px-4 py-2.5 bg-[#24292e] text-white font-medium rounded-md hover:bg-[#2f363d] focus:outline-none focus:ring-2 focus:ring-gray-500/50 disabled:opacity-50 transition-colors"
            >
              {isOAuthLoading === "github" ? (
                <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
                </svg>
              )}
              Sign up with GitHub
            </button>
          </div>

          {/* Divider */}
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-slate-700" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-[#1e293b] text-slate-500">Or continue with email</span>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* General error */}
            {errors.general && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 text-sm animate-shake">
                {errors.general}
              </div>
            )}

            {/* Organization name */}
            <div className="space-y-1.5">
              <label htmlFor="orgName" className="block text-sm font-medium text-slate-300">
                Organization Name
              </label>
              <div className="relative">
                <input
                  id="orgName"
                  type="text"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="Acme Corp"
                  className={`w-full px-4 py-2.5 bg-[#0f172a] border ${
                    errors.orgName ? "border-red-500" : "border-slate-600 focus:border-cyan-500"
                  } text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50 transition-colors`}
                />
                <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                  <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                  </svg>
                </div>
              </div>
              {errors.orgName && (
                <p className="text-xs text-red-400 mt-1">{errors.orgName}</p>
              )}
            </div>

            {/* Email */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="block text-sm font-medium text-slate-300">
                Email Address
              </label>
              <div className="relative">
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className={`w-full px-4 py-2.5 bg-[#0f172a] border ${
                    errors.email ? "border-red-500" : "border-slate-600 focus:border-cyan-500"
                  } text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50 transition-colors`}
                />
                <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                  <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </div>
              </div>
              {errors.email && (
                <p className="text-xs text-red-400 mt-1">{errors.email}</p>
              )}
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label htmlFor="password" className="block text-sm font-medium text-slate-300">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min. 8 characters"
                  className={`w-full px-4 py-2.5 bg-[#0f172a] border ${
                    errors.password ? "border-red-500" : "border-slate-600 focus:border-cyan-500"
                  } text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50 transition-colors`}
                />
                <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                  <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                </div>
              </div>
              {errors.password && (
                <p className="text-xs text-red-400 mt-1">{errors.password}</p>
              )}
            </div>

            {/* Password strength indicator */}
            {password && (
              <div className="space-y-1.5">
                <div className="flex gap-1">
                  <div className={`h-1 flex-1 rounded-full transition-colors ${password.length >= 8 ? "bg-cyan-500" : "bg-slate-700"}`} />
                  <div className={`h-1 flex-1 rounded-full transition-colors ${/[A-Z]/.test(password) ? "bg-cyan-500" : "bg-slate-700"}`} />
                  <div className={`h-1 flex-1 rounded-full transition-colors ${/[a-z]/.test(password) ? "bg-cyan-500" : "bg-slate-700"}`} />
                  <div className={`h-1 flex-1 rounded-full transition-colors ${/[0-9]/.test(password) ? "bg-cyan-500" : "bg-slate-700"}`} />
                </div>
                <p className="text-xs text-slate-500">Must include: uppercase, lowercase, number</p>
              </div>
            )}

            {/* Confirm Password */}
            <div className="space-y-1.5">
              <label htmlFor="passwordConfirm" className="block text-sm font-medium text-slate-300">
                Confirm Password
              </label>
              <div className="relative">
                <input
                  id="passwordConfirm"
                  type="password"
                  value={passwordConfirm}
                  onChange={(e) => setPasswordConfirm(e.target.value)}
                  placeholder="Re-enter your password"
                  className={`w-full px-4 py-2.5 bg-[#0f172a] border ${
                    errors.passwordConfirm ? "border-red-500" : "border-slate-600 focus:border-cyan-500"
                  } text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50 transition-colors`}
                />
                {passwordConfirm && (
                  <div className="absolute inset-y-0 right-0 flex items-center pr-3">
                    {password === passwordConfirm ? (
                      <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      <svg className="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    )}
                  </div>
                )}
              </div>
              {errors.passwordConfirm && (
                <p className="text-xs text-red-400 mt-1">{errors.passwordConfirm}</p>
              )}
            </div>

            {/* Submit button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3 px-4 bg-gradient-to-r from-cyan-500 to-emerald-500 text-[#0f172a] font-semibold rounded-md hover:from-cyan-400 hover:to-emerald-400 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 relative overflow-hidden group"
            >
              <span className="relative z-10">{isLoading ? "Creating account..." : "Create Account"}</span>
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/25 to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-500" />
            </button>
          </form>

          {/* Divider */}
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-slate-700" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-[#1e293b] text-slate-500">Already have an account?</span>
            </div>
          </div>

          {/* Sign in link */}
          <Link
            href="/auth/signin"
            className="block w-full py-2.5 px-4 border border-slate-600 text-slate-300 font-medium rounded-md hover:bg-slate-800 hover:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500/50 text-center transition-all duration-200"
          >
            Sign in to your account
          </Link>
        </div>

        {/* Terms */}
        <p className="text-center text-xs text-slate-600 mt-6">
          By creating an account, you agree to our{" "}
          <a href="#" className="text-slate-500 hover:text-cyan-400 transition-colors">Terms of Service</a>
          {" "}and{" "}
          <a href="#" className="text-slate-500 hover:text-cyan-400 transition-colors">Privacy Policy</a>
        </p>
      </div>

      <style jsx>{`
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(-10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes slide-up {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          25% { transform: translateX(-5px); }
          75% { transform: translateX(5px); }
        }
        .animate-fade-in { animation: fade-in 0.5s ease-out; }
        .animate-slide-up { animation: slide-up 0.6s ease-out 0.1s both; }
        .animate-shake { animation: shake 0.4s ease-out; }
        .clip-path-polygon-0 { clip-path: polygon(0 0, 100% 0, 100% 100%); }
        .clip-path-polygon-50-0-100-100 { clip-path: polygon(50% 0, 100% 0, 100% 100%); }
      `}</style>
    </div>
  );
}