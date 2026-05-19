"use client";

import type { ReactNode } from "react";

interface LayoutShellProps {
  children: ReactNode;
}

const LAYOUT_CLASSES =
  "mx-auto flex min-h-screen flex-col bg-zinc-950 text-zinc-100 antialiased";

/**
 * Terminal layout shell — full viewport, dark background, monospace stack.
 * Content area grows to fill available space and enables scroll for overflow.
 */
export function LayoutShell({ children }: LayoutShellProps) {
  return <div className={LAYOUT_CLASSES}>{children}</div>;
}