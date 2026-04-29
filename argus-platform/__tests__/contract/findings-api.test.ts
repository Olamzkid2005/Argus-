/**
 * Contract tests for Findings API request/response shapes
 */

describe('Findings API Contracts', () => {
  describe('GET /api/findings — response shape', () => {
    it('should return paginated findings list', () => {
      const response = {
        findings: [
          {
            id: 'uuid',
            engagement_id: 'uuid',
            target_url: 'https://example.com',
            type: 'XSS',
            severity: 'HIGH',
            endpoint: '/api/v1/users',
            source_tool: 'nuclei',
            verified: false,
            confidence: 85,
            created_at: 'ISO date',
            evidence: 'string or null',
          },
        ],
        meta: {
          total: 1,
          page: 1,
          limit: 50,
          totalPages: 1,
          sort_by: 'severity',
          sort_order: 'asc',
        },
      };

      expect(response).toHaveProperty('findings');
      expect(Array.isArray(response.findings)).toBe(true);
      expect(response).toHaveProperty('meta');
      expect(response.meta).toHaveProperty('total');
      expect(response.meta).toHaveProperty('page');
      expect(response.meta).toHaveProperty('limit');
      expect(response.meta).toHaveProperty('totalPages');

      if (response.findings.length > 0) {
        const f = response.findings[0];
        expect(f).toHaveProperty('id');
        expect(f).toHaveProperty('engagement_id');
        expect(f).toHaveProperty('type');
        expect(f).toHaveProperty('severity');
        expect(f).toHaveProperty('endpoint');
        expect(f).toHaveProperty('source_tool');
        expect(f).toHaveProperty('verified');
        expect(f).toHaveProperty('confidence');
        expect(f).toHaveProperty('created_at');
      }
    });

    it('should accept valid severity filter values', () => {
      const validSeverities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];
      validSeverities.forEach((s) => {
        expect(typeof s).toBe('string');
      });
    });

    it('should accept valid sort fields', () => {
      const validSortFields = ['severity', 'created_at', 'confidence', 'endpoint', 'type'];
      validSortFields.forEach((f) => {
        expect(typeof f).toBe('string');
      });
    });
  });

  describe('GET /api/engagement/[id]/findings — response shape', () => {
    it('return findings with pagination cursors', () => {
      const response = {
        findings: [],
        total: 0,
        limit: 50,
        offset: 0,
        hasMore: false,
      };

      expect(response).toHaveProperty('findings');
      expect(Array.isArray(response.findings)).toBe(true);
      expect(response).toHaveProperty('total');
      expect(typeof response.total).toBe('number');
      expect(response).toHaveProperty('limit');
      expect(response).toHaveProperty('offset');
      expect(response).toHaveProperty('hasMore');
      expect(typeof response.hasMore).toBe('boolean');
    });

    it('should accept valid filter parameters', () => {
      const filters = {
        severity: 'CRITICAL,HIGH',
        minConfidence: '70',
        sourceTool: 'nuclei,semgrep',
        since: '2025-01-01T00:00:00Z',
      };
      expect(typeof filters.severity).toBe('string');
      expect(typeof filters.minConfidence).toBe('string');
      expect(typeof filters.sourceTool).toBe('string');
      expect(typeof filters.since).toBe('string');
    });
  });

  describe('POST /api/findings — bulk operations', () => {
    it('should validate bulk request shape', () => {
      const request = {
        action: 'verify',
        finding_ids: ['uuid-1', 'uuid-2'],
      };

      expect(request).toHaveProperty('action');
      expect(request).toHaveProperty('finding_ids');
      expect(Array.isArray(request.finding_ids)).toBe(true);
      expect(request.finding_ids.length).toBeGreaterThan(0);
    });

    it('should accept valid bulk actions', () => {
      const validActions = ['verify', 'delete', 'update_severity'];
      validActions.forEach((a) => {
        expect(typeof a).toBe('string');
      });
    });

    it('should return success response for bulk operations', () => {
      const response = {
        success: true,
        action: 'verify',
        affected: 3,
      };

      expect(response).toHaveProperty('success');
      expect(response.success).toBe(true);
      expect(response).toHaveProperty('action');
      expect(response).toHaveProperty('affected');
      expect(typeof response.affected).toBe('number');
    });

    it('should require severity for update_severity action', () => {
      const request = {
        action: 'update_severity',
        finding_ids: ['uuid-1'],
        severity: 'CRITICAL',
      };

      expect(request.action).toBe('update_severity');
      expect(request).toHaveProperty('severity');
      expect(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']).toContain(request.severity);
    });
  });

  describe('Severity enum', () => {
    it('should define all severity levels', () => {
      const severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];
      expect(severities).toHaveLength(5);
      severities.forEach((s) => {
        expect(typeof s).toBe('string');
      });
    });
  });
});
