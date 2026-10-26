import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { PanelLeftClose, Settings, Sliders, Globe } from 'lucide-react';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onConfigChange: () => void;
  onOpenCustomizer?: () => void;
  onOpenUniverseSelector?: () => void;
}

export default function Sidebar({ isOpen, onClose, onConfigChange, onOpenCustomizer, onOpenUniverseSelector }: SidebarProps) {
  const [dataMode, setDataMode] = useState("Live Market (Google RSS)");
  const [initialCapital, setInitialCapital] = useState(1000000);
  const [alphaTilt, setAlphaTilt] = useState(0.05);
  const [maxItems, setMaxItems] = useState(2);
  const [reportingCurrency, setReportingCurrency] = useState("INR");
  const [isSaved, setIsSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    Promise.all([
      api.getConfig(),
      api.getReportingCurrency().catch(() => ({ reporting_currency: 'INR' }))
    ]).then(([config, repCurrRes]) => {
      setDataMode(config.data_mode);
      setInitialCapital(config.initial_capital);
      setAlphaTilt(config.alpha_tilt);
      setMaxItems(config.max_items ?? 2);
      if (repCurrRes?.reporting_currency) {
        setReportingCurrency(repCurrRes.reporting_currency);
      } else if (config.reporting_currency) {
        setReportingCurrency(config.reporting_currency);
      }
    }).catch(console.error);
  }, []);

  const handleUpdate = async () => {
    if (initialCapital <= 0) return;
    setIsSaving(true);
    try {
      await api.updateConfig({
        data_mode: dataMode,
        initial_capital: initialCapital,
        alpha_tilt: alphaTilt,
        max_items: maxItems,
        reporting_currency: reportingCurrency
      });
      await api.setReportingCurrency(reportingCurrency);
      setIsSaved(true);
      setTimeout(() => setIsSaved(false), 2500);
      onConfigChange();
    } catch (e) {
      console.error(e);
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) {
    return null;
  }

  return (
    <>
      {/* Mobile backdrop overlay */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-xs z-30 md:hidden"
        onClick={onClose}
        aria-hidden="true"
      />

      <aside className="fixed inset-y-0 left-0 z-40 w-72 bg-surface border-r border-border p-4 flex flex-col gap-6 overflow-y-auto shadow-2xl md:static md:w-64 lg:w-72 md:shadow-none shrink-0 h-full">
        {/* Sidebar Header with Collapse Button */}
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Settings size={18} className="text-primary" />
            <h2 className="text-lg font-bold text-heading">System Control</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-background/80 transition-colors"
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
          >
            <PanelLeftClose size={18} />
          </button>
        </div>

        {/* Reporting Currency Section */}
        <div>
          <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Reporting Currency
          </label>
          <select
            value={reportingCurrency}
            onChange={e => setReportingCurrency(e.target.value)}
            className="w-full bg-background border border-border rounded-lg p-2.5 text-xs text-heading focus:outline-hidden focus:border-primary transition-colors font-medium"
          >
            <option value="INR">₹ INR — Indian Rupee (Default)</option>
            <option value="USD">$ USD — US Dollar</option>
          </select>
          <p className="text-[11px] text-gray-500 mt-1">
            Global consolidated portfolio reporting currency. Native instruments retain their traded currency.
          </p>
        </div>

        {/* Data Feed Section */}
        <div>
          <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Data Feed
          </label>
          <select
            value={dataMode}
            onChange={e => setDataMode(e.target.value)}
            className="w-full bg-background border border-border rounded-lg p-2.5 text-xs text-heading focus:outline-hidden focus:border-primary transition-colors"
          >
            <option value="Live Market (Google RSS)">Live Market (Google RSS)</option>
            <option value="Offline Crisis Replay">Offline Crisis Replay</option>
          </select>
        </div>

        {/* Portfolio Parameters */}
        <div className="border-t border-border pt-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Portfolio Parameters
          </h3>

          <div className="mb-4">
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-gray-300 font-medium">
                Initial Portfolio Capital ($)
              </label>
              <span className="text-[10px] text-gray-400 font-mono">
                Max $1,000,000
              </span>
            </div>
            <p className="text-[11px] text-gray-500 mb-2 leading-relaxed">
              Configured starting budget for index rebalancing simulation.
            </p>
            <input
              type="number"
              min="10000"
              max="1000000"
              step="10000"
              value={initialCapital}
              onChange={e => setInitialCapital(Number(e.target.value))}
              className={`w-full bg-background border rounded-lg p-2 text-xs font-mono text-heading focus:outline-hidden ${
                initialCapital > 1000000 || initialCapital <= 0
                  ? 'border-danger focus:border-danger'
                  : 'border-border focus:border-primary'
              }`}
            />
            {initialCapital > 1000000 && (
              <p className="text-[10px] text-danger mt-1">
                Maximum allowed starting capital for this simulation is $1,000,000.00.
              </p>
            )}
            {initialCapital <= 0 && (
              <p className="text-[10px] text-danger mt-1">
                Starting capital must be greater than $0.
              </p>
            )}
          </div>

          <div className="mb-4">
            <div className="flex items-center justify-between mb-1">
              <label
                className="text-xs text-gray-300 font-medium"
                title="Scales average entity sentiment into tactical rebalancing weight tilts (bounded to baseline ±5 pp)"
              >
                Tilt Strength (alpha)
              </label>
              <span className="text-xs font-mono font-bold text-primary">
                {alphaTilt.toFixed(2)}
              </span>
            </div>
            <p className="text-[11px] text-gray-500 mb-2 leading-relaxed">
              Scales entity sentiment into tactical weight tilts (clamped to ±5 pp).
            </p>
            <input
              type="range"
              min="0.01" max="0.10" step="0.01"
              value={alphaTilt}
              onChange={e => setAlphaTilt(Number(e.target.value))}
              className="w-full accent-primary h-1.5 bg-background rounded-lg cursor-pointer"
              title="Scales average entity sentiment into tactical weight tilts"
            />
          </div>

          {/* Quick link to constituent customization */}
          <div className="pt-1 flex flex-col gap-2">
            {onOpenUniverseSelector && (
              <button
                type="button"
                onClick={onOpenUniverseSelector}
                className="w-full flex items-center justify-center gap-2 bg-background hover:bg-border/60 border border-border text-heading px-3 py-2 rounded-lg text-xs font-semibold transition-all shadow-xs"
              >
                <Globe size={14} className="text-primary" />
                <span>Select Stock Universe (10 / 20)</span>
              </button>
            )}
            {onOpenCustomizer && (
              <button
                type="button"
                onClick={onOpenCustomizer}
                className="w-full flex items-center justify-center gap-2 bg-primary/10 hover:bg-primary/20 border border-primary/30 hover:border-primary text-primary px-3 py-2 rounded-lg text-xs font-semibold transition-all shadow-xs"
              >
                <Sliders size={14} />
                <span>Customize Stock Weights</span>
              </button>
            )}
          </div>
        </div>

        {/* Live Feed Options */}
        <div className="border-t border-border pt-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              Live Feed Options
            </h3>
            <span className="text-xs font-mono font-bold text-heading">
              {maxItems}
            </span>
          </div>
          <div className="mb-2">
            <label className="block text-xs text-gray-300 font-medium mb-1">
              Max Articles Per Company
            </label>
            <input
              type="range"
              min="1" max="10" step="1"
              value={maxItems}
              onChange={e => setMaxItems(Number(e.target.value))}
              className="w-full accent-primary h-1.5 bg-background rounded-lg cursor-pointer"
            />
          </div>
        </div>

        {/* Action Button & Feedback */}
        <div className="mt-auto pt-4 border-t border-border flex flex-col gap-2">
          <button
            type="button"
            onClick={handleUpdate}
            disabled={isSaving || initialCapital > 1000000 || initialCapital <= 0}
            className="w-full bg-primary hover:bg-blue-600 text-white p-2.5 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50 shadow-sm"
          >
            {isSaving ? "Applying..." : "Apply Configuration"}
          </button>
          {isSaved && (
            <div className="text-xs text-center text-success font-medium bg-success/10 py-1.5 rounded-lg border border-success/30">
              ✓ Configuration Saved Successfully
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
