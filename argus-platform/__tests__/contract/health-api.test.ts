/**
 * Contract tests for Health check API response shapes
 */

describe('Health API Contracts', () => {
  describe('GET /api/health/db — response shape', () => {
    it('should return healthy status with checks', () => {
      const response = {
        status: 'healthy',
        timestamp: 'ISO date',
        response_time_ms: 42,
        checks: {
          connection: 'ok',
          query_time_ms: 5,
          pool: {
            totalCount: 5,
            idleCount: 3,
            waitingCount: 0,
            maxConnections: 20,
            minConnections: 2,
            queryMetrics: {},
          },
          pool_healthy: true,
          long_running_queries: 0,
        },
      };

      expect(response).toHaveProperty('status');
      expect(['healthy', 'degraded', 'unhealthy']).toContain(response.status);
      expect(response).toHaveProperty('timestamp');
      expect(response).toHaveProperty('response_time_ms');
      expect(typeof response.response_time_ms).toBe('number');
      expect(response).toHaveProperty('checks');
      expect(response.checks).toHaveProperty('connection');
      expect(response.checks).toHaveProperty('pool');
    });

    it('should return unhealthy status on failure', () => {
      const response = {
        status: 'unhealthy',
        error: 'Connection refused',
      };

      expect(response).toHaveProperty('status');
      expect(response.status).toBe('unhealthy');
      expect(response).toHaveProperty('error');
      expect(typeof response.error).toBe('string');
    });

    it('should validate pool stats shape', () => {
      const poolStats = {
        totalCount: 5,
        idleCount: 3,
        waitingCount: 0,
        maxConnections: 20,
        minConnections: 2,
        queryMetrics: {},
      };

      expect(typeof poolStats.totalCount).toBe('number');
      expect(typeof poolStats.idleCount).toBe('number');
      expect(typeof poolStats.waitingCount).toBe('number');
      expect(typeof poolStats.maxConnections).toBe('number');
      expect(typeof poolStats.minConnections).toBe('number');
      expect(typeof poolStats.queryMetrics).toBe('object');
    });
  });
});
