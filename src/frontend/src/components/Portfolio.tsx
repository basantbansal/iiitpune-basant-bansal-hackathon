import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Sliders, RefreshCw } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LineChart, Line, Legend } from 'recharts';
import HumanExpertReview from './HumanExpertReview';

interface PortfolioProps {
  metrics: any;
  refreshTrigger?: number;
  isLoading?: boolean;
  isScanning?: boolean;
  scanResult?: any;
  scanDuration?: number | null;
  onScan?: () => void;
  onOpenCustomizer?: () => void;
}

const TICKER_NAME_MAP: Record<string, string> = {
  AAPL: 'Apple Inc.',
  MSFT: 'Microsoft Corporation',
  NVDA: 'NVIDIA Corporation',
  AMZN: 'Amazon.com Inc.',
  GOOGL: 'Alphabet Inc. (Google)',
  META: 'Meta Platforms Inc.',
  TSLA: 'Tesla Inc.',
  JPM: 'JPMorgan Chase & Co.',
  JNJ: 'Johnson & Johnson',
  XOM: 'Exxon Mobil Corporation',
};

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    const delta = data.delta;
    const company = data.company_name || TICKER_NAME_MAP[data.name] || data.name;
    const deltaColor = delta > 0.05 ? 'text-success' : delta < -0.05 ? 'text-danger' : 'text-gray-400';
    const deltaSign = delta > 0 ? '+' : '';
    return (
      <div className="bg-[#161B22] border border-[#30363D] p-3 rounded-lg shadow-xl text-xs space-y-1.5 min-w-[220px]">
        <div className="font-bold text-sm text-heading border-b border-[#30363D] pb-1 flex justify-between items-center gap-4">
          <div>
            <span className="text-white block font-semibold">{company}</span>
            <span className="text-gray-400 font-mono text-[11px]">Ticker: {data.name}</span>
          </div>
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-semibold shrink-0 ${
            delta > 0.05 ? 'bg-success/20 text-success border border-success/30' : delta < -0.05 ? 'bg-danger/20 text-danger border border-danger/30' : 'bg-gray-800 text-gray-400 border border-gray-700'
          }`}>
            {delta > 0.05 ? 'Overweight' : delta < -0.05 ? 'Underweight' : 'Neutral'}
          </span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-gray-400">Baseline Weight:</span>
          <span className="font-mono text-gray-200">{data.Baseline.toFixed(2)}%</span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-gray-400">Target Weight:</span>
          <span className="font-mono font-bold text-heading">{data.Target.toFixed(2)}%</span>
        </div>
        <div className="flex justify-between gap-6 pt-1 border-t border-[#30363D]/60">
          <span className="text-gray-400">Allocation Delta:</span>
          <span className={`font-mono font-bold ${deltaColor}`}>
            {deltaSign}{delta.toFixed(2)} pp
          </span>
        </div>
        <div className="pt-1.5 border-t border-[#30363D]/60 text-[10px] text-primary flex items-center justify-center gap-1 font-medium">
          👉 Click bar to view full {data.name} details & news
        </div>
      </div>
    );
  }
  return null;
};

const CustomHistoryTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-[#161B22] border border-[#30363D] p-3 rounded-lg shadow-2xl text-xs space-y-2 max-w-sm max-h-[340px] overflow-y-auto">
        <div className="font-bold text-xs text-primary border-b border-[#30363D] pb-1 flex justify-between items-center">
          <span>Scan: {label}</span>
          <span className="text-[10px] text-gray-400 font-mono">10 S&P Constituents</span>
        </div>
        <div className="space-y-1.5 divide-y divide-[#30363D]/50">
          {payload.map((entry: any) => {
            const ticker = entry.dataKey;
            const company = TICKER_NAME_MAP[ticker] || ticker;
            const target = Number(entry.value);
            const baseline = 10.0;
            const delta = target - baseline;
            const deltaSign = delta > 0 ? '+' : '';
            const deltaColor = delta > 0.05 ? 'text-success' : delta < -0.05 ? 'text-danger' : 'text-gray-400';
            return (
              <div key={ticker} className="pt-1.5 first:pt-0 flex items-center justify-between gap-3">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
                  <span className="font-semibold text-gray-200 truncate">{company}</span>
                  <span className="text-gray-400 font-mono text-[11px] shrink-0">({ticker})</span>
                </div>
                <div className="text-right shrink-0">
                  <span className="font-mono font-bold text-heading">{target.toFixed(2)}%</span>
                  <span className={`font-mono text-[10px] ml-1.5 ${deltaColor}`}>
                    ({deltaSign}{delta.toFixed(2)} pp)
                  </span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="pt-1 border-t border-[#30363D] text-[10px] text-gray-400 text-center">
          Baseline Weight: 10.00% &bull; Min 5.0% – Max 15.0%
        </div>
      </div>
    );
  }
  return null;
};

export default function Portfolio({
  metrics,
  refreshTrigger,
  isLoading,
  isScanning,
  scanResult,
  scanDuration,
  onScan,
  onOpenCustomizer
}: PortfolioProps) {
  const [portfolio, setPortfolio] = useState<any[]>([]);
  const [historyData, setHistoryData] = useState<any[]>([]);
  const [isFetching, setIsFetching] = useState<boolean>(false);
  const navigate = useNavigate();

  useEffect(() => {
    let isCancelled = false;
    setIsFetching(true);
    Promise.all([
      api.getPortfolio(),
      api.getPortfolioHistory().catch(() => [])
    ])
      .then(([portData, histData]) => {
        if (!isCancelled) {
          setPortfolio(portData || []);
          setHistoryData(histData || []);
        }
      })
      .catch(console.error)
      .finally(() => {
        if (!isCancelled) {
          setIsFetching(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [metrics, refreshTrigger]);

  const chartData = portfolio.map(item => {
    const tgt = Number(((item.target_weight ?? item.baseline_weight ?? 0.10) * 100).toFixed(2));
    const base = Number(((item.pre_weight ?? item.baseline_weight ?? 0.10) * 100).toFixed(2));
    const delta = item.signed_delta_pct != null
      ? Number(item.signed_delta_pct.toFixed(2))
      : Number((tgt - base).toFixed(2));
    return {
      name: item.ticker,
      company_name: item.company_name || TICKER_NAME_MAP[item.ticker] || item.ticker,
      Target: tgt,
      Baseline: base,
      delta: delta,
    };
  });

  const getTargetColor = (delta: number) => {
    if (delta > 0.05) return '#2ea043'; // Overweight: Emerald Green
    if (delta < -0.05) return '#da3633'; // Underweight: Crimson Red
    return '#64748b'; // Neutral / Unchanged: Slate Gray
  };

  const renderCustomXAxisTick = ({ x, y, payload }: any) => {
    return (
      <g transform={`translate(${x},${y})`}>
        <text
          x={0}
          y={0}
          dy={14}
          textAnchor="middle"
          fill="#8B949E"
          className="cursor-pointer hover:fill-primary font-bold text-xs transition-colors"
          onClick={() => navigate(`/stock/${payload.value}`)}
        >
          {payload.value}
        </text>
      </g>
    );
  };

  const formatCurrency = (val: number | null | undefined) => {
    if (val == null) return '—';
    const abs = Math.abs(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return val < 0 ? `-$${abs}` : `$${abs}`;
  };

  return (
    <div className="space-y-6">
      {/* Module A Header & Overview Card */}
      <div className="bg-surface border border-border p-4 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-mono px-2 py-0.5 rounded bg-primary/20 text-primary border border-primary/30">MODULE A</span>
            <h3 className="text-base sm:text-lg font-bold text-heading">Module A — Tactical Portfolio Rebalancing</h3>
          </div>
          <p className="text-xs text-gray-300 mt-1.5 leading-relaxed max-w-4xl">
            Converts news-based risk signals into tactical changes in target stock allocations. Positive sentiment can increase a stock's target weight and negative sentiment can reduce it, subject to portfolio constraints (±5.0 pp tracking-error limits, simplex renormalization, and preserving baseline weights for stocks without news).
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-[11px] font-mono text-gray-400 bg-background px-2.5 py-1 rounded-md border border-border">
            Top 10 S&P Universe • ±5.0 pp Limits
          </span>
          {onOpenCustomizer && (
            <button
              onClick={onOpenCustomizer}
              className="text-xs px-2.5 py-1 rounded-md bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 font-medium flex items-center gap-1.5 transition-colors"
              title="Open constituent holdings editor"
            >
              <Sliders size={12} />
              <span>Edit Holdings</span>
            </button>
          )}
        </div>
      </div>

      {/* Module A Action: Market News Scan Control & Stats (Placed inside Module A) */}
      <div className="bg-surface border border-border p-4 rounded-xl flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          {onScan && (
            <div className="flex flex-col gap-1.5 shrink-0">
              <button
                onClick={onScan}
                disabled={isScanning || isLoading}
                className="flex items-center justify-center gap-2 bg-primary hover:bg-blue-600 text-white px-5 py-2.5 rounded-lg font-semibold disabled:opacity-50 transition-colors shadow-sm text-xs sm:text-sm"
                title="Initiate live financial market news scan and entity risk extraction for tactical rebalancing"
              >
                <RefreshCw className={isScanning ? "animate-spin" : ""} size={16} />
                {isScanning ? "Scanning news & calculating rebalance..." : "Execute Market Scan (Module A)"}
              </button>
              {isScanning && (
                <div className="w-full bg-[#30363D] rounded-full h-1.5 overflow-hidden">
                  <div className="bg-primary h-full animate-pulse w-3/4 rounded-full" />
                </div>
              )}
            </div>
          )}
          <div className="text-[11px] text-gray-400 leading-tight">
            Scans live market news feeds to extract entity risk signals & trigger tactical rebalances.
            <span className="text-gray-500 block mt-0.5">Note: Rebalances tactical equity weights; does not alter Module B banking stress testing.</span>
          </div>
        </div>

        {scanResult && (
          <div className="text-xs sm:text-sm text-gray-300 flex-1 bg-background/50 p-2.5 rounded-lg border border-border/50">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-heading">{scanResult.message}</span>
              {scanDuration !== null && scanDuration !== undefined && (
                <span className="text-xs text-primary font-mono bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
                  ⏱️ {scanDuration}s
                </span>
              )}
            </div>
            {(scanResult.stats_duplicates !== undefined || scanResult.stats_already_processed !== undefined) && (
              <div className="text-xs text-gray-400 mt-1 flex flex-wrap gap-2.5">
                <span>Retrieved: <strong className="text-gray-300">{scanResult.stats_retrieved ?? 0}</strong></span>
                <span>•</span>
                <span>Filtered: <strong className="text-amber-400">{scanResult.stats_filtered ?? 0}</strong></span>
                {scanResult.stats_stale_filtered > 0 && (
                  <>
                    <span>•</span>
                    <span>Stale (&gt;7d): <strong className="text-amber-400">{scanResult.stats_stale_filtered}</strong></span>
                  </>
                )}
                <span>•</span>
                <span>Assignments: <strong className="text-gray-300">{scanResult.stats_ticker_assignments ?? 0}</strong></span>
                <span>•</span>
                <span>New Signals: <strong className="text-gray-300">{scanResult.stats_new_signals ?? scanResult.new_signals?.length ?? 0}</strong></span>
                <span>•</span>
                <span>Duplicates: <strong className="text-gray-300">{scanResult.stats_duplicates ?? 0}</strong></span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Target vs. Baseline Weight Distribution Chart and Volatility Cards */}
      <div className="bg-surface border border-border p-5 rounded-xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div>
            <h4 className="text-base sm:text-lg font-semibold flex items-center gap-2">
              <span>Target vs. Baseline Weight Distribution</span>
              <span className="text-[11px] font-normal text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded">
                Click any bar to open company
              </span>
            </h4>
            <p className="text-xs text-gray-400 mt-0.5">
              Tactical target allocation vs constituent holdings baseline &bull; Click any bar or constituent ticker below to inspect single-stock fundamentals
            </p>
          </div>

          {/* Visual distinction legend */}
          <div className="flex flex-wrap items-center gap-3 text-xs bg-background/60 px-3 py-1.5 rounded-lg border border-border">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-xs bg-[#475569] inline-block"></span>
              <span className="text-gray-300">Baseline Weight</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-xs bg-[#2ea043] inline-block"></span>
              <span className="text-success font-medium">Overweight (&gt;+0.05 pp)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-xs bg-[#da3633] inline-block"></span>
              <span className="text-danger font-medium">Underweight (&lt;-0.05 pp)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-xs bg-[#64748b] inline-block"></span>
              <span className="text-gray-400">Neutral (±0.05 pp)</span>
            </span>
          </div>
        </div>

        {metrics && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div className="bg-background border border-border p-3.5 rounded-lg">
              <div className="text-sm font-medium text-gray-300">Baseline Volatility (Annualized Est.)</div>
              <div className="text-xl font-bold font-mono">{metrics.baseline_volatility != null ? `${metrics.baseline_volatility.toFixed(2)}%` : 'N/A'}</div>
              <p className="text-xs text-gray-500 mt-1">Estimated annualized risk under original baseline portfolio weights</p>
            </div>
            <div className="bg-background border border-border p-3.5 rounded-lg">
              <div className="text-sm font-medium text-gray-300">Target Volatility (Annualized Est.)</div>
              <div className="text-xl font-bold font-mono">
                {metrics.target_volatility != null ? `${metrics.target_volatility.toFixed(2)}%` : 'N/A'}
                {metrics.target_volatility != null && metrics.baseline_volatility != null && (
                  <span className={`ml-2 text-sm ${(metrics.target_volatility - metrics.baseline_volatility) <= 0 ? 'text-success' : 'text-danger'}`}>
                    {(metrics.target_volatility - metrics.baseline_volatility > 0 ? '+' : '')}
                    {(metrics.target_volatility - metrics.baseline_volatility).toFixed(2)} pp
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500 mt-1">Estimated annualized risk under proposed tactical weights</p>
            </div>
          </div>
        )}

        {portfolio.length === 0 ? (
          <div className="h-[280px] flex items-center justify-center text-gray-500 text-sm">
            {isLoading || isFetching ? "Loading portfolio snapshot..." : "No portfolio constituent data available"}
          </div>
        ) : (
          <div className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <BarChart
                data={chartData}
                margin={{ top: 10, right: 30, left: 10, bottom: 5 }}
                className="cursor-pointer"
                onClick={(state: any) => {
                  if (state && state.activePayload && state.activePayload.length) {
                    const ticker = state.activePayload[0].payload.name;
                    if (ticker) navigate(`/stock/${ticker}`);
                  }
                }}
              >
                <XAxis dataKey="name" stroke="#8B949E" tick={renderCustomXAxisTick} />
                <YAxis stroke="#8B949E" unit="%" domain={[0, 20]} />
                <Tooltip content={<CustomTooltip />} />
                <Bar
                  dataKey="Baseline"
                  fill="#475569"
                  name="Baseline Weight (%)"
                  cursor="pointer"
                  isAnimationActive={false}
                  onClick={(entry: any) => {
                    if (entry && entry.name) navigate(`/stock/${entry.name}`);
                  }}
                />
                <Bar
                  dataKey="Target"
                  name="Target Weight (%)"
                  cursor="pointer"
                  isAnimationActive={false}
                  onClick={(entry: any) => {
                    if (entry && entry.name) navigate(`/stock/${entry.name}`);
                  }}
                >
                  {chartData.map((entry) => (
                    <Cell key={`cell-${entry.name}-${entry.delta}-${entry.Target}`} fill={getTargetColor(entry.delta)} cursor="pointer" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Target Weights Over Scans Line Chart */}
      <div className="bg-surface border border-border p-5 rounded-xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div>
            <h4 className="text-base sm:text-lg font-semibold">Target Weights Over Scans</h4>
            <p className="text-xs text-gray-400 mt-0.5">
              Multi-scan tactical allocation trajectory across all 10 monitored constituents (5% min – 15% max bounds).
            </p>
          </div>
          <span className="text-xs text-gray-400 bg-background/60 px-3 py-1 rounded-md border border-border font-mono">
            Tracking Bounds: 5%–15%
          </span>
        </div>

        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={historyData} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
              <XAxis dataKey="scan_label" stroke="#8B949E" tick={{ fontSize: 11 }} />
              <YAxis stroke="#8B949E" unit="%" domain={[4, 16]} tick={{ fontSize: 11 }} />
              <Tooltip content={<CustomHistoryTooltip />} />
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
              {['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'JPM', 'JNJ', 'XOM'].map((t, i) => {
                const colors = [
                  '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6',
                  '#06b6d4', '#eab308', '#6366f1', '#14b8a6', '#f97316'
                ];
                return (
                  <Line
                    key={t}
                    type="monotone"
                    dataKey={t}
                    name={t}
                    stroke={colors[i % colors.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    activeDot={{ r: 5 }}
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Trader Execution View: Simulated Orders Table */}
      <div className="bg-surface border border-border p-5 rounded-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
          <div>
            <div className="flex items-center gap-3">
              <h4 className="text-base sm:text-lg font-semibold">Simulated Orders & Execution Schedule</h4>
              <span className="text-xs px-2.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-mono">
                Trader Execution View
              </span>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              Fractional execution simulated &bull; Institutional 10 bps transaction fee model &bull; Holdings synchronized with backend engine
            </p>
          </div>

          {/* Action & Status Legend */}
          <div className="flex items-center gap-3 text-xs text-gray-300 bg-background/60 px-3 py-1.5 rounded-lg border border-border">
            <span className="text-gray-400 font-medium">Legend:</span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-success inline-block"></span>
              <span>Buy (+)</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-danger inline-block"></span>
              <span>Sell (-)</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-gray-500 inline-block"></span>
              <span>Hold (0)</span>
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left border-collapse">
            <thead className="text-xs uppercase bg-background text-gray-400">
              <tr>
                <th className="px-3 py-3 border-b border-border">Ticker</th>
                <th className="px-3 py-3 border-b border-border text-right">Price</th>
                <th className="px-3 py-3 border-b border-border text-right">Pre-Trade Wt</th>
                <th className="px-3 py-3 border-b border-border text-right">Target Wt</th>
                <th className="px-3 py-3 border-b border-border text-right">Delta (pp)</th>
                <th className="px-3 py-3 border-b border-border text-right">Pre-Trade Shs</th>
                <th className="px-3 py-3 border-b border-border text-center">Action</th>
                <th className="px-3 py-3 border-b border-border text-right">Signed Trade Qty</th>
                <th className="px-3 py-3 border-b border-border text-right">Post-Trade Shs</th>
                <th className="px-3 py-3 border-b border-border text-right">Order Notional</th>
                <th className="px-3 py-3 border-b border-border text-right">Est. Fee (10bps)</th>
                <th className="px-3 py-3 border-b border-border">Rationale / Net Sentiment</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.map(row => {
                const preWt = (row.pre_weight ?? row.current_weight ?? row.baseline_weight) * 100;
                const tgtWt = row.target_weight * 100;
                const deltaPct = row.signed_delta_pct ?? (tgtWt - preWt);
                const isBuy = row.action === 'BUY';
                const isSell = row.action === 'SELL';
                const isHold = !isBuy && !isSell;
                const signedQty = row.signed_qty ?? (isBuy ? row.order_qty : (isSell ? -row.order_qty : 0.0));
                const preShs = row.pre_shares ?? row.current_shares;
                const postShs = row.post_shares ?? row.target_shares;

                return (
                  <tr key={row.ticker} className="border-b border-border hover:bg-background/40 transition-colors">
                    <td className="px-3 py-3 font-semibold">
                      <button
                        onClick={() => navigate(`/stock/${row.ticker}`)}
                        className="text-primary hover:underline font-bold text-left flex flex-col"
                        title="Click to view detailed stock news, sentiment breakdown, and technical charts"
                      >
                        <span>{row.ticker}</span>
                        {row.company_name && row.company_name !== row.ticker && (
                          <span className="text-[11px] text-gray-400 font-normal">{row.company_name}</span>
                        )}
                      </button>
                    </td>
                    <td className="px-3 py-3 text-right font-mono">
                      {row.price != null ? `$${row.price.toFixed(2)}` : <span className="text-gray-500 italic">Ref $100.00</span>}
                    </td>
                    <td className="px-3 py-3 text-right font-mono">
                      {preWt.toFixed(2)}%
                    </td>
                    <td className="px-3 py-3 text-right font-mono font-medium text-heading">
                      {tgtWt.toFixed(2)}%
                    </td>
                    <td className={`px-3 py-3 text-right font-mono font-semibold ${
                      deltaPct > 0.001 ? 'text-success' : deltaPct < -0.001 ? 'text-danger' : 'text-gray-400'
                    }`}>
                      {deltaPct > 0 ? `+${deltaPct.toFixed(2)} pp` : `${deltaPct.toFixed(2)} pp`}
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-gray-300">
                      {preShs != null ? preShs.toFixed(2) : '—'}
                    </td>
                    <td className="px-3 py-3 text-center">
                      {isBuy && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-success/20 text-success border border-success/30 font-mono">
                          + BUY
                        </span>
                      )}
                      {isSell && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-danger/20 text-danger border border-danger/30 font-mono">
                          - SELL
                        </span>
                      )}
                      {isHold && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700 font-mono">
                          HOLD
                        </span>
                      )}
                    </td>
                    <td className={`px-3 py-3 text-right font-mono font-medium ${
                      signedQty > 0.001 ? 'text-success' : signedQty < -0.001 ? 'text-danger' : 'text-gray-400'
                    }`}>
                      {signedQty > 0 ? `+${signedQty.toFixed(2)}` : signedQty < 0 ? signedQty.toFixed(2) : '0.00'}
                    </td>
                    <td className="px-3 py-3 text-right font-mono font-medium text-heading">
                      {postShs != null ? postShs.toFixed(2) : '—'}
                    </td>
                    <td className="px-3 py-3 text-right font-mono font-medium">
                      {formatCurrency(row.trade_value)}
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-gray-400">
                      {formatCurrency(row.est_fee)}
                    </td>
                    <td className="px-3 py-3 max-w-[320px]">
                      <div className="flex items-center gap-2">
                        <span
                          onClick={() => navigate(`/stock/${row.ticker}`)}
                          className={`text-xs px-1.5 py-0.5 rounded font-mono font-bold shrink-0 cursor-pointer ${
                            row.net_sentiment > 0.05
                              ? 'bg-success/20 text-success border border-success/30'
                              : row.net_sentiment < -0.05
                              ? 'bg-danger/20 text-danger border border-danger/30'
                              : 'bg-gray-800 text-gray-400 border border-gray-700'
                          }`}
                          title="Average entity sentiment score • Click to view constituent details"
                        >
                          {row.net_sentiment > 0 ? `+${row.net_sentiment.toFixed(2)}` : row.net_sentiment?.toFixed(2) ?? '0.00'}
                        </span>
                        {row.signal_count > 1 && (
                          <button
                            onClick={() => navigate(`/stock/${row.ticker}`)}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary border border-primary/30 font-mono font-semibold shrink-0 hover:bg-primary/30 cursor-pointer"
                            title={`Click to view all ${row.signal_count} news signals for ${row.ticker}`}
                          >
                            {row.signal_count} news
                          </button>
                        )}
                        {row.driving_headline && row.driving_headline !== '—' && row.driving_headline !== 'No active news signals' ? (
                          <a
                            href={row.driving_headline_url || `https://news.google.com/search?q=${encodeURIComponent(row.driving_headline)}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-gray-300 truncate hover:text-primary hover:underline transition-colors flex items-center gap-1 group/link cursor-pointer min-w-0"
                            title={`Original news: "${row.driving_headline}"\n👉 Click to read real news article in new tab`}
                          >
                            <span className="truncate">{row.driving_headline}</span>
                            <ExternalLink size={12} className="opacity-60 group-hover/link:opacity-100 shrink-0 text-primary" />
                          </a>
                        ) : (
                          <span className="text-xs text-gray-400 truncate">
                            {row.driving_headline || '—'}
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Human Expert Review Second Opinion Card */}
      <HumanExpertReview />
    </div>
  );
}
