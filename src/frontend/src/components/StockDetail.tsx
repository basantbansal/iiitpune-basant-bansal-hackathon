import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { 
  ArrowLeft, 
  ExternalLink, 
  Newspaper, 
  TrendingUp, 
  TrendingDown, 
  Minus, 
  Sparkles, 
  Calendar,
  Building,
  CheckCircle2
} from 'lucide-react';
import { ComposedChart, Line, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts';

function formatArticleAge(days: number | undefined, pubStr?: string): string {
  if (days != null && !isNaN(days)) {
    if (days < 0.04) return '< 1h ago';
    if (days < 1.0) return `${Math.max(1, Math.round(days * 24))}h ago`;
    return `${days.toFixed(1)}d ago`;
  }
  if (!pubStr) return '';
  try {
    const diffMs = Date.now() - new Date(pubStr).getTime();
    const diffHours = diffMs / (1000 * 60 * 60);
    if (diffHours < 1) return '< 1h ago';
    if (diffHours < 24) return `${Math.round(diffHours)}h ago`;
    return `${(diffHours / 24).toFixed(1)}d ago`;
  } catch {
    return '';
  }
}

export default function StockDetail() {
  const { ticker: routeTicker } = useParams<{ ticker: string }>();
  const ticker = (routeTicker || '').toUpperCase();
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
    return <div className="p-8 text-center text-gray-400">Loading {ticker} data & news signals...</div>;
  }

  if (!details) {
    return <div className="p-8 text-center text-danger">Failed to load {ticker}.</div>;
  }

  const delta = details.delta_pp ?? Number(((details.current_weight - details.baseline_weight) * 100).toFixed(2));
  const isOverweight = delta > 0.05;
  const isUnderweight = delta < -0.05;
  
  const signals = details.signals || [];
  const bullishSignals = signals.filter((s: any) => s.sentiment_score > 0.15);
  const bearishSignals = signals.filter((s: any) => s.sentiment_score < -0.15);
  const neutralSignals = signals.filter((s: any) => Math.abs(s.sentiment_score) <= 0.15);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Navigation */}
      <button 
        onClick={() => navigate('/')}
        className="flex items-center gap-2 text-gray-400 hover:text-white transition-colors group text-sm font-medium"
      >
        <ArrowLeft size={16} className="group-hover:-translate-x-1 transition-transform" /> Back to Portfolio Rebalancer
      </button>

      {/* Header with Ticker, Company Name & Order Badge */}
      <div className="bg-surface border border-border p-6 rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-extrabold text-heading tracking-tight flex items-center gap-2">
              <span>{ticker}</span>
              <span className="text-xl text-gray-400 font-normal">| {details.company_name || ticker}</span>
            </h1>
            {details.action === 'BUY' && (
              <span className="inline-flex items-center gap-1 px-3 py-1 rounded text-xs font-bold bg-success/20 text-success border border-success/30 font-mono">
                <TrendingUp size={14} /> + BUY {details.order_qty ? details.order_qty.toFixed(2) : ''} SHS
              </span>
            )}
            {details.action === 'SELL' && (
              <span className="inline-flex items-center gap-1 px-3 py-1 rounded text-xs font-bold bg-danger/20 text-danger border border-danger/30 font-mono">
                <TrendingDown size={14} /> - SELL {details.order_qty ? details.order_qty.toFixed(2) : ''} SHS
              </span>
            )}
            {details.action === 'HOLD' && (
              <span className="inline-flex items-center gap-1 px-3 py-1 rounded text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700 font-mono">
                <Minus size={14} /> HOLD
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400 mt-1 flex items-center gap-1.5">
            <Building size={14} /> Monitored Mega-Cap Constituent &bull; Automated NLP Event Sensitivity Active
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-xs text-gray-400 uppercase tracking-wider">Latest Portfolio Price</div>
            <div className="text-2xl font-mono font-bold text-heading">
              {details.price != null ? `$${details.price.toFixed(2)}` : <span className="text-gray-500 italic text-base">Unavailable</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Allocation Rationale Banner */}
      <div className="bg-surface border border-border p-5 rounded-lg space-y-3">
        <div className="flex items-center justify-between border-b border-border/60 pb-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-heading">
            <Sparkles size={16} className="text-primary" />
            <span>Why did this stock's allocation change? (Explainability Engine)</span>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded font-mono font-semibold ${
            isOverweight ? 'bg-success/20 text-success border border-success/30' :
            isUnderweight ? 'bg-danger/20 text-danger border border-danger/30' :
            'bg-gray-800 text-gray-400 border border-gray-700'
          }`}>
            {isOverweight ? 'Overweight Tilt' : isUnderweight ? 'Underweight Tilt' : 'Equal-Weight Baseline'}
          </span>
        </div>
        <p className="text-sm text-gray-200 leading-relaxed">
          {details.rationale_text}
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 text-xs">
          <div className="bg-background/50 border border-border/50 p-2.5 rounded">
            <div className="text-gray-400">Baseline Weight</div>
            <div className="font-mono font-bold text-gray-200 mt-0.5">{(details.baseline_weight * 100).toFixed(2)}%</div>
          </div>
          <div className="bg-background/50 border border-border/50 p-2.5 rounded">
            <div className="text-gray-400">Target Allocation</div>
            <div className="font-mono font-bold text-heading mt-0.5">{(details.current_weight * 100).toFixed(2)}%</div>
          </div>
          <div className="bg-background/50 border border-border/50 p-2.5 rounded">
            <div className="text-gray-400">Allocation Delta</div>
            <div className={`font-mono font-bold mt-0.5 ${
              delta > 0.001 ? 'text-success' : delta < -0.001 ? 'text-danger' : 'text-gray-400'
            }`}>
              {delta > 0 ? `+${delta.toFixed(2)} pp` : `${delta.toFixed(2)} pp`}
            </div>
          </div>
          <div className="bg-background/50 border border-border/50 p-2.5 rounded">
            <div className="text-gray-400">Net Event Sentiment</div>
            <div className={`font-mono font-bold mt-0.5 ${
              details.net_sentiment > 0.05 ? 'text-success' : details.net_sentiment < -0.05 ? 'text-danger' : 'text-gray-400'
            }`}>
              {details.net_sentiment > 0 ? `+${details.net_sentiment.toFixed(2)}` : details.net_sentiment?.toFixed(2) ?? '0.00'}
            </div>
          </div>
        </div>
      </div>

      {/* 4 Overview Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-surface border border-border p-4 rounded-lg">
          <div className="text-xs text-gray-400 uppercase tracking-wider">Holding Quantity</div>
          <div className="text-xl font-mono font-bold text-heading mt-1">
            {details.post_shares != null ? `${details.post_shares.toFixed(2)} shs` : '—'}
          </div>
          <div className="text-[11px] text-gray-400 mt-1">
            Pre-trade: {details.pre_shares != null ? `${details.pre_shares.toFixed(2)} shs` : '—'}
          </div>
        </div>

        <div className="bg-surface border border-border p-4 rounded-lg">
          <div className="text-xs text-gray-400 uppercase tracking-wider">Active Trade Value</div>
          <div className="text-xl font-mono font-bold text-heading mt-1">
            ${details.trade_value != null ? details.trade_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'}
          </div>
          <div className="text-[11px] text-gray-400 mt-1">
            Action: <span className="font-semibold text-gray-300">{details.action}</span>
          </div>
        </div>

        <div className="bg-surface border border-border p-4 rounded-lg">
          <div className="text-xs text-gray-400 uppercase tracking-wider">Signals Analyzed</div>
          <div className="text-xl font-mono font-bold text-heading mt-1">
            {details.signal_count ?? signals.length}
          </div>
          <div className="text-[11px] text-gray-400 mt-1 flex items-center gap-2">
            <span className="text-success font-medium">{bullishSignals.length} Bullish</span> &bull; 
            <span className="text-danger font-medium">{bearishSignals.length} Bearish</span> &bull; 
            <span className="text-gray-400">{neutralSignals.length} Neutral</span>
          </div>
        </div>

        <div className="bg-surface border border-border p-4 rounded-lg">
          <div className="text-xs text-gray-400 uppercase tracking-wider">Average Impact Score</div>
          <div className="text-xl font-mono font-bold text-heading mt-1">
            {details.avg_impact ? `${details.avg_impact} / 10` : '—'}
          </div>
          <div className="text-[11px] text-gray-400 mt-1">
            {details.avg_impact >= 7 ? '⚠️ High Impact Event' : 'Standard Routine Flow'}
          </div>
        </div>
      </div>

      {/* SECTION: Monitored News & NLP Risk Signals (UNTRUNCATED FULL NEWS) */}
      <div className="bg-surface border border-border p-6 rounded-lg space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border pb-4">
          <div>
            <h3 className="text-lg font-bold text-heading flex items-center gap-2">
              <Newspaper size={20} className="text-primary" />
              <span>Constituent News & NLP Event Intelligence ({signals.length})</span>
            </h3>
            <p className="text-xs text-gray-400 mt-0.5">
              Every headline parsed and scored by Groq LLaMA 3.3 70B & Financial Lexicon fallback driving this stock's allocation.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="px-2 py-0.5 rounded bg-success/10 text-success border border-success/30 font-semibold">
              +{bullishSignals.length} Bullish
            </span>
            <span className="px-2 py-0.5 rounded bg-danger/10 text-danger border border-danger/30 font-semibold">
              -{bearishSignals.length} Bearish
            </span>
            <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700">
              {neutralSignals.length} Neutral
            </span>
          </div>
        </div>

        {signals.length > 0 ? (
          <div className="space-y-4">
            {signals.map((sig: any, idx: number) => {
              const sent = sig.sentiment_score ?? 0.0;
              const badgeType = sig.direction_badge || (
                sent > 0.15 ? 'Bullish' : sent < -0.15 ? 'Bearish' : 'Neutral'
              );
              const isUnclassified = sig.is_unclassified || sig.event_classification === 'Unclassified' || sig.event_classification?.includes('Unclassified');
              const ageLabel = formatArticleAge(sig.article_age_days, sig.published_at);

              return (
                <div 
                  key={idx} 
                  className="p-4 bg-background/60 hover:bg-background/80 transition-colors rounded-lg border border-border flex flex-col gap-3"
                >
                  <div className="flex justify-between items-start gap-4 flex-col lg:flex-row">
                    <div className="flex-1 space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        {/* Direction Badge */}
                        <span className={`text-xs px-2 py-0.5 rounded font-bold font-mono border ${
                          badgeType === 'Bullish'
                            ? 'bg-success/20 text-success border-success/30'
                            : badgeType === 'Bearish'
                            ? 'bg-danger/20 text-danger border-danger/30'
                            : badgeType === 'Needs Review'
                            ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
                            : 'bg-gray-800 text-gray-400 border-gray-700'
                        }`}>
                          {badgeType === 'Bullish' && '📈 '}
                          {badgeType === 'Bearish' && '📉 '}
                          {badgeType === 'Needs Review' && '⚠️ '}
                          {badgeType}
                        </span>

                        {/* Separate Unclassified Badge */}
                        {isUnclassified && (
                          <span className="text-[11px] px-2 py-0.5 rounded font-mono font-medium bg-amber-500/20 text-amber-300 border border-amber-500/40">
                            ⚠️ Event: Unclassified
                          </span>
                        )}

                        {/* Synthetic Data Label */}
                        {sig.is_synthetic && (
                          <span className="text-[11px] px-2 py-0.5 rounded font-mono font-bold bg-purple-500/20 text-purple-300 border border-purple-500/40" title="Synthetic fixture data (excluded from live rebalancing)">
                            🧪 SYNTHETIC DEMO DATA
                          </span>
                        )}

                        {/* Shared Headline Label */}
                        {sig.is_shared_headline && (
                          <span className="text-[11px] px-2 py-0.5 rounded font-mono font-medium bg-blue-500/20 text-blue-300 border border-blue-500/30" title="Multi-ticker headline: discounted confidence & 0.5x rebalancer weight">
                            👥 Shared Headline (0.5x Wt)
                          </span>
                        )}

                        <h4 className="font-bold text-heading text-base inline leading-snug">
                          {sig.headline}
                        </h4>
                        {sig.url && (
                          <a 
                            href={sig.url} 
                            target="_blank" 
                            rel="noreferrer" 
                            className="text-primary hover:text-primary/80 shrink-0 inline-flex items-center ml-1"
                            title="Open original news article in new tab"
                          >
                            <ExternalLink size={16} />
                          </a>
                        )}
                      </div>

                      <div className="text-xs text-gray-400 flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-gray-200">{sig.ticker || ticker}</span>
                        <span>•</span>
                        <span className="px-2 py-0.5 rounded bg-surface border border-border font-medium text-gray-300">
                          {sig.event_classification || 'Unclassified / Needs Review'}
                        </span>
                        <span>•</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-medium ${
                          sig.inference_source === 'groq'
                            ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                            : 'bg-gray-800 text-gray-300 border border-gray-700'
                        }`}>
                          {sig.inference_source === 'groq' ? '⚡ Groq LLM' : '⚙️ Fallback Rules'}
                        </span>
                        <span>•</span>
                        <span>{sig.source || 'Market Feed'}</span>
                        <span>•</span>
                        <span title={sig.published_at ? new Date(sig.published_at).toLocaleString() : ''} className="flex items-center gap-1 font-mono">
                          <Calendar size={12} />
                          {ageLabel ? `⏱️ ${ageLabel}` : (sig.published_at ? new Date(sig.published_at).toLocaleDateString() : '')}
                        </span>
                      </div>
                    </div>

                    {/* 5 Risk Engine Metric Boxes */}
                    <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
                      {/* Ticker Net Change */}
                      <div className="text-center px-2.5 py-1.5 rounded bg-surface border border-border min-w-[75px]" title="Ticker allocation change from baseline resulting from scan">
                        <div className="text-[10px] text-gray-400 font-medium">Ticker Net Change</div>
                        <div className={`text-xs font-bold font-mono ${
                          sig.net_delta && sig.net_delta.startsWith('+') && sig.net_delta !== '+0.00 pp'
                            ? 'text-success' 
                            : sig.net_delta && sig.net_delta.startsWith('-') && sig.net_delta !== '-0.00 pp'
                            ? 'text-danger' 
                            : 'text-gray-400'
                        }`}>
                          {sig.net_delta || (delta > 0 ? `+${delta.toFixed(2)} pp` : `${delta.toFixed(2)} pp`)}
                        </div>
                      </div>

                      {/* Sentiment Score */}
                      <div className="text-center px-2.5 py-1.5 rounded bg-surface border border-border min-w-[65px]" title="Finance-aware entity sentiment score [-1.0, 1.0]">
                        <div className="text-[10px] text-gray-400 font-medium">Sentiment</div>
                        <div className={`text-xs font-bold font-mono ${
                          sent > 0.15 ? 'text-success' : sent < -0.15 ? 'text-danger' : 'text-gray-400'
                        }`}>
                          {sent > 0 ? `+${sent.toFixed(2)}` : sent.toFixed(2)}
                        </div>
                      </div>

                      {/* Base Severity */}
                      <div className="text-center px-2.5 py-1.5 rounded bg-surface border border-border min-w-[75px]" title="Base Severity: category prior risk benchmark (not article-specific)">
                        <div className="text-[10px] text-gray-400 font-medium">Base Severity</div>
                        <div className={`text-xs font-bold ${
                          sig.severity == null 
                            ? 'text-gray-400 italic font-normal text-[10px]' 
                            : sig.severity >= 7.5 ? 'text-danger' : sig.severity >= 5.0 ? 'text-amber-400' : 'text-blue-400'
                        }`}>
                          {sig.severity != null ? Number(sig.severity).toFixed(1) : 'Unclassified'}
                        </div>
                      </div>

                      {/* Impact Score */}
                      <div className="text-center px-2.5 py-1.5 rounded bg-surface border border-border min-w-[55px]" title="Multi-factor portfolio impact score (1 to 10)">
                        <div className="text-[10px] text-gray-400 font-medium">Impact</div>
                        <div className="text-xs font-bold text-primary font-mono">
                          {sig.impact_score != null ? `${sig.impact_score}/10` : '—'}
                        </div>
                      </div>

                      {/* Confidence */}
                      <div className="text-center px-2.5 py-1.5 rounded bg-surface border border-border min-w-[65px]" title={sig.inference_source === 'groq' ? "Model parse confidence" : "Heuristic keyword-match confidence estimate"}>
                        <div className="text-[10px] text-gray-400 font-medium">Confidence</div>
                        <div className="text-xs font-bold text-success font-mono">
                          {sig.confidence != null ? `${(sig.confidence * 100).toFixed(0)}%` : '—'}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* AI Evidence Span / Snippet */}
                  {(sig.evidence || sig.evidence_span) && sig.evidence !== "No evidence provided." && (
                    <div className="bg-surface border-l-2 border-primary/70 px-3 py-2 rounded-r text-xs text-gray-300 italic flex items-start gap-1.5">
                      <span className="font-semibold not-italic text-primary shrink-0">Evidence Span:</span>
                      <span>"{sig.evidence || sig.evidence_span}"</span>
                    </div>
                  )}

                  {/* Model version & ticker footer */}
                  <div className="text-[10px] text-gray-500 font-mono pt-1.5 border-t border-border/40 flex justify-between items-center">
                    <span>Evaluated by {sig.model_version || (sig.inference_source === 'groq' ? 'Groq LLaMA 3.3 70B' : 'Financial Lexicon & Rule Engine')}</span>
                    <span>Constituent: {ticker}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="bg-background/40 border border-dashed border-border rounded-lg p-6 text-center space-y-2">
            <CheckCircle2 size={28} className="text-gray-500 mx-auto" />
            <h4 className="text-sm font-semibold text-gray-300">No Active News Signals for {ticker}</h4>
            <p className="text-xs text-gray-400 max-w-lg mx-auto">
              No sentiment or credit risk events were detected for {ticker} in recent scans. As per institutional index rebalancing rules, absence of news is not negative sentiment—this constituent retains its baseline equal weight of 10.00%.
            </p>
          </div>
        )}
      </div>

      {/* Technicals Period & Historical Charts */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold text-heading">📊 Technicals & Price Performance</h3>
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-gray-400">History Period:</label>
            <select 
              value={period} 
              onChange={e => setPeriod(e.target.value)}
              className="bg-surface border border-border rounded p-1.5 text-xs text-gray-200"
            >
              <option value="1M">1 Month</option>
              <option value="3M">3 Months</option>
              <option value="6M">6 Months</option>
              <option value="1Y">1 Year</option>
            </select>
          </div>
        </div>

        {history.length > 0 ? (
          <div className="space-y-6">
            <div className="bg-surface border border-border p-4 rounded-lg h-[400px]">
              <h4 className="font-semibold mb-2 text-center text-sm text-gray-300">{ticker} Price & Moving Averages</h4>
              <ResponsiveContainer width="100%" height="90%">
                <ComposedChart data={history} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid stroke="#30363D" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" stroke="#8B949E" minTickGap={30} tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="left" stroke="#8B949E" domain={['auto', 'auto']} tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#161B22', borderColor: '#30363D', color: '#C9D1D9' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line yAxisId="left" type="monotone" dataKey="close" name="Close Price" stroke="#C9D1D9" dot={false} strokeWidth={2} />
                  <Line yAxisId="left" type="monotone" dataKey="sma20" name="SMA 20" stroke="#f59e0b" dot={false} />
                  <Line yAxisId="left" type="monotone" dataKey="sma50" name="SMA 50" stroke="#3b82f6" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            
            <div className="bg-surface border border-border p-4 rounded-lg h-[240px]">
              <h4 className="font-semibold mb-2 text-center text-sm text-gray-300">{ticker} Trading Volume</h4>
              <ResponsiveContainer width="100%" height="85%">
                <ComposedChart data={history} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid stroke="#30363D" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" stroke="#8B949E" minTickGap={30} tick={{ fontSize: 11 }} />
                  <YAxis stroke="#8B949E" tickFormatter={val => (val/1000000).toFixed(0) + 'M'} tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#161B22', borderColor: '#30363D', color: '#C9D1D9' }} />
                  <Bar dataKey="volume" name="Volume" fill="rgba(100, 150, 250, 0.5)" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        ) : (
          <div className="p-8 text-center text-gray-400 border border-dashed border-border rounded">No historical technical data available for {ticker}.</div>
        )}
      </div>
    </div>
  );
}
