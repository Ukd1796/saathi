"use client";

import { CheckCircle2, AlertCircle } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Toast = { id: number; text: string; tone: "good" | "bad" };
const ToastContext = createContext<(text: string, tone?: "good" | "bad") => void>(() => {});

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "good" | "bad" = "good") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto flex items-start gap-2 rounded-xl border border-line bg-card px-4 py-3 text-sm text-ink shadow-xl [animation:toast-in_.2s_ease-out]">
            {t.tone === "good" ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-good" /> : <AlertCircle size={18} className="mt-0.5 shrink-0 text-bad" />}
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
