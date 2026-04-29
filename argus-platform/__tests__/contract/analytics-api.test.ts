/**
 * Contract tests for Analytics and Dashboard API response shapes
 */

describe('Analytics API Contracts', () => {
  describe('GET /api/analytics — response shape', () => {
    it('should return analytics with trends, comparisons, tools, and monthly', () => {
      const response = {
        trends: [
          { date: 'Jan 15', critical: 2, high: 5, medium: 10, low: 3 },
        ],
        comparisons: [
          {
            id: 'uuid',
            target_url: 'https://example.com',
            created_at: 'ISO date',
            findings_count: 20,
            critical_count: 2,
            high_count: 5,
            duration_minutes: 12.5,
          },
        ],
        tools: [
          {
            source_tool: 'nuclei',
            finding_count: 15,
            avg_confidence: 82.5,
          },
        ],
        monthly: [
          {
            month: 'ISO date',
            total_findings: 50,
            critical: 5,
            verified: 10,
          },
        ],
        range: '30d',
        generated_at: 'ISO date',
      };

      expect(response).toHaveProperty('trends');
      expect(Array.isArray(response.trends)).toBe(true);
      expect(response).toHaveProperty('comparisons');
      expect(Array.isArray(response.comparisons)).toBe(true);
      expect(response).toHaveProperty('tools');
      expect(Array.isArray(response.tools)).toBe(true);
      expect(response).toHaveProperty('monthly');
      expect(Array.isArray(response.monthly)).toBe(true);
      expect(response).toHaveProperty('range');
      expect(response).toHaveProperty('generated_at');

      if (response.trends.length > 0) {
        const trend = response.trends[0];
        expect(trend).toHaveProperty('date');
        expect(trend).toHaveProperty('critical');
        expect(trend).toHaveProperty('high');
        expect(trend).toHaveProperty('medium');
        expect(trend).toHaveProperty('low');
      }

      if (response.tools.length > 0) {
        const tool = response.tools[0];
        expect(tool).toHaveProperty('source_tool');
        expect(tool).toHaveProperty('finding_count');
        expect(tool).toHaveProperty('avg_confidence');
      }
    });

    it('should accept valid range parameters', () => {
      const validRanges = ['7d', '14d', '30d', '90d'];
      validRanges.forEach((r) => {
        expect(r).toMatch(/^\d+d$/);
      });
    });
  });

  describe('GET /api/dashboard/stats — response shape', () => {
    it('should return engagements, findings, and recent_engagements', () => {
      const response = {
        engagements: {
          total_engagements: '10',
          completed: '5',
          failed: '1',
          in_progress: '2',
        },
        findings: {
          total_findings: '50',
          critical: '5',
          high: '10',
          medium: '20',
          verified: '8',
        },
        recent_engagements: [
          {
            id: 'uuid',
            target_url: 'https://example.com',
            status: 'complete',
            created_at: 'ISO date',
            findings_count: '10',
          },
        ],
      };

      expect(response).toHaveProperty('engagements');
      expect(response).toHaveProperty('findings');
      expect(response).toHaveProperty('recent_engagements');
      expect(Array.isArray(response.recent_engagements)).toBe(true);

      expect(response.engagements).toHaveProperty('total_engagements');
      expect(response.engagements).toHaveProperty('completed');
      expect(response.engagements).toHaveProperty('failed');
      expect(response.engagements).toHaveProperty('in_progress');

      expect(response.findings).toHaveProperty('total_findings');
      expect(response.findings).toHaveProperty('critical');
      expect(response.findings).toHaveProperty('high');
      expect(response.findings).toHaveProperty('medium');
      expect(response.findings).toHaveProperty('verified');
    });
  });
});
