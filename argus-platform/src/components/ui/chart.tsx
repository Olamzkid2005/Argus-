"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

// Stub chart components for future use (recharts installed but not currently used)
export function Chart({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("w-full h-full", className)} {...props}>
      {children}
    </div>
  )
}

export function ChartContainer({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("w-full h-full", className)} {...props}>
      {children}
    </div>
  )
}

export function ChartTooltip({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("chart-tooltip", className)} {...props} />
}

export function ChartTooltipContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("chart-tooltip-content", className)} {...props} />
}

export function ChartLegend({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("chart-legend", className)} {...props} />
}