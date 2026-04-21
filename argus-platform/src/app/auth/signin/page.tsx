"use client";

import { signIn } from "next-auth/react";
import { useState, FormEvent, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ShieldCheck, Eye, EyeOff, ArrowRight, Loader2 } from "lucide-react";
import MatrixDataRain from "@/components/effects/MatrixDataRain";
import ScannerReveal from "@/components/effects/ScannerReveal";

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
        setError("INVALID CREDENTIALS");
      } else {
        const callbackUrl = searchParams.get("callbackUrl") || "/dashboard";
        router.push(callbackUrl);
      }
    } catch {
      setError("SYSTEM ERROR");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center overflow-hidden bg-void">
      {/* Background: Matrix Data Rain */}
      <div className="absolute inset-0 z-0 opacity-20">
        <MatrixDataRain />
      </div>

      {/* Auth Card */}
      <div
        className="relative z-10 w-full max-w-[400px] mx-4 p-8 border border-structural bg-surface/80 backdrop-blur-2xl shadow-2xl"
        style={{
          borderRadius: "4px",
        }}
      >
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-12 h-12 mx-auto mb-4 flex items-center justify-center border border-prism-cream/20 bg-surface/10">
            <ShieldCheck size={24} className="text-prism-cream" />
          </div>
          <h1 className="text-2xl font-semibold text-text-primary tracking-tight font-mono uppercase italic">
            Terminal Access
          </h1>
          <p className="text-[10px] text-text-secondary mt-2 font-mono uppercase tracking-[0.2em] font-bold">
            Authentication Required
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Email */}
          <div>
            <label className="block text-[11px] font-mono text-text-secondary uppercase tracking-wider mb-2 font-bold">
              Identifier (Email)
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onFocus={() => setFocusedField("email")}
              onBlur={() => setFocusedField(null)}
              placeholder="operator@argus.io"
              className="w-full px-4 py-3 bg-surface/40 border border-structural text-sm text-text-primary outline-none transition-all duration-200 placeholder:text-text-secondary/40 font-mono focus:border-prism-cream/50"
            />
          </div>

          {/* Password */}
          <div>
            <label className="block text-[11px] font-mono text-text-secondary uppercase tracking-wider mb-2 font-bold">
              Passcode
            </label>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setFocusedField("password")}
                onBlur={() => setFocusedField(null)}
                placeholder="••••••••"
                className="w-full px-4 py-3 pr-12 bg-surface/40 border border-structural text-sm text-text-primary outline-none transition-all duration-200 placeholder:text-text-secondary/40 font-mono focus:border-prism-cream/50"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary transition-colors"
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="text-[10px] font-mono text-red-500 bg-red-500/10 border border-red-500/20 px-3 py-2 uppercase tracking-widest font-bold">
              !!! {error} !!!
            </div>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isLoading}
            className="w-full flex items-center justify-center gap-2 py-4 text-xs font-bold transition-all duration-200 disabled:opacity-50 group relative uppercase tracking-[0.3em] bg-prism-cream text-void hover:bg-white shadow-glow-cream"
          >
            {isLoading ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                VERIFYING...
              </span>
            ) : (
              <>
                AUTHENTICATE
                <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </button>
        </form>

        {/* Footer */}
        <div className="mt-8 pt-5 border-t border-structural text-center">
          <p className="text-[9px] font-mono text-text-secondary uppercase tracking-[0.3em] font-bold">
            Argus Intelligence :: Platform Support
          </p>
        </div>
      </div>
    </div>
  );
}

export default function SignIn() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-void text-prism-cream">
          <Loader2 className="animate-spin h-8 w-8" />
        </div>
      }
    >
      <SignInForm />
    </Suspense>
  );
}
