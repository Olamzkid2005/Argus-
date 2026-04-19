"use client";

import { ReactNode } from "react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // SessionProvider is already in root layout.tsx via AuthProvider
  return <>{children}</>;
}
