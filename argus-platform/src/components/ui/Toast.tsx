"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  ReactNode,
} from "react";
import { X, CheckCircle2, AlertCircle, Info, AlertTriangle } from "lucide-react";

const MAX_TOASTS = 5;
const TOAST_DURATION = 5000;

interface Toast {
  id: string;
  type: "success" | "error" | "info" | "warning";
  message: string;
  createdAt: number;
}

interface ToastContextType {
  showToast: (type: Toast["type"], message: string) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [pausedId, setPausedId] = useState<string | null>(null);
  const timersRef = useRef<Map<string, NodeJS.Timeout>>(new Map());

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const showToast = useCallback((type: Toast["type"], message: string) => {
    const id = crypto.randomUUID();
    const createdAt = Date.now();

    setToasts((prev) => {
      const newToasts = [...prev, { id, type, message, createdAt }];
      // Keep only the last MAX_TOASTS
      if (newToasts.length > MAX_TOASTS) {
        return newToasts.slice(-MAX_TOASTS);
      }
      return newToasts;
    });

    // Auto-remove after duration (unless paused)
    const timer = setTimeout(() => {
      if (pausedId !== id) {
        removeToast(id);
      }
    }, TOAST_DURATION);
    timersRef.current.set(id, timer);
  }, [pausedId, removeToast]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => clearTimeout(timer));
      timersRef.current.clear();
    };
  }, []);

  const getIcon = (type: Toast["type"]) => {
    switch (type) {
      case "success":
        return <CheckCircle2 className="h-4 w-4 text-[#00FF88]" />;
      case "error":
        return <AlertCircle className="h-4 w-4 text-[#FF4444]" />;
      case "warning":
        return <AlertTriangle className="h-4 w-4 text-[#FF8800]" />;
      case "info":
        return <Info className="h-4 w-4 text-prism-cyan" />;
    }
  };

  const getStyles = (type: Toast["type"]) => {
    switch (type) {
      case "success":
        return "border-[#00FF88]/20 bg-void/90";
      case "error":
        return "border-[#FF4444]/20 bg-void/90";
      case "warning":
        return "border-[#FF8800]/20 bg-void/90";
      case "info":
        return "border-prism-cyan/20 bg-void/90";
    }
  };

  const getAriaRole = (type: Toast["type"]) => {
    switch (type) {
      case "error":
        return "alert";
      default:
        return "status";
    }
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toasts.length > 0 && (
        <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-3 max-w-[420px]">
          {toasts.map((toast) => {
            const elapsed = Date.now() - toast.createdAt;
            const remaining = Math.max(0, TOAST_DURATION - elapsed);
            const progressWidth = (remaining / TOAST_DURATION) * 100;

            return (
              <div
                key={toast.id}
                role={getAriaRole(toast.type)}
                aria-live={toast.type === "error" ? "assertive" : "polite"}
                className={`relative flex items-center gap-4 px-5 py-4 border backdrop-blur-xl shadow-2xl animate-in fade-in slide-in-from-right-8 duration-300 ${getStyles(toast.type)}`}
                style={{ borderRadius: '2px' }}
                onMouseEnter={() => {
                  setPausedId(toast.id);
                }}
                onMouseLeave={() => {
                  setPausedId(null);
                }}
              >
                <div className="shrink-0">{getIcon(toast.type)}</div>
                <div className="flex-1 min-w-[200px]">
                  <div className="text-[10px] font-mono font-bold uppercase tracking-widest text-text-secondary mb-0.5">
                    System Notification
                  </div>
                  <div className="text-[12px] font-mono text-text-primary tracking-tight">
                    {toast.message}
                  </div>
                </div>
                <button
                  onClick={() => removeToast(toast.id)}
                  className="shrink-0 p-1 hover:bg-white/5 transition-colors"
                  aria-label="Dismiss notification"
                >
                  <X className="h-3.5 w-3.5 text-text-secondary" />
                </button>
               
               {/* Progress bar line */}
               <div className="absolute bottom-0 left-0 h-[1px] bg-prism-cream/30" style={{ width: `${progressWidth}%`, transition: 'width 0.1s linear' }} />
              </div>
            );
          })}
        </div>
      )}
    </ToastContext.Provider>
  );
}

function useToastInternal() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
}

export { ToastProvider as default, useToastInternal as useToast };
