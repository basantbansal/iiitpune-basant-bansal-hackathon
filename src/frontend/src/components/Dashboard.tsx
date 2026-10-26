import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { formatCurrency } from '../utils/formatters';
import Sidebar from './Sidebar';
import Portfolio from './Portfolio';
import RiskSignals from './RiskSignals';
import StressTest from './StressTest';
import PortfolioCustomization from './PortfolioCustomization';
import StockUniverseSelector from './StockUniverseSelector';
import {
  RotateCcw,
  PanelLeftClose,
  PanelLeftOpen,
  Sliders,
  Sparkles,
  X,
  Clock,
  Globe
} from 'lucide-react';

const ONBOARDING_STORAGE_KEY = 'portfolio_first_visit_completed';
const SIDEBAR_STORAGE_KEY = 'sidebar_collapsed';

export default function Dashboard() {
  const [metrics, setMetrics] = useState<any>(null);
  const [portfolioData, setPortfolioData] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState('portfolio');
  const [isScanning, setIsScanning] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [scanResult, setScanResult] = useState<any>(null);
  const [scanDuration, setScanDuration] = useState<number | null>(null);
  const [scanCount, setScanCount] = useState(0);

  // 1. Collapsible Sidebar State - Collapsed by default on desktop for maximum data visibility
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem(SIDEBAR_STORAGE_KEY);
      // Collapsed by default on desktop unless explicitly set to 'false' (open)
      return saved === 'false';
    } catch {
      return false;
    }
  });

  // 2. Portfolio Customization Drawer State
  const [isCustomizerOpen, setIsCustomizerOpen] = useState(false);

  // 3. Stock Universe Selector Modal State
  const [isUniverseSelectorOpen, setIsUniverseSelectorOpen] = useState(false);

  // 3. Compact First-Visit Guide State
  const [showOnboarding, setShowOnboarding] = useState<boolean>(() => {
    try {
      return localStorage.getItem(ONBOARDING_STORAGE_KEY) !== 'true';
    } catch {
      return false;
    }
  });

  const toggleSidebar = () => {
    setIsSidebarOpen(prev => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, String(!next));
      } catch (e) {
        console.error(e);
      }
      return next;
    });
  };

  const handleDismissOnboarding = () => {
    setShowOnboarding(false);
    try {
      localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true');
    } catch (e) {
      console.error(e);
    }
  };

  const handleStartCustomizingFromOnboarding = () => {
    handleDismissOnboarding();
    setIsCustomizerOpen(true);
  };

  const loadData = useCallback(() => {
    Promise.all([
      api.getPortfolioMetrics().then(setMetrics),
      api.getPortfolio().then(setPortfolioData)
    ]).catch(console.error);
  }, []);

  const handleConfigChange = () => {
    setScanResult(null);
    setScanDuration(null);
    loadData();
    setScanCount(c => c + 1);
  };

  const handleHoldingsUpdated = () => {
    loadData();
    setScanCount(c => c + 1);
  };

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleScan = async () => {
    if (isScanning || isResetting) return;
    setIsScanning(true);
    setScanResult(null);
    const startTime = performance.now();
    try {
      const res = await api.scanMarket();
      const elapsed = Number(((performance.now() - startTime) / 1000).toFixed(1));
      setScanDuration(elapsed);
      setScanResult(res);
      setScanCount(c => c + 1);
      loadData();
    } catch (err: any) {
      console.error(err);
      const msg = err?.response?.data?.detail || err?.message || "Market scan could not be completed. Please check connection and retry.";
      setScanResult({ message: `Scan error: ${msg}` });
    } finally {
      setIsScanning(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm("Are you sure you want to reset runtime risk signals and restore portfolio baseline? System capital and settings will be preserved.")) {
      return;
    }
    setIsResetting(true);
    try {
      await api.resetData();
      setScanResult({ message: "Runtime risk signals and rebalance orders successfully reset to baseline." });
      setScanDuration(null);
      setScanCount(c => c + 1);
      loadData();
    } catch (err) {
      console.error(err);
      setScanResult({ message: "Failed to reset data." });
    } finally {
      setIsResetting(false);
    }
  };

  const repCurr = (metrics?.reporting_currency || 'INR').toUpperCase();
  const repSymbol = metrics?.reporting_currency_symbol || (repCurr === 'INR' ? '₹' : '$');

  const handleCurrencyToggle = async (curr: 'INR' | 'USD') => {
    try {
      await api.setReportingCurrency(curr);
      loadData();
    } catch (e) {
      console.error(e);
    }
  };

  const isPreScan = !metrics?.last_updated || metrics.last_updated === 'Never' || metrics.last_updated.toLowerCase().includes('no scan');
  const lastScanLabel = !isPreScan
    ? `Last scan: ${metrics?.last_updated}${metrics?.last_scan_duration ? ` (${metrics.last_scan_duration}s)` : (scanDuration ? ` (${scanDuration}s)` : '')}`
    : 'No market scan executed yet (initial baseline state)';

  const initialCap = metrics?.initial_capital ?? (repCurr === 'INR' ? 84000000 : 1000000);
  const holdingsVal = metrics?.holdings_market_value;
  const cashBal = metrics?.cash_balance;
  const totalVal = metrics?.total_value;

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden">
      {/* 1. Collapsible Sidebar Component */}
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => {
          setIsSidebarOpen(false);
          try {
            localStorage.setItem(SIDEBAR_STORAGE_KEY, 'true');
          } catch (e) {
            console.error(e);
          }
        }}
        onConfigChange={handleConfigChange}
        onOpenCustomizer={() => setIsCustomizerOpen(true)}
        onOpenUniverseSelector={() => setIsUniverseSelectorOpen(true)}
      />

      {/* Main Content Area - Expands to 100% width when sidebar is collapsed */}
      <div className="flex-1 min-w-0 h-full overflow-y-auto p-4 sm:p-6 lg:p-7 space-y-4">

        {/* Main Title Header */}
        <div>
          <h1 className="text-xl sm:text-2xl lg:text-3xl font-bold text-heading tracking-tight">
            AI Financial Risk & Portfolio Intelligence Platform
          </h1>
          <p className="text-xs text-gray-400 font-mono mt-0.5">
            Cross-Asset Risk Engine, Tactical Rebalancing & Banking Stress Testing
          </p>
        </div>

        {/* Compact Action Toolbar directly below Main Title */}
        <div className="bg-surface border border-border rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 shadow-xs">
          <div className="flex items-center gap-2.5 flex-wrap">
            {/* System Controls Toggle */}
            <button
              type="button"
              onClick={toggleSidebar}
              className="flex items-center gap-2 bg-background hover:bg-border/60 border border-border px-3 py-1.5 rounded-lg text-xs font-semibold text-gray-300 hover:text-white transition-all shadow-xs"
              title={isSidebarOpen ? "Collapse System Controls" : "Expand System Controls"}
              aria-label={isSidebarOpen ? "Collapse System Controls" : "Expand System Controls"}
            >
              {isSidebarOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
              <span>{isSidebarOpen ? "Collapse Controls" : "System Controls"}</span>
            </button>

            {/* Reporting Currency Switcher */}
            <div className="flex items-center bg-background border border-border rounded-lg p-0.5 text-xs font-semibold">
              <button
                type="button"
                onClick={() => handleCurrencyToggle('INR')}
                className={`px-2.5 py-1 rounded-md transition-colors font-mono ${
                  repCurr === 'INR'
                    ? 'bg-primary text-white shadow-xs font-bold'
                    : 'text-gray-400 hover:text-white'
                }`}
                title="Switch default reporting currency to Indian Rupee (₹ INR)"
              >
                ₹ INR
              </button>
              <button
                type="button"
                onClick={() => handleCurrencyToggle('USD')}
                className={`px-2.5 py-1 rounded-md transition-colors font-mono ${
                  repCurr === 'USD'
                    ? 'bg-primary text-white shadow-xs font-bold'
                    : 'text-gray-400 hover:text-white'
                }`}
                title="Switch default reporting currency to US Dollar ($ USD)"
              >
                $ USD
              </button>
            </div>

            {/* Select Stock Universe */}
            <button
              type="button"
              onClick={() => setIsUniverseSelectorOpen(true)}
              className="flex items-center gap-2 bg-background hover:bg-border/60 border border-border px-3.5 py-1.5 rounded-lg font-semibold text-xs text-gray-200 hover:text-white transition-all shadow-xs"
              title="Select 10 stocks from the 20-stock US and Indian catalog universe"
            >
              <Globe size={14} className="text-primary" />
              <span>Stock Universe (10 / 20)</span>
            </button>

            {/* Customize Portfolio Holdings */}
            <button
              type="button"
              onClick={() => setIsCustomizerOpen(true)}
              className="flex items-center gap-2 bg-primary hover:bg-blue-600 text-white px-3.5 py-1.5 rounded-lg font-semibold text-xs shadow-sm transition-all"
              title="Open constituent share holdings editor"
            >
              <Sliders size={14} />
              <span>Customize Portfolio</span>
            </button>

            {/* Reset Data Action */}
            <button
              type="button"
              onClick={handleReset}
              disabled={isScanning || isResetting}
              className="flex items-center gap-1.5 bg-background hover:bg-red-500/10 hover:border-red-500 text-gray-400 hover:text-red-400 border border-border px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
              title="Reset runtime risk signals and restore portfolio baseline"
            >
              <RotateCcw className={isResetting ? "animate-spin" : ""} size={13} />
              <span>{isResetting ? "Resetting..." : "Reset Data"}</span>
            </button>
          </div>

          {/* Compact Timestamp Pill */}
          <div className="flex items-center gap-2 text-xs text-gray-400 font-mono">
            <Clock size={13} className="text-primary" />
            <span className="truncate max-w-[280px] sm:max-w-none">{lastScanLabel}</span>
          </div>
        </div>

        {/* Compact, Non-Blocking First-Visit Guide */}
        {showOnboarding && (
          <div className="bg-primary/10 border border-primary/30 rounded-xl px-4 py-2.5 flex items-center justify-between gap-3 text-xs animate-in fade-in duration-200">
            <div className="flex items-center gap-2.5 min-w-0">
              <Sparkles size={16} className="text-primary shrink-0" />
              <span className="text-gray-200 truncate">
                <strong>Welcome!</strong> Customize your constituent share positions across the 10 S&P assets or explore with the baseline $1,000,000 equal-weight benchmark.
              </span>
            </div>
            <div className="flex items-center gap-2.5 shrink-0">
              <button
                type="button"
                onClick={handleStartCustomizingFromOnboarding}
                className="text-primary hover:underline font-semibold"
              >
                Customize Holdings
              </button>
              <span className="text-gray-600">•</span>
              <button
                type="button"
                onClick={handleDismissOnboarding}
                className="text-gray-400 hover:text-white"
              >
                Dismiss
              </button>
              <button
                type="button"
                onClick={handleDismissOnboarding}
                className="text-gray-500 hover:text-white p-0.5 rounded"
                aria-label="Close guide"
              >
                <X size={14} />
              </button>
            </div>
          </div>
        )}

        {/* Financial Accounting Top Metrics Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          <MetricCard
            title={`Consolidated NAV (${repCurr})`}
            value={
              <div className="flex items-center gap-2 flex-wrap">
                <span>
                  {totalVal != null 
                    ? formatCurrency(totalVal, repCurr) 
                    : (repCurr === 'INR' && metrics?.indicative_nav_inr != null
                      ? formatCurrency(metrics.indicative_nav_inr, 'INR')
                      : (metrics?.indicative_nav_usd != null 
                        ? formatCurrency(metrics.indicative_nav_usd, 'USD') 
                        : 'Unavailable'))}
                </span>
                {metrics?.nav_status === 'LIVE' && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-semibold font-mono">
                    LIVE
                  </span>
                )}
                {metrics?.nav_status === 'INDICATIVE_FALLBACK' && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 font-semibold font-mono" title={metrics?.nav_unavailability_reason || 'Indicative fallback prices'}>
                    INDICATIVE
                  </span>
                )}
                {metrics?.nav_status === 'UNAVAILABLE' && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30 font-semibold font-mono" title={metrics?.nav_unavailability_reason || 'Missing market data'}>
                    UNAVAILABLE
                  </span>
                )}
              </div>
            }
            subtitle={`Reporting: ${repCurr} (${repSymbol}) • Initial Capital: ${formatCurrency(initialCap, repCurr)}`}
            footnote={
              totalVal != null 
                ? `NAV = Cash (${repCurr}) + Invested Holdings (${repCurr})` 
                : (metrics?.nav_unavailability_reason ? `Reason: ${metrics.nav_unavailability_reason}` : "Consolidated multi-currency valuation (USD/INR)")
            }
          />
          <MetricCard
            title="Invested Market Value"
            value={
              holdingsVal != null ? (
                formatCurrency(holdingsVal, repCurr)
              ) : metrics?.indicative_holdings_value != null ? (
                <div className="flex items-center gap-2">
                  <span>{formatCurrency(metrics.indicative_holdings_value, repCurr)}</span>
                  <span className="text-[10px] font-semibold bg-amber-500/20 text-amber-400 border border-amber-500/30 px-1.5 py-0.5 rounded">
                    INDICATIVE
                  </span>
                </div>
              ) : (
                <span className="text-muted-foreground text-sm font-normal">Valuation Pending</span>
              )
            }
            subtitle={
              metrics?.holdings_market_value_inr > 0 && metrics?.holdings_market_value_usd > 0
                ? `INR: ${formatCurrency(metrics?.holdings_market_value_inr, 'INR')} • USD: ${formatCurrency(metrics?.holdings_market_value_usd, 'USD')}`
                : (metrics?.holdings_market_value_inr > 0 
                  ? `INR: ${formatCurrency(metrics?.holdings_market_value_inr, 'INR')} (NSE Quotes)` 
                  : `USD: ${formatCurrency(metrics?.holdings_market_value_usd, 'USD')} (US Quotes)`)
            }
            footnote={`FX Rate: 1 USD = ${metrics?.fx_rate ?? 84.00} INR • Source: ${metrics?.fx_rate_source || 'Verified Rate'}`}
          />
          <MetricCard
            title="Available Cash Balances"
            value={
              <div className="flex flex-col text-sm sm:text-base font-bold font-mono">
                <span>{formatCurrency(cashBal, repCurr)} ({repCurr})</span>
                <span className="text-xs text-amber-400 font-normal">
                  USD: {formatCurrency(metrics?.cash_usd, 'USD')} • INR: {formatCurrency(metrics?.cash_inr, 'INR')}
                </span>
              </div>
            }
            subtitle={`Trading Fees: ${formatCurrency(metrics?.cumulative_fees_paid ?? metrics?.est_txn_cost ?? 0, repCurr)}`}
            footnote="Strict currency isolation: orders draw strictly from currency-specific cash"
          />
          <MetricCard
            title="Gross Traded Volume & Turnover"
            value={metrics ? formatCurrency(metrics?.gross_turnover ?? metrics?.total_turnover ?? 0, repCurr) : '...'}
            subtitle={metrics ? `One-Way: ${formatCurrency(metrics?.one_way_turnover ?? 0, repCurr)} (${(metrics?.one_way_turnover_pct ?? 0).toFixed(2)}%)` : `One-Way: ${formatCurrency(0, repCurr)}`}
            footnote="Simulated execution at 10 bps transaction fee rate in native currency"
          />
        </div>

        {/* Navigation Tabs */}
        <div className="border-b border-border pt-1">
          <nav className="-mb-px flex space-x-6 sm:space-x-8 overflow-x-auto">
            <TabButton active={activeTab === 'portfolio'} onClick={() => setActiveTab('portfolio')} label="📊 Module A — Tactical Portfolio Rebalancing" />
            <TabButton active={activeTab === 'signals'} onClick={() => setActiveTab('signals')} label="📡 Risk Engine — Structured Signals" />
            <TabButton active={activeTab === 'stress'} onClick={() => setActiveTab('stress')} label="⚠️ Module B — Strategic Banking Stress Testing" />
          </nav>
        </div>

        {/* Tab Content */}
        <div className="pt-2">
          {activeTab === 'portfolio' && (
            <Portfolio
              metrics={metrics}
              refreshTrigger={scanCount}
              isLoading={isResetting}
              isScanning={isScanning}
              scanResult={scanResult}
              scanDuration={scanDuration}
              onScan={handleScan}
              onOpenCustomizer={() => setIsCustomizerOpen(true)}
            />
          )}
          {activeTab === 'signals' && <RiskSignals refreshTrigger={scanCount} />}
          {activeTab === 'stress' && <StressTest />}
        </div>
      </div>

      {/* 2. Portfolio Customization Holdings Editor Drawer */}
      {isCustomizerOpen && (
        <PortfolioCustomization
          isOpen={true}
          onClose={() => setIsCustomizerOpen(false)}
          initialCapital={initialCap}
          portfolioData={portfolioData}
          onHoldingsUpdated={handleHoldingsUpdated}
        />
      )}

      {/* 3. Stock Universe Selection Modal */}
      {isUniverseSelectorOpen && (
        <StockUniverseSelector
          isOpen={true}
          onClose={() => setIsUniverseSelectorOpen(false)}
          onUniverseUpdated={handleConfigChange}
        />
      )}
    </div>
  );
}

function MetricCard({ title, value, subtitle, footnote }: { title: string, value: React.ReactNode, subtitle?: string, footnote?: string }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex flex-col justify-between shadow-xs">
      <div>
        <h3 className="text-xs font-medium text-gray-400 mb-1">{title}</h3>
        <div className="text-lg sm:text-xl font-bold text-heading font-mono">{value}</div>
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
      className={`whitespace-nowrap py-3 px-1 border-b-2 font-medium text-xs sm:text-sm transition-colors ${
        active
          ? 'border-primary text-primary font-semibold'
          : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-500'
      }`}
    >
      {label}
    </button>
  );
}
