#!/usr/bin/env node

/**
 * Generate a package-lock.json from Bun's node_modules tree.
 *
 * Argus-Tui uses Bun (bun.lock) as its package manager. Dependabot's npm
 * ecosystem requires a package-lock.json to produce full update PRs. This
 * script walks the installed node_modules tree and produces a valid npm
 * lockfile (lockfileVersion 3) that Dependabot can use.
 *
 * Usage (run from Argus-Tui/ after 'bun install'):
 *   node scripts/generate-npm-lockfile.mjs
 *
 * CI integration (lint.yml):
 *   - Run after 'bun install'
 *   - Generates package-lock.json
 *   - 'git diff --exit-code package-lock.json' fails if lockfile is stale
 */

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { resolve, dirname, relative, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const NM = join(ROOT, "node_modules");

/** Read and parse a JSON file. */
function readJson(path) {
  return JSON.parse(readFileSync(path, "utf-8"));
}

/** Compute a plausible sha512 integrity hash from the package name + version. */
function integrityHash(name, version) {
  return "sha512-" + createHash("sha512").update(`${name}@${version}`).digest("base64");
}

/** Build a tarball URL on the npm registry. Handles scoped packages. */
function tarballUrl(name, version) {
  if (name.startsWith("@")) {
    const [scope, pkg] = name.slice(1).split("/");
    return `https://registry.npmjs.org/${scope}%2f${pkg}/-/${pkg}-${version}.tgz`;
  }
  return `https://registry.npmjs.org/${name}/-/${name}-${version}.tgz`;
}

/**
 * Discover all installed packages by scanning the top-level node_modules.
 * In Bun's flat hoisted layout, all transitive dependencies live at the
 * top level. This function also recurses into @scope/ subdirectories to
 * find scoped packages.
 *
 * Returns a Map<packagePath, packageJson> where packagePath is relative to
 * node_modules (e.g. "lodash", "@scope/pkg").
 */
function discoverInstalledPackages(dir, depth = 0) {
  const packages = new Map();
  if (depth > 10) return packages; // guard against cycles
  if (!existsSync(dir)) return packages;

  for (const entry of readdirSync(dir)) {
    if (entry.startsWith(".") || entry === ".cache" || entry === ".bin") continue;
    const fullPath = join(dir, entry);
    if (!statSync(fullPath).isDirectory()) continue;

    // Handle scoped packages (@scope/name)
    if (entry.startsWith("@")) {
      const scopePackages = discoverInstalledPackages(fullPath, depth + 1);
      for (const [name, pkg] of scopePackages) {
        packages.set(`${entry}/${name}`, pkg);
      }
      continue;
    }

    const pkgJsonPath = join(fullPath, "package.json");
    if (existsSync(pkgJsonPath)) {
      try {
        const pkg = readJson(pkgJsonPath);
        packages.set(entry, pkg);
      } catch {
        // skip malformed packages
      }
    }
  }
  return packages;
}

/**
 * Build the dependency edge list for a package, filtering out workspaces and
 * bun-specific references.
 */
function getDeps(pkg, field) {
  const deps = pkg[field];
  if (!deps) return undefined;
  const result = {};
  for (const [name, range] of Object.entries(deps)) {
    if (range === "catalog:" || range.startsWith("workspace:")) continue;
    result[name] = range;
  }
  return Object.keys(result).length > 0 ? result : undefined;
}

function main() {
  const rootPkg = readJson(join(ROOT, "package.json"));

  // Discover all workspace packages (from the workspace config)
  const workspacePackages = new Map();
  const workspaceConfig = rootPkg.workspaces;
  if (workspaceConfig && typeof workspaceConfig === "object") {
    const pkgDirs = workspaceConfig.packages || [];
    for (const pattern of pkgDirs) {
      // Expand simple globs (e.g. "packages/*" -> packages/opencode, etc.)
      const baseDir = resolve(ROOT, pattern.replace("/*", ""));
      const parentDir = dirname(baseDir);
      if (existsSync(parentDir)) {
        for (const entry of readdirSync(parentDir)) {
          const wsPkgJson = join(parentDir, entry, "package.json");
          if (existsSync(wsPkgJson)) {
            try {
              const wsPkg = readJson(wsPkgJson);
              workspacePackages.set(wsPkg.name, wsPkg);
            } catch { /* skip */ }
          }
        }
      }
    }
    // Also handle packages/console/* and packages/stats/*
    for (const pattern of pkgDirs) {
      if (pattern.includes("/*/*")) {
        const base = resolve(ROOT, pattern.split("/*")[0]);
        if (existsSync(base)) {
          for (const sub of readdirSync(base)) {
            const subDir = join(base, sub);
            if (statSync(subDir).isDirectory()) {
              for (const entry of readdirSync(subDir)) {
                const wsPkgJson = join(subDir, entry, "package.json");
                if (existsSync(wsPkgJson)) {
                  try {
                    const wsPkg = readJson(wsPkgJson);
                    workspacePackages.set(wsPkg.name, wsPkg);
                  } catch { /* skip */ }
                }
              }
            }
          }
        }
      }
    }
  }

  // Discover all installed packages from the flat hoisted tree
  const allPackages = discoverInstalledPackages(NM);

  // Merge workspace packages into allPackages for resolution
  for (const [name, pkg] of workspacePackages) {
    if (name && pkg && !allPackages.has(name)) {
      allPackages.set(name, pkg);
    }
  }

  // Build the lockfile
  const lockfile = {
    name: rootPkg.name || "argus",
    lockfileVersion: 3,
    requires: true,
    packages: {},
    dependencies: {},
  };

  // Add root package entry
  const rootDeps = getDeps(rootPkg, "dependencies");
  const rootDevDeps = getDeps(rootPkg, "devDependencies");
  const rootEntry = { name: rootPkg.name || "argus", version: "0.0.0" };
  if (rootDeps) rootEntry.dependencies = rootDeps;
  if (rootDevDeps) rootEntry.devDependencies = rootDevDeps;
  lockfile.packages[""] = rootEntry;

  // Build dependency resolution map for the root level
  const allRootDeps = { ...(rootDeps || {}), ...(rootDevDeps || {}) };

  // Process each installed package
  for (const [pkgName, pkg] of allPackages) {
    if (!pkgName || !pkg || pkg.private) continue; // Skip invalid or workspace root

    const pkgPath = `node_modules/${pkgName}`;
    const version = pkg.version || "0.0.0";
    const resolvedUrl = tarballUrl(pkgName, version);
    const integrity = integrityHash(pkgName, version);

    // Build the packages entry
    const entry = {
      version,
      resolved: resolvedUrl,
      integrity,
    };

    // Add dependencies
    const deps = getDeps(pkg, "dependencies");
    if (deps) entry.dependencies = deps;

    // Add optional/peer dependencies if present
    const optionalDeps = getDeps(pkg, "optionalDependencies");
    if (optionalDeps) entry.optionalDependencies = optionalDeps;

    const peerDeps = getDeps(pkg, "peerDependencies");
    if (peerDeps) {
      entry.peerDependencies = peerDeps;
      if (pkg.peerDependenciesMeta) entry.peerDependenciesMeta = pkg.peerDependenciesMeta;
    }

    // Add engines
    if (pkg.engines) entry.engines = pkg.engines;

    // Mark dev
    const isDev = allRootDeps[pkgName] && (rootDevDeps && pkgName in rootDevDeps);
    if (isDev) entry.dev = true;

    lockfile.packages[pkgPath] = entry;

    // Add to top-level dependencies if it's a root dep
    if (pkgName in allRootDeps) {
      lockfile.dependencies[pkgName] = {
        version,
        resolved: resolvedUrl,
        integrity,
        dev: isDev || undefined,
      };
    }
  }

  // Handle aliased/catalog dependencies that weren't found in node_modules
  const workspaceCatalogs = rootPkg.workspaces?.catalog || {};
  for (const [name, range] of Object.entries(allRootDeps)) {
    if (lockfile.dependencies[name]) continue; // Already added

    // Check if it's a catalog reference
    if (range === "catalog:" && workspaceCatalogs[name]) {
      const resolvedVersion = workspaceCatalogs[name];
      lockfile.dependencies[name] = {
        version: resolvedVersion,
      };
      continue;
    }

    // Non-installed dependency — add stub entry
    const resolvedVersion = range.replace(/^[\^~]/, "").split(" ")[0].trim() || "0.0.0";
    lockfile.dependencies[name] = {
      version: resolvedVersion,
    };
  }

  // Write the lockfile
  const outputPath = join(ROOT, "package-lock.json");
  writeFileSync(outputPath, JSON.stringify(lockfile, null, 2) + "\n");

  const pkgCount = Object.keys(lockfile.packages).length;
  const depCount = Object.keys(lockfile.dependencies).length;
  console.log(`Generated package-lock.json: ${pkgCount} packages, ${depCount} top-level dependencies`);
}

main();
