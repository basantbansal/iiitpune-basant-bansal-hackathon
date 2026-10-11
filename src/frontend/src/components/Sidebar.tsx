import React, { useState, useEffect } from 'react';
import { api } from '../api';

export default function Sidebar({ onConfigChange }: { onConfigChange: () => void }) {
  const [dataMode, setDataMode] = useState("Live Market (Google RSS)");
  const [initialCapital, setInitialCapital] = useState(1000000);
  const [alphaTilt, setAlphaTilt] = useState(0.05);
  const [maxItems, setMaxItems] = useState(2);
  const [isSaved, setIsSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  
  useEffect(() => {
    api.getConfig().then(config => {
      setDataMode(config.data_mode);
      setInitialCapital(config.initial_capital);
      setAlphaTilt(config.alpha_tilt);
      setMaxItems(config.max_items ?? 2);
    }).catch(console.error);
  }, []);

  const handleUpdate = async () => {
    setIsSaving(true);
    try {
      await api.updateConfig({
        data_mode: dataMode,
        initial_capital: initialCapital,
        alpha_tilt: alphaTilt,
        max_items: maxItems
      });
      setIsSaved(true);
      setTimeout(() => setIsSaved(false), 2500);
      onConfigChange();
    } catch (e) {
      console.error(e);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="w-64 bg-surface border-r border-border p-4 flex flex-col gap-6 overflow-y-auto">
      <div>
        <h2 className="text-xl font-bold mb-4">⚙️ System Control</h2>
        <div className="mb-4">
          <label className="block text-sm text-gray-400 mb-2">Data Feed</label>
          <select 
            value={dataMode}
            onChange={e => setDataMode(e.target.value)}
            className="w-full bg-background border border-border rounded p-2 text-sm"
          >
            <option value="Live Market (Google RSS)">Live Market (Google RSS)</option>
            <option value="Offline Crisis Replay">Offline Crisis Replay</option>
          </select>
        </div>
      </div>
      
      <div className="border-t border-border pt-4">
        <h3 className="font-semibold mb-3">Portfolio Parameters</h3>
        <div className="mb-4">
          <label className="block text-sm text-gray-400 mb-1">Initial Portfolio Capital ($)</label>
          <p className="text-xs text-gray-500 mb-2">Configured baseline equity capital for index rebalancing.</p>
          <input 
            type="number" 
            value={initialCapital}
            onChange={e => setInitialCapital(Number(e.target.value))}
            className="w-full bg-background border border-border rounded p-2 text-sm"
          />
        </div>
        <div className="mb-4">
          <label className="block text-sm text-gray-400 mb-1" title="Scales average entity sentiment into tactical rebalancing weight tilts (bounded to baseline ±5 pp)">
            Tilt strength (alpha) : {alphaTilt}
          </label>
          <p className="text-xs text-gray-500 mb-2">
            Scales entity sentiment into tactical weight tilts (clamped to ±5 pp).
          </p>
          <input 
            type="range" 
            min="0.01" max="0.10" step="0.01"
            value={alphaTilt}
            onChange={e => setAlphaTilt(Number(e.target.value))}
            className="w-full"
            title="Scales average entity sentiment into tactical weight tilts"
          />
        </div>
      </div>

      <div className="border-t border-border pt-4">
        <h3 className="font-semibold mb-3">Live Feed Options</h3>
        <div className="mb-4">
          <label className="block text-sm text-gray-400 mb-1">Max Articles Per Company: {maxItems}</label>
          <input 
            type="range" 
            min="1" max="10" step="1"
            value={maxItems}
            onChange={e => setMaxItems(Number(e.target.value))}
            className="w-full"
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <button 
          onClick={handleUpdate}
          disabled={isSaving}
          className="w-full bg-primary hover:bg-blue-600 text-white p-2.5 rounded text-sm font-semibold transition-colors disabled:opacity-50"
        >
          {isSaving ? "Saving..." : "Apply Configuration"}
        </button>
        {isSaved && (
          <div className="text-xs text-center text-success font-medium bg-success/10 py-1 rounded border border-success/30 animate-pulse">
            ✓ Configuration Saved Successfully
          </div>
        )}
      </div>
    </div>
  );
}
