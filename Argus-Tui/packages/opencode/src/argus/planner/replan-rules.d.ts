import type { PlannerContext } from "./types";
import { Capability } from "./capabilities";
/**
 * Chain-to-capability reference table — matches attack_graph.py CHAIN_RULES.
 *
 * NOTE: The actual chain→capability mapping happens server-side in
 * attack_graph.py's generate_plan_from_graph() via CHAIN_TO_CAPABILITIES.
 * This TypeScript map is kept as documentation of the expected chain IDs
 * and their associated capabilities. It is NOT directly consumed by the
 * planner — the planner reads `chainPlans` from the Python response.
 *
 * Chain IDs from attack_graph.py CHAIN_RULES mapped to exploitation capabilities.
 */
export declare const REPLAN_CHAINS: Record<string, Capability[]>;
export declare const REPLAN_INSERTABLE: Record<string, Capability>;
export declare function determineNewCapabilities(context: PlannerContext): Set<Capability>;
