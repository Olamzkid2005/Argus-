import { useTheme } from "@tui/context/theme";
interface FindingRow {
    id: string;
    title: string;
    severity: number;
    confidence: number;
    description: string;
    tool: string;
    phase: string;
    status: string;
    cwe?: string;
    owasp?: string;
    remediation?: string;
    createdAt: string;
    evidenceCount?: number;
}
export declare function FindingCard(props: {
    finding: FindingRow;
    theme: ReturnType<typeof useTheme>["theme"];
}): import("solid-js").JSX.Element;
export declare function FindingsViewer(): import("solid-js").JSX.Element;
export default FindingsViewer;
