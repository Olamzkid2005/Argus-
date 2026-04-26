"use client";

import { CheckCircle2, Trash2, Download, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface BulkActionBarProps {
  selectedCount: number;
  onClearSelection: () => void;
  onBulkVerify: () => void;
  onBulkDelete: () => void;
  onBulkExport: () => void;
  isVerifying: boolean;
  isDeleting: boolean;
  isExporting: boolean;
}

export function BulkActionBar({
  selectedCount,
  onClearSelection,
  onBulkVerify,
  onBulkDelete,
  onBulkExport,
  isVerifying,
  isDeleting,
  isExporting,
}: BulkActionBarProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl shadow-2xl p-4 flex items-center gap-4"
      style={{ minWidth: "400px" }}
    >
      <div className="flex items-center gap-3 flex-1">
        <button
          onClick={onClearSelection}
          className="p-1 hover:bg-surface-container dark:hover:bg-[#1A1A24] rounded-lg transition-all"
          aria-label="Clear selection"
        >
          <X size={16} className="text-on-surface-variant" />
        </button>
        <span className="text-sm font-mono font-bold text-on-surface dark:text-[#F0F0F5]">
          {selectedCount} selected
        </span>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onBulkVerify}
          disabled={isVerifying}
          className="flex items-center gap-2 px-4 py-2 text-xs font-bold bg-primary text-on-primary rounded-lg hover:opacity-90 transition-all disabled:opacity-50"
        >
          {isVerifying ? (
            <span className="inline-block animate-spin">⟳</span>
          ) : (
            <CheckCircle2 size={14} />
          )}
          Verify
        </button>

        <button
          onClick={onBulkDelete}
          disabled={isDeleting}
          className="flex items-center gap-2 px-4 py-2 text-xs font-bold bg-error/10 text-error border border-error/20 rounded-lg hover:bg-error/20 transition-all disabled:opacity-50"
        >
          {isDeleting ? (
            <span className="inline-block animate-spin">⟳</span>
          ) : (
            <Trash2 size={14} />
          )}
          Delete
        </button>

        <button
          onClick={onBulkExport}
          disabled={isExporting}
          className="flex items-center gap-2 px-4 py-2 text-xs font-bold border border-outline-variant dark:border-[#ffffff10] rounded-lg hover:bg-surface-container dark:hover:bg-[#1A1A24] transition-all disabled:opacity-50"
        >
          {isExporting ? (
            <span className="inline-block animate-spin">⟳</span>
          ) : (
            <Download size={14} />
          )}
          Export
        </button>
      </div>
    </motion.div>
  );
}
