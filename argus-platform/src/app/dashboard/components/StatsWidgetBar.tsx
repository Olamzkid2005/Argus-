"use client";

import { motion } from "framer-motion";
import { Zap } from "lucide-react";
import { AnimatedCounter } from "@/components/animations/AnimatedCounter";

interface Stat {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
}

interface StatsWidgetBarProps {
  stats: Stat[];
}

function StatCard({
  label,
  value,
  icon: Icon,
  color,
  index,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
  index: number;
}) {
  const numericValue = typeof value === "number" ? value : parseInt(String(value), 10);
  const isNumeric = !isNaN(numericValue);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.1 }}
      whileHover={{ y: -2, transition: { duration: 0.25 } }}
      className="relative bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-5 overflow-hidden transition-all duration-300 hover:shadow-glow hover:border-primary/30 group"
      style={{ borderLeftWidth: 4, borderLeftColor: color }}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="w-10 h-10 rounded-lg bg-surface-container dark:bg-[#1A1A24] flex items-center justify-center transition-colors duration-300">
          {/* @ts-ignore */}
          <Icon size={20} style={{ color }} />
        </div>
        <Zap size={14} className="text-on-surface-variant dark:text-[#8A8A9E] opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      </div>
      <div className="text-3xl font-headline font-bold text-on-surface dark:text-[#F0F0F5] tracking-tight">
        {isNumeric ? <AnimatedCounter value={numericValue} /> : value}
      </div>
      <div className="text-xs font-body text-on-surface-variant dark:text-[#8A8A9E] mt-1 tracking-wide uppercase">{label}</div>
    </motion.div>
  );
}

export default function StatsWidgetBar({ stats }: StatsWidgetBarProps) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
      {stats.map((s, i) => (
        <StatCard key={s.label} {...s} index={i} />
      ))}
    </div>
  );
}
