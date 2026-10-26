import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Sliders, RefreshCw, Sparkles, ChevronDown, ChevronUp, Newspaper } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LineChart, Line, Legend } from 'recharts';
import { getExecutionStatusInfo } from '../utils/formatters';
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

const getCoverageStateBadge = (state: string) => {
  switch (state) {
    case 'FRESH_NEWS_FOUND':
      return {
        label: 'Fresh News Found',
        badgeClass: 'bg-success/20 text-success border-success/30'
      };
    case 'NEUTRAL_SIGNALS_ONLY':
      return {
        label: 'Neutral Signals Only',
        badgeClass: 'bg-blue-500/20 text-blue-400 border-blue-500/30'
      };
    case 'ARTICLES_REJECTED_AS_STALE':
      return {
        label: 'Rejected Stale (>72h)',
        badgeClass: 'bg-amber-500/20 text-amber-400 border-amber-500/30'
      };
    case 'ARTICLES_REJECTED_AS_IRRELEVANT':
      return {
        label: 'Filtered SEO / 13F',
        badgeClass: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
      };
    case 'NO_NEWS_RETRIEVED':
      return {
        label: 'No News Retrieved',
        badgeClass: 'bg-gray-800 text-gray-400 border-gray-700'
      };
    case 'NO_RELEVANT_FRESH_ARTICLES':
      return {
        label: 'No Fresh Articles',
        badgeClass: 'bg-gray-800 text-gray-400 border-gray-700'
      };
    default:
      return {
        label: state ? state.replace(/_/g, ' ') : 'Pending Scan',
        badgeClass: 'bg-slate-800 text-slate-400 border-slate-700'
      };
  }
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
  const [coverageData, setCoverageData] = useState<any[]>([]);
  const [isCoverageOpen, setIsCoverageOpen] = useState<boolean>(true);
  const [isFetching, setIsFetching] = useState<boolean>(false);
  const navigate = useNavigate();

  useEffect(() => {
    let isCancelled = false;
    setIsFetching(true);
    Promise.all([
      api.getPortfolio(),
      api.getPortfolioHistory().catch(() => []),
      api.getMarketScanCoverage().catch(() => null)
    ])
      .then(([portData, histData, covResp]) => {
        if (!isCancelled) {
          setPortfolio(portData || []);
          setHistoryData(histData || []);
          if (covResp?.coverage && Array.isArray(covResp.coverage)) {
            setCoverageData(covResp.coverage);
          } else if (metrics?.constituent_coverage) {
            setCoverageData(Object.values(metrics.constituent_coverage));
          } else if (covResp && typeof covResp === 'object' && !Array.isArray(covResp)) {
            setCoverageData(Object.values(covResp));
          }
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

  useEffect(() => {
    if (metrics?.constituent_coverage) {
      setCoverageData(Object.values(metrics.constituent_coverage));
    }
  }, [metrics?.constituent_coverage]);

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

  const formatMoney = (val: number | null | undefined, symbol: string = '$') => {
    if (val == null) return '—';
    const abs = Math.abs(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return val < 0 ? `-${symbol}${abs}` : `${symbol}${abs}`;
  };

  const hasIndianConstituents = portfolio.some(p => p.market === 'IN' || p.currency === 'INR');
  const hasUsConstituents = portfolio.some(p => p.market === 'US' || p.currency === 'USD' || !p.currency);
  const hasMixedMarkets = hasIndianConstituents && hasUsConstituents;
  const isIndiaOnly = hasIndianConstituents && !hasUsConstituents;

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
            10 Monitored Constituents • ±5.0 pp Limits
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
              <span className="font-semibold text-heading flex items-center gap-1.5">
                <Sparkles size={14} className="text-primary shrink-0" />
                <span>{scanResult.message}</span>
              </span>
              {scanDuration !== null && scanDuration !== undefined && (
                <span className="text-xs text-primary font-mono bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
                  ⏱️ {scanDuration}s
                </span>
              )}
            </div>
            {(scanResult.stats_duplicates !== undefined || scanResult.stats_already_processed !== undefined || scanResult.stats_target_changes !== undefined) && (
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
                <span>Signals: <strong className="text-primary font-bold">{scanResult.stats_new_signals ?? scanResult.new_signals?.length ?? 0}</strong></span>
                {scanResult.stats_target_changes !== undefined && (
                  <>
                    <span>•</span>
                    <span>Target Changes: <strong className="text-purple-400 font-bold">{scanResult.stats_target_changes}</strong></span>
                  </>
                )}
                {scanResult.stats_executed_orders !== undefined && (
                  <>
                    <span>•</span>
                    <span>Executed: <strong className="text-emerald-400 font-bold">{scanResult.stats_executed_orders}</strong></span>
                  </>
                )}
                {scanResult.stats_withheld_orders !== undefined && (
                  <>
                    <span>•</span>
                    <span>Withheld: <strong className="text-amber-400 font-bold">{scanResult.stats_withheld_orders}</strong></span>
                  </>
                )}
                {scanResult.constituent_coverage && (
                  <>
                    <span>•</span>
                    <span>Coverage: <strong className="text-cyan-400 font-bold">{Object.keys(scanResult.constituent_coverage).length}/10</strong></span>
                  </>
                )}
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
              {(portfolio.length > 0 ? portfolio.map(p => p.ticker) : ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'JPM', 'JNJ', 'XOM']).map((t, i) => {
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

        {(hasMixedMarkets || isIndiaOnly) && (
          <div className="mb-4 px-3.5 py-2.5 bg-blue-500/10 border border-blue-500/20 rounded-lg text-xs text-blue-300 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <span>
              <strong>{isIndiaOnly ? 'Indian Equity Portfolio (NSE):' : 'Dual-Market Portfolio (US & India):'}</strong> Multi-Currency Accounting Active. Constituents priced and traded natively in {isIndiaOnly ? '₹ INR' : '$ USD and ₹ INR'}, with consolidated reporting in {metrics?.reporting_currency || 'INR'}.
            </span>
            <span className="font-mono bg-blue-950/60 px-2.5 py-1 rounded border border-blue-800/40 text-[11px] text-blue-200 shrink-0">
              FX Rate: 1 USD = {metrics?.fx_rate ?? 84.00} INR ({metrics?.fx_rate_is_live ? 'Live' : 'Fallback'})
            </span>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left border-collapse">
            <thead className="text-xs uppercase bg-background text-gray-400">
              <tr>
                <th className="px-3 py-3 border-b border-border">Ticker</th>
                <th className="px-3 py-3 border-b border-border text-center">Market</th>
                <th className="px-3 py-3 border-b border-border text-right">Price</th>
                <th className="px-3 py-3 border-b border-border text-right">Pre-Trade Wt</th>
                <th className="px-3 py-3 border-b border-border text-right">Target Wt</th>
                <th className="px-3 py-3 border-b border-border text-right">Delta (pp)</th>
                <th className="px-3 py-3 border-b border-border text-right">Pre-Trade Shs</th>
                <th className="px-3 py-3 border-b border-border text-center">Action / Status</th>
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
                const symbol = row.currency_symbol || (row.currency === 'INR' ? '₹' : '$');
                const isIndian = row.market === 'IN' || row.currency === 'INR';
                const execStatus = row.execution_status || (isHold ? 'HOLD_NO_CHANGE' : 'EXECUTED_SIMULATED');

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
                    <td className="px-3 py-3 text-center">
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold font-mono ${
                        isIndian
                          ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20'
                          : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                      }`}>
                        {isIndian ? '🇮🇳 IN' : '🇺🇸 US'}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right font-mono">
                      {row.price != null ? (
                        <span>
                          {symbol}{row.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          <span className="text-[10px] text-gray-400 block font-normal">
                            {row.currency || (isIndian ? 'INR' : 'USD')}
                            {isIndian && row.price_usd != null && ` ($${row.price_usd.toFixed(2)})`}
                            {!isIndian && row.price_inr != null && ` (₹${row.price_inr.toFixed(2)})`}
                          </span>
                        </span>
                      ) : (
                        <span className="text-gray-500 italic block leading-tight" title={row.is_fallback_price ? 'Fallback reference price (non-executable)' : 'Reference price'}>
                          Ref {symbol}{Number(row.reference_price ?? (isIndian ? 1000 : 100)).toFixed(2)}
                          <span className="text-[10px] text-amber-500/80 block font-normal not-italic">fallback</span>
                        </span>
                      )}
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
                      <div className="flex flex-col items-center gap-1">
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
                        {(() => {
                          const statusInfo = getExecutionStatusInfo(execStatus);
                          return (
                            <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${statusInfo.badgeClass}`} title={statusInfo.description}>
                              {statusInfo.label}
                            </span>
                          );
                        })()}
                      </div>
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
                      <span>{formatMoney(row.trade_value, symbol)}</span>
                      {isIndian && row.trade_value_usd > 0 && (
                        <span className="text-[10px] text-gray-400 block font-normal">
                          (${row.trade_value_usd.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})})
                        </span>
                      )}
                      {!isIndian && row.trade_value_inr > 0 && (
                        <span className="text-[10px] text-gray-400 block font-normal">
                          (₹{row.trade_value_inr.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})})
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-gray-400">
                      <span>{formatMoney(row.est_fee, symbol)}</span>
                      {isIndian && row.est_fee_usd > 0 && (
                        <span className="text-[10px] text-gray-500 block font-normal">
                          (${row.est_fee_usd.toFixed(2)})
                        </span>
                      )}
                      {!isIndian && row.est_fee_inr > 0 && (
                        <span className="text-[10px] text-gray-500 block font-normal">
                          (₹{row.est_fee_inr.toFixed(2)})
                        </span>
                      )}
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

      {/* Constituent News Ingestion & Freshness Coverage Matrix */}
      <div className="card border border-border p-5 rounded-xl bg-card space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Newspaper size={18} className="text-primary shrink-0" />
            <div>
              <h3 className="text-base font-bold text-heading flex items-center gap-2">
                Constituent News Coverage & Freshness Matrix
                <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                  10 Monitored Stocks
                </span>
              </h3>
              <p className="text-xs text-gray-400">
                Live verification across all 10 portfolio constituents: accounts for raw retrieved headlines, 72h freshness quarantine, generic SEO/13F exclusions, and active signal generation.
              </p>
            </div>
          </div>
          <button
            onClick={() => setIsCoverageOpen(!isCoverageOpen)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-background hover:bg-border/60 text-gray-300 transition-colors border border-border shrink-0 cursor-pointer self-start sm:self-auto"
          >
            <span>{isCoverageOpen ? 'Collapse Matrix' : 'Expand Matrix'}</span>
            {isCoverageOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>

        {isCoverageOpen && (
          <div className="overflow-x-auto pt-2">
            <table className="min-w-full text-xs text-left border-collapse">
              <thead className="uppercase bg-background text-gray-400">
                <tr>
                  <th className="px-3 py-2.5 border-b border-border">Constituent</th>
                  <th className="px-3 py-2.5 border-b border-border text-center">Feed Status</th>
                  <th className="px-3 py-2.5 border-b border-border text-right font-mono">Raw Retrieved</th>
                  <th className="px-3 py-2.5 border-b border-border text-right font-mono">Fresh Retained (≤72h)</th>
                  <th className="px-3 py-2.5 border-b border-border text-right font-mono">Rejected Stale</th>
                  <th className="px-3 py-2.5 border-b border-border text-right font-mono">Rejected SEO/13F</th>
                  <th className="px-3 py-2.5 border-b border-border text-right font-mono">Assigned</th>
                  <th className="px-3 py-2.5 border-b border-border text-right font-mono">LLM Analyzed</th>
                  <th className="px-3 py-2.5 border-b border-border text-right font-mono">Signals</th>
                  <th className="px-3 py-2.5 border-b border-border text-center">Coverage State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {coverageData.length > 0 ? (
                  coverageData.map((row: any) => {
                    const badge = getCoverageStateBadge(row.coverage_state);
                    return (
                      <tr key={row.ticker} className="hover:bg-background/40 transition-colors">
                        <td className="px-3 py-2 font-medium">
                          <button
                            onClick={() => navigate(`/stock/${row.ticker}`)}
                            className="text-primary hover:underline font-bold text-left flex items-center gap-1.5 cursor-pointer"
                          >
                            <span>{row.ticker}</span>
                            <span className="text-[11px] text-gray-400 font-normal truncate max-w-[140px]">
                              {row.company_name}
                            </span>
                          </button>
                        </td>
                        <td className="px-3 py-2 text-center font-mono text-[11px]">
                          <span className={`px-1.5 py-0.5 rounded ${
                            row.feed_status === 'DEGRADED'
                              ? 'bg-danger/20 text-danger border border-danger/30'
                              : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          }`}>
                            {row.feed_status || 'OK'}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-300">{row.raw_retrieved ?? 0}</td>
                        <td className="px-3 py-2 text-right font-mono font-semibold text-emerald-400">{row.fresh_retained ?? 0}</td>
                        <td className="px-3 py-2 text-right font-mono text-amber-400">{row.rejected_stale ?? 0}</td>
                        <td className="px-3 py-2 text-right font-mono text-yellow-400">{row.rejected_irrelevant ?? 0}</td>
                        <td className="px-3 py-2 text-right font-mono text-gray-300">{row.assigned_to_company ?? 0}</td>
                        <td className="px-3 py-2 text-right font-mono text-gray-300">{row.analyzed_count ?? 0}</td>
                        <td className="px-3 py-2 text-right font-mono font-bold text-heading">{row.signals_count ?? 0}</td>
                        <td className="px-3 py-2 text-center font-mono text-[11px]">
                          <span className={`inline-flex px-2 py-0.5 rounded font-semibold border ${badge.badgeClass}`}>
                            {badge.label}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={10} className="px-3 py-4 text-center text-gray-400">
                      No market scan executed yet. Run a market scan to observe real-time news coverage across all 10 constituents.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Human Expert Review Second Opinion Card */}
      <HumanExpertReview />
    </div>
  );
}
