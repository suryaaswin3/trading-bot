"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { RejectionStat } from "@/types/dashboard";

interface Props {
  data: RejectionStat[];
}

export function RejectionStatsChart({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-600">
        No rejection data yet
      </div>
    );
  }

  const chartData = data.map((r) => ({
    reason: r.rejection_reason,
    count: r.count,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={chartData} layout="vertical" margin={{ left: 120 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          type="number"
          tick={{ fontSize: 10, fill: "#a1a1aa" }}
        />
        <YAxis
          type="category"
          dataKey="reason"
          tick={{ fontSize: 10, fill: "#a1a1aa" }}
          width={110}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #27272a",
            borderRadius: 6,
            fontSize: 12,
          }}
        />
        <Bar dataKey="count" fill="#f59e0b" radius={[0, 4, 4, 0]} maxBarSize={20} />
      </BarChart>
    </ResponsiveContainer>
  );
}