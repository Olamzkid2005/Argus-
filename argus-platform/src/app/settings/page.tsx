"use client";

import { useState, useEffect } from "react";
import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui/Toast";
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
} from "lucide-react";
import ScanModeHelp from "@/components/ui-custom/ScanModeHelp";

interface Settings {
  openrouter_api_key?: string;
  preferred_ai_model?: string;
  scan_aggressiveness?: string;
}

// Scan aggressiveness presets
const AGGRESSIVENESS_PRESETS = [
  {
    id: "default",
    name: "Default",
    description: "Standard scan depth — balanced coverage and speed",
    icon: <Target size={20} />,
    color: "text-prism-cyan",
    borderColor: "border-prism-cyan/30",
    bgColor: "bg-prism-cyan/5",
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
    color: "text-red-400",
    borderColor: "border-red-400/30",
    bgColor: "bg-red-400/5",
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
  // Anthropic
  { id: "anthropic/claude-3.5-sonnet", name: "Claude 3.5 Sonnet", provider: "anthropic", description: "Best balance of speed and intelligence" },
  { id: "anthropic/claude-3.7-sonnet", name: "Claude 3.7 Sonnet", provider: "anthropic", description: "Latest Sonnet with extended thinking" },
  { id: "anthropic/claude-3.7-sonnet:thinking", name: "Claude 3.7 Sonnet (Thinking)", provider: "anthropic", description: "Extended reasoning mode" },
  { id: "anthropic/claude-3-opus", name: "Claude 3 Opus", provider: "anthropic", description: "Most powerful Anthropic model" },
  { id: "anthropic/claude-3.5-haiku", name: "Claude 3.5 Haiku", provider: "anthropic", description: "Fast and cost-effective" },
  
  // OpenAI
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
  
  // Google
  { id: "google/gemini-2.5-pro", name: "Gemini 2.5 Pro", provider: "google", description: "Google's most capable model" },
  { id: "google/gemini-2.5-flash", name: "Gemini 2.5 Flash", provider: "google", description: "Fast multimodal model" },
  { id: "google/gemini-2.0-flash", name: "Gemini 2.0 Flash", provider: "google", description: "Fast and versatile" },
  { id: "google/gemini-2.0-flash-lite", name: "Gemini 2.0 Flash Lite", provider: "google", description: "Lightweight and cheap" },
  { id: "google/gemini-1.5-pro", name: "Gemini 1.5 Pro", provider: "google", description: "Long context champion" },
  { id: "google/gemini-1.5-flash", name: "Gemini 1.5 Flash", provider: "google", description: "Fast with 1M context" },
  
  // Meta
  { id: "meta-llama/llama-4-maverick", name: "Llama 4 Maverick", provider: "meta", description: "Latest Llama flagship" },
  { id: "meta-llama/llama-4-scout", name: "Llama 4 Scout", provider: "meta", description: "Efficient Llama variant" },
  { id: "meta-llama/llama-3.3-70b", name: "Llama 3.3 70B", provider: "meta", description: "High performance open model" },
  
  // DeepSeek
  { id: "deepseek/deepseek-chat", name: "DeepSeek Chat", provider: "deepseek", description: "Strong reasoning model" },
  { id: "deepseek/deepseek-r1", name: "DeepSeek R1", provider: "deepseek", description: "Advanced reasoning specialist" },
  
  // Mistral
  { id: "mistralai/mistral-large", name: "Mistral Large", provider: "mistral", description: "Mistral's best model" },
  { id: "mistralai/mistral-medium", name: "Mistral Medium", provider: "mistral", description: "Balanced performance" },
  { id: "mistralai/mistral-small", name: "Mistral Small", provider: "mistral", description: "Fast and cheap" },
  
  // Qwen
  { id: "qwen/qwq-32b", name: "QWEN QWQ 32B", provider: "qwen", description: "Strong open reasoning model" },
  
  // NVIDIA
  { id: "nvidia/llama-3.1-nemotron-70b", name: "NVIDIA Nemotron 70B", provider: "nvidia", description: "NVIDIA optimized Llama" },
  
  // Perplexity
  { id: "perplexity/sonar", name: "Perplexity Sonar", provider: "perplexity", description: "Search-augmented model" },
];

const PROVIDER_COLORS: Record<string, string> = {
  anthropic: "text-orange-400 bg-orange-400/10 border-orange-400/20",
  openai: "text-prism-cream bg-prism-cream/10 border-prism-cream/20",
  google: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  meta: "text-indigo-400 bg-indigo-400/10 border-indigo-400/20",
  deepseek: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20",
  mistral: "text-purple-400 bg-purple-400/10 border-purple-400/20",
  qwen: "text-pink-400 bg-pink-400/10 border-pink-400/20",
  nvidia: "text-green-400 bg-green-400/10 border-green-400/20",
  perplexity: "text-teal-400 bg-teal-400/10 border-teal-400/20",
};

export default function SettingsPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const { showToast } = useToast();

  const [settings, setSettings] = useState<Settings>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [customModel, setCustomModel] = useState("");
  const [showCustomInput, setShowCustomInput] = useState(false);

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
      if (customModel && showCustomInput) {
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

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-void">
        <Loader2 className="h-8 w-8 animate-spin text-prism-cream" />
      </div>
    );
  }

  if (!session) return null;

  const currentModel = settings.preferred_ai_model;
  const isCustomModel = currentModel ? !OPENROUTER_MODELS.some((m) => m.id === currentModel) : false;

  return (
    <div className="min-h-screen px-8 py-8 bg-void">
      {/* Header */}
      <div className="mb-10">
        <div className="flex items-center gap-2 mb-2">
          <SettingsIcon size={18} className="text-prism-cream" />
          <span className="text-[11px] font-mono text-text-secondary tracking-widest uppercase">
            Platform Configuration
          </span>
        </div>
        <h1 className="text-4xl font-semibold text-text-primary tracking-tight">SETTINGS</h1>
        <p className="text-sm text-text-secondary mt-2">
          Manage operational parameters and external intelligence integrations
        </p>
      </div>

      <div className="max-w-3xl space-y-6">
        {/* OpenRouter API Key */}
        <div className="border border-white/[0.08] bg-surface/30 p-8">
          <div className="flex items-center gap-3 mb-8">
            <Key className="h-5 w-5 text-prism-cream" />
            <h2 className="text-sm font-bold text-text-primary uppercase tracking-widest">
              OpenRouter API Key
            </h2>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <label className="text-[11px] font-bold text-text-primary uppercase tracking-wider">
                API Key
              </label>
              <a
                href="https://openrouter.ai/keys"
                target="_blank"
                className="flex items-center gap-1 text-[10px] font-mono text-prism-cyan hover:underline uppercase"
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
                className="w-full px-4 py-3 pr-12 bg-void/50 border border-white/10 text-sm font-mono text-text-primary outline-none focus:border-prism-cream transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary transition-colors"
              >
                {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <p className="text-[11px] text-text-secondary">
              One key unlocks 100+ models from OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral, and more.
            </p>
          </div>
        </div>

        {/* AI Model Selection */}
        <div className="border border-white/[0.08] bg-surface/30 p-8">
          <div className="flex items-center gap-3 mb-8">
            <Sparkles className="h-5 w-5 text-prism-cyan" />
            <h2 className="text-sm font-bold text-text-primary uppercase tracking-widest">
              AI Model Selection
            </h2>
          </div>

          <p className="text-xs text-text-secondary mb-6 leading-relaxed">
            Choose the model for vulnerability explanations and attack chain analysis. 
            All models are accessible through your single OpenRouter key.
          </p>

          <div className="space-y-2 max-h-[500px] overflow-y-auto pr-2">
            {OPENROUTER_MODELS.map((model) => {
              const isSelected = currentModel === model.id;
              return (
                <button
                  key={model.id}
                  onClick={() => {
                    setSettings((p) => ({ ...p, preferred_ai_model: model.id }));
                    setShowCustomInput(false);
                  }}
                  className={`w-full flex items-center gap-4 px-4 py-3 border transition-all text-left ${
                    isSelected
                      ? "border-prism-cyan/40 bg-prism-cyan/10"
                      : "border-structural bg-surface/20 hover:border-text-secondary/30"
                  }`}
                >
                  <div
                    className={`w-5 h-5 border flex items-center justify-center shrink-0 ${
                      isSelected ? "border-prism-cyan bg-prism-cyan" : "border-text-secondary/30"
                    }`}
                  >
                    {isSelected && <Check size={12} className="text-void" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-sm font-medium ${
                          isSelected ? "text-prism-cyan" : "text-text-primary"
                        }`}
                      >
                        {model.name}
                      </span>
                      <span
                        className={`text-[10px] font-mono uppercase px-1.5 py-0.5 border ${
                          PROVIDER_COLORS[model.provider] || "text-text-secondary bg-surface/10 border-structural"
                        }`}
                      >
                        {model.provider}
                      </span>
                    </div>
                    <p className="text-[11px] text-text-secondary mt-0.5">{model.description}</p>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Custom Model Option */}
          <div className="mt-4">
            {showCustomInput || isCustomModel ? (
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={customModel || (isCustomModel ? currentModel : "")}
                  onChange={(e) => {
                    setCustomModel(e.target.value);
                    setSettings((p) => ({ ...p, preferred_ai_model: e.target.value }));
                  }}
                  placeholder="provider/model-name (e.g. google/gemini-2.0-pro)"
                  className="flex-1 px-4 py-2 bg-void/50 border border-white/10 text-sm font-mono text-text-primary outline-none focus:border-prism-cream transition-colors"
                />
                <button
                  onClick={() => {
                    setShowCustomInput(false);
                    setCustomModel("");
                  }}
                  className="text-[11px] text-text-secondary hover:text-text-primary"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowCustomInput(true)}
                className="text-xs text-prism-cyan hover:underline"
              >
                Use a custom model ID not listed above
              </button>
            )}
          </div>
        </div>

        {/* Scan Aggressiveness */}
        <div className="border border-white/[0.08] bg-surface/30 p-8">
          <div className="flex items-center gap-3 mb-6">
            <Zap className="h-5 w-5 text-orange-400" />
            <h2 className="text-sm font-bold text-text-primary uppercase tracking-widest">
              Scan Aggressiveness
            </h2>
            <ScanModeHelp trigger="icon" />
          </div>

          <p className="text-xs text-text-secondary mb-6 leading-relaxed">
            Control how deep and thorough the reconnaissance and scanning tools go.
            Higher aggressiveness finds more attack surface but takes significantly longer.
          </p>

          <div className="space-y-3">
            {AGGRESSIVENESS_PRESETS.map((preset) => {
              const isSelected = settings.scan_aggressiveness === preset.id;
              return (
                <button
                  key={preset.id}
                  onClick={() => setSettings((p) => ({ ...p, scan_aggressiveness: preset.id }))}
                  className={`w-full text-left border transition-all ${
                    isSelected
                      ? `${preset.borderColor} ${preset.bgColor}`
                      : "border-structural bg-surface/20 hover:border-text-secondary/30"
                  }`}
                >
                  <div className="flex items-center gap-4 px-4 py-4">
                    <div className={`${preset.color}`}>{preset.icon}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-sm font-bold ${preset.color}`}>{preset.name}</span>
                        {isSelected && (
                          <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 bg-green-400/10 text-green-400 border border-green-400/20">
                            Active
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-text-secondary">{preset.description}</p>
                    </div>
                    <div
                      className={`w-5 h-5 border flex items-center justify-center shrink-0 ${
                        isSelected ? "border-prism-cyan bg-prism-cyan" : "border-text-secondary/30"
                      }`}
                    >
                      {isSelected && <Check size={12} className="text-void" />}
                    </div>
                  </div>
                  {/* Expanded details when selected */}
                  {isSelected && (
                    <div className="px-4 pb-4 pt-1 border-t border-white/5">
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                        {preset.details.map((detail, i) => (
                          <div key={i} className="flex items-center gap-2">
                            <div className={`w-1 h-1 ${preset.color.replace("text-", "bg-")} opacity-60`} />
                            <span className="text-[10px] font-mono text-text-secondary">{detail}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Save Button */}
        <div className="flex items-center justify-end">
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-8 py-3 bg-prism-cream text-void font-bold text-xs uppercase tracking-widest hover:bg-white transition-all disabled:opacity-50"
          >
            {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {isSaving ? "CONFIGURING..." : "SAVE PARAMETERS"}
          </button>
        </div>

        {/* Authorization Section */}
        <div className="border border-red-500/20 bg-red-500/[0.03] p-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <LogOut size={16} className="text-red-500" />
              <h2 className="text-sm font-bold text-red-500 uppercase tracking-widest">
                Authorization Termination
              </h2>
            </div>
            <p className="text-xs text-text-secondary leading-relaxed">
              Revoke local node access and terminate your current operational session.
            </p>
          </div>
          <button
            onClick={() => signOut({ callbackUrl: "/" })}
            className="px-6 py-2.5 border border-red-500/30 text-red-500 text-[10px] font-bold uppercase tracking-[0.2em] hover:bg-red-500 hover:text-void transition-all duration-300"
          >
            Revoke Access
          </button>
        </div>

        {/* Security Notice */}
        <div className="border border-white/[0.08] bg-surface/10 p-5 flex gap-4 items-start">
          <AlertCircle className="h-5 w-5 text-prism-muted mt-0.5" />
          <div className="space-y-1">
            <h3 className="text-xs font-bold text-text-primary uppercase tracking-wider">
              Cryptographic Security
            </h3>
            <p className="text-xs text-text-secondary leading-relaxed">
              All credentials are encrypted and stored within the Argus secure perimeter.
              Intelligence keys are routed through hardened proxies to prevent exposure during analysis.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
