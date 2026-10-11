import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ArrowLeft } from 'lucide-react';
import { ComposedChart, Line, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts';

export default function StockDetail() {
  const { ticker } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  
  const [details, setDetails] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [period, setPeriod] = useState('1Y');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    
    Promise.all([
      api.getStockDetails(ticker),
      api.getStockHistory(ticker, period)
    ]).then(([det, hist]) => {
      setDetails(det);
      setHistory(hist);
    }).catch(console.error).finally(() => setLoading(false));
  }, [ticker, period]);

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading {ticker} data...</div>;
  }

  if (!details) {
    return <div className="p-8 text-center text-danger">Failed to load {ticker}.</div>;
  }

  return (
    <div className="p-6">
      <button 
        onClick={() => navigate('/')}
        className="flex items-center gap-2 text-gray-400 hover:text-white mb-6 transition-colors"
      >
        <ArrowLeft size={18} /> Back to Portfolio
      </button>

      <h2 className="text-2xl font-bold mb-6">📈 {ticker} Detail Explorer</h2>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-surface border border-border p-4 rounded-lg">
          <div className="text-sm text-gray-400">Latest Portfolio Price</div>
          <div className="text-xl font-bold">{details.price != null ? `$${details.price.toFixed(2)}` : <span className="text-gray-500 italic text-base">Unavailable</span>}</div>
        </div>
        <div className="bg-surface border border-border p-4 rounded-lg">
          <div className="text-sm text-gray-400">Current Target Weight</div>
          <div className="text-xl font-bold">{(details.current_weight * 100).toFixed(2)}%</div>
        </div>
        <div className="bg-surface border border-border p-4 rounded-lg">
          <div className="text-sm text-gray-400">Baseline Weight</div>
          <div className="text-xl font-bold">
            {(details.baseline_weight * 100).toFixed(2)}%
            <span className="ml-2 text-sm text-gray-500">
              {((details.current_weight - details.baseline_weight) * 100).toFixed(2)}%
            </span>
          </div>
        </div>
      </div>

      <div className="mb-6">
        <label className="mr-3 font-medium text-gray-300">Select History Period:</label>
        <select 
          value={period} 
          onChange={e => setPeriod(e.target.value)}
          className="bg-surface border border-border rounded p-2 text-sm"
        >
          <option value="1M">1 Month</option>
          <option value="3M">3 Months</option>
          <option value="6M">6 Months</option>
          <option value="1Y">1 Year</option>
        </select>
      </div>

      {history.length > 0 ? (
        <div className="space-y-6">
          <div className="bg-surface border border-border p-4 rounded-lg h-[400px]">
            <h4 className="font-semibold mb-4 text-center">{ticker} Price & SMAs</h4>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={history} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid stroke="#30363D" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" stroke="#8B949E" minTickGap={30} />
                <YAxis yAxisId="left" stroke="#8B949E" domain={['auto', 'auto']} />
                <Tooltip contentStyle={{ backgroundColor: '#161B22', borderColor: '#30363D', color: '#C9D1D9' }} />
                <Legend />
                <Line yAxisId="left" type="monotone" dataKey="close" name="Close Price" stroke="#C9D1D9" dot={false} strokeWidth={2} />
                <Line yAxisId="left" type="monotone" dataKey="sma20" name="SMA 20" stroke="#f59e0b" dot={false} />
                <Line yAxisId="left" type="monotone" dataKey="sma50" name="SMA 50" stroke="#3b82f6" dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          
          <div className="bg-surface border border-border p-4 rounded-lg h-[250px]">
            <h4 className="font-semibold mb-4 text-center">Volume</h4>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={history} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid stroke="#30363D" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" stroke="#8B949E" minTickGap={30} />
                <YAxis stroke="#8B949E" tickFormatter={val => (val/1000000).toFixed(0) + 'M'} />
                <Tooltip contentStyle={{ backgroundColor: '#161B22', borderColor: '#30363D', color: '#C9D1D9' }} />
                <Bar dataKey="volume" name="Volume" fill="rgba(100, 150, 250, 0.5)" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <div className="p-8 text-center text-gray-400 border border-dashed border-border rounded">No historical data available.</div>
      )}
    </div>
  );
}
