import React from "react";
import { AlertTriangle, Clock, Cpu, DollarSign, Layers } from "lucide-react";
import type { Session, StatsResponse } from "../types";

interface MetricCardProps {
  icon: React.ReactNode;
  iconClassName: string;
  label: string;
  valueClassName: string;
  value: React.ReactNode;
}

function MetricCard({ icon, iconClassName, label, valueClassName, value }: MetricCardProps) {
  return (
    <div className="p-4 rounded-xl glass-panel flex items-center gap-3">
      <div className={`p-2.5 rounded-lg ${iconClassName}`}>{icon}</div>
      <div>
        <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
          {label}
        </div>
        <div className={`text-lg font-extrabold leading-none mt-1 ${valueClassName}`}>{value}</div>
      </div>
    </div>
  );
}

/**
 * The five metric cards. Values come from the stats endpoint once loaded and
 * fall back to the session's own aggregates until then.
 */
export function StatsPanel({ session, stats }: { session: Session; stats: StatsResponse | null }) {
  return (
    <div className="p-4 grid grid-cols-5 gap-4">
      <MetricCard
        icon={<Cpu className="w-5 h-5" />}
        iconClassName="bg-purple-500/10 text-purple-400"
        label="Total Tokens"
        valueClassName="text-white"
        value={stats?.total_tokens ?? session.total_tokens}
      />
      <MetricCard
        icon={<DollarSign className="w-5 h-5" />}
        iconClassName="bg-emerald-500/10 text-emerald-400"
        label="Total Cost (USD)"
        valueClassName="text-emerald-400"
        value={`$${(stats?.total_cost_usd ?? session.total_cost_usd).toFixed(5)}`}
      />
      <MetricCard
        icon={<Clock className="w-5 h-5" />}
        iconClassName="bg-sky-500/10 text-sky-400"
        label="Duration (s)"
        valueClassName="text-white"
        value={stats?.total_duration_ms ? (stats.total_duration_ms / 1000).toFixed(2) : "0.00"}
      />
      <MetricCard
        icon={<AlertTriangle className="w-5 h-5" />}
        iconClassName="bg-rose-500/10 text-rose-400"
        label="Errors"
        valueClassName="text-rose-400"
        value={stats?.error_count ?? session.error_count}
      />
      <MetricCard
        icon={<Layers className="w-5 h-5" />}
        iconClassName="bg-amber-500/10 text-amber-400"
        label="Active Agents"
        valueClassName="text-white"
        value={stats?.agents?.length ?? session.agent_count}
      />
    </div>
  );
}
