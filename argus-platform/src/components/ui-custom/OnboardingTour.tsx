"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronRight,
  ChevronLeft,
  Sparkles,
  LayoutDashboard,
  ShieldCheck,
  Bug,
  Settings,
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
      "Your AI-powered autonomous penetration testing platform. Let's take a quick tour of the key features.",
    icon: <Sparkles size={20} />,
  },
  {
    id: "dashboard",
    title: "Dashboard",
    description:
      "The Main Intelligence Hub provides real-time security monitoring, threat intelligence, and operational command over all your engagements.",
    targetSelector: '[data-tour="dashboard"]',
    icon: <LayoutDashboard size={20} />,
  },
  {
    id: "new-scan",
    title: "New Scan",
    description:
      "Start a new engagement by connecting an engagement ID. Monitor live reconnaissance, scanning, and analysis in real-time.",
    targetSelector: '[data-tour="new-scan"]',
    icon: <ShieldCheck size={20} />,
  },
  {
    id: "findings",
    title: "Findings",
    description:
      "Review discovered vulnerabilities with severity ratings, CVSS scores, and detailed endpoint information from your security scans.",
    targetSelector: '[data-tour="findings"]',
    icon: <Bug size={20} />,
  },
  {
    id: "settings",
    title: "Settings",
    description:
      "Configure AI models, scan aggressiveness, dark mode, and other operational parameters to match your workflow.",
    targetSelector: '[data-tour="settings"]',
    icon: <Settings size={20} />,
  },
];

export function useOnboarding() {
  const [isCompleted, setIsCompleted] = useState<boolean>(true);
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const completed = window.localStorage.getItem(STORAGE_KEY) === "true";
    setIsCompleted(completed);
    if (!completed) {
      setIsOpen(true);
    }
  }, []);

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
  const { isOpen, setIsOpen, completeTour, skipTour } = useOnboarding();
  const [currentStep, setCurrentStep] = useState(0);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
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
      setIsOpen(true);
    };
    window.addEventListener("argus:restart-onboarding", handleRestart);
    return () =>
      window.removeEventListener("argus:restart-onboarding", handleRestart);
  }, [setIsOpen]);

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
    if (currentStep < totalSteps - 1) {
      setCurrentStep((prev) => prev + 1);
    } else {
      completeTour();
    }
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
          className="fixed inset-0 z-[100]"
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

          {/* Tooltip Card */}
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
                  <div
                    key={i}
                    className={`w-2 h-2 rounded-full transition-colors duration-300 ${
                      i === currentStep
                        ? "bg-primary"
                        : "bg-on-surface-variant/20 dark:bg-[#8A8A9E]/20"
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
        </motion.div>
      )}
    </AnimatePresence>
  );
}
