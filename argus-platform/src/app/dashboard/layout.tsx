"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const BREADCRUMB_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  findings: "Findings",
  engagements: "Engagements",
  reports: "Reports",
  settings: "Settings",
  admin: "Admin",
  analytics: "Analytics",
  monitoring: "Monitoring",
};

/**
 * Dashboard layout with breadcrumb navigation.
 * Provides consistent structure for all dashboard sub-pages.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  // Build breadcrumbs from path segments
  const breadcrumbs = segments.map((segment, index) => {
    const href = "/" + segments.slice(0, index + 1).join("/");
    const label = BREADCRUMB_LABELS[segment] || segment.replace(/-/g, " ");
    const isLast = index === segments.length - 1;
    return { href, label, isLast };
  });

  return (
    <div className="min-h-screen">
      {/* Breadcrumb navigation */}
      {breadcrumbs.length > 1 && (
        <nav aria-label="Breadcrumb" className="px-6 py-3 text-sm text-muted-foreground">
          <ol className="flex items-center gap-2">
            {breadcrumbs.map((crumb) => (
              <li key={crumb.href} className="flex items-center gap-2">
                {!crumb.isLast ? (
                  <>
                    <Link href={crumb.href} className="hover:text-foreground transition-colors">
                      {crumb.label.charAt(0).toUpperCase() + crumb.label.slice(1)}
                    </Link>
                    <span aria-hidden="true">/</span>
                  </>
                ) : (
                  <span className="text-foreground font-medium">
                    {crumb.label.charAt(0).toUpperCase() + crumb.label.slice(1)}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      {children}
    </div>
  );
}
