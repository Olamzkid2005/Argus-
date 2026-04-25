/**
 * Contract tests for API ↔ Workers job messages
 * Validates that API routes send job messages matching the expected schema
 */
import { JobMessage } from '@/lib/redis';

// JSON Schema for JobMessage
const jobMessageSchema = {
  type: 'object',
  required: ['type', 'engagement_id', 'target', 'budget', 'trace_id', 'created_at'],
  properties: {
    type: {
      type: 'string',
      enum: ['recon', 'scan', 'analyze', 'report', 'repo_scan', 'compliance_report'],
    },
    engagement_id: { type: 'string', format: 'uuid' },
    target: { type: 'string' },
    repo_url: { type: 'string' },
    standard: { type: 'string' },
    budget: {
      type: 'object',
      required: ['max_cycles', 'max_depth', 'max_cost'],
      properties: {
        max_cycles: { type: 'number', minimum: 1 },
        max_depth: { type: 'number', minimum: 1 },
        max_cost: { type: 'number', minimum: 0 },
      },
    },
    aggressiveness: { type: 'string' },
    trace_id: { type: 'string', format: 'uuid' },
    created_at: { type: 'string', format: 'date-time' },
  },
  additionalProperties: false,
};

// Helper to validate against schema
function validateJobMessage(message: unknown): { valid: boolean; errors?: string[] } {
  const errors: string[] = [];
  const msg = message as Record<string, unknown>;

  // Check required fields
  const required = jobMessageSchema.required as string[];
  for (const field of required) {
    if (!(field in msg)) {
      errors.push(`Missing required field: ${field}`);
    }
  }

  if (errors.length > 0) {
    return { valid: false, errors };
  }

  // Validate type enum
  const validTypes = (jobMessageSchema.properties.type as { enum: string[] }).enum;
  if (!validTypes.includes(msg.type as string)) {
    errors.push(`Invalid type: ${msg.type}`);
  }

  // Validate budget structure
  const budget = msg.budget as Record<string, unknown>;
  if (budget) {
    if (typeof budget.max_cycles !== 'number' || budget.max_cycles < 1) {
      errors.push('budget.max_cycles must be a positive number');
    }
    if (typeof budget.max_depth !== 'number' || budget.max_depth < 1) {
      errors.push('budget.max_depth must be a positive number');
    }
    if (typeof budget.max_cost !== 'number' || budget.max_cost < 0) {
      errors.push('budget.max_cost must be a non-negative number');
    }
  }

  // Validate UUIDs (basic check)
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (typeof msg.engagement_id === 'string' && !uuidRegex.test(msg.engagement_id)) {
    errors.push('engagement_id must be a valid UUID');
  }
  if (typeof msg.trace_id === 'string' && !uuidRegex.test(msg.trace_id)) {
    errors.push('trace_id must be a valid UUID');
  }

  // Validate timestamps (basic ISO format check)
  const isoDateRegex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;
  if (typeof msg.created_at === 'string' && !isoDateRegex.test(msg.created_at)) {
    errors.push('created_at must be a valid ISO date string');
  }

  return { valid: errors.length === 0, errors };
}

describe('Job Message Contract Tests', () => {
  describe('Valid job messages', () => {
    it('should accept valid recon job message', () => {
      const message: Partial<JobMessage> = {
        type: 'recon',
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://example.com',
        budget: {
          max_cycles: 5,
          max_depth: 3,
          max_cost: 0.5,
        },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(true);
    });

    it('should accept valid scan job message', () => {
      const message = {
        type: 'scan',
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://example.com',
        budget: {
          max_cycles: 10,
          max_depth: 5,
          max_cost: 1.0,
        },
        aggressiveness: 'normal',
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(true);
    });

    it('should accept valid repo_scan job message', () => {
      const message = {
        type: 'repo_scan',
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://github.com/example/repo',
        repo_url: 'https://github.com/example/repo',
        budget: {
          max_cycles: 3,
          max_depth: 2,
          max_cost: 0.25,
        },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(true);
    });

    it('should accept valid compliance_report job message', () => {
      const message = {
        type: 'compliance_report',
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://example.com',
        standard: 'PCI-DSS',
        budget: {
          max_cycles: 1,
          max_depth: 1,
          max_cost: 0.1,
        },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(true);
    });
  });

  describe('Invalid job messages', () => {
    it('should reject message missing type', () => {
      const message = {
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://example.com',
        budget: { max_cycles: 5, max_depth: 3, max_cost: 0.5 },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Missing required field: type');
    });

    it('should reject invalid job type', () => {
      const message = {
        type: 'invalid_type',
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://example.com',
        budget: { max_cycles: 5, max_depth: 3, max_cost: 0.5 },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Invalid type: invalid_type');
    });

    it('should reject invalid UUID format', () => {
      const message = {
        type: 'recon',
        engagement_id: 'not-a-uuid',
        target: 'https://example.com',
        budget: { max_cycles: 5, max_depth: 3, max_cost: 0.5 },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('engagement_id must be a valid UUID');
    });

    it('should reject invalid budget values', () => {
      const message = {
        type: 'recon',
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://example.com',
        budget: { max_cycles: 0, max_depth: -1, max_cost: -5 },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: new Date().toISOString(),
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('budget.max_cycles must be a positive number');
      expect(result.errors).toContain('budget.max_depth must be a positive number');
      expect(result.errors).toContain('budget.max_cost must be a non-negative number');
    });

    it('should reject invalid timestamp format', () => {
      const message = {
        type: 'recon',
        engagement_id: '123e4567-e89b-12d3-a456-426614174000',
        target: 'https://example.com',
        budget: { max_cycles: 5, max_depth: 3, max_cost: 0.5 },
        trace_id: '123e4567-e89b-12d3-a456-426614174001',
        created_at: 'not-a-date',
      };

      const result = validateJobMessage(message);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('created_at must be a valid ISO date string');
    });
  });
});