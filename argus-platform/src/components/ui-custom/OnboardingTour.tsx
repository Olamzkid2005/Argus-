"use client";

export default function OnboardingTour() {
  return null;
}

export function useOnboarding() {
  return {
    startTour: () => {},
    isOpen: false,
  };
}

export const STORAGE_KEY = "argus:onboarding-completed";
