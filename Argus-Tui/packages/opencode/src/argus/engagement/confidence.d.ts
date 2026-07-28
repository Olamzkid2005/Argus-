import { Confidence } from "../shared/types";
import type { NormalizedFinding } from "../shared/types";
export declare class ConfidenceEngine {
    promote(finding: NormalizedFinding): Confidence;
    shouldFinalize(finding: NormalizedFinding): boolean;
}
