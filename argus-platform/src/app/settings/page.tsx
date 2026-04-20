"use client";

/**
 * Settings Page - API Key Configuration
 * 
 * Users can add their own API keys for:
 * - OpenAI API key (for GPT-powered analysis)
 * - OpenCode API key (for code analysis)
 */

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui/Toast";
import { motion } from "framer-motion";
import {
  Key,
  Eye,
  EyeOff,
  Save,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Bot,
  Code2,
} from "lucide-react";

interface Settings {
  openai_api_key?: string;
  opencode_api_key?: string;
}

export default function SettingsPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const { showToast } = useToast();
  
  const [settings, setSettings] = useState<Settings>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showOpenAIKey, setShowOpenAIKey] = useState(false);
  const [showOpenCodeKey, setShowOpenCodeKey] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Load settings on mount
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
    setSaveSuccess(false);

    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to save settings");
      }

      setSaveSuccess(true);
      showToast("success", "Settings saved successfully!");
      
      // Clear actual keys from display (show masked)
      if (settings.openai_api_key) {
        setSettings(prev => ({ ...prev, openai_api_key: "sk-" + "•".repeat(20) }));
      }
      if (settings.opencode_api_key) {
        setSettings(prev => ({ ...prev, opencode_api_key: "•".repeat(24) }));
      }
      
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (error) {
      showToast("error", error instanceof Error ? error.message : "Failed to save");
    } finally {
      setIsSaving(false);
    }
  };

  const updateSetting = (key: keyof Settings, value: string) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) {
    return null;
  }

  return (
    <div className="py-8 px-10">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-extrabold tracking-tight mb-2">
            Settings
          </h1>
          <p className="text-muted-foreground">
            Configure your API keys and preferences
          </p>
        </div>

        {/* API Keys Section */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="prism-glass rounded-3xl p-6"
        >
          <div className="flex items-center gap-3 mb-6">
            <Key className="h-5 w-5 text-primary" />
            <h2 className="text-xl font-bold">API Keys</h2>
          </div>

          <div className="space-y-6">
            {/* OpenAI API Key */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Bot className="h-4 w-4 text-muted-foreground" />
                <label className="text-sm font-medium">
                  OpenAI API Key
                </label>
              </div>
              <p className="text-xs text-muted-foreground">
                Required for GPT-powered vulnerability analysis and explanation.
                Get your key from{" "}
                <a
                  href="https://platform.openai.com/api-keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  platform.openai.com
                </a>
              </p>
              <div className="relative">
                <input
                  type={showOpenAIKey ? "text" : "password"}
                  value={settings.openai_api_key || ""}
                  onChange={(e) => updateSetting("openai_api_key", e.target.value)}
                  placeholder="sk-..."
                  className="w-full px-4 py-3 pr-12 bg-secondary/50 border border-border rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm font-mono"
                />
                <button
                  type="button"
                  onClick={() => setShowOpenAIKey(!showOpenAIKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showOpenAIKey ? (
                    <EyeOff className="h-5 w-5" />
                  ) : (
                    <Eye className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>

            {/* OpenCode API Key */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Code2 className="h-4 w-4 text-muted-foreground" />
                <label className="text-sm font-medium">
                  OpenCode API Key
                </label>
              </div>
              <p className="text-xs text-muted-foreground">
                Required for code analysis and repository scanning.
                Get your key from{" "}
                <a
                  href="https://opencode.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  opencode.ai
                </a>
              </p>
              <div className="relative">
                <input
                  type={showOpenCodeKey ? "text" : "password"}
                  value={settings.opencode_api_key || ""}
                  onChange={(e) => updateSetting("opencode_api_key", e.target.value)}
                  placeholder="ocg_..."
                  className="w-full px-4 py-3 pr-12 bg-secondary/50 border border-border rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm font-mono"
                />
                <button
                  type="button"
                  onClick={() => setShowOpenCodeKey(!showOpenCodeKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showOpenCodeKey ? (
                    <EyeOff className="h-5 w-5" />
                  ) : (
                    <Eye className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Save Button */}
          <div className="mt-8 flex items-center gap-4">
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-xl font-bold text-sm hover:shadow-[0_0_20px_rgba(59,130,246,0.5)] transition-all disabled:opacity-50"
            >
              {isSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : saveSuccess ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {isSaving ? "Saving..." : saveSuccess ? "Saved!" : "Save Settings"}
            </button>
            
            {saveSuccess && (
              <span className="text-sm text-green-400 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4" />
                Settings saved successfully
              </span>
            )}
          </div>
        </motion.div>

        {/* Info Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mt-6 prism-glass rounded-3xl p-6 border-amber-500/20"
        >
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-amber-400 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-bold text-amber-400 mb-1">Security Notice</h3>
              <p className="text-sm text-muted-foreground">
                API keys are stored securely in the database. They are never exposed 
                in logs or error messages. Your keys are encrypted at rest and used 
                only when necessary for scanning and analysis.
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}