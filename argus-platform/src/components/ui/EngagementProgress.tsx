"use client";

import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle, Circle, Loader2 } from "lucide-react";

interface StateConfig {
  key: string;
  label: string;
  description: string;
}

interface EngagementProgressProps {
  currentState: string;
  states?: StateConfig[];
}

const defaultStates = [
  { key: "created", label: "Created", description: "Engagement initialized" },
  { key: "recon", label: "Reconnaissance", description: "Discovering targets" },
  { key: "awaiting_approval", label: "Review", description: "Review findings" },
  {
    key: "scanning",
    label: "Scanning",
    description: "Running vulnerability scans",
  },
  { key: "analyzing", label: "Analyzing", description: "AI analysis" },
  { key: "reporting", label: "Reporting", description: "Generating report" },
  { key: "complete", label: "Complete", description: "Scan completed" },
];

export function EngagementProgress({
  currentState,
  states = defaultStates,
}: EngagementProgressProps) {
  const getStateIndex = (key: string) => {
    return states.findIndex((s) => s.key === key);
  };

  const currentIndex = getStateIndex(currentState);
  const isRunning = ["recon", "scanning", "analyzing", "reporting"].includes(
    currentState,
  );

  return (
    <div className="w-full">
      <div className="flex items-center justify-between relative">
        {/* Progress line */}
        <div className="absolute top-4 left-0 right-0 h-0.5 bg-border -z-10" />
        <div
          className="absolute top-4 left-0 h-0.5 bg-primary -z-10 transition-all duration-500"
          style={{
            width: `${Math.max(0, (currentIndex / (states.length - 1)) * 100)}%`,
          }}
        />

        {states.map((state, index) => {
          const isComplete = index <= currentIndex;
          const isCurrent = index === currentIndex;

          return (
            <div
              key={state.key}
              className="flex flex-col items-center relative"
            >
              <div className="flex items-center justify-center w-8 h-8 rounded-full bg-background border-2 z-10">
                <AnimatePresence mode="wait">
                  {isCurrent && isRunning ? (
                    <motion.div
                      key="loading"
                      initial={{ rotate: 0 }}
                      animate={{ rotate: 360 }}
                      transition={{
                        repeat: Infinity,
                        duration: 1,
                        ease: "linear",
                      }}
                    >
                      <Loader2 className="h-4 w-4 text-primary" />
                    </motion.div>
                  ) : isComplete ? (
                    <motion.div
                      key="complete"
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                    >
                      <CheckCircle className="h-4 w-4 text-primary" />
                    </motion.div>
                  ) : (
                    <motion.div
                      key="pending"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                    >
                      <Circle className="h-4 w-4 text-muted-foreground" />
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
              <span
                className={`text-xs mt-2 ${isCurrent ? "text-primary font-medium" : "text-muted-foreground"}`}
              >
                {state.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
