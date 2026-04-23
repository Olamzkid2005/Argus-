import { renderHook, act } from "@testing-library/react";
import { useScanEstimates } from "@/hooks/useScanEstimates";

describe("useScanEstimates", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("calculates phase estimates with default config", () => {
    const { result } = renderHook(() =>
      useScanEstimates("scanning", {}, "2024-01-01T00:00:00.000Z")
    );

    expect(result.current.phaseEstimates).toHaveLength(4);
    expect(result.current.phaseEstimates[0].id).toBe("recon");
    expect(result.current.phaseEstimates[0].label).toBe("Reconnaissance");
    expect(result.current.phaseEstimates[0].estimatedMinutes).toBeGreaterThanOrEqual(2);
    expect(result.current.totalEstimatedMinutes).toBeGreaterThan(0);
  });

  it("adjusts estimates based on target type and aggressiveness", () => {
    const { result: defaultResult } = renderHook(() =>
      useScanEstimates("scanning", { targetType: "default", aggressiveness: "medium" }, "2024-01-01T00:00:00.000Z")
    );

    const { result: highAggro } = renderHook(() =>
      useScanEstimates("scanning", { targetType: "network", aggressiveness: "high" }, "2024-01-01T00:00:00.000Z")
    );

    expect(highAggro.current.totalEstimatedMinutes).toBeGreaterThan(defaultResult.current.totalEstimatedMinutes);
  });

  it("tracks elapsed time", () => {
    const startTime = new Date().toISOString();
    const { result } = renderHook(() =>
      useScanEstimates("scanning", {}, startTime)
    );

    expect(result.current.elapsedMs).toBe(0);

    act(() => {
      jest.advanceTimersByTime(5000);
    });

    expect(result.current.elapsedMs).toBeGreaterThanOrEqual(5000);
    expect(result.current.elapsedFormatted).toBe("5s");
  });

  it("calculates remaining time for current phase", () => {
    const startTime = new Date(Date.now() - 3 * 60 * 1000).toISOString();
    const { result } = renderHook(() =>
      useScanEstimates("scanning", {}, startTime)
    );

    expect(result.current.remainingMs).toBeGreaterThan(0);
    expect(result.current.remainingFormatted).toBeTruthy();
  });

  it("returns zero remaining when no active phase", () => {
    const { result } = renderHook(() =>
      useScanEstimates("complete", {}, new Date().toISOString())
    );

    expect(result.current.remainingMs).toBe(0);
    expect(result.current.remainingFormatted).toBe("0s");
  });

  it("calculates phase progress correctly", () => {
    const startTime = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    const { result } = renderHook(() =>
      useScanEstimates("scanning", {}, startTime)
    );

    expect(result.current.getPhaseProgress("recon")).toBe(100);
    expect(result.current.getPhaseProgress("fingerprinting")).toBeGreaterThan(0);
    expect(result.current.getPhaseProgress("fingerprinting")).toBeLessThanOrEqual(100);
    expect(result.current.getPhaseProgress("vuln_mapping")).toBe(0);
  });

  it("returns phase completion times for completed phases", () => {
    const startTime = new Date().toISOString();
    const { result } = renderHook(() =>
      useScanEstimates("scanning", {}, startTime)
    );

    const reconTime = result.current.getPhaseCompletionTime("recon");
    expect(reconTime).toBeInstanceOf(Date);
    expect(reconTime!.getTime()).toBeGreaterThan(new Date(startTime).getTime());

    const fingerprintingTime = result.current.getPhaseCompletionTime("fingerprinting");
    expect(fingerprintingTime).toBeNull();
  });

  it("builds phase history for completed phases only", () => {
    const startTime = new Date().toISOString();
    const { result } = renderHook(() =>
      useScanEstimates("analyzing", {}, startTime)
    );

    expect(result.current.phaseHistory.length).toBeGreaterThanOrEqual(2);
    expect(result.current.phaseHistory.every((p) => p.status === "completed")).toBe(true);
  });
});
