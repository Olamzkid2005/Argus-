import React from "react";
import { renderHook, act, render, screen, cleanup } from "@testing-library/react";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { KeyboardShortcutsHelp } from "@/components/ui-custom/KeyboardShortcutsHelp";

const mockPush = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: jest.fn(),
    refresh: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    prefetch: jest.fn(),
    pathname: "/",
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

describe("useKeyboardShortcuts", () => {
  afterEach(() => {
    cleanup();
    mockPush.mockClear();
  });

  const fireKeyDown = (options: {
    key: string;
    ctrlKey?: boolean;
    metaKey?: boolean;
    altKey?: boolean;
    target?: HTMLElement;
  }) => {
    const event = new KeyboardEvent("keydown", {
      key: options.key,
      ctrlKey: options.ctrlKey || false,
      metaKey: options.metaKey || false,
      altKey: options.altKey || false,
      bubbles: true,
    });
    const target = options.target || window;
    target.dispatchEvent(event);
  };

  // ── Hook exports ──

  it("should export showHelp and setShowHelp", () => {
    const { result } = renderHook(() => useKeyboardShortcuts());
    expect(result.current.showHelp).toBe(false);
    expect(typeof result.current.setShowHelp).toBe("function");
  });

  it("should toggle showHelp with setShowHelp", () => {
    const { result } = renderHook(() => useKeyboardShortcuts());
    act(() => {
      result.current.setShowHelp(true);
    });
    expect(result.current.showHelp).toBe(true);
    act(() => {
      result.current.setShowHelp(false);
    });
    expect(result.current.showHelp).toBe(false);
  });

  // ── Shortcut detection ──

  it("should call onToggleCommandPalette on Cmd+K", () => {
    const onToggleCommandPalette = jest.fn();
    renderHook(() => useKeyboardShortcuts({ onToggleCommandPalette }));
    act(() => {
      fireKeyDown({ key: "k", metaKey: true });
    });
    expect(onToggleCommandPalette).toHaveBeenCalledTimes(1);
  });

  it("should call onToggleCommandPalette on Ctrl+K", () => {
    const onToggleCommandPalette = jest.fn();
    renderHook(() => useKeyboardShortcuts({ onToggleCommandPalette }));
    act(() => {
      fireKeyDown({ key: "k", ctrlKey: true });
    });
    expect(onToggleCommandPalette).toHaveBeenCalledTimes(1);
  });

  it("should navigate to /engagements on Cmd+N", () => {
    renderHook(() => useKeyboardShortcuts());
    act(() => {
      fireKeyDown({ key: "n", metaKey: true });
    });
    expect(mockPush).toHaveBeenCalledWith("/engagements");
  });

  it("should navigate to /engagements on Ctrl+N", () => {
    renderHook(() => useKeyboardShortcuts());
    act(() => {
      fireKeyDown({ key: "n", ctrlKey: true });
    });
    expect(mockPush).toHaveBeenCalledWith("/engagements");
  });

  it("should call onExplainFinding on E", () => {
    const onExplainFinding = jest.fn();
    renderHook(() => useKeyboardShortcuts({ onExplainFinding }));
    act(() => {
      fireKeyDown({ key: "e" });
    });
    expect(onExplainFinding).toHaveBeenCalledTimes(1);
  });

  it("should call onVerifyFinding on V", () => {
    const onVerifyFinding = jest.fn();
    renderHook(() => useKeyboardShortcuts({ onVerifyFinding }));
    act(() => {
      fireKeyDown({ key: "v" });
    });
    expect(onVerifyFinding).toHaveBeenCalledTimes(1);
  });

  it("should show help modal on ?", () => {
    const { result } = renderHook(() => useKeyboardShortcuts());
    act(() => {
      fireKeyDown({ key: "?" });
    });
    expect(result.current.showHelp).toBe(true);
  });

  it("should close help modal on Escape when open", () => {
    const { result } = renderHook(() => useKeyboardShortcuts());
    act(() => {
      result.current.setShowHelp(true);
    });
    expect(result.current.showHelp).toBe(true);
    act(() => {
      fireKeyDown({ key: "Escape" });
    });
    expect(result.current.showHelp).toBe(false);
  });

  it("should call onClose on Escape when help modal is closed", () => {
    const onClose = jest.fn();
    renderHook(() => useKeyboardShortcuts({ onClose }));
    act(() => {
      fireKeyDown({ key: "Escape" });
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("should not call onClose on Escape when help modal is open", () => {
    const onClose = jest.fn();
    const { result } = renderHook(() => useKeyboardShortcuts({ onClose }));
    act(() => {
      result.current.setShowHelp(true);
    });
    act(() => {
      fireKeyDown({ key: "Escape" });
    });
    expect(result.current.showHelp).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
  });

  // ── Input field prevention ──

  it("should prevent shortcuts when typing in input", () => {
    const onToggleCommandPalette = jest.fn();
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    renderHook(() => useKeyboardShortcuts({ onToggleCommandPalette }));
    act(() => {
      fireKeyDown({ key: "k", metaKey: true, target: input });
    });
    expect(onToggleCommandPalette).not.toHaveBeenCalled();

    document.body.removeChild(input);
  });

  it("should prevent shortcuts when typing in textarea", () => {
    const onExplainFinding = jest.fn();
    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);
    textarea.focus();

    renderHook(() => useKeyboardShortcuts({ onExplainFinding }));
    act(() => {
      fireKeyDown({ key: "e", target: textarea });
    });
    expect(onExplainFinding).not.toHaveBeenCalled();

    document.body.removeChild(textarea);
  });

  it("should prevent shortcuts in select elements", () => {
    const onToggleCommandPalette = jest.fn();
    const select = document.createElement("select");
    document.body.appendChild(select);
    select.focus();

    renderHook(() => useKeyboardShortcuts({ onToggleCommandPalette }));
    act(() => {
      fireKeyDown({ key: "k", metaKey: true, target: select });
    });
    expect(onToggleCommandPalette).not.toHaveBeenCalled();

    document.body.removeChild(select);
  });

  it("should still allow shortcuts outside of input elements", () => {
    const onToggleCommandPalette = jest.fn();
    renderHook(() => useKeyboardShortcuts({ onToggleCommandPalette }));
    act(() => {
      fireKeyDown({ key: "k", metaKey: true });
    });
    expect(onToggleCommandPalette).toHaveBeenCalledTimes(1);
  });
});

describe("KeyboardShortcutsHelp", () => {
  afterEach(() => {
    cleanup();
  });

  it("should render the help modal when open", () => {
    render(<KeyboardShortcutsHelp open={true} onOpenChange={() => {}} />);
    expect(screen.getByText("Keyboard Shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Toggle command palette")).toBeInTheDocument();
    expect(screen.getByText("New Scan — navigate to engagements")).toBeInTheDocument();
    expect(screen.getByText("Explain selected finding")).toBeInTheDocument();
    expect(screen.getByText("Verify selected finding")).toBeInTheDocument();
    expect(screen.getByText("Show keyboard shortcuts help")).toBeInTheDocument();
    expect(screen.getByText("Close modals / panels")).toBeInTheDocument();
  });

  it("should not render content when closed", () => {
    const { container } = render(
      <KeyboardShortcutsHelp open={false} onOpenChange={() => {}} />
    );
    expect(container.querySelector("[data-slot='dialog-content']")).not.toBeInTheDocument();
  });
});
