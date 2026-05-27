"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  Shield,
  CheckCircle,
  AlertCircle,
  Loader2,
  Eye,
  EyeOff,
  ChevronRight,
  Lock,
  Key,
  Cookie,
  Globe,
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  LogIn,
} from "lucide-react";

type AuthMethod = "form" | "bearer" | "cookie" | "api_key";

interface AuthConfig {
  type: AuthMethod;
  username?: string;
  password?: string;
  token?: string;
  cookie?: string;
  api_key?: string;
  api_key_header?: string;
  loginUrl?: string;
  loginMethod?: string;
  dualConfig?: AuthConfig; // second account for BOLA testing (User B)
}

interface DualAuthState {
  method: AuthMethod | null;
  config: AuthConfig;
  selectedLoginUrl: string;
}

interface LoginPageResult {
  path: string;
  url: string;
  status: number;
  hasForm: boolean;
  contentType: string;
  title: string;
}

interface AuthWizardProps {
  targetUrl: string;
  onComplete: (config: AuthConfig | null) => void;
  onSkip: () => void;
}

export default function AuthWizard({ targetUrl, onComplete, onSkip }: AuthWizardProps) {
  const [step, setStep] = useState<"detect" | "method" | "configure" | "test">("detect");
  const [dualMode, setDualMode] = useState(false);
  const [dualConfig, setDualConfig] = useState<AuthConfig | null>(null);
  const [dualStep, setDualStep] = useState<"method" | "configure" | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [loginPages, setLoginPages] = useState<LoginPageResult[]>([]);
  const [detectError, setDetectError] = useState("");
  const [authMethod, setAuthMethod] = useState<AuthMethod | null>(null);
  const [config, setConfig] = useState<AuthConfig>({ type: "form" });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; summary: string } | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [selectedLoginUrl, setSelectedLoginUrl] = useState("");

  // Step 1: Detect login pages
  const detectLoginPages = useCallback(async () => {
    if (!targetUrl) return;
    setDetecting(true);
    setDetectError("");
    setLoginPages([]);

    try {
      const response = await fetch("/api/engagement/detect-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targetUrl }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Detection failed");
      setLoginPages(data.loginPages || []);
      if (data.loginPages && data.loginPages.length > 0) {
        setStep("method");
      } else {
        setDetectError("No login pages detected. You can still configure authentication manually.");
        setStep("method");
      }
    } catch (err) {
      setDetectError(err instanceof Error ? err.message : "Failed to detect login pages");
      setStep("method");
    } finally {
      setDetecting(false);
    }
  }, [targetUrl]);

  // Start detection on mount/re-target
  const detectionStarted = useRef(false);
  useEffect(() => {
    if (targetUrl && !detectionStarted.current) {
      detectionStarted.current = true;
      detectLoginPages();
    }
  }, [targetUrl]);

  // Step 2: Select auth method
  const handleSelectMethod = (method: AuthMethod) => {
    setAuthMethod(method);
    setConfig({ type: method });
    setStep("configure");
  };

  // Step 3: Configure credentials
  const handleConfigure = () => {
    if (!config) return;
    if (dualMode && !dualStep) {
      // After User A config, move to User B setup
      setDualStep("method");
      return;
    }
    setStep("test");
    testAuth();
  };

  // Step 4: Test auth
  const testAuth = useCallback(async () => {
    if (!targetUrl || !config) return;
    setTesting(true);
    setTestResult(null);

    try {
      const response = await fetch("/api/engagement/test-auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targetUrl,
          authType: config.type,
          username: config.username,
          password: config.password,
          token: config.token,
          cookie: config.cookie,
          api_key: config.api_key,
          api_key_header: config.api_key_header,
          loginUrl: selectedLoginUrl || config.loginUrl,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Auth test failed");
      setTestResult({ success: data.success, summary: data.summary });
    } catch (err) {
      setTestResult({
        success: false,
        summary: err instanceof Error ? err.message : "Auth test failed",
      });
    } finally {
      setTesting(false);
    }
  }, [targetUrl, config, selectedLoginUrl]);

  // Confirm and emit config
  const handleConfirm = () => {
    const finalConfig: AuthConfig = {
      ...config,
      loginUrl: selectedLoginUrl || config.loginUrl,
    };
    // If dual mode is active and a second account was configured, attach it
    if (dualMode && dualConfig) {
      finalConfig.dualConfig = {
        ...dualConfig,
        loginUrl: dualConfig.loginUrl || "",
      };
    }
    onComplete(finalConfig);
  };

  const handleSkip = () => {
    onSkip();
  };

  const handleConfigChange = (field: string, value: string) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
  };

  // Render login page selection
  const renderLoginPageSelector = () => {
    if (loginPages.length === 0 && !detectError) return null;
    const formPages = loginPages.filter((p) => p.hasForm);
    const otherPages = loginPages.filter((p) => !p.hasForm);

    return (
      <div className="space-y-2">
        <label className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] font-body">
          Detected Login Pages
        </label>
        <div className="max-h-40 overflow-y-auto space-y-1.5">
          {formPages.map((page) => (
            <button
              key={page.path}
              type="button"
              onClick={() => setSelectedLoginUrl(page.path)}
              className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs transition-all duration-200 text-left border ${
                selectedLoginUrl === page.path
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-outline-variant dark:border-[#ffffff10] hover:border-primary/30 text-on-surface dark:text-[#F0F0F5]"
              }`}
            >
              <LogIn size={12} className="shrink-0" />
              <span className="font-mono truncate flex-1">{page.path}</span>
              {page.title && (
                <span className="text-[9px] text-on-surface-variant truncate max-w-[120px]">
                  {page.title}
                </span>
              )}
              {selectedLoginUrl === page.path && (
                <CheckCircle size={12} className="text-primary shrink-0" />
              )}
            </button>
          ))}
          {otherPages.map((page) => (
            <button
              key={page.path}
              type="button"
              onClick={() => setSelectedLoginUrl(page.path)}
              className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs transition-all duration-200 text-left border ${
                selectedLoginUrl === page.path
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-outline-variant dark:border-[#ffffff10] hover:border-primary/30 text-on-surface-variant"
              }`}
            >
              <Globe size={12} className="shrink-0" />
              <span className="font-mono truncate flex-1">{page.path}</span>
              {selectedLoginUrl === page.path && (
                <CheckCircle size={12} className="text-primary shrink-0" />
              )}
            </button>
          ))}
        </div>
        {loginPages.length > 0 && (
          <p className="text-[9px] text-on-surface-variant/60">
            {formPages.length} login form{formPages.length !== 1 ? "s" : ""} detected · Select one or skip to use default paths
          </p>
        )}
      </div>
    );
  };

  // Render credential form based on auth method
  const renderCredentialForm = () => {
    switch (authMethod) {
      case "form":
        return (
          <div className="space-y-4">
            {renderLoginPageSelector()}
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                Username / Email
              </label>
              <input
                type="text"
                value={config.username || ""}
                onChange={(e) => handleConfigChange("username", e.target.value)}
                placeholder="admin@example.com"
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200"
              />
            </div>
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={config.password || ""}
                  onChange={(e) => handleConfigChange("password", e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-3 py-2.5 pr-10 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors"
                >
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
          </div>
        );

      case "bearer":
        return (
          <div className="space-y-4">
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                Bearer Token
              </label>
              <textarea
                value={config.token || ""}
                onChange={(e) => handleConfigChange("token", e.target.value)}
                placeholder="eyJhbGciOiJIUzI1NiIs..."
                rows={3}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200 resize-none"
              />
            </div>
            <p className="text-[9px] text-on-surface-variant/60">
              Paste your JWT or API token. The scanner will attach it as a Bearer token in the Authorization header.
            </p>
          </div>
        );

      case "api_key":
        return (
          <div className="space-y-4">
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                API Key
              </label>
              <textarea
                value={config.api_key || ""}
                onChange={(e) => handleConfigChange("api_key", e.target.value)}
                placeholder="sk-..."
                rows={3}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200 resize-none"
              />
            </div>
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                Header Name
              </label>
              <input
                type="text"
                value={config.api_key_header || "X-API-Key"}
                onChange={(e) => handleConfigChange("api_key_header", e.target.value)}
                placeholder="X-API-Key"
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200"
              />
            </div>
            <p className="text-[9px] text-on-surface-variant/60">
              The scanner will attach the API key as a custom header (default: X-API-Key).
            </p>
          </div>
        );

      case "cookie":
        return (
          <div className="space-y-4">
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                Session Cookie
              </label>
              <textarea
                value={config.cookie || ""}
                onChange={(e) => handleConfigChange("cookie", e.target.value)}
                placeholder="session=abc123; token=xyz789"
                rows={3}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200 resize-none"
              />
            </div>
            <p className="text-[9px] text-on-surface-variant/60">
              Paste the full cookie string. Format: key=value; key2=value2
            </p>
          </div>
        );

      default:
        return null;
    }
  };

  const canProceed = () => {
    switch (config.type) {
      case "form":
        return config.username && config.password;
      case "bearer":
        return config.token;
      case "cookie":
        return config.cookie;
      case "api_key":
        return config.api_key;
      default:
        return false;
    }
  };

  return (
    <div className="border border-primary/30 bg-primary/[0.02] rounded-xl p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
            <Shield size={14} className="text-primary" />
          </div>
          <div>
            <h3 className="text-sm font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">
              Auth Wizard
            </h3>
            <p className="text-[10px] text-on-surface-variant">
              Configure authenticated scanning for deeper coverage
            </p>
          </div>
        </div>
        {/* Steps indicator */}
        <div className="flex items-center gap-1.5">
          {["detect", "method", "configure", "test"].map((s, i) => (
            <div key={s} className="flex items-center gap-1.5">
              <div
                className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold transition-all duration-300 ${
                  step === s
                    ? "bg-primary text-on-primary"
                    : ["detect", "method", "configure", "test"].indexOf(step) > i
                      ? "bg-green-500/20 text-green-500"
                      : "bg-surface-container dark:bg-[#1A1A24] text-on-surface-variant/40"
                }`}
              >
                {["detect", "method", "configure", "test"].indexOf(step) > i ? (
                  <CheckCircle size={10} />
                ) : (
                  i + 1
                )}
              </div>
              {i < 3 && (
                <div
                  className={`w-4 h-px ${
                    ["detect", "method", "configure", "test"].indexOf(step) > i
                      ? "bg-green-500/40"
                      : "bg-outline-variant dark:bg-[#ffffff10]"
                  }`}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Step 1: Detecting */}
      {step === "detect" && (
        <div className="flex flex-col items-center gap-3 py-6">
          {detecting ? (
            <>
              <Loader2 size={24} className="animate-spin text-primary" />
              <div className="text-xs text-on-surface-variant animate-pulse">
                Probing {targetUrl} for login pages...
              </div>
              <div className="text-[9px] text-on-surface-variant/50">
                Checking common authentication endpoints
              </div>
            </>
          ) : detectError ? (
            <>
              <AlertCircle size={20} className="text-amber-500" />
              <div className="text-xs text-amber-500 text-center">{detectError}</div>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={detectLoginPages}
                  className="flex items-center gap-1.5 px-4 py-2 border border-outline-variant rounded-lg text-[10px] font-bold uppercase tracking-wider hover:border-primary/30 transition-all"
                >
                  <RefreshCw size={12} />
                  Retry
                </button>
                <button
                  type="button"
                  onClick={() => setStep("method")}
                  className="px-4 py-2 bg-primary text-on-primary rounded-lg text-[10px] font-bold uppercase tracking-wider hover:opacity-90 transition-all"
                >
                  Configure Manually
                </button>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Step 2: Select Method */}
      {step === "method" && (
        <div className="space-y-4">
          <div>
            <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-3 font-body">
              Select Authentication Method
            </label>
            {/* Detected page summary */}
            {loginPages.length > 0 && (
              <div className="mb-3 p-3 rounded-lg bg-green-500/5 border border-green-500/20">
                <div className="flex items-center gap-2 mb-1">
                  <CheckCircle size={12} className="text-green-500" />
                  <span className="text-[10px] font-bold text-green-500 uppercase tracking-wider">
                    {loginPages.filter((p) => p.hasForm).length} login form(s) detected
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {loginPages.slice(0, 5).map((page) => (
                    <span
                      key={page.path}
                      className="text-[9px] font-mono bg-green-500/10 text-green-500 px-2 py-0.5 rounded"
                    >
                      {page.path}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Dual-Account Mode toggle */}
            <div className="mb-3 flex items-center justify-between px-4 py-3 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg">
              <div className="flex items-center gap-3">
                <Shield size={16} className={dualMode ? "text-amber-500" : "text-on-surface-variant/40"} />
                <div>
                  <div className="text-[10px] font-medium text-on-surface dark:text-[#F0F0F5]">
                    Dual-Account Mode (BOLA Testing)
                  </div>
                  <div className="text-[8px] text-on-surface-variant dark:text-[#8A8A9E]">
                    {dualMode
                      ? "Configure a second user account to test cross-account access control (BOLA/BOPLA)"
                      : "Single account — no cross-account privilege escalation testing"}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setDualMode(!dualMode)}
                className={`relative w-10 h-5 rounded-full transition-all duration-300 ${
                  dualMode ? "bg-amber-500" : "bg-surface-container-high dark:bg-[#2A2A35]"
                }`}
              >
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-md transition-all duration-300 ${
                  dualMode ? "left-[20px]" : "left-0.5"
                }`} />
              </button>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {[
                {
                  method: "form" as AuthMethod,
                  icon: <Lock size={18} />,
                  label: "Form Login",
                  desc: "Username & password",
                  color: "text-primary",
                },
                {
                  method: "bearer" as AuthMethod,
                  icon: <Key size={18} />,
                  label: "Bearer Token",
                  desc: "JWT or API token",
                  color: "text-amber-500",
                },
                {
                  method: "cookie" as AuthMethod,
                  icon: <Cookie size={18} />,
                  label: "Session Cookie",
                  desc: "Paste cookie string",
                  color: "text-cyan-500",
                },
                {
                  method: "api_key" as AuthMethod,
                  icon: <Key size={18} />,
                  label: "API Key",
                  desc: "Key in header",
                  color: "text-violet-500",
                },
              ].map((option) => (
                <button
                  key={option.method}
                  type="button"
                  onClick={() => handleSelectMethod(option.method)}
                  className="flex flex-col items-center gap-2 p-4 border border-outline-variant dark:border-[#ffffff10] rounded-xl hover:border-primary/30 hover:bg-primary/5 transition-all duration-300 group"
                >
                  <span className={`${option.color} group-hover:scale-110 transition-transform duration-300`}>
                    {option.icon}
                  </span>
                  <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface dark:text-[#F0F0F5]">
                    {option.label}
                  </span>
                  <span className="text-[9px] text-on-surface-variant text-center">
                    {option.desc}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="flex justify-between pt-2">
            <button
              type="button"
              onClick={handleSkip}
              className="text-[10px] text-on-surface-variant hover:text-on-surface transition-colors font-body"
            >
              Skip — scan without auth
            </button>
            <button
              type="button"
              onClick={() => setStep("detect")}
              className="flex items-center gap-1 text-[10px] text-primary hover:underline font-body"
            >
              <RefreshCw size={10} />
              Re-detect
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Configure */}
      {step === "configure" && (
        <div className="space-y-4">
          {renderCredentialForm()}
          <div className="flex justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep("method")}
              className="flex items-center gap-1 text-[10px] text-on-surface-variant hover:text-on-surface transition-colors font-body"
            >
              <ArrowLeft size={10} />
              Back
            </button>
            <button
              type="button"
              onClick={handleConfigure}
              disabled={!canProceed()}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-on-primary rounded-lg text-[10px] font-bold uppercase tracking-wider hover:opacity-90 transition-all disabled:opacity-50"
            >
              Test Authentication
              <ChevronRight size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Dual-Account: Step 2b — Select User B's auth method */}
      {dualMode && dualStep === "method" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <Shield size={14} className="text-amber-500" />
            <span className="text-[10px] font-bold text-amber-500 uppercase tracking-wider">
              User B — Attacker Account
            </span>
          </div>
          <p className="text-[9px] text-on-surface-variant/70 mb-3">
            Configure a second account to test cross-account access. User A (owner) creates resources; User B (attacker) attempts to access them.
          </p>
          <div className="grid grid-cols-3 gap-3">
            {[
              { method: "form" as AuthMethod, icon: <Lock size={18} />, label: "Form Login", desc: "Username & password", color: "text-primary" },
              { method: "bearer" as AuthMethod, icon: <Key size={18} />, label: "Bearer Token", desc: "JWT or API token", color: "text-amber-500" },
              { method: "cookie" as AuthMethod, icon: <Cookie size={18} />, label: "Session Cookie", desc: "Paste cookie string", color: "text-cyan-500" },
              { method: "api_key" as AuthMethod, icon: <Key size={18} />, label: "API Key", desc: "Key in header", color: "text-violet-500" },
            ].map((option) => (
              <button
                key={option.method}
                type="button"
                onClick={() => {
                  setDualConfig({ type: option.method });
                  setDualStep("configure");
                }}
                className="flex flex-col items-center gap-2 p-4 border border-outline-variant dark:border-[#ffffff10] rounded-xl hover:border-amber-500/30 hover:bg-amber-500/5 transition-all duration-300 group"
              >
                <span className={`${option.color} group-hover:scale-110 transition-transform`}>{option.icon}</span>
                <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface dark:text-[#F0F0F5]">{option.label}</span>
                <span className="text-[9px] text-on-surface-variant text-center">{option.desc}</span>
              </button>
            ))}
          </div>
          <div className="flex justify-between pt-2">
            <button
              type="button"
              onClick={() => { setDualStep(null); setStep("configure"); }}
              className="flex items-center gap-1 text-[10px] text-on-surface-variant hover:text-on-surface transition-colors font-body"
            >
              <ArrowLeft size={10} /> Back to User A
            </button>
            <button
              type="button"
              onClick={() => { setDualConfig(null); setDualStep(null); setStep("test"); testAuth(); }}
              className="text-[10px] text-on-surface-variant hover:text-on-surface transition-colors font-body"
            >
              Skip User B — single account only
            </button>
          </div>
        </div>
      )}

      {/* Dual-Account: Step 3b — Configure User B credentials */}
      {dualMode && dualStep === "configure" && dualConfig && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <Shield size={14} className="text-amber-500" />
            <span className="text-[10px] font-bold text-amber-500 uppercase tracking-wider">
              User B — Attacker Credentials
            </span>
          </div>
          {dualConfig.type === "form" && (
            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5">Username / Email</label>
                <input type="text" value={dualConfig.username || ""} onChange={(e) => setDualConfig({ ...dualConfig, username: e.target.value })}
                  placeholder="attacker@example.com"
                  className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant rounded-lg text-xs font-mono text-on-surface outline-none focus:border-primary transition-all" />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5">Password</label>
                <input type="password" value={dualConfig.password || ""} onChange={(e) => setDualConfig({ ...dualConfig, password: e.target.value })}
                  placeholder="••••••••"
                  className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant rounded-lg text-xs font-mono text-on-surface outline-none focus:border-primary transition-all" />
              </div>
            </div>
          )}
          {dualConfig.type === "bearer" && (
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5">Bearer Token (User B)</label>
              <textarea value={dualConfig.token || ""} onChange={(e) => setDualConfig({ ...dualConfig, token: e.target.value })}
                placeholder="eyJhbGciOiJIUzI1NiIs..."
                rows={3}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant rounded-lg text-xs font-mono text-on-surface outline-none focus:border-primary transition-all resize-none" />
            </div>
          )}
          {dualConfig.type === "cookie" && (
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5">Session Cookie (User B)</label>
              <textarea value={dualConfig.cookie || ""} onChange={(e) => setDualConfig({ ...dualConfig, cookie: e.target.value })}
                placeholder="session=abc123; token=xyz789"
                rows={3}
                className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant rounded-lg text-xs font-mono text-on-surface outline-none focus:border-primary transition-all resize-none" />
            </div>
          )}
          {dualConfig.type === "api_key" && (
            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5">API Key (User B)</label>
                <textarea value={dualConfig.api_key || ""} onChange={(e) => setDualConfig({ ...dualConfig, api_key: e.target.value })}
                  placeholder="sk-..."
                  rows={3}
                  className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant rounded-lg text-xs font-mono text-on-surface outline-none focus:border-primary transition-all resize-none" />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5">Header Name (User B)</label>
                <input type="text" value={dualConfig.api_key_header || "X-API-Key"} onChange={(e) => setDualConfig({ ...dualConfig, api_key_header: e.target.value })}
                  placeholder="X-API-Key"
                  className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant rounded-lg text-xs font-mono text-on-surface outline-none focus:border-primary transition-all" />
              </div>
            </div>
          )}
          <div className="flex justify-between pt-2">
            <button
              type="button"
              onClick={() => setDualStep("method")}
              className="flex items-center gap-1 text-[10px] text-on-surface-variant hover:text-on-surface transition-colors"
            >
              <ArrowLeft size={10} /> Change Method
            </button>
            <button
              type="button"
              onClick={() => { setStep("test"); testAuth(); }}
              className="flex items-center gap-1.5 px-4 py-2 bg-amber-500 text-white rounded-lg text-[10px] font-bold uppercase tracking-wider hover:opacity-90 transition-all"
            >
              Continue <ChevronRight size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Test */}
      {step === "test" && (
        <div className="space-y-4">
          {testing ? (
            <div className="flex flex-col items-center gap-3 py-6">
              <Loader2 size={24} className="animate-spin text-primary" />
              <div className="text-xs text-on-surface-variant animate-pulse">
                Testing {authMethod === "form" ? "form login" : authMethod === "bearer" ? "bearer token" : authMethod === "api_key" ? "API key" : "session cookie"}...
              </div>
            </div>
          ) : testResult ? (
            <>
              <div
                className={`flex items-start gap-3 p-4 rounded-xl border ${
                  testResult.success
                    ? "bg-green-500/5 border-green-500/20"
                    : "bg-red-500/5 border-red-500/20"
                }`}
              >
                {testResult.success ? (
                  <CheckCircle size={18} className="text-green-500 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle size={18} className="text-red-500 shrink-0 mt-0.5" />
                )}
                <div>
                  <p className={`text-xs font-bold uppercase tracking-wider ${
                    testResult.success ? "text-green-500" : "text-red-500"
                  }`}>
                    {testResult.success ? "Authentication Verified" : "Authentication Failed"}
                  </p>
                  <p className="text-[10px] text-on-surface-variant mt-1">{testResult.summary}</p>
                </div>
              </div>

              <div className="flex justify-between pt-2">
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setStep("configure")}
                    className="flex items-center gap-1 text-[10px] text-on-surface-variant hover:text-on-surface transition-colors font-body"
                  >
                    <ArrowLeft size={10} />
                    Edit Config
                  </button>
                  <button
                    type="button"
                    onClick={testAuth}
                    className="flex items-center gap-1 text-[10px] text-primary hover:underline font-body"
                  >
                    <RefreshCw size={10} />
                    Retry
                  </button>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleSkip}
                    className="px-3 py-1.5 border border-outline-variant rounded-lg text-[9px] font-bold uppercase tracking-wider hover:border-primary/30 transition-all"
                  >
                    Skip
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirm}
                    disabled={!testResult.success}
                    className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-wider transition-all ${
                      testResult.success
                        ? "bg-green-500 text-white hover:opacity-90"
                        : "bg-surface-container text-on-surface-variant/40 cursor-not-allowed"
                    }`}
                  >
                    <CheckCircle size={12} />
                    Confirm & Save
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
