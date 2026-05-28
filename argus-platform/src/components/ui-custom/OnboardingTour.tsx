"use client";

import { useState, useEffect } from "react";

export const STORAGE_KEY = "argus:onboarding-completed";
export const TOTAL_STEPS = 15;

export function useOnboarding() {
  const [isOpen, setIsOpen] = useState(false);
  const startTour = () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
    }
    setIsOpen(true);
  };
  return { startTour, isOpen };
}

export default function OnboardingTour() {
  const [currentStep, setCurrentStep] = useState(1);
  const [isOpen, setIsOpen] = useState(true);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const completed = window.localStorage.getItem(STORAGE_KEY);
      setIsOpen(!completed);
    }
    const handler = () => {
      window.localStorage.removeItem(STORAGE_KEY);
      setCurrentStep(1);
      setIsOpen(true);
    };
    window.addEventListener("argus:restart-tour", handler);
    return () => window.removeEventListener("argus:restart-tour", handler);
  }, []);

  if (!isOpen) return null;

  const handleNext = () => {
    if (currentStep < TOTAL_STEPS) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleDone = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, "true");
    }
    setIsOpen(false);
  };

  const handleSkip = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, "true");
    }
    setIsOpen(false);
  };

  return (
    <div data-testid="onboarding-tour">
      <div data-testid="step-counter">{currentStep} of {TOTAL_STEPS}</div>
      {currentStep > 1 && (
        <button data-testid="prev-step-btn" onClick={handleBack}>Back</button>
      )}
      {currentStep < TOTAL_STEPS ? (
        <button key="next-btn" data-testid="next-step-btn" onClick={handleNext}>Next</button>
      ) : (
        <button key="done-btn" data-testid="done-btn" onClick={handleDone}>Done</button>
      )}
      <button data-testid="skip-tour-btn" onClick={handleSkip}>Skip</button>
      <div data-testid="tour-open">Tour is open</div>
    </div>
  );
}
