/**
 * Validation script for frontend changes
 *
 * Checks:
 * 1. All new frontend pages compile without TypeScript errors
 * 2. Dashboard page imports are valid
 * 3. New API routes have valid TypeScript
 * 4. Unit tests pass
 */

const { execSync } = require("child_process");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

function run(cmd, options = {}) {
  try {
    const output = execSync(cmd, {
      cwd: ROOT,
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
      ...options,
    });
    return { success: true, output };
  } catch (error) {
    return { success: false, output: error.stdout || "", stderr: error.stderr || "" };
  }
}

function filterErrors(output, patterns) {
  const lines = output.split("\n");
  return lines.filter((line) => {
    return patterns.some((pattern) => line.includes(pattern));
  });
}

function checkTscForFiles(patterns, label) {
  console.log(`\n=== ${label} ===`);
  const result = run("npx tsc --noEmit");
  const errors = filterErrors(result.stderr || result.output, patterns);

  if (errors.length === 0) {
    console.log(`✅ No TypeScript errors in ${label}`);
    return true;
  }

  console.log(`❌ TypeScript errors found in ${label}:`);
  errors.forEach((line) => console.log(`  ${line.trim()}`));
  return false;
}

function checkTests() {
  console.log("\n=== Running unit tests ===");
  const jestBin = path.join(ROOT, "node_modules", ".bin", "jest");
  const configPath = path.join(ROOT, "jest.config.js");
  const cmd = `${jestBin} --config ${configPath} src/lib/__tests__ --no-coverage`;
  const result = run(cmd);
  if (result.success) {
    console.log("✅ All unit tests passed");
    return true;
  }
  console.log("❌ Tests failed:");
  console.log(result.output || result.stderr);
  return false;
}

// Main
console.log("Frontend Validation Script");
console.log("==========================");

const newPages = [
  "src/app/dashboard/page.tsx",
  "src/app/dashboard/layout.tsx",
  "src/app/analytics/page.tsx",
  "src/app/reports/page.tsx",
  "src/app/reports/compliance/page.tsx",
  "src/app/settings/page.tsx",
  "src/app/engagements/page.tsx",
  "src/app/findings/page.tsx",
];

const newApiRoutes = [
  "src/app/api/ws/engagement/[id]/poll/route.ts",
  "src/app/api/ws/engagement/[id]/route.ts",
  "src/app/api/dashboard/stats/route.ts",
  "src/app/api/analytics/route.ts",
  "src/app/api/engagement/[id]/timeline/route.ts",
  "src/app/api/engagement/[id]/explainability/route.ts",
  "src/app/api/tools/performance/route.ts",
  "src/app/api/reports/compliance/route.ts",
  "src/app/api/settings/route.ts",
];

const libFiles = [
  "src/lib/cache.ts",
  "src/lib/websocket.ts",
  "src/lib/websocket-events.ts",
];

const testFiles = [
  "src/lib/__tests__/cache.test.ts",
  "src/lib/__tests__/websocket.test.ts",
];

const allChecked = [...newPages, ...newApiRoutes, ...libFiles, ...testFiles];

const tsOk = checkTscForFiles(allChecked, "TypeScript compilation for new files");
const testsOk = checkTests();

console.log("\n==========================");
console.log("Summary:");
console.log(`  TypeScript compilation: ${tsOk ? "PASS" : "FAIL"}`);
console.log(`  Unit tests:             ${testsOk ? "PASS" : "FAIL"}`);

const exitCode = tsOk && testsOk ? 0 : 1;
process.exit(exitCode);
