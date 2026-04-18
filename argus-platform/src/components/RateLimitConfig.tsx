"use client";

/**
 * Rate Limit Configuration Component
 * 
 * Allows users to configure rate limiting settings before starting an engagement.
 * 
 * Requirements: 29.4
 */

import { useState } from "react";

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
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-white">Rate Limiting</h3>
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          {showAdvanced ? "Hide" : "Show"} Advanced Settings
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Requests Per Second */}
        <div>
          <label htmlFor="rps" className="block text-sm font-medium text-slate-300 mb-2">
            Requests Per Second
            <span className="text-slate-500 ml-2">(1-20)</span>
          </label>
          <input
            id="rps"
            type="number"
            min="1"
            max="20"
            step="0.5"
            value={value.requests_per_second}
            onChange={(e) => handleChange("requests_per_second", parseFloat(e.target.value))}
            className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="mt-1 text-xs text-slate-400">
            Maximum requests per second to target. Lower values are safer.
          </p>
        </div>

        {/* Concurrent Requests */}
        <div>
          <label htmlFor="concurrent" className="block text-sm font-medium text-slate-300 mb-2">
            Concurrent Requests
            <span className="text-slate-500 ml-2">(1-5)</span>
          </label>
          <input
            id="concurrent"
            type="number"
            min="1"
            max="5"
            step="1"
            value={value.concurrent_requests}
            onChange={(e) => handleChange("concurrent_requests", parseInt(e.target.value))}
            className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="mt-1 text-xs text-slate-400">
            Maximum simultaneous requests. Lower values reduce target load.
          </p>
        </div>
      </div>

      {showAdvanced && (
        <div className="space-y-4 pt-4 border-t border-slate-700">
          {/* Respect robots.txt */}
          <div className="flex items-start gap-3">
            <input
              id="robots"
              type="checkbox"
              checked={value.respect_robots_txt}
              onChange={(e) => handleChange("respect_robots_txt", e.target.checked)}
              className="mt-1 w-4 h-4 bg-slate-700 border-slate-600 rounded focus:ring-2 focus:ring-blue-500"
            />
            <div className="flex-1">
              <label htmlFor="robots" className="block text-sm font-medium text-slate-300">
                Respect robots.txt
              </label>
              <p className="mt-1 text-xs text-slate-400">
                Honor Crawl-delay directive from target&apos;s robots.txt file.
              </p>
            </div>
          </div>

          {/* Adaptive Slowdown */}
          <div className="flex items-start gap-3">
            <input
              id="adaptive"
              type="checkbox"
              checked={value.adaptive_slowdown}
              onChange={(e) => handleChange("adaptive_slowdown", e.target.checked)}
              className="mt-1 w-4 h-4 bg-slate-700 border-slate-600 rounded focus:ring-2 focus:ring-blue-500"
            />
            <div className="flex-1">
              <label htmlFor="adaptive" className="block text-sm font-medium text-slate-300">
                Adaptive Slowdown
              </label>
              <p className="mt-1 text-xs text-slate-400">
                Automatically reduce rate when target shows signs of stress (429, 503 responses).
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Preset Buttons */}
      <div className="flex gap-2 pt-2">
        <button
          type="button"
          onClick={() => onChange({ ...DEFAULT_CONFIG })}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors"
        >
          Default (Safe)
        </button>
        <button
          type="button"
          onClick={() =>
            onChange({
              requests_per_second: 10,
              concurrent_requests: 3,
              respect_robots_txt: true,
              adaptive_slowdown: true,
            })
          }
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors"
        >
          Moderate
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
          className="px-3 py-1.5 text-sm bg-orange-700 hover:bg-orange-600 rounded text-white transition-colors"
        >
          Aggressive (Risky)
        </button>
      </div>
    </div>
  );
}

export { DEFAULT_CONFIG };
