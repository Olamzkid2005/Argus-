// Simple validation utilities - no external dependencies
// Request validation utilities

type ValidationRule = (value: unknown) => string | null;

interface ValidationSchema {
  [key: string]: ValidationRule[];
}

// Common validation rules
export const validators = {
  required:
    (field: string): ValidationRule =>
    (value) =>
      !value ? `${field} is required` : null,

  email: (): ValidationRule => (value) =>
    !value || !String(value).includes("@") ? "Invalid email format" : null,

  minLength:
    (min: number, field: string): ValidationRule =>
    (value) =>
      !value || String(value).length < min
        ? `${field} must be at least ${min} characters`
        : null,

  maxLength:
    (max: number, field: string): ValidationRule =>
    (value) =>
      value && String(value).length > max
        ? `${field} must be less than ${max} characters`
        : null,

  url: (): ValidationRule => (value) => {
    if (!value) return null;
    try {
      new URL(String(value));
      return null;
    } catch {
      return "Invalid URL format";
    }
  },

  uuid: (): ValidationRule => (value) => {
    if (!value) return null;
    const uuidRegex =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    return !uuidRegex.test(String(value)) ? "Invalid UUID format" : null;
  },

  enum:
    (field: string, allowed: string[]): ValidationRule =>
    (value) =>
      !allowed.includes(String(value))
        ? `${field} must be one of: ${allowed.join(", ")}`
        : null,

  number: (): ValidationRule => (value) =>
    isNaN(Number(value)) ? "Must be a number" : null,

  positive: (): ValidationRule => (value) =>
    Number(value) <= 0 ? "Must be a positive number" : null,
};

// Validate an object against a schema
export function validate(
  data: Record<string, unknown>,
  schema: ValidationSchema,
): {
  valid: boolean;
  errors: Record<string, string>;
} {
  const errors: Record<string, string> = {};

  for (const field in schema) {
    const rules = schema[field];
    const value = data[field];

    for (const rule of rules) {
      const error = rule(value);
      if (error) {
        errors[field] = error;
        break;
      }
    }
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
}

// Pre-defined schemas
export const schemas = {
  engagement: {
    targetUrl: [validators.required("Target URL"), validators.url()],
    scanType: [
      validators.required("Scan type"),
      validators.enum("Scan type", ["url", "repo"]),
    ],
    authorization: [validators.required("Authorization")],
  },

  login: {
    email: [validators.required("Email"), validators.email()],
    password: [validators.required("Password")],
  },

  signup: {
    email: [validators.required("Email"), validators.email()],
    password: [
      validators.required("Password"),
      validators.minLength(8, "Password"),
    ],
    orgName: [
      validators.required("Organization"),
      validators.minLength(2, "Organization"),
    ],
  },
};
