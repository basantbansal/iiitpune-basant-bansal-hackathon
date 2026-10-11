import React, { useEffect, useState } from 'react';
import { api } from '../api';

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

export default function RiskSignals({ refreshTrigger }: { refreshTrigger?: number }) {
  const [signals, setSignals] = useState<any[]>([]);
  const [healthInfo, setHealthInfo] = useState<any>(null);

  useEffect(() => {
    api.getRiskSignals().then(data => {
      setSignals([...data].reverse());
    }).catch(console.error);

    api.getHealthDetails().then(setHealthInfo).catch(console.error);
  }, [refreshTrigger]);

  const fallbackCount = signals.filter(s => s.inference_source === 'fallback_rules' || !s.inference_source || String(s.inference_source).includes('fallback')).length;
  const groqCount = signals.filter(s => s.inference_source === 'groq').length;

  // Group signals by ticker
  const groupedByTicker = signals.reduce<Record<string, any[]>>((acc, sig) => {
    const ticker = sig.ticker?.toUpperCase() || sig.entity?.toUpperCase() || 'OTHER';
    if (!acc[ticker]) acc[ticker] = [];
    acc[ticker].push(sig);
    return acc;
  }, {});

  const tickerList = Object.keys(groupedByTicker).sort((a, b) => {
    if (a === 'OTHER') return 1;
    if (b === 'OTHER') return -1;
    return a.localeCompare(b);
  });

  const getActionBadge = (tiltStr?: string) => {
    if (tiltStr) {
      if (tiltStr.startsWith('+') && tiltStr !== '+0.00 pp') {
        return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-success/20 text-success border border-success/30 font-mono">+ BUY</span>;
      }
      if (tiltStr.startsWith('-') && tiltStr !== '-0.00 pp') {
        return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-danger/20 text-danger border border-danger/30 font-mono">- SELL</span>;
      }
    }
    return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700 font-mono">HOLD</span>;
  };

  return (
    <div className="space-y-6">
      {/* Risk Engine Header & Overview Card */}
      <div className="bg-surface border border-border p-4 rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-3 mb-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-mono px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">RISK ENGINE</span>
            <h3 className="text-lg font-bold text-heading">Risk Engine — News to Structured Risk Signals</h3>
          </div>
          <p className="text-xs text-gray-300 mt-1.5 leading-relaxed max-w-4xl">
            The Risk Engine converts financial news into structured signals, including sentiment, event category, impact score, confidence, and supporting evidence. It uses a Groq-hosted language model when available and has a deterministic fallback rule engine with grammar negation and contrastive clause handling when offline or unconfigured.
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-[11px] font-mono text-gray-400 bg-background px-2.5 py-1 rounded border border-border">
            Hybrid Cascade • LLM + Lexicon
          </span>
        </div>
      </div>

      {/* Header and Provenance Banner */}
      <div>
        <div className="flex justify-between items-center mb-3">
          <h4 className="text-lg font-semibold">Active Risk Signal Log</h4>
          {signals.length > 0 && (
            <div className="text-xs text-gray-400">
              Total Signals: <span className="text-heading font-medium">{signals.length}</span> (⚡ Groq: <span className="text-purple-400">{groqCount}</span> | ⚙️ Fallback Rules: <span className="text-amber-400">{fallbackCount}</span>)
            </div>
          )}
        </div>

        {/* NLP Provenance Notice with Groq Diagnostics */}
        <div className="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs px-3.5 py-3 rounded-lg mb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <div>
              ℹ️ <strong>NLP Provenance:</strong> {groqCount > 0 
                ? `${groqCount} signals generated via Groq LLM, ${fallbackCount} signals evaluated via Finance Lexicon + Deterministic Rule Engine.` 
                : `All ${fallbackCount} signals evaluated via Finance Lexicon + Deterministic Rule Engine.`
              }
            </div>
            {healthInfo?.groq && !healthInfo.groq.available && (
              <div className="text-[11px] text-amber-400/80 mt-1">
                ⚡ <strong>Groq Engine Status:</strong> Offline ({healthInfo.groq.reason || 'GROQ_API_KEY unset in environment'}) • Deterministic fallback engaged automatically.
              </div>
            )}
          </div>
          <span className="text-xs px-2.5 py-1 rounded bg-amber-500/20 border border-amber-500/40 font-mono text-[11px] shrink-0 self-start sm:self-center">
            {groqCount > 0 ? 'Ensemble Mode' : 'Finance Lexicon Fallback'}
          </span>
        </div>

        {/* Legend */}
        {signals.length > 0 && (
          <div className="flex items-center justify-between flex-wrap gap-2 text-xs text-gray-300 bg-surface px-3.5 py-2.5 rounded-lg border border-border mb-4">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-gray-400 font-medium">Direction Legend:</span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-success inline-block"></span>
                <span>Bullish (Sentiment &gt; +0.15)</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-danger inline-block"></span>
                <span>Bearish (Sentiment &lt; -0.15)</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-gray-500 inline-block"></span>
                <span>Neutral (|s| &le; 0.15)</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block"></span>
                <span>Event: Unclassified</span>
              </span>
            </div>
            <div className="text-[11px] text-gray-400">
              Base Severity = category prior • Shared headlines discounted (0.5x weight)
            </div>
          </div>
        )}
      </div>

      {signals.length === 0 ? (
        <div className="text-gray-400 p-8 text-center bg-surface border border-border rounded-lg">
          No active signals yet. Run a market scan to fetch news.
        </div>
      ) : (
        <div className="space-y-6">
          {tickerList.map(ticker => {
            const tickerSignals = groupedByTicker[ticker];
            const avgSentiment = tickerSignals.reduce((sum, s) => sum + (s.sentiment_score ?? 0.0), 0) / (tickerSignals.length || 1);
            const netDelta = tickerSignals[0]?.net_delta || '0.00 pp';

            return (
              <div key={ticker} className="bg-surface border border-border rounded-lg overflow-hidden">
                {/* Ticker Group Header */}
                <div className="bg-background/80 px-4 py-3 border-b border-border flex items-center justify-between flex-wrap gap-3">
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-bold font-mono text-primary">{ticker}</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-surface border border-border font-medium text-gray-300">
                      {tickerSignals.length} {tickerSignals.length === 1 ? 'signal' : 'signals'}
                    </span>
                    {getActionBadge(netDelta)}
                  </div>

                  <div className="flex items-center gap-4 text-xs font-mono">
                    <div className="flex items-center gap-1.5">
                      <span className="text-gray-400 font-sans">Avg Sentiment:</span>
                      <span className={`font-bold ${
                        avgSentiment > 0.15 ? 'text-success' : avgSentiment < -0.15 ? 'text-danger' : 'text-gray-300'
                      }`}>
                        {avgSentiment > 0 ? `+${avgSentiment.toFixed(2)}` : avgSentiment.toFixed(2)}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <span className="text-gray-400 font-sans">Net Tilt:</span>
                      <span className={`font-bold ${
                        netDelta.startsWith('+') && netDelta !== '+0.00 pp' ? 'text-success' : netDelta.startsWith('-') && netDelta !== '-0.00 pp' ? 'text-danger' : 'text-gray-300'
                      }`}>
                        {netDelta}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Individual Signals for this Ticker */}
                <div className="divide-y divide-border/60 p-2 space-y-2">
                  {tickerSignals.map((sig, idx) => {
                    // Strictly sentiment driven direction badge (|s| <= 0.15 is Neutral)
                    const sent = sig.sentiment_score ?? 0.0;
                    const badgeType = sig.direction_badge || (
                      sent > 0.15 ? 'Bullish' : sent < -0.15 ? 'Bearish' : 'Neutral'
                    );
                    const isUnclassified = sig.is_unclassified || sig.event_classification === 'Unclassified' || sig.event_classification?.includes('Unclassified');
                    const ageLabel = formatArticleAge(sig.article_age_days, sig.published_at);

                    return (
                      <div key={idx} className="p-3 bg-surface hover:bg-background/40 transition-colors rounded flex flex-col gap-2">
                        <div className="flex justify-between items-start gap-4">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
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

                              <h5 className="font-bold text-heading text-base inline">{sig.headline}</h5>
                            </div>

                            <div className="text-xs text-gray-400 mt-1 flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-gray-200">{sig.ticker}</span>
                              <span>•</span>
                              <span className="px-2 py-0.5 rounded bg-background border border-border font-medium text-gray-300">
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
                              <span>{sig.source}</span>
                              <span>•</span>
                              <span title={sig.published_at ? new Date(sig.published_at).toLocaleString() : ''}>
                                {ageLabel ? `⏱️ ${ageLabel}` : (sig.published_at ? new Date(sig.published_at).toLocaleDateString() : '')}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
                            {/* Ticker Net Change */}
                            <div className="text-center px-2 py-1 rounded bg-background border border-border min-w-[75px]" title="Ticker allocation change from baseline resulting from scan">
                              <div className="text-[10px] text-gray-400 font-medium">Ticker Net Change</div>
                              <div className={`text-xs font-bold font-mono ${
                                sig.net_delta && sig.net_delta.startsWith('+') && sig.net_delta !== '+0.00 pp'
                                  ? 'text-success' 
                                  : sig.net_delta && sig.net_delta.startsWith('-') && sig.net_delta !== '-0.00 pp'
                                  ? 'text-danger' 
                                  : 'text-gray-400'
                              }`}>
                                {sig.net_delta || '0.00 pp'}
                              </div>
                            </div>

                            {/* Sentiment Score */}
                            <div className="text-center px-2 py-1 rounded bg-background border border-border min-w-[65px]" title="Finance-aware entity sentiment score [-1.0, 1.0]">
                              <div className="text-[10px] text-gray-400 font-medium">Sentiment</div>
                              <div className={`text-xs font-bold font-mono ${
                                sent > 0.15 ? 'text-success' : sent < -0.15 ? 'text-danger' : 'text-gray-400'
                              }`}>
                                {sent > 0 ? `+${sent.toFixed(2)}` : sent.toFixed(2)}
                              </div>
                            </div>

                            {/* Base Severity */}
                            <div className="text-center px-2 py-1 rounded bg-background border border-border min-w-[75px]" title="Base Severity: category prior risk benchmark (not article-specific)">
                              <div className="text-[10px] text-gray-400 font-medium">Base Severity</div>
                              <div className={`text-xs font-bold ${
                                sig.severity == null 
                                  ? 'text-gray-400 italic font-normal text-[10px]' 
                                  : sig.severity >= 7.5 ? 'text-danger' : sig.severity >= 5.0 ? 'text-amber-400' : 'text-blue-400'
                              }`}>
                                {sig.severity != null ? sig.severity.toFixed(1) : 'Unclassified'}
                              </div>
                            </div>

                            {/* Impact Score */}
                            <div className="text-center px-2 py-1 rounded bg-background border border-border min-w-[55px]" title="Multi-factor portfolio impact score (1 to 10)">
                              <div className="text-[10px] text-gray-400 font-medium">Impact</div>
                              <div className="text-xs font-bold text-primary font-mono">
                                {sig.impact_score != null ? `${sig.impact_score}/10` : '—'}
                              </div>
                            </div>

                            {/* Confidence */}
                            <div className="text-center px-2 py-1 rounded bg-background border border-border min-w-[65px]" title={sig.inference_source === 'groq' ? "Model parse confidence" : "Heuristic keyword-match confidence estimate"}>
                              <div className="text-[10px] text-gray-400 font-medium">Confidence</div>
                              <div className="text-xs font-bold text-success font-mono">
                                {sig.confidence != null ? `${(sig.confidence * 100).toFixed(0)}%` : '—'}
                              </div>
                            </div>
                          </div>
                        </div>

                        {sig.evidence && (
                          <p className="text-gray-300 text-xs mt-1 bg-background/50 p-2 rounded border border-border/40 font-mono">
                            <span className="text-gray-500 font-sans font-medium">Evidence Snippet: </span>
                            {sig.evidence}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

