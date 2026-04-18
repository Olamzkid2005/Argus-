"use client";

/**
 * Rate Limit Configuration Component
 * 
 * Allows users to configure rate limiting settings before starting an engagement.
 * 
 * Requirements: 29.4
 */

import { useState } from "react";
import { Settings2, Zap, ShieldCheck, AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";

export interface RateLimitConfigData {
  requests_per_second: number;
  concurrent_requests: number;
  respect_robots_txt: boolean;
  adaptive_slowdown: boolean;
}

interface RateLimitConfigProps {
  value: RateLimitConfigData;
  onChange: (config: RateLimitConfigData) => void;
}

const DEFAULT_CONFIG: RateLimitConfigData = {
  requests_per_second: 5,
  concurrent_requests: 2,
  respect_robots_txt: true,
  adaptive_slowdown: true,
};

export default function RateLimitConfig({ value, onChange }: RateLimitConfigProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleChange = (field: keyof RateLimitConfigData, newValue: number | boolean) => {
    onChange({
      ...value,
      [field]: newValue,
    });
  };

  return (
    <div className="prism-glass p-6 rounded-3xl space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center border border-primary/20">
            <Zap className="h-4 w-4 text-primary" />
          </div>
          <h3 className="text-sm font-black uppercase tracking-widest">Rate Control</h3>
        </div>
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors"
        >
          {showAdvanced ? "Basic View" : "Advanced Logic"}
          {showAdvanced ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Requests Per Second */}
        <div className="space-y-4">
          <div className="flex justify-between items-end">
            <label htmlFor="rps" className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">
              Request Velocity
            </label>
            <span className="text-xs font-mono font-bold text-primary">{value.requests_per_second} RPS</span>
          </div>
          <input
            id="rps"
            type="range"
            min="1"
            max="20"
            step="0.5"
            value={value.requests_per_second}
            onChange={(e) => handleChange("requests_per_second", parseFloat(e.target.value))}
            className="w-full h-1.5 bg-secondary rounded-lg appearance-none cursor-pointer accent-primary"
          />
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            Max requests per second targeting the infrastructure.
          </p>
        </div>

        {/* Concurrent Requests */}
        <div className="space-y-4">
          <div className="flex justify-between items-end">
            <label htmlFor="concurrent" className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">
              Concurrency
            </label>
            <span className="text-xs font-mono font-bold text-argus-cyan">{value.concurrent_requests} Spans</span>
          </div>
          <input
            id="concurrent"
            type="range"
            min="1"
            max="5"
            step="1"
            value={value.concurrent_requests}
            onChange={(e) => handleChange("concurrent_requests", parseInt(e.target.value))}
            className="w-full h-1.5 bg-secondary rounded-lg appearance-none cursor-pointer accent-argus-cyan"
          />
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            Maximum simultaneous request workers.
          </p>
        </div>
      </div>

      {showAdvanced && (
        <div className="space-y-4 pt-6 border-t border-border mt-2">
          {/* Respect robots.txt */}
          <div className="flex items-start gap-4 p-4 rounded-2xl bg-white/5 border border-transparent hover:border-primary/10 transition-colors">
            <input
              id="robots"
              type="checkbox"
              checked={value.respect_robots_txt}
              onChange={(e) => handleChange("respect_robots_txt", e.target.checked)}
              className="mt-1 h-4 w-4 bg-secondary border-border rounded accent-primary text-primary"
            />
            <div className="flex-1">
              <label htmlFor="robots" className="block text-xs font-bold uppercase tracking-tight">
                Respect Robots Protocol
              </label>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Honors target&apos;s Crawl-delay and Disallow directives.
              </p>
            </div>
          </div>

          {/* Adaptive Slowdown */}
          <div className="flex items-start gap-4 p-4 rounded-2xl bg-white/5 border border-transparent hover:border-primary/10 transition-colors">
            <input
              id="adaptive"
              type="checkbox"
              checked={value.adaptive_slowdown}
              onChange={(e) => handleChange("adaptive_slowdown", e.target.checked)}
              className="mt-1 h-4 w-4 bg-secondary border-border rounded accent-primary text-primary"
            />
            <div className="flex-1">
              <label htmlFor="adaptive" className="block text-xs font-bold uppercase tracking-tight">
                Intelligent Backoff
              </label>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Automatic rate reduction upon target stress signals (429/503).
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Preset Buttons */}
      <div className="flex gap-3 pt-4 border-t border-border">
        <button
          type="button"
          onClick={() => onChange({ ...DEFAULT_CONFIG })}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-3 rounded-xl bg-white/5 text-[10px] font-black uppercase tracking-widest text-muted-foreground hover:bg-white/10 hover:text-foreground transition-all border border-transparent"
        >
          <ShieldCheck className="h-3 w-3" />
          Stealth
        </button>
        <button
          type="button"
          onClick={() =>
            onChange({
              requests_per_second: 12,
              concurrent_requests: 3,
              respect_robots_txt: true,
              adaptive_slowdown: true,
            })
          }
          className="flex-1 flex items-center justify-center gap-2 px-3 py-3 rounded-xl bg-primary/10 text-[10px] font-black uppercase tracking-widest text-primary hover:bg-primary/20 transition-all border border-primary/10"
        >
          <Settings2 className="h-3 w-3" />
          Balanced
        </button>
        <button
          type="button"
          onClick={() =>
            onChange({
              requests_per_second: 20,
              concurrent_requests: 5,
              respect_robots_txt: false,
              adaptive_slowdown: false,
            })
          }
          className="flex-1 flex items-center justify-center gap-2 px-3 py-3 rounded-xl bg-argus-magenta/10 text-[10px] font-black uppercase tracking-widest text-argus-magenta hover:bg-argus-magenta/20 transition-all border border-argus-magenta/10"
        >
          <AlertTriangle className="h-3 w-3" />
          Aggressive
        </button>
      </div>
    </div>
  );
}

export { DEFAULT_CONFIG };
