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

interface DailyPnlRow {
  date: string;
  daily_pnl: number;
  trades_today: number;
}

interface Props {
  data: DailyPnlRow[];
}

export function DailyPnLChart({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-600">
        No daily PnL data yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          dataKey="date"
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
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={(value: any, _name: any, props: any) => [
            `$${value.toFixed(2)}`,
            `${props.payload.trades_today} trades`,
          ]}
        />
        <Bar
          dataKey="daily_pnl"
          radius={[4, 4, 0, 0]}
          maxBarSize={24}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          shape={(props: any) => {
            const { x, y, width, height, payload } = props;
            const fill = payload.daily_pnl >= 0 ? "#22c55e" : "#ef4444";
            return (
              <rect x={x} y={y} width={width} height={height} fill={fill} rx={4} />
            );
          }}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}