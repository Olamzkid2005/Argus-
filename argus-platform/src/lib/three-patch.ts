/**
 * Three.js r184+ Compatibility Patch
 * 
 * Newer versions of Three.js surface a deprecation warning for THREE.Clock.
 * Since React-Three-Fiber instantiates this internally, we cannot easily prevent it.
 * This patch intercepts console warnings/errors to prevent Next.js from surfacing 
 * a disruptive Error overlay during development for this specific, harmless warning.
 */
export function applyThreePatch() {
  if (typeof window === "undefined") return;

  const filterMessage = (args: any[]) => {
    if (typeof args[0] === 'string' && args[0].includes('THREE.Clock: This module has been deprecated')) {
      return true;
    }
    return false;
  };

  const originalWarn = console.warn;
  console.warn = function (...args) {
    if (filterMessage(args)) return;
    originalWarn.apply(console, args);
  };

  const originalError = console.error;
  console.error = function (...args) {
    if (filterMessage(args)) return;
    originalError.apply(console, args);
  };
}
