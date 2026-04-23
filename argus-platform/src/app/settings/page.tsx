"use client";

import { useState, useEffect } from "react";
import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui/Toast";
import { motion } from "framer-motion";
import {
  Key,
  Eye,
  EyeOff,
  Save,
  Loader2,
  AlertCircle,
  Settings as SettingsIcon,
  ChevronRight,
  LogOut,
  Sparkles,
  Check,
  ExternalLink,
  Zap,
  Target,
  Bomb,
  Sun,
  Moon,
  Shield,
  Cpu,
  Activity,
  Thermometer,
  X,
  Monitor,
} from "lucide-react";
import ScanModeHelp from "@/components/ui-custom/ScanModeHelp";

interface Settings {
  openrouter_api_key?: string;
  preferred_ai_model?: string;
  scan_aggressiveness?: string;
}

interface AITestResult {
  ok: boolean;
  model?: string;
  message?: string;
  error?: string;
  details?: string;
}

// Scan aggressiveness presets
const AGGRESSIVENESS_PRESETS = [
  {
    id: "default",
    name: "Default",
    description: "Standard scan depth — balanced coverage and speed",
    icon: <Target size={20} />,
    color: "text-primary",
    borderColor: "border-primary/30",
    bgColor: "bg-primary/5",
    details: [
      "Katana crawl depth: 3",
      "Amass: passive enumeration",
      "Naabu: top 1000 ports",
      "Ffuf: common wordlist",
      "Nuclei: standard templates",
    ],
  },
  {
    id: "high",
    name: "High",
    description: "Deeper scanning — more thorough but slower",
    icon: <Zap size={20} />,
    color: "text-orange-400",
    borderColor: "border-orange-400/30",
    bgColor: "bg-orange-400/5",
    details: [
      "Katana crawl depth: 5",
      "Amass: active + passive",
      "Naabu: top 10,000 ports",
      "Ffuf: extended wordlist",
      "Nuclei: all templates",
    ],
  },
  {
    id: "extreme",
    name: "Extreme",
    description: "Maximum depth — exhaustive coverage",
    icon: <Bomb size={20} />,
    color: "text-error",
    borderColor: "border-error/30",
    bgColor: "bg-error/5",
    details: [
      "Katana crawl depth: 7+",
      "Amass: brute force + all sources",
      "Naabu: full port range (1-65535)",
      "Ffuf: comprehensive wordlist",
      "Nuclei: all templates + fuzzing",
    ],
  },
];

// OpenRouter models - grouped by provider
const OPENROUTER_MODELS = [
  { id: "anthropic/claude-3.5-sonnet", name: "Claude 3.5 Sonnet", provider: "anthropic", description: "Best balance of speed and intelligence" },
  { id: "anthropic/claude-3.7-sonnet", name: "Claude 3.7 Sonnet", provider: "anthropic", description: "Latest Sonnet with extended thinking" },
  { id: "anthropic/claude-3.7-sonnet:thinking", name: "Claude 3.7 Sonnet (Thinking)", provider: "anthropic", description: "Extended reasoning mode" },
  { id: "anthropic/claude-3-opus", name: "Claude 3 Opus", provider: "anthropic", description: "Most powerful Anthropic model" },
  { id: "anthropic/claude-3.5-haiku", name: "Claude 3.5 Haiku", provider: "anthropic", description: "Fast and cost-effective" },

  { id: "openai/gpt-4o", name: "GPT-4O", provider: "openai", description: "OpenAI flagship multimodal model" },
  { id: "openai/gpt-4o-mini", name: "GPT-4O Mini", provider: "openai", description: "Fast and affordable" },
  { id: "openai/gpt-4.1", name: "GPT-4.1", provider: "openai", description: "Latest GPT generation" },
  { id: "openai/gpt-4.1-mini", name: "GPT-4.1 Mini", provider: "openai", description: "Compact GPT-4.1" },
  { id: "openai/gpt-4.1-nano", name: "GPT-4.1 Nano", provider: "openai", description: "Smallest GPT-4.1" },
  { id: "openai/gpt-4.5-preview", name: "GPT-4.5 Preview", provider: "openai", description: "Experimental preview model" },
  { id: "openai/o1", name: "O1", provider: "openai", description: "Advanced reasoning" },
  { id: "openai/o1-mini", name: "O1 Mini", provider: "openai", description: "Fast reasoning" },
  { id: "openai/o3-mini", name: "O3 Mini", provider: "openai", description: "Latest reasoning model" },
  { id: "openai/o4-mini", name: "O4 Mini", provider: "openai", description: "Newest mini reasoning" },

  { id: "google/gemini-2.5-pro", name: "Gemini 2.5 Pro", provider: "google", description: "Google's most capable model" },
  { id: "google/gemini-2.5-flash", name: "Gemini 2.5 Flash", provider: "google", description: "Fast multimodal model" },
  { id: "google/gemini-2.0-flash", name: "Gemini 2.0 Flash", provider: "google", description: "Fast and versatile" },
  { id: "google/gemini-2.0-flash-lite", name: "Gemini 2.0 Flash Lite", provider: "google", description: "Lightweight and cheap" },
  { id: "google/gemini-1.5-pro", name: "Gemini 1.5 Pro", provider: "google", description: "Long context champion" },
  { id: "google/gemini-1.5-flash", name: "Gemini 1.5 Flash", provider: "google", description: "Fast with 1M context" },

  { id: "meta-llama/llama-4-maverick", name: "Llama 4 Maverick", provider: "meta", description: "Latest Llama flagship" },
  { id: "meta-llama/llama-4-scout", name: "Llama 4 Scout", provider: "meta", description: "Efficient Llama variant" },
  { id: "meta-llama/llama-3.3-70b", name: "Llama 3.3 70B", provider: "meta", description: "High performance open model" },

  { id: "deepseek/deepseek-chat", name: "DeepSeek Chat", provider: "deepseek", description: "Strong reasoning model" },
  { id: "deepseek/deepseek-r1", name: "DeepSeek R1", provider: "deepseek", description: "Advanced reasoning specialist" },

  { id: "mistralai/mistral-large", name: "Mistral Large", provider: "mistral", description: "Mistral's best model" },
  { id: "mistralai/mistral-medium", name: "Mistral Medium", provider: "mistral", description: "Balanced performance" },
  { id: "mistralai/mistral-small", name: "Mistral Small", provider: "mistral", description: "Fast and cheap" },

  { id: "qwen/qwq-32b", name: "QWEN QWQ 32B", provider: "qwen", description: "Strong open reasoning model" },

  { id: "nvidia/llama-3.1-nemotron-70b", name: "NVIDIA Nemotron 70B", provider: "nvidia", description: "NVIDIA optimized Llama" },

  { id: "perplexity/sonar", name: "Perplexity Sonar", provider: "perplexity", description: "Search-augmented model" },
];

export default function SettingsPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const { showToast } = useToast();

  const [settings, setSettings] = useState<Settings>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [customModel, setCustomModel] = useState("");
  const [temperature, setTemperature] = useState(0.7);
  const [isDark, setIsDark] = useState(false);
  const [isTestingAI, setIsTestingAI] = useState(false);
  const [aiTestResult, setAiTestResult] = useState<AITestResult | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsDark(document.documentElement.classList.contains("dark"));
    }
  }, []);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/auth/signin");
      return;
    }
    if (status === "authenticated") {
      loadSettings();
    }
  }, [status, router]);

  const loadSettings = async () => {
    try {
      const response = await fetch("/api/settings");
      const data = await response.json();
      if (response.ok && data.settings) {
        setSettings(data.settings);
      }
    } catch (error) {
      console.error("Failed to load settings:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const payload = { ...settings };
      if (customModel.trim()) {
        payload.preferred_ai_model = customModel;
      }
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error("Failed to save settings");
      showToast("success", "Parameters updated");

      if (settings.openrouter_api_key && !settings.openrouter_api_key.includes("•")) {
        setSettings((prev) => ({ ...prev, openrouter_api_key: "sk-or-" + "•".repeat(20) }));
      }
    } catch (error) {
      showToast("error", error instanceof Error ? error.message : "System failure");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDiscard = () => {
    loadSettings();
    setCustomModel("");
    showToast("info", "Changes discarded");
  };

  const toggleDarkMode = () => {
    const newDark = !isDark;
    setIsDark(newDark);
    if (newDark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  };

  const handleTestAIConnection = async () => {
    setIsTestingAI(true);
    setAiTestResult(null);
    try {
      const modelToTest = customModel.trim() || settings.preferred_ai_model || "";
      const apiKeyToTest =
        settings.openrouter_api_key && !settings.openrouter_api_key.includes("•")
          ? settings.openrouter_api_key
          : undefined;

      const response = await fetch("/api/ai/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          apiKey: apiKeyToTest,
          model: modelToTest,
        }),
      });

      const data = await response.json();
      setAiTestResult(data);

      if (response.ok && data.ok) {
        showToast("success", "AI test successful");
      } else {
        showToast("error", data.error || "AI test failed");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Network error";
      setAiTestResult({
        ok: false,
        error: "Failed to test AI connection",
        details: message,
      });
      showToast("error", "Failed to test AI connection");
    } finally {
      setIsTestingAI(false);
    }
  };

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background dark:bg-[#0A0A0F]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) return null;

  const currentModel = settings.preferred_ai_model;
  const isCustomModel = currentModel ? !OPENROUTER_MODELS.some((m) => m.id === currentModel) : false;

  return (
    <div className="min-h-screen px-6 py-6 bg-background dark:bg-[#0A0A0F] font-body pb-24">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <div className="flex items-center gap-2 mb-2">
          <SettingsIcon size={18} className="text-primary" />
          <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
            Platform Configuration
          </span>
        </div>
        <h1 className="text-3xl font-semibold text-on-surface dark:text-white tracking-tight font-headline">Settings</h1>
        <p className="text-sm text-on-surface-variant mt-1 font-body">
          Manage operational parameters and external intelligence integrations
        </p>
      </motion.div>

      <div className="grid grid-cols-12 gap-6">
        {/* Left Column - Primary Configurations */}
        <div className="col-span-12 lg:col-span-8 space-y-6">
          {/* AI Configuration Card */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-primary/10 border border-primary/20">
                <Sparkles className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  AI Configuration
                </h2>
                <p className="text-[11px] text-on-surface-variant">OpenRouter integration settings</p>
              </div>
            </div>

            {/* API Key */}
            <div className="space-y-4 mb-6">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-bold text-on-surface uppercase tracking-wider font-headline">
                  API Key
                </label>
                <a
                  href="https://openrouter.ai/keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-[10px] font-mono text-primary hover:underline uppercase transition-all duration-300"
                >
                  Get Key <ExternalLink size={10} className="inline" />
                </a>
              </div>
              <div className="relative">
                <input
                  type={showKey ? "text" : "password"}
                  value={settings.openrouter_api_key || ""}
                  onChange={(e) => setSettings((p) => ({ ...p, openrouter_api_key: e.target.value }))}
                  placeholder="sk-or-v1-..."
                  className="w-full px-4 py-3 pr-12 bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30 rounded-lg text-sm font-mono text-on-surface outline-none focus:border-primary transition-all duration-300"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-all duration-300"
                >
                  {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <p className="text-[11px] text-on-surface-variant">
                One key unlocks 100+ models from OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral, and more.
              </p>
            </div>

            {/* Model Selector */}
            <div className="mb-6">
              <label className="text-[11px] font-bold text-on-surface uppercase tracking-wider mb-3 block font-headline">
                Model Selection
              </label>
              <div className="rounded-lg border border-outline-variant dark:border-outline/30 bg-surface-container-low/50 dark:bg-surface-container/50 p-3">
                <select
                  value={isCustomModel ? "__custom__" : (currentModel || "")}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (value === "__custom__") {
                      setSettings((p) => ({ ...p, preferred_ai_model: customModel || currentModel || "" }));
                      return;
                    }
                    setCustomModel("");
                    setSettings((p) => ({ ...p, preferred_ai_model: value }));
                  }}
                  className="w-full px-3 py-2 rounded-lg bg-surface dark:bg-surface-container border border-outline-variant dark:border-outline/30 text-sm text-on-surface outline-none focus:border-primary transition-all duration-300"
                >
                  <option value="">Select a model</option>
                  {Object.entries(
                    OPENROUTER_MODELS.reduce((acc, model) => {
                      acc[model.provider] = acc[model.provider] || [];
                      acc[model.provider].push(model);
                      return acc;
                    }, {} as Record<string, typeof OPENROUTER_MODELS>)
                  ).map(([provider, models]) => (
                    <optgroup key={provider} label={provider.toUpperCase()}>
                      {models.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.name} ({model.id})
                        </option>
                      ))}
                    </optgroup>
                  ))}
                  <option value="__custom__">Custom model ID...</option>
                </select>
                <div className="mt-2">
                  {currentModel && !isCustomModel && (
                    <p className="text-[11px] text-on-surface-variant">
                      {
                        OPENROUTER_MODELS.find((m) => m.id === currentModel)?.description
                      }
                    </p>
                  )}
                </div>
              </div>

              {/* Always-available custom model input */}
              <div className="mt-4 space-y-2">
                <label className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider block">
                  Custom Model ID (optional)
                </label>
                <input
                  type="text"
                  value={customModel || (isCustomModel ? currentModel || "" : "")}
                  onChange={(e) => {
                    const value = e.target.value;
                    setCustomModel(value);
                    setSettings((p) => ({ ...p, preferred_ai_model: value }));
                  }}
                  placeholder="Paste custom model, e.g. openai/gpt-oss-120b:free"
                  className="w-full px-4 py-2 bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30 rounded-lg text-sm font-mono text-on-surface outline-none focus:border-primary transition-all duration-300"
                />
                <p className="text-[11px] text-on-surface-variant">
                  Paste any OpenRouter model slug to use a model not in the dropdown.
                </p>
              </div>

              <div className="mt-4 space-y-3">
                <button
                  type="button"
                  onClick={handleTestAIConnection}
                  disabled={isTestingAI}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-primary/10 border border-primary/20 text-primary rounded-lg text-xs font-bold uppercase tracking-wider hover:bg-primary/15 transition-all duration-300 disabled:opacity-50"
                >
                  {isTestingAI ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {isTestingAI ? "Testing Connection..." : "Test AI Connection"}
                </button>

                {aiTestResult && (
                  <div
                    className={`rounded-lg border p-3 text-xs ${
                      aiTestResult.ok
                        ? "border-green-500/30 bg-green-500/10 text-green-300"
                        : "border-error/30 bg-error/10 text-red-300"
                    }`}
                  >
                    <div className="font-bold uppercase tracking-wider mb-1">
                      {aiTestResult.ok ? "Connection Successful" : "Connection Failed"}
                    </div>
                    {aiTestResult.model && (
                      <div className="font-mono text-[11px] mb-1">Model: {aiTestResult.model}</div>
                    )}
                    <div className="text-[11px] leading-relaxed">
                      {aiTestResult.ok
                        ? aiTestResult.message
                        : aiTestResult.error || aiTestResult.details || "Unknown error"}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Temperature Slider */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[11px] font-bold text-on-surface uppercase tracking-wider font-headline flex items-center gap-2">
                  <Thermometer size={12} />
                  Temperature
                </label>
                <span className="text-[11px] font-mono text-primary">{temperature.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="w-full h-2 bg-surface-container-high dark:bg-surface-container rounded-full appearance-none cursor-pointer accent-primary"
              />
              <div className="flex justify-between mt-1">
                <span className="text-[9px] text-on-surface-variant">Precise</span>
                <span className="text-[9px] text-on-surface-variant">Creative</span>
              </div>
            </div>
          </motion.div>

          {/* Scan Aggressiveness */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-orange-400/10 border border-orange-400/20">
                <Zap className="h-5 w-5 text-orange-400" />
              </div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  Scan Aggressiveness
                </h2>
                <ScanModeHelp trigger="icon" />
              </div>
            </div>

            <p className="text-xs text-on-surface-variant mb-6 leading-relaxed">
              Control how deep and thorough the reconnaissance and scanning tools go. Higher aggressiveness finds
              more attack surface but takes significantly longer.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {AGGRESSIVENESS_PRESETS.map((preset) => {
                const isSelected = settings.scan_aggressiveness === preset.id;
                return (
                  <button
                    key={preset.id}
                    onClick={() => setSettings((p) => ({ ...p, scan_aggressiveness: preset.id }))}
                    className={`text-left border rounded-xl transition-all duration-300 ${
                      isSelected
                        ? `${preset.borderColor} ${preset.bgColor} shadow-glow`
                        : "border-outline-variant dark:border-outline/30 bg-surface-container-low/50 dark:bg-surface-container/50 hover:border-primary/20"
                    }`}
                  >
                    <div className="flex flex-col items-start p-4">
                      <div className={`${preset.color} mb-2`}>{preset.icon}</div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-sm font-bold ${preset.color}`}>{preset.name}</span>
                        {isSelected && (
                          <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 bg-green-500/10 text-green-500 border border-green-500/20 rounded">
                            Active
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-on-surface-variant mb-3">{preset.description}</p>
                      <div
                        className={`w-5 h-5 border rounded flex items-center justify-center shrink-0 mt-auto ${
                          isSelected ? "border-primary bg-primary" : "border-outline-variant dark:border-outline/30"
                        }`}
                      >
                        {isSelected && <Check size={12} className="text-white" />}
                      </div>
                    </div>
                    {/* Expanded details when selected */}
                    {isSelected && (
                      <div className="px-4 pb-4 pt-1 border-t border-white/5">
                        <div className="space-y-1">
                          {preset.details.map((detail, i) => (
                            <div key={i} className="flex items-center gap-2">
                              <div className={`w-1 h-1 rounded-full ${preset.color.replace("text-", "bg-")} opacity-60`} />
                              <span className="text-[10px] font-mono text-on-surface-variant">{detail}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </motion.div>
        </div>

        {/* Right Column - Security & Metadata */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          {/* Session & Security */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-primary/10 border border-primary/20">
                <Shield className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  Session & Security
                </h2>
                <p className="text-[11px] text-on-surface-variant">Account and access controls</p>
              </div>
            </div>

            <div className="space-y-4">
              {/* Recent Notices */}
              <div className="p-3 rounded-lg bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30">
                <div className="flex items-start gap-2">
                  <AlertCircle size={14} className="text-primary mt-0.5 shrink-0" />
                  <div>
                    <div className="text-[11px] font-bold text-on-surface">Cryptographic Security</div>
                    <p className="text-[10px] text-on-surface-variant mt-0.5 leading-relaxed">
                      All credentials are encrypted and stored within the Argus secure perimeter.
                    </p>
                  </div>
                </div>
              </div>

              {/* Dark Mode Toggle */}
              <div className="flex items-center justify-between p-3 rounded-lg bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30">
                <div className="flex items-center gap-2">
                  {isDark ? <Moon size={14} className="text-primary" /> : <Sun size={14} className="text-primary" />}
                  <span className="text-xs text-on-surface font-body">Dark Mode</span>
                </div>
                <button
                  onClick={toggleDarkMode}
                  className={`relative w-11 h-6 rounded-full transition-all duration-300 ${
                    isDark ? "bg-primary" : "bg-surface-container-high dark:bg-surface-container"
                  }`}
                >
                  <div
                    className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow transition-all duration-300 ${
                      isDark ? "left-6" : "left-1"
                    }`}
                  />
                </button>
              </div>

              {/* MFA Placeholder */}
              <div className="flex items-center justify-between p-3 rounded-lg bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30 opacity-60">
                <div className="flex items-center gap-2">
                  <Monitor size={14} className="text-on-surface-variant" />
                  <span className="text-xs text-on-surface-variant font-body">Multi-Factor Auth</span>
                </div>
                <span className="text-[10px] font-mono text-on-surface-variant">Coming Soon</span>
              </div>

              {/* Logout */}
              <button
                onClick={() => signOut({ callbackUrl: "/" })}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 border border-error/20 text-error text-xs font-bold uppercase tracking-widest hover:bg-error/10 transition-all duration-300 rounded-lg"
              >
                <LogOut size={14} />
                Revoke Access
              </button>
            </div>
          </motion.div>

          {/* System Health */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-green-500/10 border border-green-500/20">
                <Activity className="h-5 w-5 text-green-500" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  System Health
                </h2>
                <p className="text-[11px] text-on-surface-variant">Node status and resources</p>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] text-on-surface-variant font-body flex items-center gap-1">
                    <Cpu size={10} />
                    CPU Usage
                  </span>
                  <span className="text-[10px] font-mono text-primary">42%</span>
                </div>
                <div className="w-full h-1.5 bg-surface-container-high dark:bg-surface-container rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: "42%" }}
                    transition={{ delay: 0.5, duration: 0.8 }}
                    className="h-full bg-primary rounded-full"
                  />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] text-on-surface-variant font-body flex items-center gap-1">
                    <Activity size={10} />
                    RAM Usage
                  </span>
                  <span className="text-[10px] font-mono text-primary">68%</span>
                </div>
                <div className="w-full h-1.5 bg-surface-container-high dark:bg-surface-container rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: "68%" }}
                    transition={{ delay: 0.6, duration: 0.8 }}
                    className="h-full bg-primary rounded-full"
                  />
                </div>
              </div>
              <div className="flex items-center gap-2 pt-2">
                <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                <span className="text-[11px] text-on-surface font-body">All nodes operational</span>
              </div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* Floating Action Footer */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="fixed bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-3 px-6 py-3 bg-surface dark:bg-surface-container-high border border-outline-variant dark:border-outline/30 rounded-2xl shadow-glow z-50"
      >
        <button
          onClick={handleDiscard}
          className="flex items-center gap-2 px-5 py-2 text-xs font-bold text-on-surface-variant border border-outline-variant dark:border-outline/30 rounded-lg hover:bg-surface-container-high dark:hover:bg-surface-container transition-all duration-300"
        >
          <X size={14} />
          Discard Changes
        </button>
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="flex items-center gap-2 px-6 py-2 bg-primary text-white text-xs font-bold uppercase tracking-widest rounded-lg hover:bg-primary/90 transition-all duration-300 shadow-glow disabled:opacity-50"
        >
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {isSaving ? "SAVING..." : "Commit Changes"}
        </button>
      </motion.div>
    </div>
  );
}
