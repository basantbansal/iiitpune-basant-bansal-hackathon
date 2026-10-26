import React, { useState, useMemo } from 'react';
import { 
  X, 
  RotateCcw, 
  Sliders, 
  AlertTriangle, 
  Check, 
  DollarSign,
  Wallet,
  Coins,
  ShieldAlert
} from 'lucide-react';
import { api } from '../api';

export interface ConstituentStock {
  ticker: string;
  name: string;
  price: number;
  isLivePrice: boolean;
  shares: number;
  currency?: string;
  currencySymbol?: string;
  market?: string;
}

const DEFAULT_CONSTITUENTS_CONFIG = [
  { ticker: 'AAPL', name: 'Apple Inc.' },
  { ticker: 'MSFT', name: 'Microsoft Corporation' },
  { ticker: 'NVDA', name: 'NVIDIA Corporation' },
  { ticker: 'AMZN', name: 'Amazon.com Inc.' },
  { ticker: 'GOOGL', name: 'Alphabet Inc.' },
  { ticker: 'META', name: 'Meta Platforms Inc.' },
  { ticker: 'TSLA', name: 'Tesla Inc.' },
  { ticker: 'JPM', name: 'JPMorgan Chase & Co.' },
  { ticker: 'JNJ', name: 'Johnson & Johnson' },
  { ticker: 'XOM', name: 'Exxon Mobil Corporation' },
];

// Institutional tracking-error limits (5% to 15% for 10-asset universe)
const RISK_ENGINE_MIN_WEIGHT_PCT = 5.0;
const RISK_ENGINE_MAX_WEIGHT_PCT = 15.0;

interface PortfolioCustomizationProps {
  isOpen: boolean;
  onClose: () => void;
  initialCapital?: number;
  portfolioData?: any[];
  onHoldingsUpdated: () => void;
}

export default function PortfolioCustomization({
  isOpen,
  onClose,
  initialCapital = 1000000,
  portfolioData = [],
  onHoldingsUpdated,
}: PortfolioCustomizationProps) {
  // Extract live prices and current shares from portfolioData dynamically
  const constituentList: ConstituentStock[] = useMemo(() => {
    if (portfolioData && portfolioData.length > 0) {
      return portfolioData.map(p => {
        const livePrice = p.price != null && p.price > 0 ? p.price : null;
        const currency = p.currency || 'USD';
        const currencySymbol = p.currency_symbol || (currency === 'INR' ? '₹' : '$');
        const defaultRef = currency === 'INR' ? 1000.0 : 100.0;
        const refPrice = p.reference_price != null ? p.reference_price : defaultRef;
        const price = livePrice !== null ? livePrice : refPrice;
        const isLivePrice = livePrice !== null && !p.is_fallback_price;
        const existingShares = p.pre_shares != null ? Math.round(p.pre_shares) : (p.current_shares != null ? Math.round(p.current_shares) : 10);
        return {
          ticker: p.ticker,
          name: p.company_name || p.ticker,
          price,
          isLivePrice,
          shares: existingShares,
          currency,
          currencySymbol,
          market: p.market || 'US',
        };
      });
    }

    return DEFAULT_CONSTITUENTS_CONFIG.map(def => {
      return {
        ticker: def.ticker,
        name: def.name,
        price: 100.0,
        isLivePrice: false,
        shares: 10,
        currency: 'USD',
        currencySymbol: '$',
        market: 'US'
      };
    });
  }, [portfolioData]);

  // Local draft state for shares
  const [draftShares, setDraftShares] = useState<Record<string, number>>(() => {
    const initial: Record<string, number> = {};
    constituentList.forEach(c => {
      initial[c.ticker] = c.shares;
    });
    return initial;
  });

  const [inputStrings, setInputStrings] = useState<Record<string, string>>(() => {
    const strMap: Record<string, string> = {};
    constituentList.forEach(c => {
      strMap[c.ticker] = c.shares.toString();
    });
    return strMap;
  });

  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const hasMixedCurrencies = useMemo(() => {
    const currencies = new Set(constituentList.map(c => c.currency || 'USD'));
    return currencies.size > 1;
  }, [constituentList]);

  const hasInrHoldings = useMemo(() => {
    return constituentList.some(c => c.currency === 'INR');
  }, [constituentList]);

  // Real-time financial calculations (separated by currency to avoid commingling USD and INR)
  const usdInvestedValue = useMemo(() => {
    return constituentList
      .filter(item => (item.currency || 'USD') === 'USD')
      .reduce((sum, item) => sum + ((draftShares[item.ticker] || 0) * item.price), 0);
  }, [constituentList, draftShares]);

  const inrInvestedValue = useMemo(() => {
    return constituentList
      .filter(item => item.currency === 'INR')
      .reduce((sum, item) => sum + ((draftShares[item.ticker] || 0) * item.price), 0);
  }, [constituentList, draftShares]);

  const isIndiaOnly = hasInrHoldings && !constituentList.some(c => (c.currency || 'USD') === 'USD');
  const inrBudget = initialCapital >= 10_000_000 ? initialCapital : initialCapital * 84.0;
  const effectiveBudget = isIndiaOnly ? inrBudget : initialCapital;

  const roundedInvested = Number(usdInvestedValue.toFixed(2));
  const roundedInrInvested = Number(inrInvestedValue.toFixed(2));
  const remainingCash = Number((effectiveBudget - (isIndiaOnly ? roundedInrInvested : roundedInvested)).toFixed(2));
  const totalPortfolioValue = effectiveBudget; // Budget = Invested + Cash
  const currSymbol = isIndiaOnly ? '₹' : '$';
  const currName = isIndiaOnly ? 'INR' : 'USD';

  // Validations
  const hasNegativeShares = Object.values(draftShares).some(qty => qty < 0);
  const hasFractionalShares = Object.values(draftShares).some(qty => !Number.isInteger(qty));
  const exceedsBudget = remainingCash < -0.01;
  const isBudgetValid = remainingCash >= -0.01;
  const isValid = !hasNegativeShares && !hasFractionalShares && isBudgetValid;

  // Tracking error constraints check (5% to 15%)
  const outOfBoundsHoldings = constituentList.filter(item => {
    const qty = draftShares[item.ticker] || 0;
    const sameCurrencyHoldings = constituentList.filter(c => (c.currency || 'USD') === (item.currency || 'USD'));
    const totalSameCurr = sameCurrencyHoldings.reduce((sum, c) => sum + ((draftShares[c.ticker] || 0) * c.price), 0);
    if (totalSameCurr <= 0) return false;
    const weightPct = ((qty * item.price) / totalSameCurr) * 100;
    return weightPct < RISK_ENGINE_MIN_WEIGHT_PCT || weightPct > RISK_ENGINE_MAX_WEIGHT_PCT;
  });

  const handleShareChange = (ticker: string, text: string) => {
    setInputStrings(prev => ({ ...prev, [ticker]: text }));
    setErrorMessage(null);
    if (text === '') {
      setDraftShares(prev => ({ ...prev, [ticker]: 0 }));
      return;
    }
    const parsed = Number(text);
    if (!isNaN(parsed)) {
      setDraftShares(prev => ({ ...prev, [ticker]: parsed }));
    }
  };

  const handleEqualWeightAllocation = () => {
    const perAssetCapital = effectiveBudget / constituentList.length;
    const nextShares: Record<string, number> = {};
    const nextStrings: Record<string, string> = {};

    constituentList.forEach(item => {
      // Allocate whole shares within per-asset budget
      const shares = Math.floor(perAssetCapital / item.price);
      nextShares[item.ticker] = Math.max(0, shares);
      nextStrings[item.ticker] = shares.toString();
    });

    setDraftShares(nextShares);
    setInputStrings(nextStrings);
    setErrorMessage(null);
  };

  const handleClearAll = () => {
    const nextShares: Record<string, number> = {};
    const nextStrings: Record<string, string> = {};
    constituentList.forEach(item => {
      nextShares[item.ticker] = 0;
      nextStrings[item.ticker] = "0";
    });
    setDraftShares(nextShares);
    setInputStrings(nextStrings);
    setErrorMessage(null);
  };

  const handleSave = async () => {
    if (!isValid) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await api.updateHoldings(draftShares);
      setSaveSuccess(true);
      onHoldingsUpdated();
      setTimeout(() => {
        setSaveSuccess(false);
        onClose();
      }, 700);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to update holdings on the backend.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetToDefault = async () => {
    if (!window.confirm("Reset portfolio holdings to the default 10 shares per constituent benchmark (within $1,000,000 budget)?")) {
      return;
    }
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await api.resetHoldings();
      setSaveSuccess(true);
      onHoldingsUpdated();
      setTimeout(() => {
        setSaveSuccess(false);
        onClose();
      }, 700);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to reset holdings.");
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden flex justify-end">
      {/* Dark backdrop */}
      <div 
        className="fixed inset-0 bg-black/70 backdrop-blur-xs transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer Container */}
      <div className="relative w-full max-w-2xl bg-surface border-l border-border shadow-2xl flex flex-col h-full z-10 animate-in slide-in-from-right duration-200">
        
        {/* Drawer Header */}
        <div className="p-4 sm:p-5 border-b border-border flex items-center justify-between bg-surface/95 backdrop-blur-md sticky top-0 z-20">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20 text-primary">
              <Sliders size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-heading flex items-center gap-2">
                Customize Portfolio Holdings
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Simulate and customize constituent share positions across the 10 monitored S&P assets.
              </p>
            </div>
          </div>
          
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-background/80 transition-colors"
            title="Cancel and close without saving"
            aria-label="Close drawer"
          >
            <X size={20} />
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-5">

          {/* Real-time Financial Accounting Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div className="bg-background/80 border border-border rounded-xl p-3">
              <div className="text-[11px] font-medium text-gray-400 flex items-center gap-1 mb-1">
                <Wallet size={12} className="text-primary" />
                <span>Starting Budget</span>
              </div>
              <div className="text-sm sm:text-base font-bold font-mono text-heading">
                {currSymbol}{effectiveBudget.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="text-[10px] text-gray-500 mt-0.5">Budget ({currName})</div>
            </div>

            <div className="bg-background/80 border border-border rounded-xl p-3">
              <div className="text-[11px] font-medium text-gray-400 flex items-center gap-1 mb-1">
                <Coins size={12} className="text-primary" />
                <span>{hasInrHoldings && !isIndiaOnly ? 'USD Holdings' : 'Invested Value'}</span>
              </div>
              <div className="text-sm sm:text-base font-bold font-mono text-heading">
                {currSymbol}{(isIndiaOnly ? roundedInrInvested : roundedInvested).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="text-[10px] text-gray-500 mt-0.5">
                {effectiveBudget > 0 ? `${(((isIndiaOnly ? roundedInrInvested : roundedInvested) / effectiveBudget) * 100).toFixed(1)}% deployed` : '0%'}
              </div>
            </div>

            {hasMixedCurrencies ? (
              <div className="bg-background/80 border border-border rounded-xl p-3">
                <div className="text-[11px] font-medium text-gray-400 flex items-center gap-1 mb-1">
                  <Coins size={12} className="text-orange-400" />
                  <span>INR Holdings</span>
                </div>
                <div className="text-sm sm:text-base font-bold font-mono text-heading">
                  ₹{roundedInrInvested.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="text-[10px] text-gray-500 mt-0.5">
                  Native NSE quotes
                </div>
              </div>
            ) : (
              <div className="bg-background/80 border border-border rounded-xl p-3">
                <div className="text-[11px] font-medium text-gray-400 flex items-center gap-1 mb-1">
                  <span>Total Portfolio</span>
                </div>
                <div className="text-sm sm:text-base font-bold font-mono text-heading">
                  {currSymbol}{totalPortfolioValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="text-[10px] text-gray-500 mt-0.5">Holdings + Cash</div>
              </div>
            )}

            <div className={`border rounded-xl p-3 ${
              exceedsBudget ? 'bg-amber-500/10 border-amber-500/30' : 'bg-background/80 border border-border'
            }`}>
              <div className="text-[11px] font-medium text-gray-400 flex items-center gap-1 mb-1">
                <DollarSign size={12} className={exceedsBudget ? 'text-amber-400' : 'text-success'} />
                <span>Remaining {currName} Cash</span>
              </div>
              <div className={`text-sm sm:text-base font-bold font-mono ${
                exceedsBudget ? 'text-amber-400' : 'text-success'
              }`}>
                {remainingCash < 0 
                  ? `-${currSymbol}${Math.abs(remainingCash).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` 
                  : `${currSymbol}${remainingCash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </div>
              <div className="text-[10px] text-gray-500 mt-0.5">
                {exceedsBudget ? 'Exceeds budget' : 'Unallocated reserves'}
              </div>
            </div>
          </div>

          {hasMixedCurrencies && (
            <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-3 text-xs text-blue-300">
              <strong>Multi-Currency Portfolio Active:</strong> Holdings contain both USD ($) and Indian NSE (₹ INR) constituents. USD positions deduct from USD cash reserves, and INR positions are tracked natively in ₹ with automated currency isolation and consolidated reporting.
            </div>
          )}

          {/* Calm Inline Budget Summary & Auto-Fit Helper */}
          {exceedsBudget && (
            <div className="bg-surface border border-amber-500/30 rounded-xl p-3 text-xs text-gray-300 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
              <div className="flex items-center gap-2 min-w-0">
                <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0"></span>
                <span className="truncate sm:whitespace-normal">
                  Allocation exceeds available budget by <strong className="font-mono text-amber-400">{currSymbol}{Math.abs(remainingCash).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>. Reduce shares to stay within {currSymbol}{effectiveBudget.toLocaleString()}.
                </span>
              </div>
              <button
                type="button"
                onClick={handleEqualWeightAllocation}
                className="text-xs text-primary hover:underline font-semibold shrink-0 text-left sm:text-right"
              >
                Auto-Fit Equal Weight
              </button>
            </div>
          )}

          {hasNegativeShares && (
            <div className="bg-danger/10 border border-danger/40 rounded-xl p-3 text-xs text-danger flex items-center gap-2">
              <AlertTriangle size={15} />
              <span>Share quantities cannot be negative. Please enter zero or positive integers.</span>
            </div>
          )}

          {hasFractionalShares && (
            <div className="bg-danger/10 border border-danger/40 rounded-xl p-3 text-xs text-danger flex items-center gap-2">
              <AlertTriangle size={15} />
              <span>Share quantities must be whole numbers (no fractional shares in baseline holdings).</span>
            </div>
          )}

          {errorMessage && (
            <div className="bg-danger/10 border border-danger/40 rounded-xl p-3 text-xs text-danger flex items-center gap-2">
              <AlertTriangle size={15} />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* Institutional Rebalancing Constraints Banner */}
          <div className="rounded-xl p-3.5 border bg-background/50 border-border space-y-2">
            <div className="flex items-start gap-2.5">
              <div className={`p-1.5 rounded-md shrink-0 mt-0.5 ${
                outOfBoundsHoldings.length > 0 
                  ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' 
                  : 'bg-primary/10 text-primary border border-primary/20'
              }`}>
                {outOfBoundsHoldings.length > 0 ? <AlertTriangle size={15} /> : <ShieldAlert size={15} />}
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-heading">
                    Tactical Risk Engine Constraints (5.0% – 15.0%)
                  </h4>
                  {outOfBoundsHoldings.length === 0 && (
                    <span className="text-[11px] text-success font-medium flex items-center gap-1">
                      <Check size={13} /> Compliant
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-gray-400 leading-relaxed">
                  Institutional risk rules enforce tracking-error limits of 
                  <strong className="text-gray-300"> 5.0% min – 15.0% max</strong> (&plusmn;5.0 percentage points relative to equal-weight baseline).
                </p>
                {outOfBoundsHoldings.length > 0 && (
                  <p className="text-[11px] text-amber-300/90 leading-relaxed mt-1">
                    ⚠️ Constituents with weights outside 5%–15% ({outOfBoundsHoldings.map(h => h.ticker).join(', ')}) will be recorded as your custom initial holdings, but subsequent market scans will rebalance positions back toward risk bounds.
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Quick Helper Presets Toolbar */}
          <div className="flex items-center justify-between text-xs text-gray-400 pt-1">
            <span className="font-semibold uppercase tracking-wider text-[11px]">
              Constituent Positions (10 Assets)
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleEqualWeightAllocation}
                className="px-2.5 py-1 rounded bg-background hover:bg-border/60 border border-border text-gray-300 text-[11px] font-medium transition-colors"
                title="Allocate ~$100,000 equal value per constituent in whole shares"
              >
                Equal-Weight ($100k ea)
              </button>
              <button
                type="button"
                onClick={handleClearAll}
                className="px-2.5 py-1 rounded bg-background hover:bg-border/60 border border-border text-gray-300 text-[11px] font-medium transition-colors"
                title="Set all share quantities to 0"
              >
                Clear All (0 Shs)
              </button>
            </div>
          </div>

          {/* Holdings Constituents Table / Cards */}
          <div className="space-y-2">
            {constituentList.map(stock => {
              const qty = draftShares[stock.ticker] || 0;
              const positionValue = qty * stock.price;
              const weightPct = roundedInvested > 0 ? (positionValue / roundedInvested) * 100 : 0;
              const isInvalidQty = qty < 0 || !Number.isInteger(qty);
              const isOutOfBound = roundedInvested > 0 && qty > 0 && (weightPct < RISK_ENGINE_MIN_WEIGHT_PCT || weightPct > RISK_ENGINE_MAX_WEIGHT_PCT);

              return (
                <div 
                  key={stock.ticker}
                  className="bg-background/40 hover:bg-background/70 border border-border rounded-xl p-3 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                >
                  {/* Left: Ticker, Name, Price Feed */}
                  <div className="min-w-0 flex items-center gap-3">
                    <span className="font-mono font-bold text-sm text-heading px-2 py-0.5 rounded bg-surface border border-border shrink-0">
                      {stock.ticker}
                    </span>
                    <div className="truncate">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-gray-200 truncate">
                          {stock.name}
                        </span>
                        {stock.isLivePrice ? (
                          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-success/10 text-success border border-success/20">
                            Live
                          </span>
                        ) : (
                          <span 
                            className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20"
                            title="Live market feed unavailable; deterministic reference price used"
                          >
                            Ref {stock.currencySymbol || '$'}{stock.price.toFixed(2)}
                          </span>
                        )}
                        <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-background border border-border text-gray-400">
                          {stock.currency || 'USD'}
                        </span>
                      </div>
                      <div className="text-[11px] font-mono text-gray-400 mt-0.5">
                        Price: {stock.currencySymbol || '$'}{stock.price.toFixed(2)}
                      </div>
                    </div>
                  </div>

                  {/* Right: Quantity Input, Position Value, Weight */}
                  <div className="flex items-center gap-3 shrink-0 self-end sm:self-auto">
                    {/* Share Quantity Input */}
                    <div className="flex flex-col items-end">
                      <div className="flex items-center gap-1.5">
                        <label className="text-[11px] text-gray-400">Shares:</label>
                        <input 
                          type="number"
                          min="0"
                          step="1"
                          value={inputStrings[stock.ticker] ?? qty.toString()}
                          onChange={e => handleShareChange(stock.ticker, e.target.value)}
                          className={`w-28 bg-surface border rounded-lg py-1 px-2.5 text-xs font-mono text-right text-heading focus:outline-hidden focus:border-primary ${
                            isInvalidQty ? 'border-danger text-danger' : 'border-border'
                          }`}
                        />
                      </div>
                      {isInvalidQty && (
                        <span className="text-[10px] text-danger mt-0.5">Whole shares &ge; 0</span>
                      )}
                    </div>

                    {/* Position Market Value & Allocation % */}
                    <div className="w-28 text-right">
                      <div className="text-xs font-mono font-bold text-heading">
                        {stock.currencySymbol || '$'}{positionValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                      <div className="flex items-center justify-end gap-1 mt-0.5">
                        <span className="text-[10px] font-mono text-gray-400">
                          {weightPct.toFixed(1)}%
                        </span>
                        {isOutOfBound && (
                          <span 
                            className="text-[9px] font-mono px-1 py-0.2 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20"
                            title="Outside 5%–15% rebalancing bounds"
                          >
                            {weightPct < RISK_ENGINE_MIN_WEIGHT_PCT ? '<5%' : '>15%'}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

        </div>

        {/* Drawer Footer Actions */}
        <div className="p-4 border-t border-border bg-surface/95 backdrop-blur-md flex flex-col sm:flex-row items-center justify-between gap-3 sticky bottom-0 z-20">
          <button
            type="button"
            onClick={handleResetToDefault}
            disabled={isSaving}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-danger px-2 py-1.5 rounded transition-colors disabled:opacity-50"
            title="Reset portfolio to baseline $1,000,000 equal-weight benchmark"
          >
            <RotateCcw size={14} />
            <span>Reset to Default ($1M)</span>
          </button>

          <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 rounded-lg border border-border text-gray-300 hover:text-white hover:bg-background/80 text-xs font-semibold transition-colors disabled:opacity-50"
            >
              Cancel
            </button>

            <button
              type="button"
              onClick={handleSave}
              disabled={!isValid || isSaving || saveSuccess}
              className="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold shadow-md transition-all"
            >
              {saveSuccess ? (
                <>
                  <Check size={15} className="text-white animate-bounce" />
                  <span>Saved!</span>
                </>
              ) : isSaving ? (
                <span>Saving...</span>
              ) : (
                <>
                  <Check size={15} />
                  <span>Save Holdings</span>
                </>
              )}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
