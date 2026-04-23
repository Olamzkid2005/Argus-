// Security Rating Calculator
// Calculates a 0-100% security rating based on vulnerabilities found

export interface FindingForRating {
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';
  confidence?: number;
  cvss_score?: number;
  fp_likelihood?: number;
  verified?: boolean;
}

// Severity penalty points deducted from base score (100)
// This keeps scoring intuitive and easy to explain:
// - CRITICAL: -10 each
// - HIGH: -5 each
// - MEDIUM: -2 each
// - LOW: -1 each
// - INFO: -0.25 each
const SEVERITY_WEIGHTS = {
  CRITICAL: 10,
  HIGH: 5,
  MEDIUM: 2,
  LOW: 1,
  INFO: 0.25,
} as const;

// Default CVSS factor based on severity if cvss_score not available
const DEFAULT_CVSS_FACTOR: Record<string, number> = {
  CRITICAL: 0.95, // 9.5/10
  HIGH: 0.75,     // 7.5/10
  MEDIUM: 0.50,   // 5.0/10
  LOW: 0.30,      // 3.0/10
  INFO: 0.0,      // 0.0/10
};

function normalizeProbability(value: number | undefined, fallback: number): number {
  if (value === undefined || Number.isNaN(value)) return fallback;
  // Support both 0-1 and 0-100 storage formats.
  const normalized = value > 1 ? value / 100 : value;
  return Math.max(0, Math.min(1, normalized));
}

function normalizeCvssFactor(cvssScore: number | undefined, severity: FindingForRating["severity"]): number {
  if (cvssScore === undefined || Number.isNaN(cvssScore) || cvssScore <= 0) {
    return DEFAULT_CVSS_FACTOR[severity] || 0.5;
  }

  // Support either normalized CVSS (0-1) or standard CVSS (0-10).
  const normalized = cvssScore <= 1 ? cvssScore : cvssScore / 10;
  return Math.max(0, Math.min(1, normalized));
}

/**
 * Calculate security rating (0-100%) based on findings
 * 
 * Algorithm:
 * 1. Start with base score of 100
 * 2. Subtract severity penalty points per finding
 * 3. Apply confidence and false positive adjustments
 * 4. Clamp final score to 0..100
 * 
 * @param findings - Array of findings to analyze
 * @returns Security rating from 0-100
 */
export function calculateSecurityRating(findings: FindingForRating[]): number {
  if (!findings || findings.length === 0) {
    return 100; // No findings = perfect score
  }

  // Fixed, predictable deduction model requested by product:
  // score = 100 - sum(per-finding severity deduction)
  const totalDeduction = findings.reduce((sum, finding) => {
    return sum + (SEVERITY_WEIGHTS[finding.severity] || 0);
  }, 0);

  const score = 100 - totalDeduction;
  return Math.max(0, Math.min(100, Math.round(score)));
}

/**
 * Get rating label based on score
 */
export function getRatingLabel(score: number): string {
  if (score >= 90) return 'Excellent';
  if (score >= 75) return 'Good';
  if (score >= 60) return 'Fair';
  if (score >= 40) return 'Poor';
  if (score >= 20) return 'Critical';
  return 'Severe';
}

/**
 * Get rating color based on score
 */
export function getRatingColor(score: number): string {
  if (score >= 90) return '#10B981'; // Green
  if (score >= 75) return '#22C55E'; // Light green
  if (score >= 60) return '#F59E0B'; // Amber
  if (score >= 40) return '#F97316'; // Orange
  if (score >= 20) return '#EF4444'; // Red
  return '#DC2626'; // Dark red
}

/**
 * Get severity counts from findings
 */
export function getSeverityCounts(findings: FindingForRating[]) {
  return {
    CRITICAL: findings.filter(f => f.severity === 'CRITICAL').length,
    HIGH: findings.filter(f => f.severity === 'HIGH').length,
    MEDIUM: findings.filter(f => f.severity === 'MEDIUM').length,
    LOW: findings.filter(f => f.severity === 'LOW').length,
    INFO: findings.filter(f => f.severity === 'INFO').length,
  };
}
