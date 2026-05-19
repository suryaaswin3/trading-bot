"use client";

import { useState, useCallback } from "react";
import { useDashboardData } from "@/hooks/useDashboardData";
import { postControlAction, setControlApiKey } from "@/lib/api";
import { ConfirmButton } from "./ConfirmButton";
import type { ControlResponse } from "@/types/dashboard";

function PanelShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/50">
      <div className="border-b border-zinc-800 px-3 py-1.5">
        <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">{title}</h2>
      </div>
      {children}
    </section>
  );
}

type ActionState = {
  running: boolean;
  result: string | null;
  error: string | null;
};

export function ControlsPanel() {
  const [apiKey, setApiKey] = useState("");
  const [keySubmitted, setKeySubmitted] = useState(false);
  const [states, setStates] = useState<Record<string, ActionState>>({});
  const dashboard = useDashboardData();

  const updateState = useCallback(
    (action: string, partial: Partial<ActionState>) => {
      setStates((prev) => ({
        ...prev,
        [action]: { ...prev[action], ...partial } as ActionState,
      }));
    },
    [],
  );

  const handleSubmitKey = () => {
    const trimmed = apiKey.trim();
    if (!trimmed) return;
    setControlApiKey(trimmed);
    setKeySubmitted(true);
  };

  const handleAction = async (action: string) => {
    updateState(action, { running: true, result: null, error: null });
    const res = await postControlAction(action);
    if (res.error) {
      updateState(action, { running: false, error: res.error });
    } else if (res.data) {
      updateState(action, { running: false, result: formatResult(res.data) });
    }
  };

  const actions: {
    key: string;
    label: string;
    confirmLabel: string;
    variant: "danger" | "warning" | "default";
  }[] = [
    { key: "kill", label: "Kill Switch", confirmLabel: "Confirm Kill?", variant: "danger" },
    { key: "reset_kill", label: "Reset Kill", confirmLabel: "Confirm Reset?", variant: "warning" },
    { key: "start", label: "Start Bot", confirmLabel: "Confirm Start?", variant: "default" },
    { key: "stop", label: "Stop Bot", confirmLabel: "Confirm Stop?", variant: "warning" },
    { key: "flatten", label: "Flatten", confirmLabel: "Confirm Flatten?", variant: "danger" },
  ];

  // Live state from dashboard data
  const statusText = dashboard.data?.bot_status ?? "--";
  const modeText = dashboard.data?.bot_mode ? String(dashboard.data.bot_mode).toUpperCase() : "--";
  const killActive = dashboard.data?.kill_switch?.active ?? false;

  return (
    <PanelShell title="Controls">
      {!keySubmitted ? (
        <div className="flex items-center gap-2 px-3 py-2">
          <input
            type="password"
            placeholder="API Key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmitKey()}
            className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-800/60 px-2 py-1 text-xs text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-500"
          />
          <button
            onClick={handleSubmitKey}
            disabled={!apiKey.trim()}
            className="rounded border border-zinc-700 px-2.5 py-1 text-[11px] font-medium text-zinc-300 transition-colors hover:bg-zinc-800/60 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Submit
          </button>
        </div>
      ) : (
        <div className="space-y-1.5 px-3 py-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {actions.map((a) => (
              <div key={a.key} className="flex flex-col gap-0.5">
                <ConfirmButton
                  label={a.label}
                  confirmLabel={a.confirmLabel}
                  variant={a.variant}
                  disabled={states[a.key]?.running}
                  onConfirm={() => handleAction(a.key)}
                />
                {states[a.key]?.running && (
                  <span className="text-[10px] text-zinc-600 animate-pulse">running...</span>
                )}
                {states[a.key]?.error && (
                  <span className="text-[10px] text-red-500">{states[a.key].error}</span>
                )}
                {states[a.key]?.result && (
                  <span className="text-[10px] text-emerald-500">{states[a.key].result}</span>
                )}
              </div>
            ))}
          </div>

          {/* Live bot status row */}
          <div className="flex items-center gap-2 pt-1 text-[10px] text-zinc-600">
            <span>Bot: <span className="font-medium text-zinc-400">{statusText}</span></span>
            <span>·</span>
            <span>Mode: <span className="font-medium text-zinc-400">{modeText}</span></span>
            <span>·</span>
            <span>Kill: <span className={killActive ? "font-medium text-red-400" : "font-medium text-zinc-400"}>{killActive ? "ACTIVE" : "SAFE"}</span></span>
          </div>

          <button
            onClick={() => {
              setKeySubmitted(false);
              setControlApiKey("");
              setApiKey("");
            }}
            className="text-[10px] text-zinc-700 hover:text-zinc-500 transition-colors"
          >
            Change API Key
          </button>
        </div>
      )}
    </PanelShell>
  );
}

function formatResult(res: ControlResponse): string {
  const msg = res.message ?? res.status;
  return msg.length > 40 ? msg.slice(0, 40) + "…" : msg;
}