"use client";

import { useState, useEffect } from "react";

interface ThemeColors {
  primary: string;
  background: string;
  surface: string;
  text: string;
  border: string;
  success: string;
  error: string;
  warning: string;
  info: string;
}

export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState<ThemeColors>({
    primary: "#6720FF",
    background: "#ffffff",
    surface: "#f5f5f5",
    text: "#171717",
    border: "#e5e5e5",
    success: "#10B981",
    error: "#EF4444",
    warning: "#F59E0B",
    info: "#3B82F6",
  });

  useEffect(() => {
    const updateColors = () => {
      const style = getComputedStyle(document.documentElement);
      
      setColors({
        primary: style.getPropertyValue("--color-primary").trim() || "#6720FF",
        background: style.getPropertyValue("--color-background").trim() || "#ffffff",
        surface: style.getPropertyValue("--color-surface").trim() || "#f5f5f5",
        text: style.getPropertyValue("--color-text").trim() || "#171717",
        border: style.getPropertyValue("--color-border").trim() || "#e5e5e5",
        success: style.getPropertyValue("--color-success").trim() || "#10B981",
        error: style.getPropertyValue("--color-error").trim() || "#EF4444",
        warning: style.getPropertyValue("--color-warning").trim() || "#F59E0B",
        info: style.getPropertyValue("--color-info").trim() || "#3B82F6",
      });
    };

    updateColors();

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.attributeName === "class") {
          updateColors();
        }
      }
    });

    observer.observe(document.documentElement, { attributes: true });

    return () => observer.disconnect();
  }, []);

  return colors;
}


