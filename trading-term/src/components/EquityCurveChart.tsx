"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";
import type { EquityPoint } from "@/types/dashboard";

interface Props {
  data: EquityPoint[];
}

export function EquityCurveChart({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-600">
        No equity data yet
      </div>
    );
  }

  const isPositive = (data[data.length - 1]?.realized_pnl ?? 0) >= 0;
  const color = isPositive ? "#22c55e" : "#ef4444";

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data}>
        <defs>
          <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          dataKey="timestamp"
          tick={{ fontSize: 10, fill: "#a1a1aa" }}
          tickFormatter={(v: string) => {
            try {
              return new Date(v).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              });
            } catch {
              return v;
            }
          }}
        />
        <YAxis tick={{ fontSize: 10, fill: "#a1a1aa" }} />
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #27272a",
            borderRadius: 6,
            fontSize: 12,
          }}
        />
        <Area
          type="monotone"
          dataKey="realized_pnl"
          stroke={color}
          strokeWidth={2}
          fill="url(#equityFill)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}