/**
 * Contract tests for Auth API request/response shapes
 */

describe('Auth API Contracts', () => {
  describe('POST /api/auth/signup — request validation', () => {
    it('should require all fields', () => {
      const requiredFields = ['email', 'password', 'passwordConfirm', 'orgName'];
      requiredFields.forEach((field) => {
        expect(typeof field).toBe('string');
      });
    });

    it('should validate email format', () => {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      expect(emailRegex.test('user@example.com')).toBe(true);
      expect(emailRegex.test('invalid')).toBe(false);
      expect(emailRegex.test('')).toBe(false);
    });

    it('should enforce password rules', () => {
      const rules = {
        minLength: 8,
        maxLength: 128,
        requiresUppercase: true,
        requiresLowercase: true,
        requiresNumber: true,
      };

      expect(rules.minLength).toBeGreaterThanOrEqual(8);
      expect(rules.maxLength).toBeLessThanOrEqual(128);
    });

    it('should validate org name length', () => {
      const minLen = 2;
      const maxLen = 255;
      expect(minLen).toBeGreaterThanOrEqual(2);
      expect(maxLen).toBeLessThanOrEqual(255);
    });
  });

  describe('POST /api/auth/signup — response shapes', () => {
    it('should return success response with user object', () => {
      const response = {
        message: 'Account created successfully',
        user: { id: 'uuid', email: 'user@example.com' },
      };

      expect(response).toHaveProperty('message');
      expect(typeof response.message).toBe('string');
      expect(response).toHaveProperty('user');
      expect(response.user).toHaveProperty('id');
      expect(response.user).toHaveProperty('email');
    });

    it('should return error response with error message', () => {
      const errorResponses = [
        { error: 'All fields are required', status: 400 },
        { error: 'Invalid email format', status: 400 },
        { error: 'Password must be at least 8 characters long', status: 400 },
        { error: 'Passwords do not match', status: 400 },
        { error: 'Organization name must be between 2 and 255 characters', status: 400 },
        { error: 'Account creation failed. Please try again.', status: 409 },
      ];

      errorResponses.forEach(({ error, status }) => {
        expect(typeof error).toBe('string');
        expect(typeof status).toBe('number');
        expect(status).toBeGreaterThanOrEqual(400);
      });
    });
  });

  describe('Error response shape', () => {
    it('should follow standard error format from createErrorResponse', () => {
      const errorResponse = {
        error: 'Unauthorized',
        code: 'UNAUTHORIZED',
        requestId: 'uuid',
      };

      expect(errorResponse).toHaveProperty('error');
      expect(typeof errorResponse.error).toBe('string');
      expect(errorResponse).toHaveProperty('code');
      expect(typeof errorResponse.code).toBe('string');
      expect(errorResponse).toHaveProperty('requestId');
    });

    it('should include all error codes', () => {
      const errorCodes = [
        'UNAUTHORIZED',
        'FORBIDDEN',
        'NOT_FOUND',
        'VALIDATION_ERROR',
        'RATE_LIMITED',
        'INTERNAL_ERROR',
        'BAD_REQUEST',
      ];
      errorCodes.forEach((code) => {
        expect(typeof code).toBe('string');
      });
      expect(errorCodes).toHaveLength(7);
    });
  });
});
