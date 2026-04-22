"use client";

import { signIn } from "next-auth/react";
import { useState, FormEvent, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, Eye, EyeOff, ArrowRight, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import MatrixDataRain from "@/components/effects/MatrixDataRain";

function GoogleIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none">
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
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.6.11.82-.26.82-.577 0-.286-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.756-1.333-1.756-1.09-.745.083-.73.083-.73 1.205.085 1.84 1.237 1.84 1.237 1.07 1.835 2.807 1.305 3.492.998.108-.776.42-1.305.763-1.605-2.665-.305-5.467-1.334-5.467-5.93 0-1.31.468-2.382 1.235-3.22-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.3 1.23A11.51 11.51 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.29-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.838 1.233 1.91 1.233 3.22 0 4.61-2.807 5.625-5.48 5.92.43.372.823 1.103.823 2.222 0 1.606-.015 2.898-.015 3.293 0 .32.218.694.825.577C20.565 21.795 24 17.298 24 12c0-6.627-5.373-12-12-12z" />
    </svg>
  );
}

function LinkedInIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
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
    <div className="min-h-screen flex bg-surface">
      {/* Background Matrix (subtle, full page) */}
      <div className="fixed inset-0 z-0 opacity-[0.04] pointer-events-none">
        <MatrixDataRain />
      </div>

      {/* Left Side — Brand Visual (55%) */}
      <motion.div
        initial={{ opacity: 0, x: -30 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.7, ease: "easeOut" }}
        className="hidden lg:flex lg:w-[55%] relative flex-col justify-between p-12 xl:p-16 hero-mesh overflow-hidden"
      >
        <div className="relative z-10">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <ShieldCheck size={18} className="text-white" />
            </div>
            <span className="font-headline text-xl font-bold text-on-surface tracking-tight">
              Argus
            </span>
          </Link>
        </div>

        <div className="relative z-10 space-y-8 max-w-md">
          <div>
            <h2 className="text-4xl xl:text-5xl font-headline font-bold text-on-surface tracking-tight leading-[1.1]">
              Build. Tune.{" "}
              <span className="bg-gradient-to-r from-primary to-violet-400 bg-clip-text text-transparent">
                Scale.
              </span>
            </h2>
          </div>
          <p className="text-base font-body text-on-surface-variant leading-relaxed">
            The infrastructure for intelligence. Deploy, monitor, and scale
            AI security operations with unified observability.
          </p>

          {/* Abstract Infrastructure Blocks */}
          <div className="flex items-end gap-3 pt-4">
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: 80 }}
              transition={{ duration: 0.8, delay: 0.4 }}
              className="w-12 rounded-xl bg-primary/10 border border-primary/20"
            />
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: 120 }}
              transition={{ duration: 0.8, delay: 0.5 }}
              className="w-12 rounded-xl bg-primary/15 border border-primary/25"
            />
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: 60 }}
              transition={{ duration: 0.8, delay: 0.6 }}
              className="w-12 rounded-xl bg-primary/10 border border-primary/20"
            />
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: 100 }}
              transition={{ duration: 0.8, delay: 0.7 }}
              className="w-12 rounded-xl bg-primary/20 border border-primary/30"
            />
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: 140 }}
              transition={{ duration: 0.8, delay: 0.8 }}
              className="w-12 rounded-xl primary-gradient border border-primary/30"
            />
          </div>
        </div>

        <div className="relative z-10">
          <p className="text-xs font-body text-on-surface-variant/60">
            © 2026 Argus Systems
          </p>
        </div>

        {/* Decorative gradient orb */}
        <div className="absolute -bottom-32 -right-32 w-96 h-96 rounded-full bg-primary/10 blur-3xl pointer-events-none" />
      </motion.div>

      {/* Right Side — Login Form (45%) */}
      <div className="flex-1 lg:w-[45%] flex items-center justify-center p-6 md:p-12 relative z-10">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="w-full max-w-[420px]"
        >
          {/* Mobile Brand */}
          <div className="lg:hidden flex items-center gap-2.5 mb-10">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <ShieldCheck size={18} className="text-white" />
            </div>
            <span className="font-headline text-xl font-bold text-on-surface">
              Argus
            </span>
          </div>

          <div className="mb-8">
            <h1 className="text-2xl font-headline font-bold text-on-surface tracking-tight mb-2">
              Welcome back
            </h1>
            <p className="text-sm font-body text-on-surface-variant">
              Sign in to your dashboard to continue
            </p>
          </div>

          {/* Social Login */}
          <div className="grid grid-cols-3 gap-3 mb-8">
            <button
              type="button"
              onClick={() => signIn("google", { callbackUrl: "/dashboard" })}
              className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-outline/30 bg-surface hover:bg-surface-container transition-all duration-300"
            >
              <GoogleIcon />
            </button>
            <button
              type="button"
              onClick={() => signIn("github", { callbackUrl: "/dashboard" })}
              className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-outline/30 bg-surface hover:bg-surface-container transition-all duration-300"
            >
              <GitHubIcon />
            </button>
            <button
              type="button"
              onClick={() => signIn("linkedin", { callbackUrl: "/dashboard" })}
              className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-outline/30 bg-surface hover:bg-surface-container transition-all duration-300"
            >
              <LinkedInIcon />
            </button>
          </div>

          <div className="relative mb-8">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-outline/20" />
            </div>
            <div className="relative flex justify-center">
              <span className="px-3 text-xs font-body text-on-surface-variant bg-surface">
                or continue with email
              </span>
            </div>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email */}
            <div>
              <label className="block text-xs font-label font-semibold text-on-surface uppercase tracking-wider mb-2">
                Email
              </label>
              <input
                type="email"
                name="email"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={() => setFocusedField("email")}
                onBlur={() => setFocusedField(null)}
                placeholder="you@company.com"
                className={`w-full px-4 py-3 bg-surface-container-high rounded-xl text-sm font-body text-on-surface outline-none transition-all duration-300 placeholder:text-on-surface-variant/40 border ${
                  focusedField === "email"
                    ? "border-primary ring-2 ring-primary/20"
                    : "border-outline/30 hover:border-outline/60"
                }`}
              />
            </div>

            {/* Password */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-xs font-label font-semibold text-on-surface uppercase tracking-wider">
                  Password
                </label>
                <Link
                  href="/auth/reset-password"
                  className="text-xs font-body text-primary hover:underline"
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
                  onFocus={() => setFocusedField("password")}
                  onBlur={() => setFocusedField(null)}
                  placeholder="••••••••"
                  className={`w-full px-4 py-3 pr-12 bg-surface-container-high rounded-xl text-sm font-body text-on-surface outline-none transition-all duration-300 placeholder:text-on-surface-variant/40 border ${
                    focusedField === "password"
                      ? "border-primary ring-2 ring-primary/20"
                      : "border-outline/30 hover:border-outline/60"
                  }`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors"
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
                className="text-xs font-body text-error bg-error-container/30 border border-error/20 px-4 py-3 rounded-xl"
              >
                {error}
              </motion.div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl primary-gradient text-white text-sm font-semibold shadow-glow hover:shadow-glow-strong transition-all duration-300 disabled:opacity-50 disabled:shadow-none"
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in...
                </span>
              ) : (
                <>
                  Sign In to Dashboard
                  <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
                </>
              )}
            </button>
          </form>

          {/* Footer */}
          <div className="mt-8 pt-6 border-t border-outline/10 text-center">
            <p className="text-sm font-body text-on-surface-variant">
              Don&apos;t have an account?{" "}
              <Link
                href="/auth/signup"
                className="font-semibold text-primary hover:underline transition-colors"
              >
                Create an account
              </Link>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

export default function SignIn() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-surface text-primary">
          <Loader2 className="animate-spin h-8 w-8" />
        </div>
      }
    >
      <SignInForm />
    </Suspense>
  );
}
