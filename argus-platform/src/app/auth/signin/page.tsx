"use client";

import { signIn } from "next-auth/react";
import { useState, FormEvent, Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, Eye, EyeOff, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import { log } from "@/lib/logger";

function GoogleIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none">
      <path
        d="M23.766 12.2764c0-.8151-.0732-1.5986-.2109-2.3527H12.252v4.4511h6.4727c-.2793 1.4883-1.123 2.748-2.3926 3.5933v2.9883h3.873c2.2695-2.0887 3.5602-5.1655 3.5602-8.68z"
        fill="#4285F4"
      />
      <path
        d="M12.252 24c3.2377 0 5.9564-1.0738 7.9434-2.9033l-3.873-2.9883c-1.0738.7195-2.4463 1.1436-4.0704 1.1436-3.1312 0-5.7803-2.1129-6.7266-4.9512H1.4863v3.0879C3.4619 21.3047 7.6123 24 12.252 24z"
        fill="#34A853"
      />
      <path
        d="M5.5254 14.3009c-.2451-.7195-.3857-1.4854-.3857-2.2764s.1406-1.5569.3857-2.2764V6.6602H1.4863C.5381 8.5449 0 10.6973 0 13.0245s.5381 4.4795 1.4863 6.3642l4.0391-3.0878z"
        fill="#FBBC05"
      />
      <path
        d="M12.252 4.7495c1.7666 0 3.3516.6063 4.5986 1.7969l3.4492-3.4492C18.2047 1.082 15.486 0 12.252 0 7.6123 0 3.4619 2.6953 1.4863 6.6602l4.0391 3.0879c.9463-2.8383 3.5954-4.9986 6.7266-4.9986z"
        fill="#EA4335"
      />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.6.11.82-.26.82-.577 0-.286-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.756-1.333-1.756-1.09-.745.083-.73.083-.73 1.205.085 1.84 1.237 1.84 1.237 1.07 1.835 2.807 1.305 3.492.998.108-.776.42-1.305.763-1.605-2.665-.305-5.467-1.334-5.467-5.93 0-1.31.468-2.382 1.235-3.22-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.3 1.23A11.51 11.51 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.29-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.838 1.233 1.91 1.233 3.22 0 4.61-2.807 5.625-5.48 5.92.43.372.823 1.103.823 2.222 0 1.606-.015 2.898-.015 3.293 0 .32.218.694.825.577C20.565 21.795 24 17.298 24 12c0-6.627-5.373-12-12-12z" />
    </svg>
  );
}

function LinkedInIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="#0A66C2">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}

function SignInForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [focusedField, setFocusedField] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (result?.error) {
        setError("Invalid credentials");
      } else {
        const callbackUrl = searchParams.get("callbackUrl") || "/dashboard";
        router.push(callbackUrl);
      }
    } catch {
      setError("System error");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div suppressHydrationWarning className="min-h-screen flex">
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
            Build.<br />
            Tune.<br />
            Scale.
          </h2>

          <p className="text-[11px] font-semibold text-[#6720FF] uppercase tracking-[0.2em]">
            NEXT-GEN AI INFRASTRUCTURE
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

      {/* Right Side — Login Form (50%) */}
      <div className="flex-1 lg:w-1/2 flex items-center justify-center p-6 md:p-12 bg-white relative">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="w-full max-w-[400px]"
        >
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
              Welcome back
            </h1>
            <p className="text-sm text-gray-500">
              Log in to manage your neural clusters.
            </p>
          </div>

          {/* Social Login */}
          <div className="grid grid-cols-3 gap-3 mb-6">
            <button
              type="button"
              onClick={() => signIn("google", { callbackUrl: "/dashboard" })}
              className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 transition-all duration-200 text-xs font-medium text-gray-700"
            >
              <GoogleIcon />
              <span className="hidden sm:inline">Google</span>
            </button>
            <button
              type="button"
              onClick={() => signIn("github", { callbackUrl: "/dashboard" })}
              className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 transition-all duration-200 text-xs font-medium text-gray-700"
            >
              <GitHubIcon />
              <span className="hidden sm:inline">GitHub</span>
            </button>
            <button
              type="button"
              onClick={() => signIn("linkedin", { callbackUrl: "/dashboard" })}
              className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 transition-all duration-200 text-xs font-medium text-gray-700"
            >
              <LinkedInIcon />
              <span className="hidden sm:inline">LinkedIn</span>
            </button>
          </div>

          <div className="relative mb-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200" />
            </div>
            <div className="relative flex justify-center">
              <span className="px-3 text-[10px] font-medium text-gray-400 uppercase tracking-wider bg-white">
                Or use email
              </span>
            </div>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email */}
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
                onInput={(e) => setEmail((e.target as HTMLInputElement).value)}
                onKeyDown={(e) => e.stopPropagation()}
                onFocus={() => setFocusedField("email")}
                onBlur={() => setFocusedField(null)}
                placeholder="architect@argus.ai"
                autoComplete="email"
                className={`w-full px-4 py-2.5 bg-gray-100 rounded-lg text-sm text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 border ${
                  focusedField === "email"
                    ? "border-[#6720FF] ring-2 ring-[#6720FF]/10 bg-white"
                    : "border-transparent hover:bg-gray-200"
                }`}
              />
            </div>

            {/* Password */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                  Password
                </label>
                <Link
                  href="/auth/reset-password"
                  className="text-[11px] text-[#6720FF] hover:underline font-medium"
                >
                  Forgot?
                </Link>
              </div>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  name="password"
                  id="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onInput={(e) => setPassword((e.target as HTMLInputElement).value)}
                  onKeyDown={(e) => e.stopPropagation()}
                  onFocus={() => setFocusedField("password")}
                  onBlur={() => setFocusedField(null)}
                  placeholder="••••••••"
                  autoComplete="current-password"
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
            </div>

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
                  Signing in...
                </span>
              ) : (
                "Sign In to Dashboard"
              )}
            </button>
          </form>

          <div className="text-center text-sm text-gray-600 mt-6">
            Don&apos;t have an account?{" "}
            <Link
              href="/auth/signup"
              className="text-[#6720FF] font-semibold hover:underline"
            >
              Sign up
            </Link>
          </div>

        </motion.div>

      </div>
    </div>
  );
}

export default function SignIn() {
  useEffect(() => {
    log.pageMount("SignIn");
    return () => log.pageUnmount("SignIn");
  }, []);

  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-white">
          <Loader2 className="animate-spin h-8 w-8 text-[#6720FF]" />
        </div>
      }
    >
      <SignInForm />
    </Suspense>
  );
}
