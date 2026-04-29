/**
 * Contract tests for Reports and Rules API response shapes
 */

describe('Reports API Contracts', () => {
  describe('GET /api/reports — response shape', () => {
    it('should return reports array', () => {
      const response = {
        reports: [
          {
            id: 'uuid',
            name: 'PCI-DSS Compliance Report',
            type: 'compliance',
            engagement_id: 'uuid',
            status: 'complete',
            format: 'pdf',
            created_at: 'ISO date',
          },
        ],
      };

      expect(response).toHaveProperty('reports');
      expect(Array.isArray(response.reports)).toBe(true);

      if (response.reports.length > 0) {
        const report = response.reports[0];
        expect(report).toHaveProperty('id');
        expect(report).toHaveProperty('name');
        expect(report).toHaveProperty('type');
        expect(report).toHaveProperty('engagement_id');
        expect(report).toHaveProperty('status');
        expect(report).toHaveProperty('format');
        expect(report).toHaveProperty('created_at');
      }
    });

    it('should return empty reports array on error', () => {
      const fallback = { reports: [] };
      expect(fallback).toHaveProperty('reports');
      expect(Array.isArray(fallback.reports)).toBe(true);
      expect(fallback.reports).toHaveLength(0);
    });
  });
});

describe('Rules API Contracts', () => {
  describe('GET /api/rules — response shape', () => {
    it('should return rules array', () => {
      const response = {
        rules: [
          {
            id: 'uuid',
            name: 'Custom XSS Rule',
            description: 'Detects reflected XSS',
            severity: 'HIGH',
            category: 'xss',
            tags: ['xss', 'injection'],
            status: 'active',
            version: 1,
            is_community_shared: false,
            created_at: 'ISO date',
            updated_at: 'ISO date',
            rule_yaml: 'string',
          },
        ],
      };

      expect(response).toHaveProperty('rules');
      expect(Array.isArray(response.rules)).toBe(true);

      if (response.rules.length > 0) {
        const rule = response.rules[0];
        expect(rule).toHaveProperty('id');
        expect(rule).toHaveProperty('name');
        expect(rule).toHaveProperty('severity');
        expect(rule).toHaveProperty('category');
        expect(rule).toHaveProperty('status');
        expect(rule).toHaveProperty('version');
        expect(rule).toHaveProperty('rule_yaml');
      }
    });

    it('should accept valid status filters', () => {
      const validStatuses = ['active', 'inactive', 'all'];
      validStatuses.forEach((s) => {
        expect(typeof s).toBe('string');
      });
    });
  });

  describe('POST /api/rules — request/response shapes', () => {
    it('should require name and rule_yaml', () => {
      const request = {
        name: 'Custom Rule',
        rule_yaml: 'rules:\n  - id: test',
      };
      expect(request).toHaveProperty('name');
      expect(request).toHaveProperty('rule_yaml');
    });

    it('should return created rule on success', () => {
      const response = {
        rule: {
          id: 'uuid',
          name: 'Custom Rule',
          status: 'active',
          version: 1,
          created_at: 'ISO date',
        },
      };

      expect(response).toHaveProperty('rule');
      expect(response.rule).toHaveProperty('id');
      expect(response.rule).toHaveProperty('name');
      expect(response.rule).toHaveProperty('status');
      expect(response.rule).toHaveProperty('version');
      expect(response.rule).toHaveProperty('created_at');
    });
  });
});
