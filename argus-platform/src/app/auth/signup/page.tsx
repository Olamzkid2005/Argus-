"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, ArrowRight, Loader2, Building, Mail, Lock, UserCheck } from "lucide-react";
import MatrixDataRain from "@/components/effects/MatrixDataRain";

export default function SignUp() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [orgName, setOrgName] = useState("");
  const [errors, setErrors] = useState<any>({});
  const [isLoading, setIsLoading] = useState(false);
  const [success, setSuccess] = useState(false);

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
      <div className="fixed inset-0 flex items-center justify-center bg-void">
        <div className="absolute inset-0 z-0 opacity-20">
          <MatrixDataRain />
        </div>
        <div className="relative z-10 p-12 border border-prism-cream/30 bg-surface/80 backdrop-blur-2xl text-center max-w-sm rounded-[4px] shadow-2xl">
          <UserCheck size={48} className="text-prism-cream mx-auto mb-6" />
          <h2 className="text-2xl font-bold text-text-primary uppercase tracking-[0.2em] mb-3 italic font-mono">Node Provisioned</h2>
          <p className="text-[10px] text-text-secondary font-mono uppercase tracking-widest font-bold">Redirecting to terminal initialization...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center overflow-hidden bg-void">
      <div className="absolute inset-0 z-0 opacity-20">
        <MatrixDataRain />
      </div>

      <div
        className="relative z-10 w-full max-w-[450px] mx-4 p-8 border border-structural bg-surface/80 backdrop-blur-2xl shadow-2xl"
        style={{ borderRadius: "4px" }}
      >
        <div className="text-center mb-8">
          <div className="w-12 h-12 mx-auto mb-4 flex items-center justify-center border border-prism-cream/20 bg-surface/10">
            <ShieldCheck size={24} className="text-prism-cream" />
          </div>
          <h1 className="text-2xl font-semibold text-text-primary tracking-tight font-mono uppercase italic">Provision Node</h1>
          <p className="text-[10px] font-mono text-text-secondary mt-2 uppercase tracking-[0.2em] font-bold">Operational Access Registration</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Org Name */}
          <div className="space-y-1.5">
            <label className="block text-[10px] font-mono text-text-secondary uppercase tracking-wider font-bold">Organization identifier</label>
            <div className="relative">
              <Building size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
              <input
                type="text"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                placeholder="ACME_CORP"
                className="w-full pl-10 pr-4 py-2.5 bg-surface/40 border border-structural text-sm font-mono text-text-primary outline-none focus:border-prism-cream/50 transition-colors placeholder:text-text-secondary/40 font-bold"
                required
              />
            </div>
          </div>

          {/* Email */}
          <div className="space-y-1.5">
            <label className="block text-[10px] font-mono text-text-secondary uppercase tracking-wider font-bold">Operator email</label>
            <div className="relative">
              <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@internal.vanguard"
                className="w-full pl-10 pr-4 py-2.5 bg-surface/40 border border-structural text-sm font-mono text-text-primary outline-none focus:border-prism-cream/50 transition-colors placeholder:text-text-secondary/40 font-bold"
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="block text-[10px] font-mono text-text-secondary uppercase tracking-wider font-bold">Passcode</label>
              <div className="relative">
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-surface/40 border border-structural text-sm font-mono text-text-primary outline-none focus:border-prism-cream/50 transition-colors font-bold"
                  required
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <label className="block text-[10px] font-mono text-text-secondary uppercase tracking-wider font-bold">Confirm</label>
              <input
                type="password"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                className="w-full px-4 py-2.5 bg-surface/40 border border-structural text-sm font-mono text-text-primary outline-none focus:border-prism-cream/50 transition-colors font-bold"
                required
              />
            </div>
          </div>

          {errors.general && (
            <div className="text-[10px] font-mono text-red-500 bg-red-500/10 border border-red-500/20 px-3 py-2 uppercase tracking-widest font-bold text-center">
              !!! {errors.general} !!!
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full flex items-center justify-center gap-2 py-4 mt-4 text-xs font-bold transition-all duration-200 disabled:opacity-50 group relative uppercase tracking-[0.3em] bg-prism-cream text-void hover:bg-white shadow-glow-cream"
          >
            {isLoading ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                PROVISIONING...
              </span>
            ) : (
              <>
                INITIALIZATION
                <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </button>
        </form>

        <div className="mt-8 pt-5 border-t border-structural text-center">
          <p className="text-[10px] text-text-secondary uppercase tracking-widest font-bold">
            Existing operator? <Link href="/auth/signin" className="text-prism-cream hover:underline">terminal-access</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
