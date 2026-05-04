"use client";

import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";

interface CompletionBannerProps {
  show: boolean;
  currentState: string;
  completionCount: number;
  engagementId: string;
  onDismiss: () => void;
}

export default function CompletionBanner({
  show,
  currentState,
  completionCount,
  engagementId,
  onDismiss,
}: CompletionBannerProps) {
  const router = useRouter();

  return (
    <AnimatePresence>
      {show && currentState === "complete" && (
        <motion.div
          initial={{ opacity: 0, y: -20, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -20, scale: 0.95 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="mb-6 p-4 bg-green-500/10 border border-green-500/30 rounded-xl flex items-center gap-4"
        >
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring", stiffness: 200, damping: 15, delay: 0.1 }}
          >
            <CheckCircle2 size={24} className="text-green-500" />
          </motion.div>
          <div className="flex-1">
            <h3 className="text-sm font-bold text-green-500 uppercase tracking-wide">
              Scan Complete!
            </h3>
            <p className="text-xs text-on-surface-variant mt-0.5">
              Found {completionCount} findings •{" "}
              <button
                onClick={() => router.push(`/engagements/${engagementId}/report`)}
                className="text-primary hover:underline font-medium"
              >
                View Full Report →
              </button>
            </p>
          </div>
          <button
            onClick={onDismiss}
            aria-label="Dismiss completion banner"
            className="p-1 hover:bg-green-500/10 rounded-lg transition-all"
          >
            <XCircle size={16} className="text-on-surface-variant" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
