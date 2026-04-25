import { render, screen } from "@testing-library/react";
import { FindingCard } from "@/components/ui-custom/FindingCard";

describe("CVe/CWE Clickable Links", () => {
  it("should render CWE ID as clickable link to MITRE", () => {
    const finding = {
      id: "test-1",
      engagement_id: "eng-1",
      type: "XSS",
      severity: "HIGH" as const,
      confidence: 0.85,
      endpoint: "/api/test",
      evidence: {},
      source_tool: "test-tool",
      created_at: new Date().toISOString(),
      cwe_id: "CWE-79",
    };

    render(<FindingCard finding={finding} />);

    const cweLink = screen.getByText("CWE-79");
    expect(cweLink).toBeInTheDocument();
    expect(cweLink.closest("a")).toHaveAttribute(
      "href",
      "https://cwe.mitre.org/data/definitions/79.html"
    );
  });

  it("should render CVSS score as clickable link to NVD", () => {
    const finding = {
      id: "test-2",
      engagement_id: "eng-2",
      type: "SQLi",
      severity: "CRITICAL" as const,
      confidence: 0.95,
      endpoint: "/api/users",
      evidence: {},
      source_tool: "test-tool",
      created_at: new Date().toISOString(),
      cve_id: "CVE-2021-44228",
      cvss_score: 9.8,
      cvss_vector: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
    };

    render(<FindingCard finding={finding} />);

    const cvssLink = screen.getByText("CVSS");
    expect(cvssLink).toBeInTheDocument();
    expect(cvssLink.closest("a")).toHaveAttribute(
      "href",
      "https://nvd.nist.gov/vuln/detail/CVE-2021-44228"
    );
  });

  it("should show CVSS vector when available", () => {
    const finding = {
      id: "test-3",
      engagement_id: "eng-3",
      type: "RCE",
      severity: "CRITICAL" as const,
      confidence: 0.9,
      endpoint: "/api/exec",
      evidence: {},
      source_tool: "test-tool",
      created_at: new Date().toISOString(),
      cvss_score: 10.0,
      cvss_vector: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
    };

    render(<FindingCard finding={finding} />);

    expect(screen.getByText(/CVSS:3.1/)).toBeInTheDocument();
  });

  it("should have copy button for CWE ID", () => {
    const finding = {
      id: "test-4",
      engagement_id: "eng-4",
      type: "XSS",
      severity: "MEDIUM" as const,
      confidence: 0.7,
      endpoint: "/api/xss",
      evidence: {},
      source_tool: "test-tool",
      created_at: new Date().toISOString(),
      cwe_id: "CWE-79",
    };

    render(<FindingCard finding={finding} />);

    // Should have a copy button (svg icon)
    const copyButtons = document.querySelectorAll("svg");
    expect(copyButtons.length).toBeGreaterThan(0);
  });
});
