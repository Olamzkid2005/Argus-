/**
 * Report Dashboard — Generate and view assessment reports.
 *
 * Loads an engagement and its findings from the EngagementStore,
 * generates a markdown report via ReportGenerator, and displays
 * the rendered report in a scrollable terminal viewer.
 */
interface ReportDashboardProps {
    engagementId: string;
}
export declare function ReportDashboard(props: ReportDashboardProps): import("solid-js").JSX.Element;
export default ReportDashboard;
