// Threat intelligence enrichment endpoint
import { NextResponse } from "next/server";
import { log } from "@/lib/logger";

interface EnrichmentRequest {
  value: string;
  type: "url" | "domain" | "ip";
}

interface Finding {
  type: string;
  description: string;
  severity: string;
}

/**
 * POST /api/system/enrichment
 *
 * Enriches an IOC (indicator of compromise) with threat intelligence.
 * Mock data — in production, proxy to Python backend enrichment service.
 */
export async function POST(req: Request) {
  log.api("POST", "/api/system/enrichment");
  try {
    const body: EnrichmentRequest = await req.json();
    const { value, type } = body;

    if (!value || !type) {
      return NextResponse.json(
        { error: "Missing required fields: value, type" },
        { status: 400 }
      );
    }

    if (!["url", "domain", "ip"].includes(type)) {
      return NextResponse.json(
        { error: "Invalid type. Must be one of: url, domain, ip" },
        { status: 400 }
      );
    }

    const findings: Finding[] = [
      {
        type: "reputation",
        description: `No known malicious activity for ${value}`,
        severity: "info",
      },
    ];

    const threat_level: "clean" | "low" | "medium" | "high" | "critical" = "clean";

    log.apiEnd("POST", "/api/system/enrichment", 200);
    return NextResponse.json({
      data: {
        ioc_value: value,
        ioc_type: type,
        threat_level,
        confidence: 0.95,
        findings,
        sources: ["virustotal", "abuseipdb", "shodan"],
      },
    });
  } catch (error) {
    log.error("Enrichment error:", error);
    return NextResponse.json(
      { error: "Failed to enrich IOC" },
      { status: 500 }
    );
  }
}
