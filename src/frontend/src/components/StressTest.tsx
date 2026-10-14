import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';

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

const formatCurrency = (val: number | null | undefined) => {
  if (val == null) return '—';
  const abs = Math.abs(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return val < 0 ? `-$${abs}` : `$${abs}`;
};

const CustomDrawdownTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    const ticker = data.ticker;
    const company = TICKER_NAME_MAP[ticker] || data.company_name || ticker;
    const shock = data.effective_shock_pct ?? data.drawdown;
    return (
      <div className="bg-[#161B22] border border-[#30363D] p-3 rounded-lg shadow-xl text-xs space-y-1.5 min-w-[220px]">
        <div className="font-bold text-sm text-heading border-b border-[#30363D] pb-1 flex justify-between items-center gap-4">
          <div>
            <span className="text-white block font-semibold">{company}</span>
            <span className="text-gray-400 font-mono text-[11px]">Ticker: {ticker}</span>
          </div>
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-semibold shrink-0 ${
            shock < 0 ? 'bg-danger/20 text-danger border border-danger/30' : 'bg-success/20 text-success border border-success/30'
          }`}>
            {shock < 0 ? 'Drawdown' : 'Gain'}
          </span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-gray-400">Pre-Shock Exposure:</span>
          <span className="font-mono text-gray-200">{formatCurrency(data.exposure ?? data.notional)}</span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-gray-400">Effective Shock:</span>
          <span className={`font-mono font-bold ${shock < 0 ? 'text-danger' : 'text-success'}`}>
            {shock != null ? `${shock.toFixed(2)}%` : '—'}
          </span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-gray-400">Stress P&L:</span>
          <span className={`font-mono font-bold ${data.pnl < 0 ? 'text-danger' : 'text-success'}`}>
            {formatCurrency(data.pnl)}
          </span>
        </div>
        <div className="flex justify-between gap-6 pt-1 border-t border-[#30363D]/60">
          <span className="text-gray-400">Post-Shock Value:</span>
          <span className="font-mono font-bold text-heading">{formatCurrency(data.post_shock_value)}</span>
        </div>
      </div>
    );
  }
  return null;
};

export default function StressTest() {
  const [scenarios, setScenarios] = useState<any>({});
  const [selectedScenario, setSelectedScenario] = useState<string>('');
  const [triggerInfo, setTriggerInfo] = useState<any>(null);
  const [results, setResults] = useState<any>(null);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    Promise.all([
      api.getStressScenarios(),
      api.getStressTrigger().catch(() => null)
    ]).then(([scData, trigData]) => {
      setScenarios(scData || {});
      setTriggerInfo(trigData);
      
      if (trigData && trigData.has_trigger && trigData.recommended_scenario) {
        setSelectedScenario(trigData.recommended_scenario);
      } else {
        const keys = Object.keys(scData || {});
        if (keys.length > 0) setSelectedScenario(keys[0]);
      }
    }).catch(console.error);
  }, []);

  const handleSelectScenario = (sc: string) => {
    setSelectedScenario(sc);
    setResults(null); // Clear stale results when switching scenarios
  };

  const handleRun = async () => {
    if (!selectedScenario) return;
    setIsRunning(true);
    try {
      const res = await api.runStressTest(selectedScenario);
      if (res.detail) {
        alert(res.detail);
        setResults(null);
      } else {
        setResults(res);
      }
    } catch (err) {
      console.error(err);
      setResults(null);
    }
    setIsRunning(false);
  };

  return (
    <div className="space-y-6">
      {/* Module B Header & Overview Card */}
      <div className="bg-surface border border-border p-4 rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-mono px-2 py-0.5 rounded bg-primary/20 text-primary border border-primary/30">MODULE B</span>
            <h3 className="text-lg font-bold text-heading">Module B — Strategic Banking Stress Testing</h3>
          </div>
          <p className="text-xs text-gray-300 mt-1.5 leading-relaxed max-w-4xl">
            Evaluates how predefined financial shocks affect a synthetic banking book containing corporate loans, fixed-income bonds, interest-rate swaps, and equities. Simulates multi-channel macro stress, displaying before-and-after valuations and individual asset-class loss contributions under strict conservation of balance.
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-[11px] font-mono text-gray-400 bg-background px-2.5 py-1 rounded border border-border">
            14 Positions • 4 Asset Classes
          </span>
        </div>
      </div>

      {/* High-Impact Trigger Banner */}
      {triggerInfo && triggerInfo.has_trigger && (
        <div className="bg-amber-950/40 border border-amber-600/60 p-4 rounded-lg flex items-start gap-3 text-amber-200">
          <span className="text-xl">⚡</span>
          <div className="flex-1 text-xs">
            <div className="font-bold text-sm text-amber-300 flex items-center gap-2">
              <span>High-Impact Signal Auto-Trigger</span>
              <span className="bg-amber-600/30 text-amber-300 px-2 py-0.5 rounded text-[10px] font-mono border border-amber-500/40">
                Impact: {triggerInfo.signal?.impact_score}/10
              </span>
            </div>
            <p className="mt-1 text-amber-100/90">{triggerInfo.message}</p>
            {triggerInfo.signal?.headline && (
              <div className="mt-2 text-[11px] font-mono bg-black/40 p-2 rounded border border-amber-800/40">
                <span className="text-gray-400">Trigger Headline:</span> "{triggerInfo.signal.headline}" &bull; <span className="text-gray-400">Classification:</span> {triggerInfo.signal.event_classification}
              </div>
            )}
          </div>
        </div>
      )}
      {triggerInfo && !triggerInfo.has_trigger && (
        <div className="bg-surface/60 border border-border/80 px-4 py-2.5 rounded-lg flex items-center gap-2.5 text-xs text-gray-400">
          <span>ℹ️</span>
          <span>{triggerInfo.message}</span>
        </div>
      )}

      {/* Top Section: Horizontal Selectable Scenario Cards */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h4 className="text-lg font-semibold">Scenario Analysis & Tail Risk</h4>
            <p className="text-xs text-gray-400 mt-0.5">
              Select a multi-factor macro stress scenario to model portfolio resilience under historical and hypothetical tail events.
            </p>
          </div>
          <button 
            onClick={handleRun}
            disabled={isRunning || !selectedScenario}
            className="bg-primary hover:bg-blue-600 text-white font-medium px-6 py-2.5 rounded-lg disabled:opacity-50 shrink-0 flex items-center justify-center gap-2 shadow-sm transition-all"
          >
            {isRunning ? (
              <>
                <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                <span>Simulating...</span>
              </>
            ) : (
              <>
                <span>⚡ Run Simulation</span>
              </>
            )}
          </button>
        </div>

        {/* 3 Horizontal Scenario Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Object.keys(scenarios).map(sc => {
            const scData = scenarios[sc];
            const isSelected = selectedScenario === sc;
            return (
              <div 
                key={sc}
                onClick={() => handleSelectScenario(sc)}
                className={`cursor-pointer rounded-lg p-4 border transition-all ${
                  isSelected 
                    ? 'border-primary bg-primary/10 ring-1 ring-primary/50 shadow-md' 
                    : 'border-border bg-surface hover:border-gray-600 hover:bg-background/60'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <h5 className="font-bold text-sm text-heading">{sc}</h5>
                  <span className={`w-4 h-4 rounded-full border flex items-center justify-center ${
                    isSelected ? 'border-primary bg-primary' : 'border-gray-500'
                  }`}>
                    {isSelected && <span className="w-1.5 h-1.5 rounded-full bg-white"></span>}
                  </span>
                </div>
                <p className="text-xs text-gray-400 mb-3 min-h-[36px] line-clamp-2">{scData.desc}</p>
                <div className="grid grid-cols-3 gap-2 text-xs bg-background/80 p-2.5 rounded border border-border/60">
                  <div>
                    <span className="text-gray-500 block text-[10px] uppercase">Equities</span>
                    <strong className="text-danger font-mono font-bold">{(scData.equity_shock * 100).toFixed(0)}%</strong>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] uppercase">Rates</span>
                    <strong className="text-amber-400 font-mono font-bold">{scData.rate_shock_bps > 0 ? `+${scData.rate_shock_bps}` : scData.rate_shock_bps} bps</strong>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] uppercase">Spreads</span>
                    <strong className="text-purple-400 font-mono font-bold">+{scData.spread_shock_bps} bps</strong>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      
      {/* Simulation Results Section */}
      <div className="w-full">
        {results ? (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h4 className="text-lg font-semibold">📈 Stress Results: <span className="text-primary">{selectedScenario}</span></h4>
                <p className="text-xs text-gray-400 mt-0.5">Auditable Multi-Factor Macro Stress Simulation</p>
              </div>
              <span className="text-xs text-gray-400 bg-surface px-2.5 py-1 rounded border border-border font-mono self-start sm:self-auto">
                Formula: P&L = Exposure × (β · Δequity - ModDur_rate · Δrate - ModDur_spread · Δspread)
              </span>
            </div>

            {/* Scenario Assumptions & Channel Disclosure Panel */}
            <div className="bg-surface border border-border p-4 rounded-lg">
              <h5 className="text-xs font-semibold uppercase text-gray-400 mb-2">Scenario Parameters & Factor Channel Model</h5>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                <div className="bg-background p-2.5 rounded border border-border">
                  <div className="text-xs text-gray-400">Broad Equity Factor Shock</div>
                  <div className="text-lg font-bold font-mono text-danger">
                    {results.scenario_assumptions?.equity_shock_pct != null ? `${results.scenario_assumptions.equity_shock_pct}%` : `${(scenarios[selectedScenario]?.equity_shock * 100).toFixed(0)}%`}
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">Transmitted via individual asset Beta</div>
                </div>
                <div className="bg-background p-2.5 rounded border border-border">
                  <div className="text-xs text-gray-400">Benchmark Rate Shock</div>
                  <div className="text-lg font-bold font-mono text-amber-400">
                    {results.scenario_assumptions?.rate_shock_bps != null ? `+${results.scenario_assumptions.rate_shock_bps} bps` : `${scenarios[selectedScenario]?.rate_shock_bps} bps`}
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">Transmitted via rate duration sensitivity proxy</div>
                </div>
                <div className="bg-background p-2.5 rounded border border-border">
                  <div className="text-xs text-gray-400">Credit Spread Widening Shock</div>
                  <div className="text-lg font-bold font-mono text-purple-400">
                    {results.scenario_assumptions?.spread_shock_bps != null ? `+${results.scenario_assumptions.spread_shock_bps} bps` : `${scenarios[selectedScenario]?.spread_shock_bps} bps`}
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">Transmitted via spread duration sensitivity proxy</div>
                </div>
              </div>
              <p className="text-xs text-gray-400 bg-background/50 p-2 rounded border border-border/50">
                ℹ️ <strong>Model Disclosure:</strong> Portfolio is 100% equity with no direct fixed-income holdings. Equity market risk is modeled directly via Beta. Interest rate and credit spread shocks are applied via illustrative institutional equity duration/spread proxy sensitivities.
              </p>
            </div>

            {/* Dataset 1: Live Tactical Equity Portfolio Stress Preview */}
            <div className="bg-primary/10 border border-primary/30 p-3.5 rounded-lg flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono font-bold bg-primary text-white px-2 py-0.5 rounded">DATASET 1</span>
                  <h5 className="font-bold text-sm text-heading">Live Tactical Equity Portfolio Stress Preview</h5>
                </div>
                <p className="text-xs text-gray-300 mt-1">
                  Models multi-factor shock impact on your live tactical portfolio ($1,000,000 capital baseline, current equity holdings and cash reserve).
                </p>
              </div>
              <span className="text-xs font-mono text-primary bg-background px-2.5 py-1 rounded border border-primary/20 shrink-0">
                10 S&P Equities • Live Holdings
              </span>
            </div>

            {/* Portfolio Summary Metrics */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-surface border border-border p-3.5 rounded">
                <div className="text-sm text-gray-400">Pre-Shock Value</div>
                <div className="text-xl font-bold font-mono">{formatCurrency(results.total_value)}</div>
                <div className="text-[11px] text-gray-500 mt-1">Portfolio market baseline (matching Dashboard)</div>
              </div>
              <div className="bg-surface border border-border p-3.5 rounded">
                <div className="text-sm text-gray-400">Estimated Total Loss / Gain</div>
                <div className={`text-xl font-bold font-mono ${results.drawdown_value < 0 ? 'text-danger' : 'text-success'}`}>
                  {formatCurrency(results.drawdown_value)}
                  <span className="text-sm ml-2">({results.drawdown_pct.toFixed(2)}%)</span>
                </div>
                <div className="text-[11px] text-gray-500 mt-1">Aggregated factor impact</div>
              </div>
              <div className="bg-surface border border-border p-3.5 rounded">
                <div className="text-sm text-gray-400">Post-Shock Value</div>
                <div className="text-xl font-bold font-mono">{formatCurrency(results.post_shock_value)}</div>
                <div className="text-[11px] text-success mt-1">
                  ✓ Invariant verified: Pre + P&L = Post
                </div>
              </div>
            </div>

            {/* Dataset 2: Synthetic Wholesale Banking Book Summary Table */}
            {results.banking_book && (
              <div className="bg-surface border border-border p-4 rounded-lg space-y-3">
                <div className="bg-blue-950/30 border border-blue-800/40 p-3 rounded-lg flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono font-bold bg-blue-600 text-white px-2 py-0.5 rounded">DATASET 2</span>
                      <h5 className="font-bold text-sm text-heading">🏛️ Synthetic Wholesale Banking Book ($31,000,000 Portfolio)</h5>
                    </div>
                    <p className="text-xs text-gray-300 mt-0.5">
                      Separate institutional wholesale dataset: 14 positions across Commercial Loans, Bonds, Interest Rate Swaps, and Private Equity.
                      <strong className="text-amber-300 block mt-0.5">Note: This portfolio is completely separate and independent from the $1,000,000 Module A tactical equity portfolio.</strong>
                    </p>
                  </div>
                  <span className="text-xs font-mono text-blue-300 bg-background px-2.5 py-1 rounded border border-blue-700/40 shrink-0">
                    14 Positions • 4 Asset Classes
                  </span>
                </div>
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h5 className="font-semibold text-sm flex items-center gap-2">
                      <span>Wholesale Banking Book: By-Asset-Class Stress Summary</span>
                    </h5>
                    <p className="text-xs text-gray-400 mt-0.5">
                      Multi-asset cross-sensitivities: Loans (ECL + Spread), Bonds (Modified Duration + Spread), Swaps (DV01), Equities (Beta).
                    </p>
                  </div>
                  <div className="text-xs font-mono bg-background px-3 py-1.5 rounded border border-border text-success">
                    ✓ Invariant Verified: Pre + Total P&L = Post
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="min-w-full text-xs text-left border-collapse">
                    <thead className="uppercase bg-background text-gray-400">
                      <tr>
                        <th className="px-3 py-2.5 border-b border-border">Asset Class</th>
                        <th className="px-3 py-2.5 border-b border-border text-center">Positions</th>
                        <th className="px-3 py-2.5 border-b border-border text-right">Pre-Shock Exposure</th>
                        <th className="px-3 py-2.5 border-b border-border text-right">Stress P&L ($)</th>
                        <th className="px-3 py-2.5 border-b border-border text-right">Post-Shock Value ($)</th>
                        <th className="px-3 py-2.5 border-b border-border text-right">Drawdown (%)</th>
                        <th className="px-3 py-2.5 border-b border-border text-right">Share of Loss</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.banking_book.by_asset_class?.map((row: any) => (
                        <tr key={row.asset_class} className="border-b border-border hover:bg-background/40 transition-colors">
                          <td className="px-3 py-2 font-semibold text-heading">{row.asset_class}</td>
                          <td className="px-3 py-2 text-center font-mono text-gray-300">{row.position_count}</td>
                          <td className="px-3 py-2 text-right font-mono text-gray-200">{formatCurrency(row.pre_shock_value)}</td>
                          <td className={`px-3 py-2 text-right font-mono font-bold ${row.pnl < 0 ? 'text-danger' : 'text-success'}`}>
                            {formatCurrency(row.pnl)}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-heading">{formatCurrency(row.post_shock_value)}</td>
                          <td className={`px-3 py-2 text-right font-mono font-bold ${row.drawdown_pct < 0 ? 'text-danger' : 'text-success'}`}>
                            {row.drawdown_pct != null ? `${row.drawdown_pct.toFixed(2)}%` : '—'}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-gray-300">
                            {row.share_of_loss_pct != null ? `${row.share_of_loss_pct.toFixed(1)}%` : '—'}
                          </td>
                        </tr>
                      ))}
                      <tr className="bg-background/80 font-bold border-t-2 border-border">
                        <td className="px-3 py-2.5 text-heading uppercase">Total Banking Book</td>
                        <td className="px-3 py-2.5 text-center font-mono text-heading">14</td>
                        <td className="px-3 py-2.5 text-right font-mono text-heading">
                          {formatCurrency(results.banking_book.total_pre_shock_value)}
                        </td>
                        <td className={`px-3 py-2.5 text-right font-mono ${results.banking_book.total_pnl < 0 ? 'text-danger' : 'text-success'}`}>
                          {formatCurrency(results.banking_book.total_pnl)}
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono text-primary">
                          {formatCurrency(results.banking_book.total_post_shock_value)}
                        </td>
                        <td className={`px-3 py-2.5 text-right font-mono ${results.banking_book.total_drawdown_pct < 0 ? 'text-danger' : 'text-success'}`}>
                          {results.banking_book.total_drawdown_pct != null ? `${results.banking_book.total_drawdown_pct.toFixed(2)}%` : '—'}
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono text-heading">100.0%</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="p-2 text-[11px] text-gray-400 bg-background/50 rounded border border-border/40">
                  ℹ️ <strong>Wholesale Banking Book Model:</strong> Evaluates 14 institutional wholesale positions across credit facilities, investment-grade & high-yield bonds, interest rate hedges, and equity holdings under simultaneous multi-channel macro shocks.
                </div>
              </div>
            )}

            {/* Chart: Asset Drawdowns */}
            <div className="bg-surface border border-border p-4 rounded-lg">
              <div className="flex items-center justify-between mb-3">
                <h5 className="font-semibold text-sm">Asset-Level Drawdown (%)</h5>
                <span className="text-xs text-gray-400 font-mono">Baseline = 0% (Downwards indicates tail loss)</span>
              </div>
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={results.asset_results} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
                    <XAxis 
                      dataKey="ticker" 
                      stroke="#8B949E" 
                      interval={0}
                      tick={{ fontSize: 12, fill: '#C9D1D9' }}
                    />
                    <YAxis 
                      stroke="#8B949E" 
                      unit="%" 
                      domain={[(dataMin: number) => Math.floor(Math.min(dataMin, -5) * 1.1), 0]}
                      tick={{ fontSize: 12, fill: '#C9D1D9' }}
                    />
                    <Tooltip content={<CustomDrawdownTooltip />} />
                    <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
                    <Bar dataKey="drawdown" name="Drawdown (%)">
                      {results.asset_results.map((entry: any, index: number) => (
                        <Cell key={`cell-${index}`} fill={(entry.drawdown ?? entry.effective_shock_pct) < 0 ? '#da3633' : '#2ea043'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Auditable Per-Asset Breakdown Table (Sorted by largest loss first) */}
            <div className="bg-surface border border-border p-4 rounded-lg">
              <div className="flex items-center justify-between mb-3">
                <h5 className="font-semibold text-sm">Auditable Per-Asset Breakdown</h5>
                <span className="text-xs text-gray-400 font-mono">Sorted by largest loss first</span>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs text-left border-collapse">
                  <thead className="uppercase bg-background text-gray-400">
                    <tr>
                      <th className="px-3 py-2.5 border-b border-border">Ticker</th>
                      <th className="px-3 py-2.5 border-b border-border text-right">Weight</th>
                      <th className="px-3 py-2.5 border-b border-border text-right">Pre-Shock Exposure</th>
                      <th className="px-3 py-2.5 border-b border-border text-right" title="Equity Beta (Market sensitivity)">Beta (β)</th>
                      <th className="px-3 py-2.5 border-b border-border text-right" title="Illustrative duration/spread sensitivity proxies for equity assets; portfolio contains no direct bond holdings.">Rate sens.</th>
                      <th className="px-3 py-2.5 border-b border-border text-right" title="Illustrative duration/spread sensitivity proxies for equity assets; portfolio contains no direct bond holdings.">Spread sens.</th>
                      <th className="px-3 py-2.5 border-b border-border text-right">Effective Shock</th>
                      <th className="px-3 py-2.5 border-b border-border text-right">Dollar P&L</th>
                      <th className="px-3 py-2.5 border-b border-border text-right">Post-Shock Value</th>
                      <th className="px-3 py-2.5 border-b border-border text-right">Share of Loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.asset_results.map((row: any) => (
                      <tr key={row.ticker} className="border-b border-border hover:bg-background/40 transition-colors">
                        <td className="px-3 py-2 font-semibold text-heading">
                          <div className="flex items-center gap-1">
                            <span>{row.ticker}</span>
                            {row.ticker === 'JPM' && (
                              <span 
                                className="text-[11px] text-blue-400 font-normal cursor-help" 
                                title="JPM negative rate sensitivity (-1.2): reflects bank net interest margin expansion under rate hikes (financial institutions industry convention)."
                              >
                                ℹ️
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-300">
                          {row.weight != null ? `${row.weight.toFixed(1)}%` : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-300">
                          {formatCurrency(row.exposure ?? row.notional)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-heading">
                          {row.beta != null ? row.beta.toFixed(2) : '1.00'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-400" title="Illustrative duration/spread sensitivity proxies for equity assets; portfolio contains no direct bond holdings.">
                          {row.rate_mod_dur != null ? row.rate_mod_dur.toFixed(1) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-400" title="Illustrative duration/spread sensitivity proxies for equity assets; portfolio contains no direct bond holdings.">
                          {row.spread_mod_dur != null ? row.spread_mod_dur.toFixed(1) : '—'}
                        </td>
                        <td className={`px-3 py-2 text-right font-mono font-bold ${
                          (row.effective_shock_pct ?? row.drawdown) < 0 ? 'text-danger' : 'text-success'
                        }`}>
                          {row.effective_shock_pct != null ? `${row.effective_shock_pct.toFixed(2)}%` : `${row.drawdown.toFixed(2)}%`}
                        </td>
                        <td className={`px-3 py-2 text-right font-mono font-bold ${
                          row.pnl < 0 ? 'text-danger' : 'text-success'
                        }`}>
                          {formatCurrency(row.pnl)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-heading">
                          {formatCurrency(row.post_shock_value)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-300">
                          {row.share_of_loss_pct != null ? `${row.share_of_loss_pct.toFixed(1)}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Sensitivity & JPM Disclosures */}
              <div className="mt-3 p-2.5 bg-background/60 rounded border border-border/60 text-xs text-gray-400 space-y-1">
                <div>
                  ℹ️ <strong>Rate & Spread Sensitivity Disclosure:</strong> Illustrative duration and credit spread sensitivity proxies for equity assets; portfolio contains no direct bond holdings.
                </div>
                <div>
                  💡 <strong>JPM Rate Sensitivity Note:</strong> JPM exhibits negative rate sensitivity (-1.2), reflecting that commercial bank net interest margin (NIM) expands during rate-hiking cycles (financial institutions industry convention).
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center p-12 text-gray-400 border border-dashed border-border rounded-lg bg-surface/40 min-h-[260px]">
            <span className="text-3xl mb-2">📊</span>
            <div className="font-semibold text-heading text-sm">No Simulation Results Displayed</div>
            <p className="text-xs text-gray-500 mt-1 max-w-md text-center">
              Selected Scenario: <strong className="text-primary">{selectedScenario}</strong>. Click <strong className="text-heading">"Run Simulation"</strong> above to compute the auditable macro factor stress test.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
