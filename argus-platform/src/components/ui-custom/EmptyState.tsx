import React from "react";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
}

export default function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
  secondaryActionLabel,
  onSecondaryAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {icon && (
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-white/[0.05] dark:bg-[#12121A]">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-semibold text-on-surface">{title}</h3>
      {description && (
        <p className="mt-2 text-sm text-on-surface-variant">{description}</p>
      )}
      <div className="mt-6 flex items-center gap-4">
        {actionLabel && onAction && (
          <button
            onClick={onAction}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:opacity-90"
          >
            {actionLabel}
          </button>
        )}
        {secondaryActionLabel && onSecondaryAction && (
          <button
            onClick={onSecondaryAction}
            className="text-sm font-medium text-primary hover:underline"
          >
            {secondaryActionLabel}
          </button>
        )}
      </div>
    </div>
  );
}
