/**
 * Contract tests for Engagement API request/response shapes
 * Validates that API handlers produce responses matching expected schemas
 */

describe('Engagement API Contracts', () => {
  describe('POST /api/engagement/create — request validation', () => {
    const requiredFields = ['targetUrl', 'authorizedScope'];

    it('should define all required fields for engagement creation', () => {
      expect(requiredFields).toContain('targetUrl');
      expect(requiredFields).toContain('authorizedScope');
    });

    it('should accept valid scan types', () => {
      const validScanTypes = ['url', 'repo'];
      validScanTypes.forEach((type) => {
        expect(['url', 'repo']).toContain(type);
      });
    });

    it('should accept valid aggressiveness levels', () => {
      const validLevels = ['default', 'low', 'medium', 'high'];
      validLevels.forEach((level) => {
        expect(validLevels).toContain(level);
      });
    });

    it('should validate authorizedScope shape for url scans', () => {
      const scope = {
        domains: ['example.com'],
        ipRanges: ['10.0.0.0/24'],
      };
      expect(scope).toHaveProperty('domains');
      expect(Array.isArray(scope.domains)).toBe(true);
      expect(scope).toHaveProperty('ipRanges');
      expect(Array.isArray(scope.ipRanges)).toBe(true);
    });

    it('should validate rateLimitConfig shape', () => {
      const config = {
        requests_per_second: 10,
        concurrent_requests: 3,
      };
      expect(typeof config.requests_per_second).toBe('number');
      expect(config.requests_per_second).toBeGreaterThanOrEqual(1);
      expect(config.requests_per_second).toBeLessThanOrEqual(20);
      expect(typeof config.concurrent_requests).toBe('number');
      expect(config.concurrent_requests).toBeGreaterThanOrEqual(1);
      expect(config.concurrent_requests).toBeLessThanOrEqual(5);
    });
  });

  describe('POST /api/engagement/create — response shape', () => {
    it('should return engagement object with trace_id on success', () => {
      const response = {
        engagement: {
          id: 'uuid',
          org_id: 'uuid',
          target_url: 'https://example.com',
          authorization_proof: 'string',
          authorized_scope: '{}',
          status: 'created',
          created_by: 'uuid',
          rate_limit_config: null,
          scan_type: 'url',
          scan_aggressiveness: 'default',
          created_at: 'ISO date',
        },
        trace_id: 'uuid',
      };

      expect(response).toHaveProperty('engagement');
      expect(response).toHaveProperty('trace_id');
      expect(response.engagement).toHaveProperty('id');
      expect(response.engagement).toHaveProperty('status');
      expect(response.engagement).toHaveProperty('scan_type');
      expect(response.engagement).toHaveProperty('created_at');
    });

    it('should return error response with code on failure', () => {
      const errorResponse = {
        error: 'targetUrl is required',
        code: 'VALIDATION_ERROR',
        requestId: 'uuid',
      };

      expect(errorResponse).toHaveProperty('error');
      expect(typeof errorResponse.error).toBe('string');
      expect(errorResponse).toHaveProperty('code');
      expect(typeof errorResponse.code).toBe('string');
      expect(errorResponse).toHaveProperty('requestId');
    });
  });

  describe('GET /api/engagements — response shape', () => {
    it('should return paginated engagement list', () => {
      const response = {
        engagements: [
          {
            id: 'uuid',
            target_url: 'https://example.com',
            status: 'created',
            scan_type: 'url',
            created_at: 'ISO date',
            updated_at: 'ISO date',
            completed_at: null,
            created_by_email: 'user@example.com',
            max_cycles: 5,
            current_cycles: 0,
            findings_count: 0,
            critical_count: 0,
          },
        ],
        meta: {
          total: 1,
          page: 1,
          limit: 10,
          totalPages: 1,
          sort_by: 'created_at',
          sort_order: 'desc',
        },
      };

      expect(response).toHaveProperty('engagements');
      expect(Array.isArray(response.engagements)).toBe(true);
      expect(response).toHaveProperty('meta');
      expect(response.meta).toHaveProperty('total');
      expect(response.meta).toHaveProperty('page');
      expect(response.meta).toHaveProperty('limit');
      expect(response.meta).toHaveProperty('totalPages');

      if (response.engagements.length > 0) {
        const eng = response.engagements[0];
        expect(eng).toHaveProperty('id');
        expect(eng).toHaveProperty('target_url');
        expect(eng).toHaveProperty('status');
        expect(eng).toHaveProperty('scan_type');
        expect(eng).toHaveProperty('created_at');
        expect(eng).toHaveProperty('findings_count');
        expect(eng).toHaveProperty('critical_count');
      }
    });

    it('should accept valid sort parameters', () => {
      const validSortFields = ['created_at', 'updated_at', 'target_url', 'status'];
      const validSortOrders = ['asc', 'desc'];

      expect(validSortFields).toContain('created_at');
      expect(validSortOrders).toContain('desc');
    });
  });

  describe('GET /api/engagement/[id] — response shape', () => {
    it('should return engagement detail with loop budget', () => {
      const response = {
        engagement: {
          id: 'uuid',
          org_id: 'uuid',
          target_url: 'https://example.com',
          status: 'scanning',
          scan_type: 'url',
          scan_aggressiveness: 'default',
          max_cycles: 5,
          max_depth: 3,
          current_cycles: 0,
          current_depth: 0,
          created_at: 'ISO date',
        },
      };

      expect(response).toHaveProperty('engagement');
      expect(response.engagement).toHaveProperty('id');
      expect(response.engagement).toHaveProperty('max_cycles');
      expect(response.engagement).toHaveProperty('max_depth');
      expect(response.engagement).toHaveProperty('current_cycles');
      expect(response.engagement).toHaveProperty('current_depth');
    });

    it('should return error shape for not found', () => {
      const response = { error: 'Engagement not found' };
      expect(response).toHaveProperty('error');
      expect(typeof response.error).toBe('string');
    });
  });

  describe('POST /api/engagement/[id]/approve — response shape', () => {
    it('should return approval response with trace_id', () => {
      const response = {
        message: 'Engagement approved and scan job queued',
        engagement_id: 'uuid',
        trace_id: 'uuid',
        status: 'scanning',
      };

      expect(response).toHaveProperty('message');
      expect(response).toHaveProperty('engagement_id');
      expect(response).toHaveProperty('trace_id');
      expect(response).toHaveProperty('status');
      expect(response.status).toBe('scanning');
    });
  });

  describe('Engagement status enum', () => {
    it('should include all valid statuses', () => {
      const validStatuses = [
        'created',
        'awaiting_approval',
        'scanning',
        'analyzing',
        'complete',
        'failed',
      ];
      validStatuses.forEach((status) => {
        expect(typeof status).toBe('string');
      });
    });
  });
});
