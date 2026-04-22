/** @type {import('ts-jest').JestConfigWithTsJest} **/
module.exports = {
  rootDir: "/Users/mac/Documents/Argus-/argus-platform",
  roots: ["<rootDir>/src", "<rootDir>/__tests__"],
  testEnvironment: "jsdom",
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      { tsconfig: "/Users/mac/Documents/Argus-/argus-platform/tsconfig.test.json" },
    ],
  },
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
    "^react$": "<rootDir>/node_modules/react",
    "^react-dom$": "<rootDir>/node_modules/react-dom",
    "^react-dom/test-utils$": "<rootDir>/node_modules/react-dom/test-utils",
    "^react-dom/client$": "<rootDir>/node_modules/react-dom/client",
  },
  testMatch: ["**/__tests__/**/*.test.{ts,tsx}", "**/src/**/*.test.{ts,tsx}"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.tsx"],
  modulePathIgnorePatterns: [
    "<rootDir>/../",
    "<rootDir>/node_modules/",
    "/Downloads/",
    "/onepay-monitoring/",
  ],
  watchPathIgnorePatterns: [
    "<rootDir>/../",
    "<rootDir>/node_modules/",
  ],
  transformIgnorePatterns: [
    "node_modules/(?!(uuid|@testing-library|lucide-react)/)",
  ],
  haste: {
    throwOnModuleCollision: false,
    retainAllFiles: false,
  },
  testPathIgnorePatterns: [
    "<rootDir>/../",
    "<rootDir>/node_modules/",
    "/Downloads/",
    "/onepay-monitoring/",
  ],
};
