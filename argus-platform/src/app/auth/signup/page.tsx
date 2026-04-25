"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, Loader2, ArrowRight, UserCheck, Eye, EyeOff, Check, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { signIn } from "next-auth/react";

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

// Password strength calculation
function calculatePasswordStrength(password: string): { score: number; label: string; color: string } {
  let score = 0;
  if (password.length >= 8) score++;
  if (password.length >= 12) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;

  const levels = [
    { score: 0, label: "Very Weak", color: "bg-red-500" },
    { score: 1, label: "Weak", color: "bg-red-400" },
    { score: 2, label: "Fair", color: "bg-yellow-500" },
    { score: 3, label: "Good", color: "bg-yellow-400" },
    { score: 4, label: "Strong", color: "bg-green-400" },
    { score: 5, label: "Very Strong", color: "bg-green-500" },
  ];

  return levels[Math.min(score, 5)];
}

// Password Strength Indicator Component
function PasswordStrengthIndicator({ password }: { password: string }) {
  if (!password) return null;

  const strength = calculatePasswordStrength(password);
  const percentage = (strength.score / 5) * 100;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${percentage}%` }}
            transition={{ duration: 0.3 }}
            className={`h-full rounded-full ${strength.color}`}
          />
        </div>
        <span className={`text-xs font-medium ${
          strength.score <= 1 ? "text-red-500" :
          strength.score <= 3 ? "text-yellow-600" :
          "text-green-600"
        }`}>
          {strength.label}
        </span>
      </div>
      <p className="text-[10px] text-gray-400">
        Use 8+ chars with uppercase, numbers & symbols
      </p>
    </div>
  );
}

// Password Field Component with visibility toggle and matching indicator
interface PasswordFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  showPassword: boolean;
  setShowPassword: (show: boolean) => void;
  focusedField: string | null;
  setFocusedField: (field: string | null) => void;
  fieldName: string;
  matchTarget?: string;
}

function PasswordField({
  label,
  value,
  onChange,
  showPassword,
  setShowPassword,
  focusedField,
  setFocusedField,
  fieldName,
  matchTarget,
}: PasswordFieldProps) {
  const isConfirmField = fieldName === "passwordConfirm";
  const passwordsMatch = isConfirmField && matchTarget && value
    ? value === matchTarget
    : null;

  return (
    <div>
      <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
        {label}
      </label>
      <div className="relative">
        <input
          type={showPassword ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocusedField(fieldName)}
          onBlur={() => setFocusedField(null)}
          placeholder="••••••••"
          className={`w-full px-4 py-2.5 bg-gray-100 rounded-lg text-sm text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 border pr-20 ${
            focusedField === fieldName
              ? "border-[#6720FF] ring-2 ring-[#6720FF]/10 bg-white"
              : "border-transparent hover:bg-gray-200"
          } ${
            isConfirmField && value && passwordsMatch === false
              ? "border-red-300 bg-red-50"
              : ""
          } ${
            isConfirmField && value && passwordsMatch === true
              ? "border-green-300 bg-green-50"
              : ""
          }`}
          required
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          {/* Password Match Indicator (only for confirm field) */}
          {isConfirmField && value && (
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              className={`p-1 rounded-full ${
                passwordsMatch ? "bg-green-100 text-green-600" : "bg-red-100 text-red-600"
              }`}
            >
              {passwordsMatch ? <Check size={12} /> : <X size={12} />}
            </motion.div>
          )}
          {/* Toggle Visibility Button */}
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="p-1.5 text-gray-400 hover:text-gray-600 transition-colors rounded-md hover:bg-gray-100"
            tabIndex={-1}
          >
            {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>
      {/* Match Status Text */}
      {isConfirmField && value && (
        <motion.p
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className={`text-[10px] mt-1 ${
            passwordsMatch ? "text-green-600" : "text-red-500"
          }`}
        >
          {passwordsMatch ? "Passwords match" : "Passwords do not match"}
        </motion.p>
      )}
    </div>
  );
}

export default function SignUp() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [orgName, setOrgName] = useState("");
  const [errors, setErrors] = useState<any>({});
  const [isLoading, setIsLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [focusedField, setFocusedField] = useState<string | null>(null);
  const [step, setStep] = useState<"email" | "details">("email");
  const [showPassword, setShowPassword] = useState(false);
  const [showPasswordConfirm, setShowPasswordConfirm] = useState(false);

  const handleEmailSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!email || !email.includes("@")) {
      setErrors({ email: "Please enter a valid email address" });
      return;
    }
    setErrors({});
    setStep("details");
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrors({});

    if (password !== passwordConfirm) {
      setErrors({ passwordConfirm: "Passwords do not match" });
      return;
    }

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
        setErrors({ general: data.error });
        return;
      }

      setSuccess(true);
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
      <div className="min-h-screen flex items-center justify-center bg-white">
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5 }}
          className="p-12 border border-gray-200 bg-white rounded-2xl shadow-xl text-center max-w-sm"
        >
          <div className="w-14 h-14 mx-auto mb-6 rounded-2xl bg-[#6720FF] flex items-center justify-center">
            <UserCheck size={28} className="text-white" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 tracking-tight mb-3">
            Account created
          </h2>
          <p className="text-sm text-gray-500">
            Redirecting to sign in...
          </p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex">
      {/* Left Side — Brand Visual (50%) */}
      <motion.div
        initial={{ opacity: 0, x: -30 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.7, ease: "easeOut" }}
        className="hidden lg:flex lg:w-1/2 relative flex-col justify-between p-12 xl:p-16 overflow-hidden bg-[#F8F7FA]"
      >
        {/* Subtle background pattern */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23000000' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
          }}
        />

        <div className="relative z-10">
          <Link href="/" className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-[#6720FF]" />
            <span className="text-sm font-semibold text-gray-900 tracking-tight">
              Argus
            </span>
          </Link>
        </div>

        <div className="relative z-10 space-y-6 max-w-md">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#6720FF]/10 text-[10px] font-semibold text-[#6720FF] uppercase tracking-wider">
            <span className="w-1.5 h-1.5 rounded-full bg-[#6720FF]" />
            Infrastructure 2.0
          </div>

          <h2 className="text-5xl xl:text-6xl font-bold text-gray-900 tracking-tight leading-[1.05]">
            Build.<br />
            Tune.<br />
            Scale.
          </h2>

          <p className="text-sm text-gray-500 leading-relaxed max-w-sm">
            Orchestrate your AI models with the precision of a kinetic architect. 
            High-performance compute, managed effortlessly.
          </p>

          {/* Server room image placeholder */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="relative w-full aspect-[16/10] rounded-2xl overflow-hidden bg-gray-900 shadow-2xl"
          >
            {/* CSS-based server corridor effect */}
            <div className="absolute inset-0 bg-gradient-to-b from-gray-800 via-gray-900 to-black">
              {/* Ceiling lights */}
              <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full flex justify-center gap-8 pt-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="w-8 h-1 bg-white/20 rounded-full" />
                ))}
              </div>
              {/* Server racks left */}
              <div className="absolute left-0 top-0 bottom-0 w-1/3 bg-gradient-to-r from-gray-700/40 to-transparent">
                <div className="h-full flex flex-col justify-around py-4 px-2">
                  {[...Array(8)].map((_, i) => (
                    <div key={i} className="flex gap-1">
                      {[...Array(6)].map((_, j) => (
                        <div key={j} className="w-2 h-1 bg-[#6720FF]/30 rounded-sm" />
                      ))}
                    </div>
                  ))}
                </div>
              </div>
              {/* Server racks right */}
              <div className="absolute right-0 top-0 bottom-0 w-1/3 bg-gradient-to-l from-gray-700/40 to-transparent">
                <div className="h-full flex flex-col justify-around py-4 px-2 items-end">
                  {[...Array(8)].map((_, i) => (
                    <div key={i} className="flex gap-1">
                      {[...Array(6)].map((_, j) => (
                        <div key={j} className="w-2 h-1 bg-[#6720FF]/20 rounded-sm" />
                      ))}
                    </div>
                  ))}
                </div>
              </div>
              {/* Floor reflection */}
              <div className="absolute bottom-0 left-0 right-0 h-1/3 bg-gradient-to-t from-[#6720FF]/10 to-transparent" />
              {/* Perspective lines */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-px h-full bg-gradient-to-b from-transparent via-white/5 to-transparent" />
              </div>
            </div>
          </motion.div>
        </div>

        <div className="relative z-10">
          <p className="text-[10px] text-[#6720FF] uppercase tracking-wider font-semibold">
            © 2026 Argus AI Infrastructure
          </p>
        </div>
      </motion.div>

      {/* Right Side — Signup Form (50%) */}
      <div className="flex-1 lg:w-1/2 flex flex-col bg-white relative">
        {/* Top Support Link */}
        <div className="flex justify-end p-6 md:p-8">
          <Link
            href="#"
            className="text-sm text-[#6720FF] hover:underline font-medium"
          >
            Support
          </Link>
        </div>

        <div className="flex-1 flex items-center justify-center px-6 md:px-12 pb-12">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="w-full max-w-[380px]"
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
                Create account
              </h1>
              <p className="text-sm text-gray-500">
                Get started with Argus&apos;s high-speed AI infrastructure.
              </p>
            </div>

            {step === "email" ? (
              <>
                <form onSubmit={handleEmailSubmit} className="space-y-5">
                  <div>
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      Email Address
                    </label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      onFocus={() => setFocusedField("email")}
                      onBlur={() => setFocusedField(null)}
                      placeholder="name@company.com"
                      className={`w-full px-4 py-2.5 bg-gray-100 rounded-lg text-sm text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 border ${
                        focusedField === "email"
                          ? "border-[#6720FF] ring-2 ring-[#6720FF]/10 bg-white"
                          : "border-transparent hover:bg-gray-200"
                      }`}
                    />
                  </div>

                  <AnimatePresence>
                    {errors.email && (
                      <motion.div
                        initial={{ opacity: 0, y: -8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -8 }}
                        className="text-xs text-red-600 bg-red-50 border border-red-100 px-4 py-3 rounded-lg"
                      >
                        {errors.email}
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <button
                    type="submit"
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-[#6720FF] text-white text-sm font-semibold hover:bg-[#5a1be6] transition-all duration-200 shadow-sm"
                  >
                    Next
                    <ArrowRight size={16} />
                  </button>
                </form>

                <div className="relative my-6">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-gray-200" />
                  </div>
                  <div className="relative flex justify-center">
                    <span className="px-3 text-[10px] font-medium text-gray-400 uppercase tracking-wider bg-white">
                      Or sign up with
                    </span>
                  </div>
                </div>

                {/* Social Signup */}
                <div className="grid grid-cols-3 gap-3">
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
              </>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-5">
                <div>
                  <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    Email
                  </label>
                  <div className="w-full px-4 py-2.5 bg-gray-50 rounded-lg text-sm text-gray-700 border border-gray-200">
                    {email}
                  </div>
                </div>

                <div>
                  <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    Organization Name
                  </label>
                  <input
                    type="text"
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    onFocus={() => setFocusedField("orgName")}
                    onBlur={() => setFocusedField(null)}
                    placeholder="Acme Corp"
                    className={`w-full px-4 py-2.5 bg-gray-100 rounded-lg text-sm text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 border ${
                      focusedField === "orgName"
                        ? "border-[#6720FF] ring-2 ring-[#6720FF]/10 bg-white"
                        : "border-transparent hover:bg-gray-200"
                    }`}
                    required
                  />
                </div>

                <PasswordField
                  label="Password"
                  value={password}
                  onChange={setPassword}
                  showPassword={showPassword}
                  setShowPassword={setShowPassword}
                  focusedField={focusedField}
                  setFocusedField={setFocusedField}
                  fieldName="password"
                />

                {/* Password Strength Indicator */}
                <PasswordStrengthIndicator password={password} />

                <PasswordField
                  label="Confirm Password"
                  value={passwordConfirm}
                  onChange={setPasswordConfirm}
                  showPassword={showPasswordConfirm}
                  setShowPassword={setShowPasswordConfirm}
                  focusedField={focusedField}
                  setFocusedField={setFocusedField}
                  fieldName="passwordConfirm"
                  matchTarget={password}
                />

                <AnimatePresence>
                  {errors.passwordConfirm && (
                    <motion.div
                      initial={{ opacity: 0, y: -8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      className="text-xs text-red-600 bg-red-50 border border-red-100 px-4 py-3 rounded-lg"
                    >
                      {errors.passwordConfirm}
                    </motion.div>
                  )}
                  {errors.general && (
                    <motion.div
                      initial={{ opacity: 0, y: -8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      className="text-xs text-red-600 bg-red-50 border border-red-100 px-4 py-3 rounded-lg"
                    >
                      {errors.general}
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setStep("email")}
                    className="flex-1 py-2.5 rounded-lg border border-gray-200 text-gray-700 text-sm font-semibold hover:bg-gray-50 transition-all duration-200"
                  >
                    Back
                  </button>
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="flex-[2] flex items-center justify-center gap-2 py-2.5 rounded-lg bg-[#6720FF] text-white text-sm font-semibold hover:bg-[#5a1be6] transition-all duration-200 disabled:opacity-50 shadow-sm"
                  >
                    {isLoading ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Creating...
                      </>
                    ) : (
                      <>
                        Create Account
                        <ArrowRight size={16} />
                      </>
                    )}
                  </button>
                </div>
              </form>
            )}

            {/* Footer */}
            <div className="mt-8 text-center">
              <p className="text-sm text-gray-500">
                Already have an account?{" "}
                <Link
                  href="/auth/signin"
                  className="font-semibold text-[#6720FF] hover:underline transition-colors"
                >
                  Login
                </Link>
              </p>
            </div>
          </motion.div>
        </div>

        {/* Bottom Footer */}
        <div className="flex justify-center gap-6 pb-6 text-[10px] text-gray-400 uppercase tracking-wider font-medium">
          <Link href="#" className="hover:text-gray-600 transition-colors">Terms of Service</Link>
          <Link href="#" className="hover:text-gray-600 transition-colors">Privacy Policy</Link>
          <Link href="#" className="hover:text-gray-600 transition-colors">Contact Support</Link>
        </div>
      </div>
    </div>
  );
}
