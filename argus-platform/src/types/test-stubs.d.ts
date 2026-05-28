// ---------------------------------------------------------------------------
// Test type stubs for modules that are referenced in tests but don't yet
// exist as implementation files (or exist only partially). These allow
// TypeScript compilation to pass while the real modules are being built.
// Remove each stub once the corresponding module is available.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// __tests__/api/engagement/approve.test.ts
// ---------------------------------------------------------------------------
declare module "@/app/api/engagement/[id]/approve/route" {
  export function POST(
    request: Request,
    context: { params: Promise<{ id: string }> },
  ): Promise<Response>;
}

// ---------------------------------------------------------------------------
// src/__tests__/components/CveCweLinks.test.tsx
// ---------------------------------------------------------------------------
declare module "@/components/ui-custom/FindingCard" {
  import type { FC } from "react";

  export interface Finding {
    id: string;
    engagement_id: string;
    type: string;
    severity: string;
    confidence: number;
    endpoint: string;
    evidence: Record<string, unknown>;
    source_tool: string;
    created_at: string;
    cwe_id?: string;
    cve_id?: string;
    cvss_score?: number;
    cvss_vector?: string;
  }

  export const FindingCard: FC<{ finding: Finding }>;
}

// ---------------------------------------------------------------------------
// src/__tests__/hooks/useMobileDetect.test.tsx
// ---------------------------------------------------------------------------
declare module "@/hooks/useMobileDetect" {
  export function useMobileDetect(): boolean;
}

// ---------------------------------------------------------------------------
// src/components/animations/__tests__/PageTransition.test.tsx
// ---------------------------------------------------------------------------
declare module "@/components/animations/PageTransition" {
  import type { FC, ReactNode } from "react";

  export const PageTransition: FC<{ children: ReactNode }>;
  export const FadeIn: FC<{ children: ReactNode; delay?: number }>;
  export const SlideUp: FC<{
    children: ReactNode;
    delay?: number;
    y?: number;
  }>;
}
