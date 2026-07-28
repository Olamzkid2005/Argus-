import type { TargetType, AuthState } from "./types";
import { Capability } from "./capabilities";
export declare function detectTargetType(url: string, techStack?: string[]): TargetType;
/**
 * Detects auth state from URL alone.
 *
 * NOTE: URL-only detection is unreliable — it may miss auth mechanisms that
 * don't appear in the URL (e.g., header-based, cookie-based, form-based auth).
 * This is a best-effort heuristic and should be supplemented with actual page
 * analysis when accuracy is critical.
 */
export declare function detectAuthState(url: string): AuthState;
export declare function determineRequiredCapabilities(targetType: TargetType, authState: AuthState, techStack?: string[]): Capability[];
