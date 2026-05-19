import { TopStatusBar } from "@/components/TopStatusBar";
import { ExecutionFeed } from "@/components/ExecutionFeed";
import { PositionPanel } from "@/components/PositionPanel";
import { PnLRiskPanel } from "@/components/PnLRiskPanel";
import { SignalFeed } from "@/components/SignalFeed";
import { ControlsPanel } from "@/components/ControlsPanel";

export default function Home() {
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

        {/* Controls — API-key-protected action buttons */}
        <ControlsPanel />

        <footer className="mt-auto border-t border-zinc-800 pt-2 text-center text-[11px] text-zinc-700">
          Trading Terminal &middot; v0.2.0
        </footer>
      </main>
    </>
  );
}