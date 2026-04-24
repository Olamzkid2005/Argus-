"use client";

import { useState, FormEvent, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, Eye, EyeOff, Loader2, ArrowLeft, CheckCircle } from "lucide-react";
import { motion } from "framer-motion";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [focusedField, setFocusedField] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      if (token) {
        // Reset password with token
        if (password !== confirmPassword) {
          setError("Passwords do not match");
          setIsLoading(false);
          return;
        }
        if (password.length < 8) {
          setError("Password must be at least 8 characters");
          setIsLoading(false);
          return;
        }

        const response = await fetch("/api/auth/reset-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, password }),
        });

        const data = await response.json();

        if (!response.ok) {
          setError(data.message || "Failed to reset password");
        } else {
          setSuccess(true);
          setTimeout(() => {
            router.push("/auth/signin");
          }, 3000);
        }
      } else {
        // Request password reset email
        const response = await fetch("/api/auth/forgot-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });

        const data = await response.json();

        if (!response.ok) {
          setError(data.message || "Failed to send reset email");
        } else {
          setSuccess(true);
        }
      }
    } catch {
      setError("System error");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left Side — Brand Visual (50%) */}
      <motion.div
        initial={{ opacity: 0, x: -30 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.7, ease: "easeOut" }}
        className="hidden lg:flex lg:w-1/2 relative flex-col justify-between p-12 xl:p-16 overflow-hidden"
        style={{
          background: "linear-gradient(135deg, #F3E8FF 0%, #E9D5FF 40%, #DDD6FE 70%, #C4B5FD 100%)",
        }}
      >
        {/* Subtle grid pattern overlay */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23000000' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
          }}
        />

        <div className="relative z-10">
          {/* Small logo icon */}
          <div className="w-10 h-10 rounded-lg bg-white/80 backdrop-blur-sm flex items-center justify-center shadow-sm">
            <ShieldCheck size={20} className="text-[#6720FF]" />
          </div>
        </div>

        <div className="relative z-10 space-y-6 max-w-md">
          <h2 className="text-5xl xl:text-6xl font-bold text-gray-900 tracking-tight leading-[1.05]">
            Secure.<br />
            Reset.<br />
            Access.
          </h2>

          <p className="text-[11px] font-semibold text-[#6720FF] uppercase tracking-[0.2em]">
            ACCOUNT RECOVERY
          </p>

          {/* Decorative purple squares */}
          <div className="flex items-end gap-4 pt-8">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.5 }}
              className="w-16 h-16 rounded-2xl bg-[#A78BFA]/60"
            />
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.7 }}
              className="w-20 h-20 rounded-2xl bg-[#8B5CF6]/50"
            />
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.9 }}
              className="w-14 h-14 rounded-2xl bg-[#7C3AED]/40"
            />
          </div>
        </div>

        <div className="relative z-10">
          <p className="text-xs text-gray-500">
            © 2026 Argus Systems
          </p>
        </div>
      </motion.div>

      {/* Right Side — Reset Password Form (50%) */}
      <div className="flex-1 lg:w-1/2 flex items-center justify-center p-6 md:p-12 bg-white relative">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="w-full max-w-[400px]"
        >
          {/* Back to Sign In */}
          <Link
            href="/auth/signin"
            className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-[#6720FF] transition-colors mb-8"
          >
            <ArrowLeft size={16} />
            Back to Sign In
          </Link>

          {/* Mobile Brand */}
          <div className="lg:hidden flex items-center gap-2.5 mb-10">
            <div className="w-8 h-8 rounded-lg bg-[#6720FF] flex items-center justify-center">
              <ShieldCheck size={18} className="text-white" />
            </div>
            <span className="text-xl font-bold text-gray-900">
              Argus
            </span>
          </div>

          <div className="mb-8">
            <h1 className="text-2xl font-bold text-gray-900 tracking-tight mb-1">
              {token ? "Set new password" : "Reset your password"}
            </h1>
            <p className="text-sm text-gray-500">
              {token 
                ? "Enter your new password below." 
                : "Enter your email address and we'll send you a link to reset your password."}
            </p>
          </div>

          {/* Success State */}
          {success ? (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="text-center py-8"
            >
              <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
                <CheckCircle size={32} className="text-green-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                {token ? "Password reset successful!" : "Reset email sent!"}
              </h3>
              <p className="text-sm text-gray-500 mb-6">
                {token 
                  ? "Your password has been updated. Redirecting to sign in..." 
                  : "Check your email for a link to reset your password. If it doesn't appear within a few minutes, check your spam folder."}
              </p>
              {!token && (
                <Link
                  href="/auth/signin"
                  className="inline-flex items-center justify-center px-6 py-2.5 rounded-lg bg-[#6720FF] text-white text-sm font-semibold hover:bg-[#5a1be6] transition-all duration-200"
                >
                  Return to Sign In
                </Link>
              )}
            </motion.div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              {!token ? (
                /* Email Field */
                <div>
                  <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    Email Address
                  </label>
                  <input
                    type="email"
                    name="email"
                    id="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onFocus={() => setFocusedField("email")}
                    onBlur={() => setFocusedField(null)}
                    placeholder="architect@argus.ai"
                    autoComplete="email"
                    required
                    className={`w-full px-4 py-2.5 bg-gray-100 rounded-lg text-sm text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 border ${
                      focusedField === "email"
                        ? "border-[#6720FF] ring-2 ring-[#6720FF]/10 bg-white"
                        : "border-transparent hover:bg-gray-200"
                    }`}
                  />
                </div>
              ) : (
                <>
                  {/* New Password */}
                  <div>
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      New Password
                    </label>
                    <div className="relative">
                      <input
                        type={showPassword ? "text" : "password"}
                        name="password"
                        id="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onFocus={() => setFocusedField("password")}
                        onBlur={() => setFocusedField(null)}
                        placeholder="••••••••"
                        autoComplete="new-password"
                        required
                        minLength={8}
                        className={`w-full px-4 py-2.5 pr-12 bg-gray-100 rounded-lg text-sm text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 border ${
                          focusedField === "password"
                            ? "border-[#6720FF] ring-2 ring-[#6720FF]/10 bg-white"
                            : "border-transparent hover:bg-gray-200"
                        }`}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                      >
                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                    <p className="text-[10px] text-gray-400 mt-1">
                      Must be at least 8 characters
                    </p>
                  </div>

                  {/* Confirm Password */}
                  <div>
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      Confirm Password
                    </label>
                    <div className="relative">
                      <input
                        type={showConfirmPassword ? "text" : "password"}
                        name="confirmPassword"
                        id="confirmPassword"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        onFocus={() => setFocusedField("confirmPassword")}
                        onBlur={() => setFocusedField(null)}
                        placeholder="••••••••"
                        autoComplete="new-password"
                        required
                        className={`w-full px-4 py-2.5 pr-12 bg-gray-100 rounded-lg text-sm text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 border ${
                          focusedField === "confirmPassword"
                            ? "border-[#6720FF] ring-2 ring-[#6720FF]/10 bg-white"
                            : "border-transparent hover:bg-gray-200"
                        }`}
                      />
                      <button
                        type="button"
                        onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                      >
                        {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </div>
                </>
              )}

              {/* Error */}
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="text-xs text-red-600 bg-red-50 border border-red-100 px-4 py-3 rounded-lg"
                >
                  {error}
                </motion.div>
              )}

              {/* Submit Button */}
              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 rounded-lg bg-[#6720FF] text-white text-sm font-semibold hover:bg-[#5a1be6] transition-all duration-200 disabled:opacity-50 shadow-sm"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {token ? "Updating..." : "Sending..."}
                  </span>
                ) : (
                  token ? "Reset Password" : "Send Reset Link"
                )}
              </button>
            </form>
          )}
        </motion.div>
      </div>
    </div>
  );
}

export default function ResetPassword() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-white">
          <Loader2 className="animate-spin h-8 w-8 text-[#6720FF]" />
        </div>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}
