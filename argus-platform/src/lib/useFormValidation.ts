// Form validation hook with real-time validation
"use client";

import { useState, useCallback } from "react";

interface ValidationRule {
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  pattern?: RegExp;
  custom?: (value: string) => string | null;
}

interface ValidationRules {
  [key: string]: ValidationRule;
}

interface ValidationErrors {
  [key: string]: string;
}

export function useFormValidation(rules: ValidationRules) {
  const [errors, setErrors] = useState<ValidationErrors>({});
  const [touched, setTouched] = useState<{ [key: string]: boolean }>({});

  const validateField = useCallback(
    (name: string, value: string): string | null => {
      const rule = rules[name];
      if (!rule) return null;

      if (rule.required && !value) {
        return `${name} is required`;
      }

      if (rule.minLength && value.length < rule.minLength) {
        return `${name} must be at least ${rule.minLength} characters`;
      }

      if (rule.maxLength && value.length > rule.maxLength) {
        return `${name} must be less than ${rule.maxLength} characters`;
      }

      if (rule.pattern && value && !rule.pattern.test(value)) {
        return `${name} format is invalid`;
      }

      if (rule.custom) {
        return rule.custom(value);
      }

      return null;
    },
    [rules],
  );

  const validateAll = useCallback(
    (values: { [key: string]: string }): boolean => {
      const newErrors: ValidationErrors = {};
      let isValid = true;

      for (const name in rules) {
        const error = validateField(name, values[name] || "");
        if (error) {
          newErrors[name] = error;
          isValid = false;
        }
      }

      setErrors(newErrors);
      return isValid;
    },
    [rules, validateField],
  );

  const handleBlur = useCallback((name: string) => {
    setTouched((prev) => ({ ...prev, [name]: true }));
  }, []);

  const getError = useCallback(
    (name: string): string | null => {
      if (!touched[name]) return null;
      return errors[name] || null;
    },
    [errors, touched],
  );

  return {
    errors,
    touched,
    validateField,
    validateAll,
    handleBlur,
    getError,
    setErrors,
  };
}

// Pre-defined validation rules
export const VALIDATION_RULES = {
  email: {
    required: true,
    pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
  },
  password: {
    required: true,
    minLength: 8,
  },
  url: {
    required: true,
    pattern: /^https?:\/\/.+/,
  },
  domain: {
    required: true,
    pattern: /^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]*(\.[a-zA-Z]{2,})+$/,
  },
  name: {
    required: true,
    minLength: 2,
    maxLength: 100,
  },
};
