import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LineChart, Line, Legend } from 'recharts';
import HumanExpertReview from './HumanExpertReview';

interface PortfolioProps {
  metrics: any;
  refreshTrigger?: number;
  isLoading?: boolean;
}

export default function Portfolio({ metrics, refreshTrigger, isLoading }: PortfolioProps) {
  const [portfolio, setPortfolio] = useState<any[]>([]);
  const [historyData, setHistoryData] = useState<any[]>([]);
  const [isFetching, setIsFetching] = useState<boolean>(false);
  const navigate = useNavigate();

  useEffect(() => {
    setIsFetching(true);
    Promise.all([
      api.getPortfolio(),
      api.getPortfolioHistory().catch(() => [])
    ])
      .then(([portData, histData]) => {
        setPortfolio(portData || []);
        setHistoryData(histData || []);
      })
      .catch(console.error)
      .finally(() => {
        setIsFetching(false);
      });
  }, [metrics, refreshTrigger]);

  const chartData = portfolio.map(item => {
    const tgt = Number(((item.target_weight ?? item.baseline_weight ?? 0.10) * 100).toFixed(2));
    const base = Number(((item.baseline_weight ?? 0.10) * 100).toFixed(2));
    const delta = item.signed_delta_pct != null
      ? Number(item.signed_delta_pct.toFixed(2))
      : Number((tgt - base).toFixed(2));
    return {
      name: item.ticker,
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

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      const delta = data.delta;
      const deltaColor = delta > 0.05 ? 'text-success' : delta < -0.05 ? 'text-danger' : 'text-gray-400';
      const deltaSign = delta > 0 ? '+' : '';
      return (
        <div className="bg-[#161B22] border border-[#30363D] p-3 rounded shadow-xl text-xs space-y-1.5">
          <div className="font-bold text-sm text-heading border-b border-[#30363D] pb-1 flex justify-between items-center gap-4">
            <span>{data.name}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-semibold ${
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
        </div>
      );
    }
    return null;
  };

  const formatCurrency = (val: number | null | undefined) => {
    if (val == null) return '—';
    const abs = Math.abs(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return val < 0 ? `-$${abs}` : `$${abs}`;
  };

  return (
    <div className="space-y-8">
      {/* Module A Header & Overview Card */}
      <div className="bg-surface border border-border p-4 rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-mono px-2 py-0.5 rounded bg-primary/20 text-primary border border-primary/30">MODULE A</span>
            <h3 className="text-lg font-bold text-heading">Module A — Tactical Portfolio Rebalancing</h3>
          </div>
          <p className="text-xs text-gray-300 mt-1.5 leading-relaxed max-w-4xl">
            Converts news-based risk signals into changes in target stock allocations. Positive sentiment can increase a stock's target weight and negative sentiment can reduce it, subject to portfolio constraints (±5.0 pp tracking-error limits, simplex renormalization, and preserving baseline weights for stocks without news).
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-[11px] font-mono text-gray-400 bg-background px-2.5 py-1 rounded border border-border">
            Top 10 S&P Universe • ±5.0 pp Limits
          </span>
        </div>
      </div>

      {/* Top Section: Weight Chart and Volatility Cards */}
      <div className="bg-surface border border-border p-5 rounded-lg">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div>
            <h4 className="text-lg font-semibold">Target vs. Baseline Weight Distribution</h4>
            <p className="text-xs text-gray-400 mt-0.5">Authoritative tactical index allocation vs 10% equal-weight benchmark</p>
          </div>
          
          {/* Visual distinction legend */}
          <div className="flex flex-wrap items-center gap-3 text-xs bg-background/60 px-3 py-1.5 rounded border border-border">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-[#475569] inline-block"></span>
              <span className="text-gray-300">Baseline (10.0%)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-[#2ea043] inline-block"></span>
              <span className="text-success font-medium">Overweight (&gt;+0.05 pp)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-[#da3633] inline-block"></span>
              <span className="text-danger font-medium">Underweight (&lt;-0.05 pp)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-[#64748b] inline-block"></span>
              <span className="text-gray-400">Neutral (±0.05 pp)</span>
            </span>
          </div>
        </div>
        
        {metrics && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div className="bg-background border border-border p-3 rounded">
              <div className="text-sm font-medium text-gray-300">Baseline Volatility (Annualized Est.)</div>
              <div className="text-xl font-bold">{metrics.baseline_volatility != null ? `${metrics.baseline_volatility.toFixed(2)}%` : 'N/A'}</div>
              <p className="text-xs text-gray-500 mt-1">Estimated annualized risk under original baseline portfolio weights</p>
            </div>
            <div className="bg-background border border-border p-3 rounded">
              <div className="text-sm font-medium text-gray-300">Target Volatility (Annualized Est.)</div>
              <div className="text-xl font-bold">
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
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
                <XAxis dataKey="name" stroke="#8B949E" />
                <YAxis stroke="#8B949E" unit="%" domain={[0, 20]} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="Baseline" fill="#475569" name="Baseline Weight (10.0%)" />
                <Bar dataKey="Target" name="Target Weight (%)">
                  {chartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={getTargetColor(entry.delta)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Target Weights Over Scans Line Chart */}
      <div className="bg-surface border border-border p-5 rounded-lg">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div>
            <h4 className="text-lg font-semibold">Target Weights Over Scans</h4>
            <p className="text-xs text-gray-400 mt-0.5">
              Multi-scan tactical allocation trajectory across all 10 monitored constituents (5% min – 15% max bounds).
            </p>
          </div>
          <span className="text-xs text-gray-400 bg-background/60 px-3 py-1 rounded border border-border font-mono">
            Baseline: 10.0%
          </span>
        </div>

        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={historyData} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
              <XAxis dataKey="scan_label" stroke="#8B949E" tick={{ fontSize: 11 }} />
              <YAxis stroke="#8B949E" unit="%" domain={[4, 16]} tick={{ fontSize: 11 }} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#161B22', borderColor: '#30363D', color: '#C9D1D9' }} 
                formatter={(val: any) => [`${Number(val).toFixed(2)}%`]}
              />
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
      <div className="bg-surface border border-border p-5 rounded-lg">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
          <div>
            <div className="flex items-center gap-3">
              <h4 className="text-lg font-semibold">Simulated Orders from Last Market Scan</h4>
              <span className="text-xs px-2.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-mono">
                Trader Execution View
              </span>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              Fractional shares simulated (2 decimals) • Simulated execution (no broker connected)
            </p>
          </div>

          {/* Action & Status Legend */}
          <div className="flex items-center gap-3 text-xs text-gray-300 bg-background/60 px-3 py-1.5 rounded border border-border">
            <span className="text-gray-400 font-medium">Legend:</span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-success inline-block"></span>
              <span>Buy / Increase (+)</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-danger inline-block"></span>
              <span>Sell / Reduce (-)</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-gray-500 inline-block"></span>
              <span>Hold / Unchanged</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block"></span>
              <span>Needs Review</span>
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
                        className="text-primary hover:underline font-bold"
                        title="Click to view single-stock analysis"
                      >
                        {row.ticker}
                      </button>
                    </td>
                    <td className="px-3 py-3 text-right font-mono">
                      {row.price != null ? `$${row.price.toFixed(2)}` : <span className="text-gray-500 italic">Unavailable</span>}
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
                    <td className="px-3 py-3 max-w-[280px]">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded font-mono font-bold shrink-0 ${
                          row.net_sentiment > 0.05 
                            ? 'bg-success/20 text-success border border-success/30' 
                            : row.net_sentiment < -0.05 
                            ? 'bg-danger/20 text-danger border border-danger/30' 
                            : 'bg-gray-800 text-gray-400 border border-gray-700'
                        }`} title="Average entity sentiment score">
                          {row.net_sentiment > 0 ? `+${row.net_sentiment.toFixed(2)}` : row.net_sentiment?.toFixed(2) ?? '0.00'}
                        </span>
                        <span className="text-xs text-gray-300 truncate" title={row.driving_headline}>
                          {row.driving_headline || '—'}
                        </span>
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
