"use client";

import { useState, useCallback } from "react";
import { motion } from "framer-motion";

export interface ScanTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  settings: {
    aggressiveness: string;
    tools: string[];
    timeout: number;
  };
}

export const SCAN_TEMPLATES: ScanTemplate[] = [
  {
    id: "quick",
    name: "Quick Scan",
    description: "Fast scan with basic checks",
    icon: "⚡",
    settings: { aggressiveness: "default", tools: ["basics"], timeout: 300 },
  },
  {
    id: "full",
    name: "Full Scan",
    description: "Comprehensive security audit",
    icon: "🔍",
    settings: { aggressiveness: "high", tools: ["all"], timeout: 1800 },
  },
  {
    id: "compliance",
    name: "Compliance Check",
    description: "OWASP Top 10, PCI-DSS, HIPAA",
    icon: "📋",
    settings: { aggressiveness: "default", tools: ["compliance"], timeout: 600 },
  },
  {
    id: "api",
    name: "API Security",
    description: "REST/GraphQL endpoint testing",
    icon: "🔌",
    settings: { aggressiveness: "default", tools: ["api"], timeout: 600 },
  },
];

interface ScanTemplatesProps {
  selectedTemplate: string | null;
  onSelect: (templateId: string) => void;
}

export function ScanTemplates({
  selectedTemplate,
  onSelect,
}: ScanTemplatesProps) {
  const handleSelect = useCallback(
    (templateId: string) => {
      onSelect(templateId === selectedTemplate ? null : templateId);
    },
    [selectedTemplate, onSelect],
  );

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[11px] font-bold text-on-surface-variant uppercase tracking-widest font-body">
          Quick Templates
        </span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {SCAN_TEMPLATES.map((template) => {
          const isSelected = selectedTemplate === template.id;
          return (
            <motion.button
              key={template.id}
              whileHover={{ y: -2 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => handleSelect(template.id)}
              className={`relative p-4 border rounded-xl text-left transition-all duration-300 ${
                isSelected
                  ? "border-primary bg-primary/5 shadow-glow"
                  : "border-outline-variant dark:border-[#ffffff10] bg-surface-container dark:bg-[#1A1A24] hover:border-primary/30"
              }`}
            >
              <div className="text-2xl mb-2">{template.icon}</div>
              <div className="text-sm font-semibold text-on-surface dark:text-[#F0F0F5] mb-1">
                {template.name}
              </div>
              <div className="text-[10px] text-on-surface-variant font-body leading-relaxed">
                {template.description}
              </div>
              {isSelected && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className="absolute top-2 right-2 w-5 h-5 bg-primary rounded-full flex items-center justify-center"
                >
                  <svg
                    className="w-3 h-3 text-white"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                </motion.div>
              )}
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
