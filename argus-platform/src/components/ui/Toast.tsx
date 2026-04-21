"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { X, CheckCircle2, AlertCircle, Info, AlertTriangle } from "lucide-react";

interface Toast {
  id: string;
  type: "success" | "error" | "info" | "warning";
  message: string;
}

interface ToastContextType {
  showToast: (type: Toast["type"], message: string) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = useCallback((type: Toast["type"], message: string) => {
    const id = Math.random().toString(36).substring(7);
    setToasts((prev) => [...prev, { id, type, message }]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
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

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toasts.length > 0 && (
        <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-3">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`flex items-center gap-4 px-5 py-4 border backdrop-blur-xl shadow-2xl animate-in fade-in slide-in-from-right-8 duration-300 ${getStyles(toast.type)}`}
              style={{ borderRadius: '2px' }}
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
              >
                <X className="h-3.5 w-3.5 text-text-secondary" />
              </button>
              
              {/* Progress bar line */}
              <div className="absolute bottom-0 left-0 h-[1px] bg-prism-cream/30 animate-[shrink_5s_linear_forwards]" style={{ width: '100%' }} />
            </div>
          ))}
        </div>
      )}
      <style jsx global>{`
        @keyframes shrink {
          from { width: 100%; }
          to { width: 0%; }
        }
      `}</style>
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
