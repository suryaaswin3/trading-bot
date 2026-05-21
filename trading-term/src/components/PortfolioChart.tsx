"use client";

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface PositionSlice {
  symbol: string;
  exposure_pct: number;
  side: string;
}

interface Props {
  positions: PositionSlice[];
}

const COLORS = ["#a855f7", "#22c55e", "#3b82f6", "#f59e0b", "#ef4444", "#ec4899", "#14b8a6", "#84cc16"];

export function PortfolioChart({ positions }: Props) {
  if (!positions || positions.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-600">
        No positions to display
      </div>
    );
  }

  const data = positions.map((p) => ({
    name: `${p.symbol} (${p.side})`,
    value: Math.abs(p.exposure_pct),
    exposure_pct: p.exposure_pct,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={90}
          dataKey="value"
          paddingAngle={2}
        >
          {data.map((_entry, idx) => (
            <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #27272a",
            borderRadius: 6,
            fontSize: 12,
          }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={(_value: any, _name: any, props: any) => [
            `${props.payload.exposure_pct.toFixed(1)}%`,
            props.payload.name,
          ]}
        />
        <Legend
          wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}