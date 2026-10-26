import React, { useState, useEffect, useMemo } from 'react';
import {
  X,
  Search,
  Check,
  RotateCcw,
  AlertCircle,
  Globe,
  SlidersHorizontal,
  Info
} from 'lucide-react';
import { api, type UniverseInstrument } from '../api';

interface StockUniverseSelectorProps {
  isOpen: boolean;
  onClose: () => void;
  onUniverseUpdated: () => void;
}

export default function StockUniverseSelector({
  isOpen,
  onClose,
  onUniverseUpdated,
}: StockUniverseSelectorProps) {
  const [instruments, setInstruments] = useState<UniverseInstrument[]>([]);
  const [activeSelection, setActiveSelection] = useState<string[]>([]);
  const [defaultSelection, setDefaultSelection] = useState<string[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const [searchQuery, setSearchQuery] = useState('');
  const [marketFilter, setMarketFilter] = useState<'ALL' | 'US' | 'IN' | 'SELECTED'>('ALL');

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Load catalog universe and active selection
  useEffect(() => {
    if (!isOpen) return;
    let isCancelled = false;
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    Promise.all([
      api.getUniverse(),
      api.getUniverseSelection(),
    ])
      .then(([allInsts, selectionData]) => {
        if (isCancelled) return;
        setInstruments(allInsts);
        setActiveSelection(selectionData.selection);
        setDefaultSelection(selectionData.default_selection);
        setSelectedIds(new Set(selectionData.selection));
        setIsLoading(false);
      })
      .catch(err => {
        if (isCancelled) return;
        console.error(err);
        setErrorMessage(err.message || 'Failed to load stock universe');
        setIsLoading(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [isOpen]);

  // Toggle selection
  const handleToggle = (id: string) => {
    setErrorMessage(null);
    setSuccessMessage(null);
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        if (next.size >= 10) {
          // Cannot add more than 10
          return prev;
        }
        next.add(id);
      }
      return next;
    });
  };

  // Reset to default 10 US stocks
  const handleResetToDefault = () => {
    setErrorMessage(null);
    setSuccessMessage(null);
    setSelectedIds(new Set(defaultSelection));
  };

  const [showConfirm, setShowConfirm] = useState(false);

  // Compute changes between activeSelection and selectedIds
  const hasSelectionChanged = useMemo(() => {
    if (selectedIds.size !== activeSelection.length) return true;
    return !activeSelection.every(id => selectedIds.has(id));
  }, [selectedIds, activeSelection]);

  const addedInstruments = useMemo(() => {
    return instruments.filter(i => selectedIds.has(i.id) && !activeSelection.includes(i.id));
  }, [instruments, selectedIds, activeSelection]);

  const removedInstruments = useMemo(() => {
    return instruments.filter(i => activeSelection.includes(i.id) && !selectedIds.has(i.id));
  }, [instruments, selectedIds, activeSelection]);

  const retainedInstruments = useMemo(() => {
    return instruments.filter(i => activeSelection.includes(i.id) && selectedIds.has(i.id));
  }, [instruments, selectedIds, activeSelection]);

  // Handle Apply button click
  const handleApplyClick = () => {
    if (selectedIds.size !== 10) {
      setErrorMessage(`Portfolio selection must contain exactly 10 instruments (currently ${selectedIds.size} selected).`);
      return;
    }
    if (hasSelectionChanged) {
      setShowConfirm(true);
    } else {
      onClose();
    }
  };

  // Confirm and persist selection to backend
  const handleConfirmAndSave = async () => {
    setIsSaving(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const idList = Array.from(selectedIds);
      const res = await api.updateUniverseSelection(idList);
      setActiveSelection(res.selection || idList);
      setSuccessMessage('Stock universe successfully updated.');
      setShowConfirm(false);
      onUniverseUpdated();
      setTimeout(() => {
        setSuccessMessage(null);
        onClose();
      }, 900);
    } catch (err: any) {
      console.error(err);
      setErrorMessage(err.message || 'Failed to update stock universe selection.');
    } finally {
      setIsSaving(false);
    }
  };

  // Filtered instruments
  const filteredInstruments = useMemo(() => {
    return instruments.filter(inst => {
      // Market filter
      if (marketFilter === 'US' && inst.market !== 'US') return false;
      if (marketFilter === 'IN' && inst.market !== 'IN') return false;
      if (marketFilter === 'SELECTED' && !selectedIds.has(inst.id)) return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchesTicker = inst.display_ticker.toLowerCase().includes(q);
        const matchesName = inst.name.toLowerCase().includes(q);
        const matchesSector = inst.sector.toLowerCase().includes(q);
        const matchesExchange = inst.exchange.toLowerCase().includes(q);
        const matchesId = inst.id.toLowerCase().includes(q);
        return matchesTicker || matchesName || matchesSector || matchesExchange || matchesId;
      }
      return true;
    });
  }, [instruments, marketFilter, searchQuery, selectedIds]);

  const selectedCount = selectedIds.size;
  const isExactlyTen = selectedCount === 10;
  const countColor = isExactlyTen ? 'text-success' : selectedCount > 10 ? 'text-danger' : 'text-amber-400';

  // Count by market in selection
  const usSelectedCount = useMemo(() => {
    return Array.from(selectedIds).filter(id => id.startsWith('US_')).length;
  }, [selectedIds]);
  const inSelectedCount = selectedCount - usSelectedCount;

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/75 backdrop-blur-xs animate-in fade-in duration-150"
      role="dialog"
      aria-modal="true"
      aria-labelledby="stock-universe-title"
    >
      <div className="bg-surface border border-border w-full max-w-4xl max-h-[92vh] rounded-xl flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-border flex items-center justify-between gap-3 bg-surface shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20 text-primary">
              <Globe size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h2 id="stock-universe-title" className="text-base sm:text-lg font-bold text-heading">
                  Stock Universe Selection
                </h2>
                <span
                  className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-bold border ${
                    isExactlyTen
                      ? 'bg-success/15 text-success border-success/30'
                      : 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                  }`}
                >
                  {selectedCount} / 10 Selected
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                Select exactly 10 stocks across US (S&P 500) and Indian (NSE Nifty) markets for index rebalancing.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-background/80 transition-colors"
            aria-label="Close dialog"
          >
            <X size={18} />
          </button>
        </div>

        {/* Status / Notice Banner */}
        <div className="px-4 py-2.5 bg-background/60 border-b border-border/80 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-400 shrink-0">
          <div className="flex items-center gap-2">
            <Info size={14} className="text-primary shrink-0" />
            <span>
              Current composition: <strong className="text-heading font-mono">{usSelectedCount} US</strong> ({usSelectedCount > 0 ? 'USD' : '—'}) &bull; <strong className="text-heading font-mono">{inSelectedCount} Indian</strong> ({inSelectedCount > 0 ? 'INR' : '—'})
            </span>
          </div>
          <div className="flex items-center gap-2 text-[11px] font-mono">
            <span className="text-gray-500">Dual-market quotes supported</span>
            <span className="text-gray-600">&bull;</span>
            <span className="text-gray-500">FX accounting separated in Phase 3</span>
          </div>
        </div>

        {/* Filter and Search Bar */}
        <div className="p-4 border-b border-border/80 flex flex-col sm:flex-row gap-3 bg-surface/80 shrink-0">
          {/* Search */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 text-gray-400" size={15} />
            <input
              type="text"
              placeholder="Search by ticker, company, sector, or exchange..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-background border border-border rounded-lg pl-9 pr-3 py-1.5 text-xs text-heading placeholder-gray-500 focus:outline-hidden focus:border-primary transition-colors font-sans"
            />
          </div>

          {/* Market Filter Tabs */}
          <div className="flex items-center gap-1.5 bg-background p-1 rounded-lg border border-border">
            <button
              type="button"
              onClick={() => setMarketFilter('ALL')}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                marketFilter === 'ALL'
                  ? 'bg-primary text-white font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              All (20)
            </button>
            <button
              type="button"
              onClick={() => setMarketFilter('US')}
              className={`px-2.5 py-1 rounded text-xs font-medium flex items-center gap-1.5 transition-colors ${
                marketFilter === 'US'
                  ? 'bg-primary text-white font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <span>🇺🇸 US (10)</span>
            </button>
            <button
              type="button"
              onClick={() => setMarketFilter('IN')}
              className={`px-2.5 py-1 rounded text-xs font-medium flex items-center gap-1.5 transition-colors ${
                marketFilter === 'IN'
                  ? 'bg-primary text-white font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <span>🇮🇳 India (10)</span>
            </button>
            <button
              type="button"
              onClick={() => setMarketFilter('SELECTED')}
              className={`px-2.5 py-1 rounded text-xs font-medium flex items-center gap-1 transition-colors ${
                marketFilter === 'SELECTED'
                  ? 'bg-primary text-white font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <span>Selected ({selectedCount})</span>
            </button>
          </div>
        </div>

        {/* Error / Validation Alert */}
        {errorMessage && (
          <div className="mx-4 mt-3 p-3 bg-danger/10 border border-danger/30 rounded-lg flex items-center gap-2.5 text-xs text-danger shrink-0">
            <AlertCircle size={15} className="shrink-0" />
            <span className="font-medium">{errorMessage}</span>
          </div>
        )}

        {/* Success Alert */}
        {successMessage && (
          <div className="mx-4 mt-3 p-3 bg-success/10 border border-success/30 rounded-lg flex items-center gap-2.5 text-xs text-success shrink-0">
            <Check size={15} className="shrink-0" />
            <span className="font-medium">{successMessage}</span>
          </div>
        )}

        {/* Instruments Grid / List */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5">
          {isLoading ? (
            <div className="h-64 flex flex-col items-center justify-center text-gray-400 text-xs gap-2">
              <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              <span>Loading 20-stock catalog universe...</span>
            </div>
          ) : filteredInstruments.length === 0 ? (
            <div className="h-48 flex flex-col items-center justify-center text-gray-400 text-xs">
              <SlidersHorizontal size={28} className="text-gray-600 mb-2" />
              <span>No instruments matched your search or filter criteria.</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              {filteredInstruments.map(inst => {
                const isSelected = selectedIds.has(inst.id);
                const isActive = activeSelection.includes(inst.id);
                const isMarketUS = inst.market === 'US';
                const isDisabled = !isSelected && selectedCount >= 10;

                return (
                  <div
                    key={inst.id}
                    onClick={() => !isDisabled && handleToggle(inst.id)}
                    className={`relative p-3.5 rounded-xl border text-left transition-all select-none cursor-pointer flex items-start gap-3 ${
                      isSelected
                        ? 'bg-primary/10 border-primary/50 shadow-xs'
                        : isDisabled
                        ? 'bg-surface/40 border-border/40 opacity-45 cursor-not-allowed'
                        : 'bg-surface border-border hover:border-gray-600 hover:bg-surface/80'
                    }`}
                  >
                    {/* Checkbox */}
                    <div
                      className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 mt-0.5 transition-colors ${
                        isSelected
                          ? 'bg-primary border-primary text-white'
                          : isDisabled
                          ? 'border-gray-700 bg-gray-800'
                          : 'border-gray-500 bg-background'
                      }`}
                    >
                      {isSelected && <Check size={13} strokeWidth={3} />}
                    </div>

                    {/* Stock Details */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-sm text-heading font-mono">
                            {inst.display_ticker}
                          </span>
                          <span className="text-xs text-gray-400">
                            {isMarketUS ? '🇺🇸' : '🇮🇳'}
                          </span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded font-mono uppercase bg-background border border-border text-gray-300">
                            {inst.exchange}
                          </span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded font-mono font-medium text-gray-400">
                            {inst.currency}
                          </span>
                        </div>

                        {/* Badges: Active or Selected */}
                        <div className="flex items-center gap-1.5">
                          {isActive && (
                            <span
                              className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/30 font-medium"
                              title="Currently active in live portfolio"
                            >
                              Active
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="text-xs text-gray-200 font-medium truncate mt-0.5">
                        {inst.name}
                      </div>

                      <div className="flex items-center justify-between text-[11px] text-gray-400 mt-2 pt-1.5 border-t border-border/40">
                        <span className="truncate">{inst.sector}</span>
                        <span className="font-mono text-[10px] text-gray-500 shrink-0">
                          {inst.provider_symbol}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer with Actions */}
        <div className="p-4 sm:p-5 border-t border-border bg-surface flex flex-col sm:flex-row items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <button
              type="button"
              onClick={handleResetToDefault}
              disabled={isSaving}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white px-3 py-1.5 rounded-lg border border-border hover:bg-background/80 transition-colors disabled:opacity-50"
              title="Reset selection to the original 10 US S&P constituents"
            >
              <RotateCcw size={13} />
              <span>Reset to Default (10 US)</span>
            </button>
            <span className={`text-xs font-mono font-semibold ${countColor}`}>
              {selectedCount} / 10 Selected
            </span>
          </div>

          <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
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
              onClick={handleApplyClick}
              disabled={!isExactlyTen || isSaving}
              className="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold shadow-md transition-all"
            >
              {isSaving ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Applying Universe...</span>
                </>
              ) : (
                <>
                  <Check size={14} />
                  <span>Apply Selection</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Confirmation Modal Overlay */}
        {showConfirm && (
          <div className="fixed inset-0 z-60 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4">
            <div className="bg-surface border border-border rounded-xl max-w-lg w-full p-5 space-y-4 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
              <div className="flex items-center justify-between border-b border-border pb-3">
                <div className="flex items-center gap-2">
                  <AlertCircle size={18} className="text-amber-400" />
                  <h4 className="text-sm font-bold text-heading">Confirm Portfolio Universe Reconfiguration</h4>
                </div>
                <button
                  type="button"
                  onClick={() => setShowConfirm(false)}
                  className="text-gray-400 hover:text-white p-1 rounded"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="space-y-3 text-xs text-gray-300">
                <p>
                  You are changing the active 10-constituent portfolio universe. Please review how this affects your portfolio state:
                </p>

                {/* Diff summary */}
                <div className="bg-background/80 border border-border p-3 rounded-lg space-y-2">
                  {addedInstruments.length > 0 && (
                    <div className="flex items-start gap-2">
                      <span className="font-semibold text-success shrink-0">+ Added ({addedInstruments.length}):</span>
                      <div className="flex flex-wrap gap-1">
                        {addedInstruments.map(i => (
                          <span key={i.id} className="px-1.5 py-0.5 rounded bg-success/10 text-success border border-success/20 font-mono text-[11px]">
                            {i.display_ticker} ({i.market === 'IN' ? '₹' : '$'})
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {removedInstruments.length > 0 && (
                    <div className="flex items-start gap-2">
                      <span className="font-semibold text-danger shrink-0">- Replaced ({removedInstruments.length}):</span>
                      <div className="flex flex-wrap gap-1">
                        {removedInstruments.map(i => (
                          <span key={i.id} className="px-1.5 py-0.5 rounded bg-danger/10 text-danger border border-danger/20 font-mono text-[11px]">
                            {i.display_ticker}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="text-[11px] text-gray-400 pt-1 border-t border-border/60">
                    <strong>{retainedInstruments.length}</strong> constituents remain in the portfolio and will retain their existing share quantities.
                  </div>
                </div>

                {/* Explanation points */}
                <ul className="list-disc list-inside space-y-1 text-gray-400 text-[11px] leading-relaxed">
                  <li><strong className="text-gray-300">Preserved Holdings:</strong> Custom shares for retained constituents will NOT be lost.</li>
                  <li><strong className="text-gray-300">New Constituents:</strong> Initialized to default 10.0 shares.</li>
                  <li><strong className="text-gray-300">Target Allocations:</strong> Baseline weights reset to 10.00% equal weights until next news scan or customizer adjustment.</li>
                  <li><strong className="text-gray-300">Cash Reserves:</strong> Cash balance automatically updates to reflect remaining budget.</li>
                </ul>
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-border">
                <button
                  type="button"
                  onClick={() => setShowConfirm(false)}
                  disabled={isSaving}
                  className="px-3.5 py-1.5 rounded-lg border border-border text-gray-300 hover:text-white hover:bg-background text-xs font-semibold"
                >
                  Go Back / Modify
                </button>
                <button
                  type="button"
                  onClick={handleConfirmAndSave}
                  disabled={isSaving}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-primary hover:bg-blue-600 text-white text-xs font-semibold shadow-md disabled:opacity-50"
                >
                  {isSaving ? (
                    <>
                      <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      <span>Saving...</span>
                    </>
                  ) : (
                    <span>Confirm & Apply Universe</span>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
