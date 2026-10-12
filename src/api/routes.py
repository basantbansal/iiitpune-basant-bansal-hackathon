from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import re
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import time
import urllib.parse
import yfinance as yf

from src.api.dependencies import get_state, AppState
from src.api.schemas import PortfolioMetrics, ScanResponse, RebalanceConfig, HistoryDataPoint
from src.api.utils import fetch_portfolio_covariance, calculate_portfolio_volatility
from src.engine.processor import EntityResolver, SemanticDedup

def round_currency(val: Optional[float]) -> Optional[float]:
    """Explicit currency-rounding policy: standard financial half-up rounding to nearest cent (2 decimal places).
    
    Half-cent amounts ($0.005) round up to the next cent ($0.01).
    Example: $88,445.00 * 0.0010 = $88.445 -> $88.45.
    """
    if val is None:
        return None
    d = Decimal(f"{val:.6f}")
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

router = APIRouter(prefix="/api")

@router.get("/health")
async def health_check(details: bool = Query(False), state: AppState = Depends(get_state)):
    res = {"status": "ok"}
    if details:
        res["groq"] = {
            "available": getattr(state.risk_engine, "groq_available", False),
            "reason": getattr(state.risk_engine, "groq_reason", "no key (GROQ_API_KEY unset in environment)")
        }
    return res

@router.get("/config", response_model=RebalanceConfig)
async def get_config(state: AppState = Depends(get_state)):
    return RebalanceConfig(
        initial_capital=state.rebalancer.initial_capital,
        alpha_tilt=state.rebalancer.alpha_tilt,
        data_mode=state.data_mode,
        max_items=state.max_items
    )

@router.post("/config")
async def update_config(config: RebalanceConfig, state: AppState = Depends(get_state)):
    async with state.lock:
        state.initial_capital = config.initial_capital
        state.rebalancer.initial_capital = config.initial_capital
        state.rebalancer.alpha_tilt = config.alpha_tilt
        state.data_mode = config.data_mode
        state.max_items = config.max_items
        
        state.db.save_config(config.model_dump())
    return config

@router.get("/portfolio")
async def get_portfolio(state: AppState = Depends(get_state)):
    prices = state.rebalancer.fetch_current_prices()
    baseline = 1.0 / len(state.rebalancer.tickers)
    
    orders_map = {}
    if not state.latest_orders.empty and "Ticker" in state.latest_orders.columns:
        for _, row in state.latest_orders.iterrows():
            orders_map[row["Ticker"]] = row

    portfolio = []
    for ticker in state.rebalancer.tickers:
        price = prices.get(ticker)
        curr_sh = state.rebalancer.current_shares.get(ticker)
        order_row = orders_map.get(ticker)

        if order_row is not None:
            # "Current Shares" recorded in rebalance orders represents PRE-TRADE shares
            pre_sh = float(order_row["Current Shares"]) if "Current Shares" in order_row and order_row["Current Shares"] is not None and not pd.isna(order_row["Current Shares"]) else (curr_sh or 0.0)
            target_sh = float(order_row["Target Shares"]) if "Target Shares" in order_row and order_row["Target Shares"] is not None and not pd.isna(order_row["Target Shares"]) else (curr_sh or 0.0)
            action = str(order_row["Action"])
            order_qty = float(order_row["Order Qty"]) if order_row["Order Qty"] is not None and not pd.isna(order_row["Order Qty"]) else 0.0
            signed_qty = float(order_row["Signed Qty"]) if "Signed Qty" in order_row and order_row["Signed Qty"] is not None and not pd.isna(order_row["Signed Qty"]) else (order_qty if action == "BUY" else (-order_qty if action == "SELL" else 0.0))
            trade_val = float(order_row["Trade Value ($)"]) if order_row["Trade Value ($)"] is not None and not pd.isna(order_row["Trade Value ($)"]) else 0.0
            trade_val = round_currency(trade_val) or 0.0
            est_fee = round_currency(trade_val * 0.0010) or 0.0
            try:
                pre_w = float(str(order_row["Prev Weight"]).replace("%", "")) / 100.0
            except Exception:
                pre_w = baseline
            try:
                target_w = float(str(order_row["New Weight"]).replace("%", "")) / 100.0
            except Exception:
                target_w = state.rebalancer.current_weights.get(ticker, baseline)
            # Invariant: Allocation delta (percentage points) = target weight - baseline weight
            signed_delta_pct = round((target_w - baseline) * 100, 2)
        else:
            pre_sh = curr_sh
            target_sh = curr_sh
            action = "HOLD"
            order_qty = 0.0
            signed_qty = 0.0
            trade_val = 0.0
            est_fee = 0.0
            pre_w = baseline
            target_w = state.rebalancer.current_weights.get(ticker, baseline)
            signed_delta_pct = round((target_w - baseline) * 100, 2)

        # Enforce exact invariant: target_shares = pre_shares + signed_qty
        pre_sh_round = round(pre_sh, 2) if pre_sh is not None else None
        signed_qty_round = round(signed_qty, 2)
        if pre_sh_round is not None:
            target_sh_round = round(pre_sh_round + signed_qty_round, 2)
        else:
            target_sh_round = round(target_sh, 2) if target_sh is not None else None

        # Trade notional = signed trade quantity * valid price, with correct sign convention
        signed_trade_notional = round_currency(signed_qty_round * price) if (price is not None and action != "HOLD") else 0.0

        t_signals = [s for s in state.signals_log if s.get("entity", "").upper() == ticker or s.get("ticker", "").upper() == ticker]
        company_name = state.ingestor.TICKER_COMPANY_MAP.get(ticker, ticker)
        if t_signals:
            sentiments = [float(s.get("sentiment_score", 0.0)) for s in t_signals]
            net_sentiment = round(float(np.mean(sentiments)), 2)
            driving_signal = max(t_signals, key=lambda s: float(s.get("impact_score", 0.0)))
            driving_headline = driving_signal.get("headline", "—")
            driving_url = driving_signal.get("url")
            if not driving_url and driving_headline and driving_headline != "—":
                driving_url = f"https://news.google.com/search?q={urllib.parse.quote(driving_headline)}"
        else:
            net_sentiment = 0.0
            driving_headline = "No active news signals"
            driving_url = ""

        portfolio.append({
            "ticker": ticker,
            "company_name": company_name,
            "price": price,
            "pre_shares": pre_sh_round,
            "current_shares": pre_sh_round,
            "target_shares": target_sh_round,
            "post_shares": target_sh_round,
            "action": action,
            "order_qty": round(abs(signed_qty_round), 2),
            "signed_qty": signed_qty_round,
            "trade_value": trade_val,
            "trade_notional": signed_trade_notional,
            "est_fee": est_fee,
            "pre_weight": round(pre_w, 4),
            "current_weight": round(pre_w, 4),
            "target_weight": round(target_w, 4),
            "baseline_weight": baseline,
            "signed_delta_pct": signed_delta_pct,
            "net_sentiment": net_sentiment,
            "driving_headline": driving_headline,
            "driving_headline_url": driving_url,
            "signal_count": len(t_signals)
        })
    return portfolio

@router.get("/portfolio/metrics", response_model=PortfolioMetrics)
async def get_portfolio_metrics(state: AppState = Depends(get_state)):
    state.sync_holdings()
    prices = state.rebalancer.fetch_current_prices()

    if not state.latest_orders.empty and "Trade Value ($)" in state.latest_orders.columns:
        gross_turnover = round_currency(float(state.latest_orders["Trade Value ($)"].fillna(0.0).sum())) or 0.0
    else:
        gross_turnover = 0.0

    one_way_turnover = round_currency(gross_turnover / 2.0) or 0.0
    cost_rate = 0.0010  # 10 bps
    est_txn_cost = round_currency(gross_turnover * cost_rate) or 0.0

    holdings_market_val = 0.0
    has_missing = False
    for t in state.rebalancer.tickers:
        sh = state.rebalancer.current_shares.get(t)
        p = prices.get(t)
        if sh is not None and p is not None:
            holdings_market_val += sh * p
        else:
            has_missing = True
            
    if has_missing:
        total_val = None
        holdings_market_val = None
        one_way_turnover_pct = 0.0
    else:
        holdings_market_val = round_currency(holdings_market_val)
        total_val = round_currency(holdings_market_val - est_txn_cost)
        one_way_turnover_pct = round((one_way_turnover / total_val) * 100, 2) if total_val else 0.0

    cw_series = pd.Series(state.rebalancer.current_weights)
    if cw_series.empty:
        max_asset = "Equal Weight"
        max_asset_weight = 1.0 / len(state.rebalancer.tickers)
    else:
        max_val = float(cw_series.max())
        min_val = float(cw_series.min())
        if abs(max_val - min_val) < 1e-4:
            max_asset = "Equal Weight"
            max_asset_weight = max_val
        else:
            max_asset = str(cw_series.idxmax())
            max_asset_weight = max_val
    
    cov_matrix = fetch_portfolio_covariance(state.rebalancer.tickers)
    baseline_vol = None
    target_vol = None
    if cov_matrix is not None:
        baseline_weights = {t: 1.0/len(state.rebalancer.tickers) for t in state.rebalancer.tickers}
        baseline_vol = calculate_portfolio_volatility(baseline_weights, cov_matrix, state.rebalancer.tickers)
        target_vol = calculate_portfolio_volatility(state.rebalancer.current_weights, cov_matrix, state.rebalancer.tickers)
        
    return PortfolioMetrics(
        initial_capital=float(state.initial_capital),
        total_value=total_val,
        holdings_market_value=holdings_market_val,
        max_asset=str(max_asset),
        max_asset_weight=max_asset_weight,
        total_turnover=gross_turnover,
        gross_turnover=gross_turnover,
        one_way_turnover=one_way_turnover,
        one_way_turnover_pct=one_way_turnover_pct,
        est_txn_cost=est_txn_cost,
        cumulative_fees_paid=est_txn_cost,
        cash_balance=-est_txn_cost,
        last_updated=state.last_updated,
        last_scan_duration=getattr(state, "last_scan_duration", None),
        baseline_volatility=baseline_vol,
        target_volatility=target_vol
    )

@router.get("/stocks")
async def get_stocks(state: AppState = Depends(get_state)):
    return state.rebalancer.tickers

@router.get("/stocks/{ticker}/details")
async def get_stock_details(ticker: str, state: AppState = Depends(get_state)):
    ticker = ticker.upper()
    if ticker not in state.rebalancer.tickers:
        raise HTTPException(status_code=404, detail="Stock not found")
        
    prices = state.rebalancer.fetch_current_prices()
    price = prices.get(ticker)
    current_w = state.rebalancer.current_weights.get(ticker, 0.0)
    baseline_w = 1.0 / len(state.rebalancer.tickers)
    company_name = state.ingestor.TICKER_COMPANY_MAP.get(ticker, ticker)
    
    # Filter signals matching this ticker from runtime signals and persistent DB
    ticker_upper = ticker.upper()
    t_signals = [
        s for s in state.signals_log 
        if s.get("entity", "").upper() == ticker_upper or s.get("ticker", "").upper() == ticker_upper
    ]
    # Sort signals most recent first
    t_signals_sorted = sorted(
        t_signals,
        key=lambda s: str(s.get("published_at", "") or ""),
        reverse=True
    )
    
    if t_signals:
        sentiments = [float(s.get("sentiment_score", 0.0)) for s in t_signals]
        net_sentiment = round(float(np.mean(sentiments)), 2)
        avg_impact = round(float(np.mean([float(s.get("impact_score", 5.0)) for s in t_signals])), 1)
        driving_signal = max(t_signals, key=lambda s: float(s.get("impact_score", 0.0)))
    else:
        net_sentiment = 0.0
        avg_impact = 0.0
        driving_signal = None
        
    delta_pp = round((current_w - baseline_w) * 100, 2)
    
    # Extract trade execution data for this stock if orders exist
    action = "HOLD"
    order_qty = 0.0
    signed_qty = 0.0
    trade_value = 0.0
    pre_shares = state.rebalancer.current_shares.get(ticker)
    post_shares = pre_shares
    
    if not state.latest_orders.empty and "Ticker" in state.latest_orders.columns:
        matching_order = state.latest_orders[state.latest_orders["Ticker"] == ticker]
        if not matching_order.empty:
            row = matching_order.iloc[0]
            action = str(row.get("Action", "HOLD"))
            order_qty = float(row.get("Order Qty", 0.0) or 0.0)
            signed_qty = float(row.get("Signed Qty", 0.0) or 0.0)
            trade_value = float(row.get("Trade Value ($)", 0.0) or 0.0)
            pre_shares = float(row.get("Current Shares", 0.0) or (pre_shares or 0.0))
            post_shares = float(row.get("Target Shares", 0.0) or (pre_shares or 0.0))
            
    formatted_signals = []
    for sig in t_signals_sorted:
        s = sig.copy()
        event_type = s.get("event_classification", "")
        is_unclass = event_type in ("Unclassified / Needs Review", "Unclassified")
        
        if is_unclass:
            sev = None
        elif "severity" not in s or s["severity"] == event_type or s["severity"] == "N/A":
            sev_val = state.risk_engine.base_severities.get(event_type)
            sev = float(sev_val) if isinstance(sev_val, (int, float)) else None
        elif s.get("severity") == "N/A":
            sev = None
        else:
            try:
                sev = float(s["severity"])
            except Exception:
                sev = None

        evidence_text = s.get("evidence", s.get("evidence_span", ""))
        inf_source = s.get("inference_source") or ("groq" if "groq" in str(s.get("model_version", "")).lower() else "fallback_rules")
        is_synthetic = bool(s.get("is_synthetic", False) or "synthetic" in str(s.get("source", "")).lower() or "demo data" in str(s.get("source", "")).lower())
        is_shared = bool(s.get("is_shared_headline", False))

        pub_str = str(s.get("published_at", ""))
        try:
            pub_dt = pd.to_datetime(pub_str, utc=True)
            age_days = round((pd.Timestamp.now(tz="UTC") - pub_dt).total_seconds() / 86400.0, 1)
        except Exception:
            age_days = None

        score = float(s.get("sentiment_score", 0.0))
        conf = float(s.get("confidence", 0.50))
        if conf < 0.35 or (abs(score) <= 0.15 and is_unclass):
            direction_badge = "Needs Review"
        elif score > 0.15:
            direction_badge = "Bullish"
        elif score < -0.15:
            direction_badge = "Bearish"
        else:
            direction_badge = "Neutral"

        url = s.get("url")
        if not url:
            hd = s.get("headline", "")
            url = f"https://news.google.com/search?q={urllib.parse.quote(hd)}" if hd else ""

        net_delta_str = s.get("net_delta") or f"{delta_pp:+.2f} pp"

        formatted_signals.append({
            "ticker": ticker,
            "headline": s.get("headline", ""),
            "source": s.get("source", "Market Feed"),
            "published_at": pub_str,
            "article_age_days": age_days,
            "sentiment_score": round(score, 2),
            "sentiment_label": direction_badge,
            "direction_badge": direction_badge,
            "impact_score": round(float(s.get("impact_score", 5.0)), 1),
            "severity": sev,
            "event_classification": s.get("event_classification", "Market News"),
            "confidence": round(conf, 2),
            "evidence": evidence_text,
            "evidence_span": evidence_text,
            "model_version": s.get("model_version", "Groq LLaMA 3.3 70B"),
            "inference_source": inf_source,
            "is_unclassified": is_unclass,
            "is_synthetic": is_synthetic,
            "is_shared_headline": is_shared,
            "net_delta": net_delta_str,
            "url": url
        })
        
    # Build human-readable rationale explanation
    if delta_pp > 0.05:
        rationale_text = f"Overweight tilt (+{delta_pp:.2f} pp): Positive event sentiment (net score {net_sentiment:+.2f}) drove allocation to {current_w*100:.2f}%, triggering a BUY order for {order_qty:.2f} shares."
    elif delta_pp < -0.05:
        rationale_text = f"Underweight tilt ({delta_pp:.2f} pp): Adverse sentiment or risk signals (net score {net_sentiment:+.2f}) reduced allocation to {current_w*100:.2f}%, triggering a SELL order for {order_qty:.2f} shares."
    elif len(formatted_signals) > 0:
        rationale_text = f"Neutral balanced tilt: {len(formatted_signals)} signal(s) analyzed resulted in balanced sentiment ({net_sentiment:+.2f}), maintaining allocation near baseline."
    else:
        rationale_text = "Baseline preservation: No active news signals in recent scans. As per institutional index rebalancing rules, unaffected constituents retain equal-weight baseline (10.00%) with 0 order quantity (HOLD)."

    return {
        "ticker": ticker,
        "company_name": company_name,
        "price": price,
        "current_weight": current_w,
        "baseline_weight": baseline_w,
        "delta_pp": delta_pp,
        "net_sentiment": net_sentiment,
        "avg_impact": avg_impact,
        "action": action,
        "order_qty": order_qty,
        "signed_qty": signed_qty,
        "trade_value": trade_value,
        "pre_shares": pre_shares,
        "post_shares": post_shares,
        "rationale_text": rationale_text,
        "signal_count": len(formatted_signals),
        "signals": formatted_signals
    }

@router.get("/stocks/{ticker}/history", response_model=List[HistoryDataPoint])
async def get_stock_history(ticker: str, period: str = Query("1Y")):
    ticker = ticker.upper()
    valid_periods = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "1Y": "1y"}
    yf_p = valid_periods.get(period, "1y")
    
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=yf_p)
        if hist.empty:
            return []
            
        benchmark_hist = yf.Ticker("SPY").history(period=yf_p)
        
        has_enough_data = len(hist) > 50
        sma20 = hist['Close'].rolling(window=20).mean() if has_enough_data else None
        sma50 = hist['Close'].rolling(window=50).mean() if has_enough_data else None
        
        result = []
        for date, row in hist.iterrows():
            d_str = date.strftime("%Y-%m-%d")
            point = HistoryDataPoint(
                date=d_str,
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=int(row['Volume']),
                sma20=float(sma20[date]) if sma20 is not None and not pd.isna(sma20[date]) else None,
                sma50=float(sma50[date]) if sma50 is not None and not pd.isna(sma50[date]) else None,
                benchmark_close=float(benchmark_hist.loc[date]['Close']) if not benchmark_hist.empty and date in benchmark_hist.index else None
            )
            result.append(point)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def is_fund_holdings_disclosure(headline: str) -> bool:
    """Filters backward-looking fund-holdings & custody position adjustment headlines, plus exchange margin notices."""
    patterns = [
        r"\b(lowers?|decreases?|raises?|increases?|trims?|boosts?|cuts?)\s+(stake|holdings?|position)\b",
        r"\b(stake|holdings?|position)\s+(in|of)\s+.*\s+(lowered|decreased|raised|increased|trimmed|boosted|cut)\b",
        r"\bshares\s+(purchased|sold|added|acquired)\s+(by|to)\b",
        r"\bshares\s+added\s+to\s+.*portfolio\b",
        r"\b(acquires?|sells?|purchases?)\s+[\d,]+\s+shares\s+of\b",
        r"\bposition\s+in\s+.*\b(llc|capital|advisors|management|group|fund|asset|wealth)\b",
        r"\bstake\s+in\s+.*\b(llc|capital|advisors|management|group|fund|asset|wealth)\b",
        r"\b(dupree|capital|financial|advisors|wealth|asset)\s+group\s+llc\b",
        r"\b(capital\s+management|capital\s+advisors|wealth\s+management|asset\s+management|holdings\s+llc|fund\s+llc)\b.*\b(stake|holdings?|shares?)\b",
        r"\b(13f|form\s+13-f|institutional\s+holdings?)\b",
        r"\bdiscloses?\s+.*(stake|holdings?)\b",
        r"\bdecreases\s+holdings\b",
        r"\blowers\s+stake\b",
        r"\b(futures\s+margins?|cme\s+margins?|margin\s+requirements?)\b"
    ]
    lower = headline.lower()
    return any(re.search(p, lower) for p in patterns)

@router.get("/risk-signals")
async def get_risk_signals(state: AppState = Depends(get_state)):
    out = []
    for sig in state.signals_log:
        s = sig.copy()
        event_type = s.get("event_classification", "")
        is_unclass = event_type in ("Unclassified / Needs Review", "Unclassified")
        s["is_unclassified"] = is_unclass

        if is_unclass:
            s["severity"] = None
        elif "severity" not in s or s["severity"] == event_type or s["severity"] == "N/A":
            sev = state.risk_engine.base_severities.get(event_type)
            s["severity"] = float(sev) if isinstance(sev, (int, float)) else None
        elif s.get("severity") == "N/A":
            s["severity"] = None

        if "evidence" not in s:
            s["evidence"] = s.get("evidence_span", "No evidence provided.")

        if "inference_source" not in s:
            s["inference_source"] = "groq" if "groq" in str(s.get("model_version", "")).lower() else "fallback_rules"

        # Check synthetic demo data
        is_synthetic = bool(s.get("is_synthetic", False) or "synthetic" in str(s.get("source", "")).lower() or "demo data" in str(s.get("source", "")).lower())
        s["is_synthetic"] = is_synthetic

        # Calculate article age in days
        pub_str = str(s.get("published_at", ""))
        try:
            pub_dt = pd.to_datetime(pub_str, utc=True)
            age_days = round((pd.Timestamp.now(tz="UTC") - pub_dt).total_seconds() / 86400.0, 1)
            s["article_age_days"] = age_days
        except Exception:
            s["article_age_days"] = None

        # Direction badge: derived from SENTIMENT with documented neutral band |s| <= 0.15
        sent = float(s.get("sentiment_score", 0.0))
        conf = float(s.get("confidence", 0.50))
        if conf < 0.35 or (abs(sent) <= 0.15 and is_unclass):
            s["direction_badge"] = "Needs Review"
        elif sent > 0.15:
            s["direction_badge"] = "Bullish"
        elif sent < -0.15:
            s["direction_badge"] = "Bearish"
        else:
            s["direction_badge"] = "Neutral"

        # Ticker net allocation delta from baseline (10%) in percentage points
        ent = s.get("entity", "").upper()
        if ent in state.rebalancer.tickers:
            tgt_w = state.rebalancer.current_weights.get(ent, 0.10)
            delta_val = (tgt_w - 0.10) * 100
            s["net_delta"] = f"{delta_val:+.2f} pp"
        else:
            s["net_delta"] = "0.00 pp"

        url = s.get("url")
        if not url:
            hd = s.get("headline", "")
            s["url"] = f"https://news.google.com/search?q={urllib.parse.quote(hd)}" if hd else ""
        else:
            s["url"] = url

        out.append(s)
    return out


@router.post("/market-scan", response_model=ScanResponse)
async def execute_market_scan(state: AppState = Depends(get_state)):
    async with state.lock:
        scan_start_time = time.time()
        is_offline = "Offline" in state.data_mode
        # Pull news across all constituents without global truncation
        raw_news = state.ingestor.fetch_live_news(
            max_items_per_ticker=state.max_items,
            force_fallback=is_offline
        )

        stats_retrieved = len(raw_news)
        stats_duplicates = 0
        stats_already_processed = 0
        stats_filtered = 0
        stats_stale_filtered = 0
        stats_no_entities = 0
        stats_processed = 0
        stats_restored = 0
        stats_ticker_assignments = 0
        new_signals = []

        # Enforce per-ticker cap independently (default 2, max 5)
        max_per_ticker = max(1, min(5, getattr(state, "max_items", 2)))
        ticker_counts = {t: 0 for t in state.rebalancer.tickers}

        dedup_engine = SemanticDedup(time_window_hours=24)
        recent_docs = state.db.get_recent_documents(hours=24)
        batch_hashes = set()
        offline_run_id = str(uuid.uuid4())[:8] if is_offline else ""

        for item in raw_news:
            raw_hd = item["headline"]

            # Ingestion filter for institutional fund-holdings & custody disclosures
            if is_fund_holdings_disclosure(raw_hd):
                stats_filtered += 1
                continue

            # Recency check: ignore articles older than 7 days for allocation
            pub_str = str(item.get("published_at", ""))
            is_stale = False
            try:
                pub_dt = pd.to_datetime(pub_str, utc=True)
                age_days = (pd.Timestamp.now(tz="UTC") - pub_dt).total_seconds() / 86400.0
                if age_days > 7.0:
                    is_stale = True
                    stats_stale_filtered += 1
            except Exception:
                age_days = 0.0

            norm_hd = EntityResolver.normalize_text(raw_hd)

            if is_offline:
                d_hash = f"replay-{offline_run_id}-{SemanticDedup.get_document_hash(norm_hd)}"
            else:
                d_hash = SemanticDedup.get_document_hash(norm_hd)

            if d_hash in batch_hashes:
                continue
            batch_hashes.add(d_hash)

            resolved = EntityResolver.resolve_entities(raw_hd)
            raw_entities = {r.ticker for r in resolved}
            entities = [e for e in raw_entities if e in state.rebalancer.tickers]

            if is_offline:
                dedup_res = {"is_duplicate": False, "canonical_group_id": d_hash, "reason": None}
            else:
                dedup_res = dedup_engine.check_duplicate(norm_hd, set(entities), recent_docs)

            doc_data = {
                "document_hash": d_hash, "canonical_group_id": dedup_res["canonical_group_id"],
                "headline": raw_hd, "normalized_headline": norm_hd,
                "source": item.get("source", "News"), "published_at": item["published_at"],
                "is_duplicate": dedup_res["is_duplicate"], "duplicate_reason": dedup_res["reason"],
                "resolved_entities": list(entities)
            }
            state.db.log_document(doc_data)

            if not is_offline:
                recent_docs.insert(0, doc_data)

            if dedup_res["is_duplicate"]:
                stats_duplicates += 1
            else:
                if not entities:
                    stats_no_entities += 1
                else:
                    processed_any = False
                    is_shared = len(entities) > 1
                    is_synthetic = bool(item.get("is_synthetic", False) or "synthetic" in str(item.get("source", "")).lower() or "demo data" in str(item.get("source", "")).lower())
                    for ent in entities:
                        # Enforce independent per-ticker cap (multi-ticker counts against every ticker assigned)
                        if ticker_counts[ent] >= max_per_ticker:
                            continue

                        ticker_counts[ent] += 1
                        stats_ticker_assignments += 1

                        if is_offline:
                            a_hash = f"replay-{offline_run_id}-{state.db.generate_hash(raw_hd, ent)}"
                        else:
                            a_hash = state.db.generate_hash(raw_hd, ent)

                        if not state.db.is_article_processed(a_hash):
                            processed_any = True
                            sig = state.risk_engine.analyze(text=raw_hd, entity=ent, source=item.get("source", "News"))
                            sig_dict = sig.to_dict()
                            sig_dict["source"] = item.get("source", "News")
                            sig_dict["article_hash"] = a_hash
                            sig_dict["published_at"] = item["published_at"]
                            sig_dict["ticker"] = ent
                            sig_dict["is_shared_headline"] = is_shared
                            sig_dict["is_synthetic"] = is_synthetic
                            sig_dict["is_stale"] = is_stale
                            if is_shared:
                                sig_dict["confidence"] = round(float(sig_dict.get("confidence", 0.50)) * 0.70, 2)
                            state.db.log_signal(
                                article_hash=a_hash, signal_dict=sig_dict,
                                headline=raw_hd, source=item.get("source", "News"),
                                published_at=item["published_at"], document_hash=d_hash
                            )
                            new_signals.append(sig_dict)
                        else:
                            stats_already_processed += 1
                            sig_dict = state.db.get_signal(a_hash)
                            if sig_dict:
                                existing_hashes = {s.get("article_hash") for s in state.signals_log}
                                if a_hash not in existing_hashes:
                                    processed_any = True
                                    sig_dict["is_shared_headline"] = is_shared
                                    sig_dict["is_synthetic"] = is_synthetic
                                    sig_dict["is_stale"] = is_stale
                                    new_signals.append(sig_dict)
                                    stats_restored += 1

                    if processed_any:
                        stats_processed += 1

        stats_skipped = stats_duplicates + stats_already_processed
        stats_new_signals = len(new_signals)

        if new_signals:
            state.signals_log.extend(new_signals)
            high_impact = [s for s in new_signals if float(s.get("impact_score", 0) or 0) >= 7.0]
            if high_impact:
                state.auto_trigger_stress = high_impact[0]
            else:
                state.auto_trigger_stress = None

            # Allocation signals: exclude stale items (>7d) and exclude synthetic items in live mode
            signals_for_rebalance = [
                s for s in new_signals
                if not s.get("is_stale", False) and (is_offline or not s.get("is_synthetic", False))
            ]

            if signals_for_rebalance:
                try:
                    state.latest_orders = state.rebalancer.rebalance(signals_for_rebalance)
                    state.db.save_holdings(state.rebalancer.current_shares)
                    scan_iso = datetime.now(timezone.utc).isoformat()
                    state.db.save_target_weights_history(scan_iso, state.rebalancer.current_weights)
                except ValueError as e:
                    pass

        scan_duration = round(time.time() - scan_start_time, 1)
        state.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state.last_scan_duration = scan_duration

        if stats_retrieved == 0:
            message = "Scan failed. No articles retrieved."
        elif stats_processed == 0 and stats_skipped > 0 and stats_no_entities == 0:
            message = "Scan complete. All retrieved articles skipped (duplicates)."
        elif stats_processed == 0 and stats_no_entities > 0 and stats_skipped == 0:
            message = "Scan complete. Retrieved articles contained no monitored entities."
        else:
            message = (
                f"Scan complete: {stats_retrieved} unique articles retrieved, "
                f"{stats_filtered} fund disclosures filtered, "
                f"{stats_stale_filtered} stale articles filtered (>7d), "
                f"{stats_ticker_assignments} ticker assignments, "
                f"{stats_new_signals} new signals, "
                f"{stats_duplicates} true duplicates, "
                f"{stats_already_processed} already processed (took {scan_duration}s)."
            )

        latest_orders_summary = []
        if not state.latest_orders.empty:
            for idx, row in state.latest_orders.iterrows():
                latest_orders_summary.append({
                    "ticker": row["Ticker"],
                    "action": row["Action"],
                    "shares": float(row["Order Qty"]) if row["Order Qty"] is not None and not pd.isna(row["Order Qty"]) else 0.0,
                    "trade_value": float(row["Trade Value ($)"]) if row["Trade Value ($)"] is not None and not pd.isna(row["Trade Value ($)"]) else 0.0
                })

        return ScanResponse(
            message=message,
            stats_retrieved=stats_retrieved,
            stats_ticker_assignments=stats_ticker_assignments,
            stats_new_signals=stats_new_signals,
            stats_skipped=stats_skipped,
            stats_duplicates=stats_duplicates,
            stats_already_processed=stats_already_processed,
            stats_filtered=stats_filtered,
            stats_stale_filtered=stats_stale_filtered,
            stats_no_entities=stats_no_entities,
            stats_processed=stats_processed,
            new_signals=new_signals,
            latest_orders_summary=latest_orders_summary
        )

@router.get("/portfolio/history")
async def get_portfolio_history(state: AppState = Depends(get_state)):
    raw = state.db.get_target_weights_history()
    baseline = 1.0 / len(state.rebalancer.tickers)
    
    if not raw:
        pt = {"scan_time": "Baseline", "scan_label": "Baseline (10%)"}
        for t in state.rebalancer.tickers:
            pt[t] = round(state.rebalancer.current_weights.get(t, baseline) * 100, 2)
        return [pt]
    
    from collections import defaultdict
    grouped = defaultdict(dict)
    scan_order = []
    for r in raw:
        st = r["scan_time"]
        if st not in grouped:
            scan_order.append(st)
        grouped[st][r["ticker"]] = round(float(r["target_weight"]) * 100, 2)
    
    result = []
    first_pt = {"scan_time": "Baseline", "scan_label": "Baseline"}
    for t in state.rebalancer.tickers:
        first_pt[t] = 10.0
    result.append(first_pt)
    
    for idx, st in enumerate(scan_order):
        try:
            dt = datetime.fromisoformat(st)
            label = f"Scan {idx+1} ({dt.strftime('%H:%M')})"
        except Exception:
            label = f"Scan {idx+1}"
        pt = {"scan_time": st, "scan_label": label}
        for t in state.rebalancer.tickers:
            pt[t] = grouped[st].get(t, round(baseline * 100, 2))
        result.append(pt)
    return result

@router.get("/stress-scenarios")
async def get_stress_scenarios(state: AppState = Depends(get_state)):
    return state.stress_engine.scenarios

@router.get("/stress-trigger")
async def get_stress_trigger(state: AppState = Depends(get_state)):
    high_impact_signals = [s for s in state.signals_log if float(s.get("impact_score", 0) or 0) >= 7.0]
    if not high_impact_signals:
        return {
            "has_trigger": False,
            "recommended_scenario": "1. 2022 Fed Tightening Shock",
            "message": "No high-impact trigger in the last scan (impact ≥ 7); manual scenario selection active.",
            "signal": None
        }
    
    top_sig = max(high_impact_signals, key=lambda s: float(s.get("impact_score", 0) or 0))
    event_class = str(top_sig.get("event_classification", ""))
    
    if event_class == "Macroeconomic":
        rec_scenario = "1. 2022 Fed Tightening Shock"
    elif event_class in ("Credit Event", "Geopolitical"):
        rec_scenario = "2. Systemic Credit Crunch"
    else:
        rec_scenario = "3. Tech Bubble Burst"
        
    return {
        "has_trigger": True,
        "recommended_scenario": rec_scenario,
        "message": f"High-impact risk signal detected for {top_sig.get('entity', 'Universe')} (Impact: {top_sig.get('impact_score', 7)}/10, {event_class}). Auto-triggered scenario recommendation: '{rec_scenario}'.",
        "signal": {
            "entity": top_sig.get("entity", ""),
            "headline": top_sig.get("headline", ""),
            "impact_score": top_sig.get("impact_score", 0),
            "event_classification": event_class,
            "sentiment_score": top_sig.get("sentiment_score", 0.0)
        }
    }

class StressTestRequest(BaseModel):
    scenario_name: str

@router.post("/stress-test")
async def run_stress_test(req: StressTestRequest, state: AppState = Depends(get_state)):
    prices = state.rebalancer.fetch_current_prices()
    holdings_market_val = 0.0
    has_missing = False
    for t in state.rebalancer.tickers:
        sh = state.rebalancer.current_shares.get(t)
        p = prices.get(t)
        if sh is not None and p is not None:
            holdings_market_val += sh * p
        else:
            has_missing = True
            
    if has_missing:
        raise HTTPException(status_code=400, detail="Stress test unavailable due to missing market prices.")

    # Calculate cumulative simulated transaction fees (10 bps on gross traded value)
    if not state.latest_orders.empty and "Trade Value ($)" in state.latest_orders.columns:
        gross_turnover = round_currency(float(state.latest_orders["Trade Value ($)"].fillna(0.0).sum())) or 0.0
        est_txn_cost = round_currency(gross_turnover * 0.0010) or 0.0
    else:
        est_txn_cost = 0.0

    holdings_market_val = round_currency(holdings_market_val) or 0.0
    # Total portfolio value equals holdings market value minus cumulative fees (matching Dashboard exactly)
    total_val = round_currency(holdings_market_val - est_txn_cost)
    
    out = state.stress_engine.run_scenario(state.rebalancer.current_weights, holdings_market_val, req.scenario_name)
    df_stress = out["market_df"]
    shock = state.stress_engine.scenarios.get(req.scenario_name, {})

    t_loss = round_currency(float(df_stress["Total P&L"].sum())) or 0.0
    post_shock_val = round_currency(total_val + t_loss)

    results = []
    for _, row in df_stress.iterrows():
        ticker = row["Ticker"]
        profile = state.stress_engine.asset_profiles.get(ticker, {})
        pnl_val = float(row.get("Total P&L", 0.0))
        base_exp = float(row.get("Base Exposure", 0.0))
        stressed_val = float(row.get("Stressed Value", base_exp + pnl_val))
        drawdown_pct = float(row.get("Drawdown (%)", 0.0))
        share_loss = float((pnl_val / t_loss) * 100) if t_loss != 0 else 0.0

        results.append({
            "ticker": ticker,
            "weight": state.rebalancer.current_weights.get(ticker, 0.0) * 100,
            "exposure": round(base_exp, 2),
            "beta": round(float(profile.get("beta", 1.0)), 2),
            "rate_mod_dur": round(float(profile.get("rate_mod_dur", 1.0)), 2),
            "spread_mod_dur": round(float(profile.get("spread_mod_dur", 1.0)), 2),
            "effective_shock_pct": round(drawdown_pct, 2),
            "pnl": round(pnl_val, 2),
            "post_shock_value": round(stressed_val, 2),
            "share_of_loss_pct": round(share_loss, 2),
            # Legacy fields for chart backward compatibility
            "notional": round(base_exp, 2),
            "drawdown": round(drawdown_pct, 2)
        })

    # Sort results by largest loss (most negative P&L first)
    results.sort(key=lambda x: x["pnl"])

    scenario_assumptions = {
        "scenario_name": req.scenario_name,
        "equity_shock_pct": float(shock.get("equity_shock", 0.0) * 100),
        "rate_shock_bps": float(shock.get("rate_shock_bps", 0)),
        "spread_shock_bps": float(shock.get("spread_shock_bps", 0)),
        "description": shock.get("desc", ""),
        "channel_notes": "Equity channel modeled via asset Beta. Rate and credit spread sensitivities are illustrative equity proxy sensitivities (assumption). Portfolio is equity-only with no direct fixed-income holdings."
    }

    banking_book = state.stress_engine.run_banking_book_stress(req.scenario_name)

    return {
        "total_value": round(total_val, 2),
        "drawdown_value": round(t_loss, 2),
        "drawdown_pct": round((t_loss / total_val) * 100, 2) if total_val else 0.0,
        "post_shock_value": round(post_shock_val, 2),
        "asset_results": results,
        "scenario_assumptions": scenario_assumptions,
        "banking_book": banking_book
    }

@router.post("/reset")
async def reset_runtime_data(state: AppState = Depends(get_state)):
    await state.reset_runtime()
    return {"status": "ok", "message": "Runtime signals and orders successfully reset."}

