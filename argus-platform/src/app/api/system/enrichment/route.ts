// Threat intelligence enrichment endpoint
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { log } from "@/lib/logger";

interface EnrichmentRequest {
  value: string;
  type: "url" | "domain" | "ip";
}

/**
 * POST /api/system/enrichment
 *
 * Enriches an IOC (indicator of compromise) with threat intelligence.
 * NOTE: NVD/EPSS enrichment is not yet configured. This endpoint returns
 * placeholder data while the backend enrichment service integration is pending.
 */
export async function POST(req: Request) {
  await requireAuth();
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

    log.apiEnd("POST", "/api/system/enrichment", 200);
    return NextResponse.json({
      data: {
        ioc_value: value,
        ioc_type: type,
        status: "not_configured",
        message: "NVD/EPSS enrichment service is not yet configured. Threat intelligence data will be available once the backend enrichment service is connected.",
        findings: [],
        sources: [],
        available_sources: ["nvd", "epss", "virustotal", "abuseipdb", "shodan"],
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
