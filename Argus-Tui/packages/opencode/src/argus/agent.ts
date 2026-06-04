/**
 * ArgusAgent — Facade over the Argus intent detection and routing system.
 *
 * This module combines the three routing components for convenient importing:
 *   - ArgusIntentClassifier  (natural language → assessment or chat)
 *   - ArgusCommandRouter     (slash commands → command execution)
 *   - ArgusWorkflowRunner    (assessment execution → findings)
 *
 * Flow:
 *   User Input
 *       ↓
 *   ArgusCommandRouter
 *       ↓
 *   Slash Command?
 *       ├─ yes → command handler
 *       └─ no
 *              ↓
 *       IntentClassifier
 *              ↓
 *       Assessment?
 *           ├─ yes → WorkflowRunner
 *           └─ no  → pass to LLM
 */

export { classify, detectSlashCommand, SLASH_COMMANDS } from "./intent-classifier"
export type { ClassifiedIntent } from "./intent-classifier"

export { WorkflowRunner } from "./workflow-runner"
export type { WorkflowRunOptions, WorkflowRunResult } from "./workflow-runner"

export { getArgusTuiCommands, findArgusTuiCommand } from "./tui-commands"
export type { ArgusTuiCommand } from "./tui-commands"
