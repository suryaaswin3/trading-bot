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
import type { PnLByStrategy } from "@/types/dashboard";

interface Props {
  data: PnLByStrategy[];
}

export function PnLByStrategyChart({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-600">
        No strategy PnL data yet
      </div>
    );
  }

  // Aggregate raw orders by strategy
  const aggregated: Record<string, { buys: number; sells: number; total: number }> = {};
  for (const row of data) {
    if (!aggregated[row.strategy]) {
      aggregated[row.strategy] = { buys: 0, sells: 0, total: 0 };
    }
    aggregated[row.strategy].total += 1;
    if (row.side === "buy") aggregated[row.strategy].buys += 1;
    else aggregated[row.strategy].sells += 1;
  }

  const chartData = Object.entries(aggregated)
    .map(([strategy, stats]) => ({
      strategy,
      trades: stats.total,
    }))
    .sort((a, b) => b.trades - a.trades);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={chartData} layout="vertical" margin={{ left: 100 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          type="number"
          tick={{ fontSize: 10, fill: "#a1a1aa" }}
        />
        <YAxis
          type="category"
          dataKey="strategy"
          tick={{ fontSize: 11, fill: "#a1a1aa" }}
          width={90}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #27272a",
            borderRadius: 6,
            fontSize: 12,
          }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={(value: any) => [`${value} trades`]}
        />
        <Bar
          dataKey="trades"
          fill="#a855f7"
          radius={[0, 4, 4, 0]}
          maxBarSize={20}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}