"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { cn } from "@/lib/utils";

type Variant = "danger" | "warning" | "default";

interface ConfirmButtonProps {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  variant?: Variant;
  disabled?: boolean;
  timeoutMs?: number;
}

const variantStyles: Record<Variant, string> = {
  danger:
    "border-red-800 text-red-400 hover:bg-red-950/40 data-[confirming=true]:bg-red-950/60 data-[confirming=true]:border-red-600 data-[confirming=true]:text-red-300",
  warning:
    "border-amber-800 text-amber-400 hover:bg-amber-950/40 data-[confirming=true]:bg-amber-950/60 data-[confirming=true]:border-amber-600 data-[confirming=true]:text-amber-300",
  default:
    "border-zinc-700 text-zinc-300 hover:bg-zinc-800/60 data-[confirming=true]:bg-sky-950/40 data-[confirming=true]:border-sky-700 data-[confirming=true]:text-sky-300",
};

export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  variant = "default",
  disabled = false,
  timeoutMs = 3000,
}: ConfirmButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return clearTimer;
  }, [clearTimer]);

  const handleClick = () => {
    if (disabled) return;

    if (!confirming) {
      setConfirming(true);
      timerRef.current = setTimeout(() => {
        setConfirming(false);
      }, timeoutMs);
    } else {
      clearTimer();
      setConfirming(false);
      onConfirm();
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={disabled}
      data-confirming={confirming}
      className={cn(
        "rounded border px-2.5 py-1 text-[11px] font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-40",
        variantStyles[variant],
      )}
    >
      {confirming ? confirmLabel : label}
    </button>
  );
}