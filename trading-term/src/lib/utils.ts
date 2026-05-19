import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Safely coerce unknown to array — returns [] for null/undefined/non-array. */
export function safeArray<T>(x: unknown): T[] {
  return Array.isArray(x) ? x : [];
}
