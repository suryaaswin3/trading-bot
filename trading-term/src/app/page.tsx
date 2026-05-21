"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, BarChart3 } from "lucide-react";
import { TopStatusBar } from "@/components/TopStatusBar";
import { ExecutionFeed } from "@/components/ExecutionFeed";
import { PositionPanel } from "@/components/PositionPanel";
import { PnLRiskPanel } from "@/components/PnLRiskPanel";
import { SignalFeed } from "@/components/SignalFeed";
import { ControlsPanel } from "@/components/ControlsPanel";
import { EquityCurveChart } from "@/components/EquityCurveChart";
import { PnLByStrategyChart } from "@/components/PnLByStrategyChart";
import { RejectionStatsChart } from "@/components/RejectionStatsChart";
import { DailyPnLChart } from "@/components/DailyPnLChart";
import { PortfolioChart } from "@/components/PortfolioChart";
import { useDashboardData } from "@/hooks/useDashboardData";

export default function Home() {
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const { data } = useDashboardData();

  return (
    <>
      <TopStatusBar />
      <main className="flex flex-1 flex-col gap-4 p-3 md:p-4 lg:p-6">
        {/* Primary area: execution feed + right sidebar */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          {/* Execution feed — primary focus, 3/5 width */}
          <div className="lg:col-span-3">
            <ExecutionFeed />
          </div>

          {/* Right sidebar — position + PnL stacked */}
          <div className="flex flex-col gap-4 lg:col-span-2">
            <PositionPanel />
            <PnLRiskPanel />
          </div>
        </div>

        {/* Signal feed — full width below */}
        <SignalFeed />

        {/* Analytics section — collapsible */}
        <section className="rounded-lg border border-zinc-800 bg-zinc-900/50">
          <button
            onClick={() => setAnalyticsOpen(!analyticsOpen)}
            className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-zinc-400 hover:text-zinc-200"
          >
            {analyticsOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <BarChart3 size={16} />
            Analytics
          </button>

          {analyticsOpen && (
            <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2">
              {/* Equity Curve */}
              <div className="h-64 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                <h3 className="mb-2 text-xs font-medium text-zinc-500 uppercase tracking-wider">Equity Curve</h3>
                <EquityCurveChart data={data?.equity_curve ?? []} />
              </div>

              {/* PnL by Strategy */}
              <div className="h-64 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                <h3 className="mb-2 text-xs font-medium text-zinc-500 uppercase tracking-wider">PnL by Strategy</h3>
                <PnLByStrategyChart data={data?.pnl_by_strategy ?? []} />
              </div>

              {/* Rejection Stats */}
              <div className="h-64 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                <h3 className="mb-2 text-xs font-medium text-zinc-500 uppercase tracking-wider">Rejection Reasons</h3>
                <RejectionStatsChart data={data?.rejection_stats ?? []} />
              </div>

              {/* Daily PnL */}
              <div className="h-64 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                <h3 className="mb-2 text-xs font-medium text-zinc-500 uppercase tracking-wider">Daily PnL (30 days)</h3>
                <DailyPnLChart data={data?.daily_pnl_history ?? []} />
              </div>

              {/* Portfolio Composition */}
              <div className="h-64 rounded-lg border border-zinc-800 bg-zinc-950 p-3 md:col-span-2">
                <h3 className="mb-2 text-xs font-medium text-zinc-500 uppercase tracking-wider">Portfolio Composition</h3>
                <PortfolioChart
                  positions={
                    data?.positions?.map((p) => ({
                      symbol: p.symbol,
                      exposure_pct: p.quantity * p.entry_price / (data?.portfolio_snapshot?.total_exposure ?? 1) * 100,
                      side: p.side,
                    })) ?? []
                  }
                />
              </div>
            </div>
          )}
        </section>

        {/* Controls — API-key-protected action buttons */}
        <ControlsPanel />

        <footer className="mt-auto border-t border-zinc-800 pt-2 text-center text-[11px] text-zinc-700">
          Trading Terminal &middot; v0.2.0
        </footer>
      </main>
    </>
  );
}