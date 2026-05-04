"use client";

import { Suspense } from "react";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import { BarChart3, Loader2 } from "lucide-react";

const ToolPerformanceMetrics = dynamic(() => import("@/components/ui-custom/ToolPerformanceMetrics"), { ssr: false });

interface ToolPerformanceSectionProps {
  toolMetrics: any[];
}

export default function ToolPerformanceSection({ toolMetrics }: ToolPerformanceSectionProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.6 }}
      className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl overflow-hidden transition-all duration-300 hover:border-primary/20"
    >
      <div className="flex items-center gap-2 px-5 py-4 border-b border-outline-variant dark:border-[#ffffff08]">
        <BarChart3 size={16} className="text-primary" />
        <h2 className="text-sm font-headline font-medium text-on-surface dark:text-[#F0F0F5] tracking-wide uppercase">Tool Performance Metrics</h2>
      </div>
      <div className="p-5">
        <Suspense fallback={
          <div className="h-[200px] flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        }>
          <ToolPerformanceMetrics metrics={toolMetrics} days={7} />
        </Suspense>
      </div>
    </motion.div>
  );
}
