import React, { useState, useEffect } from 'react';
import { api } from '../api';
import Sidebar from './Sidebar';
import Portfolio from './Portfolio';
import RiskSignals from './RiskSignals';
import StressTest from './StressTest';
import { RefreshCw, RotateCcw } from 'lucide-react';

export default function Dashboard() {
  const [metrics, setMetrics] = useState<any>(null);
  const [activeTab, setActiveTab] = useState('portfolio');
  const [isScanning, setIsScanning] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [scanResult, setScanResult] = useState<any>(null);
  const [scanDuration, setScanDuration] = useState<number | null>(null);
  const [scanCount, setScanCount] = useState(0);

  const loadMetrics = () => {
    api.getPortfolioMetrics().then(setMetrics).catch(console.error);
  };

  const handleConfigChange = () => {
    loadMetrics();
    setScanCount(c => c + 1);
  };

  useEffect(() => {
    loadMetrics();
  }, []);

  const handleScan = async () => {
    if (isScanning || isResetting) return; // Prevent overlapping scans on repeated clicks
    setIsScanning(true);
    setScanResult(null);
    const startTime = performance.now();
    try {
      const res = await api.scanMarket();
      const elapsed = Number(((performance.now() - startTime) / 1000).toFixed(1));
      setScanDuration(elapsed);
      setScanResult(res);
      setScanCount(c => c + 1);
      loadMetrics();
    } catch (err) {
      console.error(err);
      setScanResult({ message: "Scan failed due to an error." });
    } finally {
      setIsScanning(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm("Are you sure you want to reset runtime data? This will clear all active risk signals, reset simulated orders, and restore portfolio holdings to the baseline 10% allocation. System configuration (capital, tilt, data feed) will be preserved.")) {
      return;
    }
    setIsResetting(true);
    try {
      await api.resetData();
      setScanResult({ message: "Runtime risk signals and rebalance orders successfully reset to baseline." });
      setScanDuration(null);
      setScanCount(c => c + 1);
      loadMetrics();
    } catch (err) {
      console.error(err);
      setScanResult({ message: "Failed to reset data." });
    } finally {
      setIsResetting(false);
    }
  };

  const lastScanLabel = metrics?.last_updated && metrics.last_updated !== 'Never'
    ? `Last scan: ${metrics.last_updated}${metrics.last_scan_duration ? ` (took ${metrics.last_scan_duration}s)` : (scanDuration ? ` (took ${scanDuration}s)` : '')}`
    : 'No scan executed yet (initial baseline state)';

  return (
    <div className="flex h-screen w-full">
      <Sidebar onConfigChange={handleConfigChange} />
      <div className="flex-1 p-6 overflow-y-auto">
        <h1 className="text-3xl font-bold mb-2">AI Financial Risk & Portfolio Intelligence Platform</h1>
        <p className="text-sm text-gray-400 mb-6 font-mono text-xs">
          {lastScanLabel}
        </p>

        {/* Top Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <MetricCard 
            title="Portfolio Value" 
            value={metrics?.total_value != null ? `$${metrics.total_value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : (metrics ? 'Price Data Unavailable' : '...')} 
            subtitle={metrics?.holdings_market_value != null ? `Holdings: $${metrics.holdings_market_value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} | Fees: -$${(metrics.cumulative_fees_paid ?? 0).toFixed(2)}` : (metrics?.initial_capital ? `Baseline: $${metrics.initial_capital.toLocaleString()}` : undefined)}
            footnote="Initial holdings valued at baseline prices; value changes only with price moves and simulated fees."
          />
          <MetricCard 
            title="Largest Target Allocation" 
            value={metrics?.max_asset || '...'} 
            subtitle={
              metrics?.max_asset === "Equal Weight"
                ? `${((metrics?.max_asset_weight ?? 0.10) * 100).toFixed(1)}% each`
                : (metrics?.max_asset_weight ? `${(metrics.max_asset_weight * 100).toFixed(1)}% wt` : '')
            } 
          />
          <MetricCard 
            title="Gross Traded Value (buys + sells)" 
            value={metrics ? `$${(metrics?.gross_turnover ?? metrics?.total_turnover ?? 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : '...'} 
            subtitle="Simulated (buys + sells), 10 bps on gross"
          />
          <MetricCard 
            title="One-Way Simulated Turnover" 
            value={metrics ? `$${(metrics?.one_way_turnover ?? ((metrics?.total_turnover ?? 0) / 2)).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : '...'} 
            subtitle={metrics ? `${(metrics?.one_way_turnover_pct ?? 0).toFixed(2)}% of portfolio • Fees: -$${(metrics?.est_txn_cost ?? 0).toFixed(2)}` : ''} 
          />
        </div>

        {/* Scan & Reset Actions */}
        <div className="bg-surface border border-border p-4 rounded-lg mb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <button 
              onClick={handleScan}
              disabled={isScanning || isResetting}
              className="flex items-center gap-2 bg-primary hover:bg-blue-600 text-white px-5 py-2.5 rounded font-medium disabled:opacity-50 transition-colors shadow-sm text-sm"
              title="Initiate live financial market news scan and entity risk extraction"
            >
              <RefreshCw className={isScanning ? "animate-spin" : ""} size={18} />
              {isScanning ? "Scanning market and analyzing risk signals..." : "Execute Market Scan (typically 20-40s)"}
            </button>
            <button
              onClick={handleReset}
              disabled={isScanning || isResetting}
              className="flex items-center gap-2 bg-surface hover:bg-red-500/10 hover:border-red-500 text-gray-300 hover:text-red-400 border border-border px-4 py-2.5 rounded font-medium disabled:opacity-50 transition-colors shadow-sm text-sm"
              title="Clear all runtime risk signals and reset portfolio holdings to baseline"
            >
              <RotateCcw className={isResetting ? "animate-spin" : ""} size={16} />
              {isResetting ? "Resetting..." : "Reset Data"}
            </button>
          </div>
          
          {scanResult && (
            <div className="text-sm text-gray-300 flex-1 bg-background/50 p-2.5 rounded border border-border/50">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-heading">{scanResult.message}</span>
                {scanDuration !== null && (
                  <span className="text-xs text-primary font-mono bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
                    ⏱️ {scanDuration}s
                  </span>
                )}
              </div>
              {(scanResult.stats_duplicates !== undefined || scanResult.stats_already_processed !== undefined) && (
                <div className="text-xs text-gray-400 mt-1 flex flex-wrap gap-3">
                  <span>Retrieved: <strong className="text-gray-300">{scanResult.stats_retrieved ?? 0}</strong></span>
                  <span>•</span>
                  <span>Filtered: <strong className="text-amber-400">{scanResult.stats_filtered ?? 0}</strong></span>
                  {scanResult.stats_stale_filtered > 0 && (
                    <>
                      <span>•</span>
                      <span>Stale Filtered (&gt;7d): <strong className="text-amber-400">{scanResult.stats_stale_filtered}</strong></span>
                    </>
                  )}
                  <span>•</span>
                  <span>Assignments: <strong className="text-gray-300">{scanResult.stats_ticker_assignments ?? 0}</strong></span>
                  <span>•</span>
                  <span>New Signals: <strong className="text-gray-300">{scanResult.stats_new_signals ?? scanResult.new_signals?.length ?? 0}</strong></span>
                  <span>•</span>
                  <span>True Duplicates: <strong className="text-gray-300">{scanResult.stats_duplicates ?? 0}</strong></span>
                  <span>•</span>
                  <span>Already Processed: <strong className="text-gray-300">{scanResult.stats_already_processed ?? 0}</strong></span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="border-b border-border mb-6">
          <nav className="-mb-px flex space-x-6 sm:space-x-8 overflow-x-auto">
            <TabButton active={activeTab === 'portfolio'} onClick={() => setActiveTab('portfolio')} label="📊 Module A — Tactical Portfolio Rebalancing" />
            <TabButton active={activeTab === 'signals'} onClick={() => setActiveTab('signals')} label="📡 Risk Engine — Structured Signals" />
            <TabButton active={activeTab === 'stress'} onClick={() => setActiveTab('stress')} label="⚠️ Module B — Strategic Banking Stress Testing" />
          </nav>
        </div>

        {/* Tab Content */}
        <div>
          {activeTab === 'portfolio' && (
            <Portfolio 
              metrics={metrics} 
              refreshTrigger={scanCount} 
              isLoading={isScanning || isResetting} 
            />
          )}
          {activeTab === 'signals' && <RiskSignals refreshTrigger={scanCount} />}
          {activeTab === 'stress' && <StressTest />}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ title, value, subtitle, footnote }: { title: string, value: string, subtitle?: string, footnote?: string }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-4 flex flex-col justify-between">
      <div>
        <h3 className="text-sm text-gray-400 mb-1">{title}</h3>
        <div className="text-2xl font-bold text-heading font-mono">{value}</div>
        {subtitle && <div className="text-xs text-gray-400 mt-1">{subtitle}</div>}
      </div>
      {footnote && <div className="text-[11px] text-gray-500 mt-2 border-t border-border/40 pt-1.5 leading-tight">{footnote}</div>}
    </div>
  );
}

function TabButton({ active, onClick, label }: { active: boolean, onClick: () => void, label: string }) {
  return (
    <button
      onClick={onClick}
      className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm ${
        active
          ? 'border-primary text-primary'
          : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300'
      }`}
    >
      {label}
    </button>
  );
}
