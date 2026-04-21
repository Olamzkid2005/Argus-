"use client";

import { useState, useEffect } from "react";
import { X, Target, Zap, Bomb, Info } from "lucide-react";

interface ScanModeHelpProps {
  trigger?: "icon" | "button";
}

const MODES = [
  {
    icon: <Target size={18} />,
    name: "Default",
    color: "text-prism-cyan",
    border: "border-prism-cyan/30",
    bg: "bg-prism-cyan/5",
    time: "~2-5 min",
    description: "Balanced coverage for typical assessments. Fast enough for CI/CD pipelines.",
    tools: [
      { tool: "Katana", detail: "Crawl depth 3" },
      { tool: "Amass", detail: "Passive enumeration only" },
      { tool: "Naabu", detail: "Top 1000 ports" },
      { tool: "Ffuf", detail: "Common wordlist" },
      { tool: "Nuclei", detail: "Standard templates" },
      { tool: "Dalfox", detail: "Basic XSS checks" },
      { tool: "SQLMap", detail: "Default level/risk" },
    ],
  },
  {
    icon: <Zap size={18} />,
    name: "High",
    color: "text-orange-400",
    border: "border-orange-400/30",
    bg: "bg-orange-400/5",
    time: "~10-20 min",
    description: "Deeper reconnaissance. Discovers more attack surface but takes longer.",
    tools: [
      { tool: "Katana", detail: "Crawl depth 5" },
      { tool: "Amass", detail: "Active + passive sources" },
      { tool: "Naabu", detail: "Top 10,000 ports" },
      { tool: "Ffuf", detail: "Extended wordlist, 50 threads" },
      { tool: "Nuclei", detail: "Low+ severity templates" },
      { tool: "Dalfox", detail: "Blind XSS detection" },
      { tool: "SQLMap", detail: "Level 3, Risk 2" },
    ],
  },
  {
    icon: <Bomb size={18} />,
    name: "Extreme",
    color: "text-red-400",
    border: "border-red-400/30",
    bg: "bg-red-400/5",
    time: "~30-60+ min",
    description: "Exhaustive coverage. Full port scans, brute force, and deep analysis. Use sparingly.",
    tools: [
      { tool: "Katana", detail: "Crawl depth 7+" },
      { tool: "Amass", detail: "Brute force + all sources" },
      { tool: "Naabu", detail: "Full range 1-65535" },
      { tool: "Ffuf", detail: "Comprehensive wordlist, 100 threads" },
      { tool: "Nuclei", detail: "All templates + fuzzing tags" },
      { tool: "Dalfox", detail: "Deep DOM analysis" },
      { tool: "SQLMap", detail: "Level 5, Risk 3, --all" },
    ],
  },
];

export default function ScanModeHelp({ trigger = "icon" }: ScanModeHelpProps) {
  const [open, setOpen] = useState(false);
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (open) {
      // Small delay to let React render the DOM before starting animation
      const t = setTimeout(() => setShow(true), 10);
      return () => clearTimeout(t);
    }
    setShow(false);
  }, [open]);

  const handleClose = () => {
    setShow(false);
    setTimeout(() => setOpen(false), 200);
  };

  const handleOpen = () => {
    setOpen(true);
  };

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      {trigger === "icon" ? (
        <button
          onClick={handleOpen}
          className="text-text-secondary/40 hover:text-prism-cyan transition-colors"
          title="Scan mode reference"
        >
          <Info size={14} />
        </button>
      ) : (
        <button
          onClick={handleOpen}
          className="text-[10px] font-mono text-prism-cyan/60 hover:text-prism-cyan underline transition-colors"
        >
          What do these mean?
        </button>
      )}

      {open && (
        <div className="fixed inset-0 z-[100]">
          {/* Backdrop */}
          <div
            className={`absolute inset-0 bg-black/80 transition-opacity duration-200 ${
              show ? "opacity-100" : "opacity-0"
            }`}
            onClick={handleClose}
          />

          {/* Modal — centered */}
          <div className="absolute inset-0 flex items-center justify-center p-4 pointer-events-none">
            <div
              className={`pointer-events-auto w-full max-w-2xl max-h-[85vh] flex flex-col border border-structural bg-surface shadow-2xl transition-all duration-200 ease-out ${
                show ? "opacity-100 scale-100 translate-y-0" : "opacity-0 scale-95 translate-y-4"
              }`}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-structural shrink-0">
                <div className="flex items-center gap-2">
                  <Target size={16} className="text-prism-cyan" />
                  <h2 className="text-sm font-bold text-text-primary uppercase tracking-widest">
                    Scan Mode Reference
                  </h2>
                </div>
                <button
                  onClick={handleClose}
                  className="p-1 text-text-secondary hover:text-text-primary transition-colors"
                >
                  <X size={16} />
                </button>
              </div>

              {/* Scrollable Body */}
              <div className="p-6 space-y-6 overflow-y-auto">
                <p className="text-xs text-text-secondary leading-relaxed">
                  Choose how deep the scanners probe your target. Higher modes find more vulnerabilities
                  but take significantly longer and generate more traffic.
                </p>

                {MODES.map((mode) => (
                  <div key={mode.name} className={`border ${mode.border} ${mode.bg}`}>
                    <div className={`flex items-center gap-3 px-4 py-3 border-b ${mode.border}`}>
                      <span className={mode.color}>{mode.icon}</span>
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <span className={`text-sm font-bold ${mode.color}`}>{mode.name}</span>
                          <span className="text-[10px] font-mono text-text-secondary/60 uppercase tracking-wider">
                            {mode.time}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="px-4 py-3">
                      <p className="text-xs text-text-secondary mb-3">{mode.description}</p>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                        {mode.tools.map((t) => (
                          <div key={t.tool} className="flex items-center justify-between">
                            <span className="text-[11px] font-mono text-text-secondary">{t.tool}</span>
                            <span className="text-[10px] font-mono text-text-primary/70">{t.detail}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}

                <div className="border border-structural/50 bg-surface/30 px-4 py-3">
                  <p className="text-[10px] font-mono text-text-secondary/60 uppercase tracking-wider">
                    Tip: Start with Default. Use High for critical assets. Reserve Extreme for
                    pre-production deep audits.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
