"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronRight,
  ChevronLeft,
  Sparkles,
  LayoutDashboard,
  ShieldCheck,
  Bug,
  Settings,
  Brain,
  Target,
  Activity,
  GitBranch,
  FileCheck,
  Zap,
  Globe,
  LineChart,
  AlertTriangle,
  Terminal,
  Cpu,
  Search,
  Wand2,
  Server,
} from "lucide-react";
import { Button } from "@/components/ui/button";

export const STORAGE_KEY = "argus:onboarding-completed";

interface TourStep {
  id: string;
  title: string;
  description: string;
  targetSelector?: string;
  icon?: React.ReactNode;
}

const STEPS: TourStep[] = [
  {
    id: "welcome",
    title: "Welcome to Argus",
    description:
      "Your AI-powered autonomous penetration testing platform. Argus automates reconnaissance, vulnerability scanning, and AI-driven analysis for comprehensive security assessments.",
    icon: <Sparkles size={20} />,
  },
  {
    id: "ai-features",
    title: "AI-Powered Analysis",
    description:
      "Argus integrates with Artificial Intelligence to provide intelligent vulnerability explanations, attack path analysis, and contextual security insights. Configure your preferred AI model in settings for customized analysis depth.",
    icon: <Brain size={20} />,
  },
  {
    id: "ai-response-analysis",
    title: "AI Response Analysis",
    description:
      "After scanning, Argus automatically reviews low-confidence HTTP responses using AI to detect subtle vulnerabilities that regex patterns miss — including reflected payloads in JSON, partial SSTI evaluation, and WAF-bypass vectors.",
    icon: <Search size={20} />,
  },
  {
    id: "ai-payload-generation",
    title: "AI Payload Generation",
    description:
      "During scanning, Argus generates context-aware probe payloads using AI. Payloads are tailored to each parameter's reflection context (HTML, script, JSON, attribute), framework, and input type — catching what static lists miss.",
    icon: <Wand2 size={20} />,
  },
  {
    id: "scan-types",
    title: "Scan Types & Modes",
    description:
      "Choose between URL scanning for web applications or Repository scanning for source code analysis. Adjust scan aggressiveness (Default, High, Aggressive) based on your target environment and testing requirements.",
    icon: <Target size={20} />,
  },
  {
    id: "engagements",
    title: "Engagements & Live Monitoring",
    description:
      "Each security assessment is an 'engagement' with a unique ID. Track real-time progress through the engagement dashboard with live WebSocket updates, scanner activities, and state transitions.",
    icon: <Activity size={20} />,
  },
  {
    id: "recon",
    title: "Automated Reconnaissance",
    description:
      "Argus automatically performs subdomain enumeration, port scanning, service detection, and technology fingerprinting. All recon data feeds into the vulnerability discovery engine.",
    icon: <Globe size={20} />,
  },
  {
    id: "scanning",
    title: "Vulnerability Scanning",
    description:
      "Multi-engine scanning with customizable tool selection. Integrates industry-standard tools with coordinated execution. Real-time findings appear as they're discovered.",
    icon: <Zap size={20} />,
  },
  {
    id: "findings",
    title: "Findings & Risk Analysis",
    description:
      "Review discovered vulnerabilities with CVSS scores, CWE classifications, severity ratings (Critical/High/Medium/Low), and detailed evidence including request/response data and remediation guidance.",
    targetSelector: '[data-tour="findings"]',
    icon: <AlertTriangle size={20} />,
  },
  {
    id: "asset-inventory",
    title: "Asset Inventory",
    description:
      "View and manage your organization's discovered assets including domains, IP addresses, endpoints, repositories, containers, APIs, and cloud resources. Filter by type, risk level, and lifecycle status. Assets are automatically discovered during scans and can also be added manually.",
    icon: <Server size={20} />,
  },
  {
    id: "attack-paths",
    title: "Attack Path Graphs",
    description:
      "Visualize how vulnerabilities chain together into attack vectors. The graph shows entry points, pivot opportunities, and critical paths to high-value targets for comprehensive risk assessment.",
    icon: <LineChart size={20} />,
  },
  {
    id: "repo-scanning",
    title: "Repository Analysis",
    description:
      "Scan GitHub/GitLab repositories for secrets, vulnerable dependencies, misconfigurations, and code-level security issues. Ideal for DevSecOps and supply chain security assessment.",
    icon: <GitBranch size={20} />,
  },
  {
    id: "compliance",
    title: "Compliance Reporting",
    description:
      "Generate compliance reports for standards like OWASP Top 10, PCI-DSS, HIPAA, and SOC 2. Map findings to specific control requirements with evidence documentation.",
    icon: <FileCheck size={20} />,
  },
  {
    id: "execution-timeline",
    title: "Execution Timeline",
    description:
      "Review the complete scan execution history with per-tool timing, output logs, and performance metrics. Debug failed operations and optimize scan efficiency.",
    icon: <Terminal size={20} />,
  },
  {
    id: "performance",
    title: "Performance Metrics",
    description:
      "Track tool performance statistics including execution time, findings-per-minute, coverage ratios, and historical trends to optimize your security testing workflow.",
    icon: <Cpu size={20} />,
  },
  {
    id: "settings",
    title: "Configuration & Customization",
    description:
      "Configure AI models (OpenRouter integration), API keys, scan aggressiveness, dark/light themes, and notification preferences. All settings sync across sessions.",
    targetSelector: '[data-tour="settings"]',
    icon: <Settings size={20} />,
  },
];

export function useOnboarding(pathname?: string) {
  const [isCompleted, setIsCompleted] = useState<boolean>(true);
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const completed = window.localStorage.getItem(STORAGE_KEY) === "true";
    setIsCompleted(completed);
    if (!completed && pathname === "/dashboard") {
      setIsOpen(true);
    }
  }, [pathname]);

  const startTour = useCallback(() => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
    }
    setIsCompleted(false);
    setIsOpen(true);
  }, []);

  const completeTour = useCallback(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, "true");
    }
    setIsCompleted(true);
    setIsOpen(false);
  }, []);

  const skipTour = useCallback(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, "true");
    }
    setIsCompleted(true);
    setIsOpen(false);
  }, []);

  return {
    isCompleted,
    isOpen,
    setIsOpen,
    startTour,
    completeTour,
    skipTour,
  };
}

function getElementRect(selector: string): DOMRect | null {
  if (typeof document === "undefined") return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  return el.getBoundingClientRect();
}

export default function OnboardingTour() {
  const pathname = usePathname();
  const { isOpen, setIsOpen, completeTour, skipTour } = useOnboarding(pathname);
  const [currentStep, setCurrentStep] = useState(0);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [showAllSteps, setShowAllSteps] = useState(false);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const step = STEPS[currentStep];
  const totalSteps = STEPS.length;

  // Listen for external restart events from settings
  useEffect(() => {
    const handleRestart = () => {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(STORAGE_KEY);
      }
      setCurrentStep(0);
      setShowAllSteps(true); // Show all steps overview when restarted
      setIsOpen(true);
    };
    window.addEventListener("argus:restart-onboarding", handleRestart);
    return () =>
      window.removeEventListener("argus:restart-onboarding", handleRestart);
  }, [setIsOpen]);

  // Listen for dashboard redirect with restart flag (from Settings page)
  useEffect(() => {
    if (pathname === "/dashboard") {
      const pending = window.localStorage.getItem("argus:restart-onboarding-pending");
      if (pending === "true") {
        window.localStorage.removeItem("argus:restart-onboarding-pending");
        window.localStorage.removeItem(STORAGE_KEY);
        setCurrentStep(0);
        setShowAllSteps(true);
        setIsOpen(true);
      }
    }
  }, [pathname, setIsOpen]);

  // Position tooltip and spotlight
  useEffect(() => {
    if (!isOpen) return;

    const updatePosition = () => {
      if (step.targetSelector) {
        const rect = getElementRect(step.targetSelector);
        if (rect) {
          setTargetRect(rect);
          const tooltipEl = tooltipRef.current;
          const tooltipWidth = tooltipEl?.offsetWidth || 360;
          const tooltipHeight = tooltipEl?.offsetHeight || 220;
          const padding = 20;
          const gap = 16;

          let x = rect.left + rect.width / 2 - tooltipWidth / 2;
          let y = rect.bottom + gap;

          // Keep within viewport horizontally
          if (x < padding) x = padding;
          if (x + tooltipWidth > window.innerWidth - padding) {
            x = window.innerWidth - tooltipWidth - padding;
          }

          // If tooltip goes below viewport, place it above the target
          if (y + tooltipHeight > window.innerHeight - padding) {
            y = rect.top - tooltipHeight - gap;
          }

          // If still out of bounds, center vertically
          if (y < padding) {
            y = window.innerHeight / 2 - tooltipHeight / 2;
          }

          setTooltipPos({ x, y });
          return;
        }
      }

      // Center if no target
      const tooltipWidth = tooltipRef.current?.offsetWidth || 360;
      const tooltipHeight = tooltipRef.current?.offsetHeight || 220;
      setTooltipPos({
        x: Math.max(20, window.innerWidth / 2 - tooltipWidth / 2),
        y: Math.max(20, window.innerHeight / 2 - tooltipHeight / 2),
      });
      setTargetRect(null);
    };

    const timer = setTimeout(updatePosition, 50);
    window.addEventListener("resize", updatePosition);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", updatePosition);
    };
  }, [isOpen, currentStep, step]);

  const handleNext = () => {
    if (showAllSteps) {
      setShowAllSteps(false);
      setCurrentStep(0);
      return;
    }
    if (currentStep < totalSteps - 1) {
      setCurrentStep((prev) => prev + 1);
    } else {
      completeTour();
    }
  };

  const startStepByIndex = (index: number) => {
    setShowAllSteps(false);
    setCurrentStep(index);
  };

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep((prev) => prev - 1);
    }
  };

  const handleSkip = () => {
    skipTour();
  };

  const handleDone = () => {
    completeTour();
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          key="onboarding-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] overflow-auto"
          data-testid="onboarding-tour"
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/60" aria-hidden="true" />

          {/* Spotlight */}
          {targetRect && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3 }}
              className="absolute pointer-events-none"
              style={{
                top: targetRect.top - 8,
                left: targetRect.left - 8,
                width: targetRect.width + 16,
                height: targetRect.height + 16,
                borderRadius: 12,
                boxShadow: "0 0 0 9999px rgba(0, 0, 0, 0.6)",
                border: "2px solid #6720FF",
              }}
              data-testid="tour-spotlight"
            />
          )}

          {/* All Steps Overview or Single Step Tooltip */}
          {showAllSteps ? (
            /* All Steps Overview Grid */
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3 }}
              className="relative z-10 min-h-screen flex items-center justify-center p-6"
            >
              <div className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-2xl p-6 sm:p-8 shadow-2xl w-full max-w-2xl">
                {/* Header */}
                <div className="flex items-center gap-3 mb-2">
                  <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                    <Sparkles size={20} />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold text-on-surface dark:text-[#F0F0F5] uppercase tracking-wider font-headline">
                      Complete Tour
                    </h2>
                    <p className="text-xs text-on-surface-variant dark:text-[#8A8A9E]">
                      All {totalSteps} steps to get you started
                    </p>
                  </div>
                </div>

                {/* Steps Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 my-6">
                  {STEPS.map((s, i) => (
                    <button
                      key={s.id}
                      onClick={() => startStepByIndex(i)}
                      className={`text-left p-4 rounded-xl border transition-all duration-200 hover:scale-[1.02] ${
                        i === 0
                          ? "border-primary/50 bg-primary/5"
                          : "border-outline-variant dark:border-[#ffffff10] hover:border-primary/30"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                          {s.icon}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-mono text-primary">Step {i + 1}</span>
                          </div>
                          <h4 className="text-sm font-bold text-on-surface dark:text-[#F0F0F5] mt-0.5">
                            {s.title}
                          </h4>
                          <p className="text-xs text-on-surface-variant dark:text-[#8A8A9E] mt-1 line-clamp-2">
                            {s.description}
                          </p>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>

                {/* Actions */}
                <div className="flex items-center justify-between pt-4 border-t border-outline-variant dark:border-[#ffffff10]">
                  <button
                    onClick={handleSkip}
                    className="text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider hover:text-primary transition-colors"
                  >
                    Skip Tour
                  </button>
                  <Button
                    size="sm"
                    onClick={() => startStepByIndex(0)}
                    className="h-9 text-xs bg-primary text-on-primary hover:bg-primary/90 px-4"
                  >
                    Start Interactive Tour
                    <ChevronRight size={14} />
                  </Button>
                </div>
              </div>
            </motion.div>
          ) : (
            /* Single Step Tooltip */
            <motion.div
              ref={tooltipRef}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ duration: 0.25, delay: 0.1 }}
              className="absolute bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-5 shadow-2xl w-[340px] sm:w-[400px]"
              style={{
                left: tooltipPos.x,
                top: tooltipPos.y,
              }}
              data-testid="tour-tooltip"
            >
              {/* Header */}
              <div className="flex items-center gap-3 mb-3">
                {step.icon && (
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                    {step.icon}
                  </div>
                )}
                <h3 className="text-sm font-bold text-on-surface dark:text-[#F0F0F5] uppercase tracking-wider font-headline">
                  {step.title}
                </h3>
              </div>

              {/* Description */}
              <p className="text-sm text-on-surface-variant dark:text-[#8A8A9E] leading-relaxed mb-5">
                {step.description}
              </p>

              {/* Step Counter */}
              <div className="flex items-center justify-between mb-4">
                <span
                  className="text-[11px] font-mono text-on-surface-variant dark:text-[#8A8A9E]"
                  data-testid="step-counter"
                >
                  {currentStep + 1} of {totalSteps}
                </span>
                <div className="flex gap-1.5">
                  {STEPS.map((_, i) => (
                    <button
                      key={i}
                      onClick={() => setCurrentStep(i)}
                      className={`w-2 h-2 rounded-full transition-colors duration-300 hover:scale-125 ${
                        i === currentStep
                          ? "bg-primary"
                          : "bg-on-surface-variant/20 dark:bg-[#8A8A9E]/20 hover:bg-primary/50"
                      }`}
                      data-testid={`step-dot-${i}`}
                    />
                  ))}
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center justify-between">
                <button
                  onClick={handleSkip}
                  className="text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider hover:text-primary transition-colors"
                  data-testid="skip-tour-btn"
                >
                  Skip Tour
                </button>
                <div className="flex items-center gap-2">
                  {currentStep > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handlePrev}
                      className="h-8 text-xs"
                      data-testid="prev-step-btn"
                    >
                      <ChevronLeft size={14} />
                      Back
                    </Button>
                  )}
                  {currentStep < totalSteps - 1 ? (
                    <Button
                      size="sm"
                      onClick={handleNext}
                      className="h-8 text-xs bg-primary text-on-primary hover:bg-primary/90"
                      data-testid="next-step-btn"
                    >
                      Next
                      <ChevronRight size={14} />
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      onClick={handleDone}
                      className="h-8 text-xs bg-primary text-on-primary hover:bg-primary/90"
                      data-testid="done-btn"
                    >
                      Done
                    </Button>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
