/** @type {import('ts-jest').JestConfigWithTsJest} **/
module.exports = {
  rootDir: "/Users/mac/Documents/Argus-/argus-platform",
  roots: ["<rootDir>/src"],
  testEnvironment: "node",
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      { tsconfig: "/Users/mac/Documents/Argus-/argus-platform/tsconfig.test.json" },
    ],
  },
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testMatch: ["**/__tests__/**/*.test.ts"],
};
