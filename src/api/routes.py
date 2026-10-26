from fastapi import APIRouter, Depends, HTTPException, Query, Body
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
from src.api.schemas import (
    PortfolioMetrics,
    ScanResponse,
    RebalanceConfig,
    HistoryDataPoint,
    HoldingsUpdateRequest,
    FXConversionRequest,
    CapitalAllocationRequest,
    ReportingCurrencyRequest
)
from src.api.utils import fetch_portfolio_covariance, calculate_portfolio_volatility
from src.engine.processor import EntityResolver, SemanticDedup
from src.engine.catalog import get_catalog
from src.engine.ingestion import parse_publication_timestamp, is_irrelevant_or_seo_headline

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

@router.get("/universe")
async def get_universe():
    """Returns all 20 instruments from the authoritative catalog."""
    catalog = get_catalog()
    return [inst.to_dict() for inst in catalog.get_all()]

@router.get("/universe/selection")
async def get_universe_selection(state: AppState = Depends(get_state)):
    """Returns current active 10-stock selection and deterministic default selection."""
    catalog = get_catalog()
    current_ids = list(state.selected_ids)
    default_ids = list(catalog.get_default_selection_ids())
    
    selected_instruments = [
        catalog.get_by_id(i_id).to_dict()
        for i_id in current_ids
        if catalog.get_by_id(i_id) is not None
    ]
    default_instruments = [
        catalog.get_by_id(i_id).to_dict()
        for i_id in default_ids
        if catalog.get_by_id(i_id) is not None
    ]
    
    return {
        "selection": current_ids,
        "default_selection": default_ids,
        "selected_instruments": selected_instruments,
        "default_instruments": default_instruments
    }

@router.put("/universe/selection")
async def update_universe_selection(
    payload: Any = Body(...),
    state: AppState = Depends(get_state)
):
    """
    Accepts exactly 10 distinct instrument IDs and validates every ID against the catalog.
    Rejects unknown IDs, duplicates, fewer than 10 selections, and more than 10 selections.
    Updates the active portfolio universe and recalculates state.
    """
    if isinstance(payload, list):
        raw_ids = payload
    elif isinstance(payload, dict):
        raw_ids = payload.get("selection") or payload.get("instrument_ids") or []
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid payload format. Expected a JSON list or object with 'selection' or 'instrument_ids'."
        )

    catalog = get_catalog()
    try:
        validated_insts = catalog.validate_selection(raw_ids)
    except (ValueError, TypeError) as err:
        raise HTTPException(status_code=400, detail=str(err))

    async with state.lock:
        state.set_universe_selection([inst.id for inst in validated_insts])
        
        # If signals exist, recalculate rebalance orders for new active universe
        if state.signals_log:
            is_offline = "Offline" in state.data_mode
            signals_for_rebalance = [
                s for s in state.signals_log
                if not s.get("is_stale", False) and (is_offline or not s.get("is_synthetic", False))
                and s.get("entity", "").upper() in state.rebalancer.tickers
            ]
            if signals_for_rebalance:
                try:
                    state.latest_orders = state.rebalancer.rebalance(signals_for_rebalance)
                    state.db.save_holdings(state.rebalancer.current_shares)
                    state.db.save_latest_orders(state.latest_orders)
                except Exception:
                    pass

    return {
        "status": "ok",
        "message": "Stock universe successfully updated.",
        "selection": state.selected_ids,
        "selected_instruments": [inst.to_dict() for inst in validated_insts]
    }

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

        # If signals exist, recalculate rebalance orders and weights using new alpha_tilt
        if state.signals_log:
            is_offline = "Offline" in state.data_mode
            signals_for_rebalance = [
                s for s in state.signals_log
                if not s.get("is_stale", False) and (is_offline or not s.get("is_synthetic", False))
            ]
            if signals_for_rebalance:
                try:
                    state.latest_orders = state.rebalancer.rebalance(signals_for_rebalance, cash_balances=state.cash_balances)
                    state.db.save_holdings(state.rebalancer.current_shares)
                    scan_iso = datetime.now(timezone.utc).isoformat()
                    state.db.save_target_weights_history(scan_iso, state.rebalancer.current_weights)
                    state.db.save_latest_orders(state.latest_orders)
                except Exception:
                    pass
    return config

@router.get("/portfolio")
async def get_portfolio(currency: Optional[str] = Query(None), state: AppState = Depends(get_state)):
    prices = state.rebalancer.fetch_current_prices()
    val_prices = state.rebalancer.fetch_valuation_prices()
    all_price_meta = state.rebalancer.price_provider.get_prices_with_metadata(state.rebalancer.tickers)
    const_meta = all_price_meta.get("constituents", {})
    baseline = 1.0 / len(state.rebalancer.tickers)
    fx_quote = state.fx_provider.get_rate("USD", "INR")
    usd_inr_rate = fx_quote.rate

    rep_curr = (currency or state.reporting_currency or "INR").upper()
    rep_curr_sym = "₹" if rep_curr == "INR" else "$"

    orders_map = {}
    if not state.latest_orders.empty and "Ticker" in state.latest_orders.columns:
        for _, row in state.latest_orders.iterrows():
            orders_map[row["Ticker"]] = row

    portfolio = []
    for ticker in state.rebalancer.tickers:
        live_price = prices.get(ticker)
        val_price = val_prices.get(ticker)
        price = live_price if (live_price is not None and live_price > 0) else None
        eff_price = price if price is not None else val_price
        curr_sh = state.rebalancer.current_shares.get(ticker)
        order_row = orders_map.get(ticker)

        if order_row is not None:
            pre_sh = float(order_row["Current Shares"]) if "Current Shares" in order_row and order_row["Current Shares"] is not None and not pd.isna(order_row["Current Shares"]) else (curr_sh or 0.0)
            target_sh = float(order_row["Target Shares"]) if "Target Shares" in order_row and order_row["Target Shares"] is not None and not pd.isna(order_row["Target Shares"]) else (curr_sh or 0.0)
            action = str(order_row["Action"])
            order_qty = float(order_row["Order Qty"]) if order_row["Order Qty"] is not None and not pd.isna(order_row["Order Qty"]) else 0.0
            signed_qty = float(order_row["Signed Qty"]) if "Signed Qty" in order_row and order_row["Signed Qty"] is not None and not pd.isna(order_row["Signed Qty"]) else (order_qty if action == "BUY" else (-order_qty if action == "SELL" else 0.0))
            
            # Trade value native vs USD
            if "Trade Value (Native)" in order_row and order_row["Trade Value (Native)"] is not None and not pd.isna(order_row["Trade Value (Native)"]):
                trade_val = float(order_row["Trade Value (Native)"])
            else:
                trade_val = float(order_row.get("Trade Value ($)", 0.0) or 0.0)
            
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
            signed_delta_pct = round((target_w - pre_w) * 100, 2)
            is_exec = bool(order_row.get("Is Executable", True))
            exec_status = str(order_row.get("Execution Status", "EXECUTABLE" if action != "HOLD" else "NO_CHANGE"))
        else:
            pre_sh = curr_sh
            target_sh = curr_sh
            action = "HOLD"
            order_qty = 0.0
            signed_qty = 0.0
            trade_val = 0.0
            est_fee = 0.0
            pre_w = state.rebalancer.current_weights.get(ticker, baseline)
            target_w = pre_w
            signed_delta_pct = 0.0
            is_exec = True
            exec_status = "NO_CHANGE"

        pre_sh_round = round(pre_sh, 2) if pre_sh is not None else None
        signed_qty_round = round(signed_qty, 2)
        if pre_sh_round is not None:
            target_sh_round = round(pre_sh_round + signed_qty_round, 2)
        else:
            target_sh_round = round(target_sh, 2) if target_sh is not None else None

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

        t_meta = const_meta.get(ticker, {})
        cat = state.catalog
        inst = cat.get_by_ticker(ticker) or cat.get_by_id(ticker) or cat.get_by_provider_symbol(ticker)

        currency_native = t_meta.get("currency") or (inst.currency if inst else "USD")
        currency_sym = "$" if currency_native == "USD" else "₹"
        is_fallback_price = t_meta.get("is_fallback", live_price is None or live_price <= 0)
        ref_price = t_meta.get("price") or val_price
        price_source = t_meta.get("source", ("Live Market (Yahoo Finance)" if not is_fallback_price else f"Deterministic Reference ({currency_sym}{eff_price:.2f})"))
        inst_name = inst.name if inst else company_name
        inst_id = inst.id if inst else ticker
        market = inst.market if inst else "US"
        exchange = inst.exchange if inst else "NASDAQ"
        provider_symbol = inst.provider_symbol if inst else ticker

        if is_fallback_price and action in ("BUY", "SELL"):
            is_exec = False
            exec_status = "WITHHELD_FALLBACK_PRICE"

        price_usd = price if currency_native == "USD" else (round_currency(price / usd_inr_rate) if price is not None else (round_currency(eff_price / usd_inr_rate) if eff_price is not None else None))
        price_inr = price if currency_native == "INR" else (round_currency(price * usd_inr_rate) if price is not None else (round_currency(eff_price * usd_inr_rate) if eff_price is not None else None))
        price_reporting = price_inr if rep_curr == "INR" else price_usd

        trade_val_usd = trade_val if currency_native == "USD" else (round_currency(trade_val / usd_inr_rate) or 0.0)
        trade_val_inr = trade_val if currency_native == "INR" else (round_currency(trade_val * usd_inr_rate) or 0.0)
        trade_val_reporting = trade_val_inr if rep_curr == "INR" else trade_val_usd

        trade_notional_usd = signed_trade_notional if currency_native == "USD" else (round_currency(signed_trade_notional / usd_inr_rate) or 0.0)
        trade_notional_inr = signed_trade_notional if currency_native == "INR" else (round_currency(signed_trade_notional * usd_inr_rate) or 0.0)
        trade_notional_reporting = trade_notional_inr if rep_curr == "INR" else trade_notional_usd

        est_fee_usd = est_fee if currency_native == "USD" else (round_currency(est_fee / usd_inr_rate) or 0.0)
        est_fee_inr = est_fee if currency_native == "INR" else (round_currency(est_fee * usd_inr_rate) or 0.0)
        est_fee_reporting = est_fee_inr if rep_curr == "INR" else est_fee_usd

        current_market_val_native = round_currency((pre_sh_round or 0.0) * (eff_price or 0.0))
        current_market_val_usd = current_market_val_native if currency_native == "USD" else (round_currency(current_market_val_native / usd_inr_rate) if current_market_val_native is not None else 0.0)
        current_market_val_inr = current_market_val_native if currency_native == "INR" else (round_currency(current_market_val_native * usd_inr_rate) if current_market_val_native is not None else 0.0)
        current_market_val_reporting = current_market_val_inr if rep_curr == "INR" else current_market_val_usd

        portfolio.append({
            "ticker": ticker,
            "id": inst_id,
            "instrument_id": inst_id,
            "provider_symbol": provider_symbol,
            "market": market,
            "exchange": exchange,
            "currency": currency_native,
            "currency_symbol": currency_sym,
            "reporting_currency": rep_curr,
            "reporting_currency_symbol": rep_curr_sym,
            "company_name": inst_name,
            "price": price,
            "price_native": price if price is not None else eff_price,
            "price_usd": price_usd,
            "price_inr": price_inr,
            "price_reporting": price_reporting,
            "reference_price": ref_price,
            "is_fallback_price": is_fallback_price,
            "price_source": price_source,
            "pre_shares": pre_sh_round,
            "current_shares": pre_sh_round,
            "target_shares": target_sh_round,
            "post_shares": target_sh_round,
            "current_market_value": current_market_val_native,
            "current_market_value_native": current_market_val_native,
            "current_market_value_usd": current_market_val_usd,
            "current_market_value_inr": current_market_val_inr,
            "current_market_value_reporting": current_market_val_reporting,
            "action": action,
            "order_qty": round(abs(signed_qty_round), 2),
            "signed_qty": signed_qty_round,
            "trade_value": trade_val,
            "trade_value_native": trade_val,
            "trade_value_usd": trade_val_usd,
            "trade_value_inr": trade_val_inr,
            "trade_value_reporting": trade_val_reporting,
            "trade_notional": signed_trade_notional,
            "trade_notional_usd": trade_notional_usd,
            "trade_notional_inr": trade_notional_inr,
            "trade_notional_reporting": trade_notional_reporting,
            "est_fee": est_fee,
            "est_fee_native": est_fee,
            "est_fee_usd": est_fee_usd,
            "est_fee_inr": est_fee_inr,
            "est_fee_reporting": est_fee_reporting,
            "pre_weight": round(pre_w, 4),
            "current_weight": round(pre_w, 4),
            "target_weight": round(target_w, 4),
            "baseline_weight": baseline,
            "signed_delta_pct": signed_delta_pct,
            "net_sentiment": net_sentiment,
            "driving_headline": driving_headline,
            "driving_headline_url": driving_url,
            "signal_count": len(t_signals),
            "is_executable": is_exec,
            "execution_status": exec_status,
            "fx_rate": usd_inr_rate,
            "fx_rate_quote": f"USD/INR = {usd_inr_rate:.2f}",
            "fx_source": fx_quote.source,
            "fx_as_of": fx_quote.as_of,
            "fx_is_fallback": fx_quote.is_fallback,
            "fx_is_live": fx_quote.is_live,
            "fx_is_stale": fx_quote.is_stale
        })
    return portfolio

@router.get("/portfolio/metrics", response_model=PortfolioMetrics)
async def get_portfolio_metrics(currency: Optional[str] = Query(None), state: AppState = Depends(get_state)):
    state.sync_holdings()
    prices = state.rebalancer.fetch_current_prices()
    val_prices = state.rebalancer.fetch_valuation_prices()
    price_meta = state.rebalancer.price_provider.get_prices_with_metadata(state.rebalancer.tickers)
    const_meta = price_meta.get("constituents", {})
    cat = state.catalog

    fx_quote = state.fx_provider.get_rate("USD", "INR")
    usd_inr_rate = fx_quote.rate

    rep_curr = (currency or state.reporting_currency or "INR").upper()
    rep_curr_sym = "₹" if rep_curr == "INR" else "$"

    # Identify currencies in current active constituents
    usd_tickers = [t for t in state.rebalancer.tickers if (cat.get_by_ticker(t) and cat.get_by_ticker(t).currency == "USD") or not cat.get_by_ticker(t)]
    inr_tickers = [t for t in state.rebalancer.tickers if cat.get_by_ticker(t) and cat.get_by_ticker(t).currency == "INR"]
    has_mixed_currencies = (len(usd_tickers) > 0 and len(inr_tickers) > 0) or (state.cash_usd > 0 and state.cash_inr > 0)

    # Check for missing prices: any constituent live price missing (None) or non-positive
    missing_prices = [t for t in state.rebalancer.tickers if prices.get(t) is None or prices.get(t) <= 0]
    fallback_prices = [t for t in state.rebalancer.tickers if const_meta.get(t, {}).get("is_fallback", False)]

    # Compute invested market values separated by currency using best valuation prices
    holdings_usd = sum(
        float(state.rebalancer.current_shares.get(t, 0.0) or 0.0) * (prices.get(t) if (prices.get(t) is not None and prices.get(t) > 0) else (val_prices.get(t) or 0.0))
        for t in usd_tickers
    )
    holdings_inr = sum(
        float(state.rebalancer.current_shares.get(t, 0.0) or 0.0) * (prices.get(t) if (prices.get(t) is not None and prices.get(t) > 0) else (val_prices.get(t) or 0.0))
        for t in inr_tickers
    )

    holdings_usd_val = round_currency(holdings_usd) if holdings_usd > 0 else 0.0
    holdings_inr_val = round_currency(holdings_inr) if holdings_inr > 0 else 0.0
    holdings_inr_usd_equiv = round_currency(holdings_inr_val / usd_inr_rate) if (usd_inr_rate > 0 and holdings_inr_val > 0) else 0.0
    holdings_usd_inr_equiv = round_currency(holdings_usd_val * usd_inr_rate) if holdings_usd_val > 0 else 0.0

    # Separate Cash Balances (fees are deducted on execution; no double deduction here)
    cash_usd = round_currency(state.cash_usd) or 0.0
    cash_inr = round_currency(state.cash_inr) or 0.0
    cash_inr_usd_equiv = round_currency(cash_inr / usd_inr_rate) if (usd_inr_rate > 0 and cash_inr > 0) else 0.0
    cash_usd_inr_equiv = round_currency(cash_usd * usd_inr_rate) or 0.0

    # Traded turnover & transaction costs for latest orders
    turnover_usd = 0.0
    turnover_inr = 0.0
    fees_usd = 0.0
    fees_inr = 0.0

    if not state.latest_orders.empty:
        for _, row in state.latest_orders.iterrows():
            if not bool(row.get("Is Executable", True)) or str(row.get("Action", "HOLD")) not in ("BUY", "SELL"):
                continue
            t = row.get("Ticker")
            val_usd = float(row.get("Trade Value ($)", 0.0) or 0.0)
            val_native = float(row.get("Trade Value (Native)", val_usd) or 0.0)
            inst = cat.get_by_ticker(t)
            if inst and inst.currency == "INR":
                turnover_inr += val_native
                fees_inr += val_native * 0.0010
            else:
                turnover_usd += val_usd
                fees_usd += val_usd * 0.0010

    turnover_usd = round_currency(turnover_usd) or 0.0
    turnover_inr = round_currency(turnover_inr) or 0.0
    fees_usd = round_currency(fees_usd) or 0.0
    fees_inr = round_currency(fees_inr) or 0.0

    # Cumulative fees recorded across execution history
    stored_cum_fees_usd = float(state.cumulative_fees.get("USD", 0.0) or 0.0)
    stored_cum_fees_inr = float(state.cumulative_fees.get("INR", 0.0) or 0.0)

    # Available cash net of trading fees:
    # If cumulative fees haven't debited cash yet (e.g. simulated test orders), deduct fees once
    avail_cash_usd = max(0.0, round_currency(cash_usd - fees_usd) or 0.0) if stored_cum_fees_usd == 0 else cash_usd
    avail_cash_inr = max(0.0, round_currency(cash_inr - fees_inr) or 0.0) if stored_cum_fees_inr == 0 else cash_inr
    avail_cash_inr_usd_equiv = round_currency(avail_cash_inr / usd_inr_rate) if usd_inr_rate > 0 else 0.0
    avail_cash_usd_inr_equiv = round_currency(avail_cash_usd * usd_inr_rate) or 0.0

    cum_fees_usd = max(stored_cum_fees_usd, fees_usd)
    cum_fees_inr = max(stored_cum_fees_inr, fees_inr)

    if rep_curr == "INR":
        initial_cap = state.get_initial_capital_in_reporting_currency("INR")
        holdings_market_val = round_currency(holdings_inr_val + holdings_usd_inr_equiv)
        cash_balance = round_currency(avail_cash_inr + avail_cash_usd_inr_equiv)
        gross_turnover = round_currency(turnover_inr + (turnover_usd * usd_inr_rate))
        one_way_turnover = round_currency(gross_turnover / 2.0)
        est_txn_cost = round_currency(fees_inr + (fees_usd * usd_inr_rate))
        cumulative_fees_paid = round_currency(cum_fees_inr + (cum_fees_usd * usd_inr_rate))
    else:
        initial_cap = state.get_initial_capital_in_reporting_currency("USD")
        holdings_market_val = round_currency(holdings_usd_val + holdings_inr_usd_equiv)
        cash_balance = round_currency(avail_cash_usd + avail_cash_inr_usd_equiv)
        gross_turnover = round_currency(turnover_usd + (turnover_inr / usd_inr_rate))
        one_way_turnover = round_currency(gross_turnover / 2.0)
        est_txn_cost = round_currency(fees_usd + (fees_inr / usd_inr_rate))
        cumulative_fees_paid = round_currency(cum_fees_usd + (cum_fees_inr / usd_inr_rate))

    total_gross_turnover = gross_turnover
    total_est_fee_usd = round_currency(fees_usd + (fees_inr / usd_inr_rate)) or 0.0

    # Data Quality Rules for Consolidated NAV
    total_val = None
    nav_status = "UNAVAILABLE"
    nav_unavailability_reason = None

    # Calculate indicative nav transparently
    indicative_nav = round_currency(holdings_market_val + cash_balance)
    indicative_nav_inr = indicative_nav if rep_curr == "INR" else round_currency(indicative_nav * usd_inr_rate)
    indicative_nav_usd = round_currency(indicative_nav / usd_inr_rate) if (rep_curr == "INR" and usd_inr_rate > 0) else indicative_nav

    indicative_holdings_val = holdings_market_val
    indicative_holdings_val_usd = round_currency(holdings_usd_val + holdings_inr_usd_equiv)
    indicative_holdings_val_inr = round_currency(holdings_inr_val + holdings_usd_inr_equiv)

    needs_fx = (rep_curr == "USD" and (holdings_inr_val > 0 or cash_inr > 0)) or \
               (rep_curr == "INR" and (holdings_usd_val > 0 or cash_usd > 0))

    if missing_prices:
        nav_status = "UNAVAILABLE"
        nav_unavailability_reason = f"Missing market prices for: {', '.join(missing_prices)}"
        total_val = None
        holdings_market_val = None
    elif needs_fx and (fx_quote.is_fallback or fx_quote.is_stale or fx_quote.rate <= 0):
        nav_status = "UNAVAILABLE"
        nav_unavailability_reason = f"USD/INR exchange rate is stale or fallback-only ({fx_quote.source}); live rate required for consolidated NAV"
        total_val = None
        holdings_market_val = None
    else:
        total_val = indicative_nav
        if fallback_prices:
            nav_status = "INDICATIVE_FALLBACK"
            nav_unavailability_reason = f"Fallback reference prices used for {len(fallback_prices)} constituents"
        else:
            nav_status = "LIVE"
            nav_unavailability_reason = None

    total_val_usd = (round_currency(total_val / usd_inr_rate) if (total_val is not None and usd_inr_rate > 0) else None) if rep_curr == "INR" else total_val
    total_val_inr = total_val if rep_curr == "INR" else (round_currency(total_val * usd_inr_rate) if total_val is not None else None)

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
        baseline_weights = {t: 1.0 / len(state.rebalancer.tickers) for t in state.rebalancer.tickers}
        baseline_vol = calculate_portfolio_volatility(baseline_weights, cov_matrix, state.rebalancer.tickers)
        target_vol = calculate_portfolio_volatility(state.rebalancer.current_weights, cov_matrix, state.rebalancer.tickers)

    effective_last_updated = state.last_updated if (state.signals_log and state.last_updated not in ("Never", "Restored")) else "No scan executed yet"

    return PortfolioMetrics(
        reporting_currency=rep_curr,
        reporting_currency_symbol=rep_curr_sym,
        initial_capital=float(initial_cap),
        initial_capital_native=float(initial_cap),
        initial_capital_reporting=float(initial_cap),
        total_value=total_val,
        total_value_usd=total_val_usd,
        total_value_inr=total_val_inr,
        holdings_market_value=holdings_market_val,
        holdings_market_value_usd=holdings_usd_val,
        holdings_market_value_inr=holdings_inr_val,
        holdings_market_value_inr_usd_equiv=holdings_inr_usd_equiv,
        max_asset=str(max_asset),
        max_asset_weight=max_asset_weight,
        total_turnover=total_gross_turnover,
        gross_turnover=total_gross_turnover,
        gross_turnover_reporting=gross_turnover,
        gross_turnover_usd=turnover_usd,
        gross_turnover_inr=turnover_inr,
        one_way_turnover=one_way_turnover,
        one_way_turnover_pct=one_way_turnover_pct,
        est_txn_cost=est_txn_cost,
        est_txn_cost_reporting=est_txn_cost,
        est_txn_cost_usd=fees_usd,
        est_txn_cost_inr=fees_inr,
        cumulative_fees_paid=cumulative_fees_paid,
        cumulative_fees_paid_reporting=cumulative_fees_paid,
        cumulative_fees_paid_usd=cum_fees_usd,
        cumulative_fees_paid_inr=cum_fees_inr,
        cash_balance=cash_balance,
        cash_reporting=cash_balance,
        cash_usd=cash_usd,
        cash_inr=cash_inr,
        cash_inr_usd_equiv=cash_inr_usd_equiv,
        cash_usd_inr_equiv=cash_usd_inr_equiv,
        fx_rate=usd_inr_rate,
        fx_rate_quote=f"USD/INR = {usd_inr_rate:.2f}",
        fx_rate_source=fx_quote.source,
        fx_rate_as_of=fx_quote.as_of or "Never",
        fx_rate_observation_time=fx_quote.observation_time,
        fx_rate_is_fallback=fx_quote.is_fallback,
        fx_rate_is_live=fx_quote.is_live,
        fx_rate_is_stale=fx_quote.is_stale,
        nav_status=nav_status,
        nav_unavailability_reason=nav_unavailability_reason,
        indicative_nav=indicative_nav,
        indicative_nav_usd=indicative_nav_usd,
        indicative_nav_inr=indicative_nav_inr,
        indicative_holdings_value=indicative_holdings_val,
        indicative_holdings_value_usd=indicative_holdings_val_usd,
        indicative_holdings_value_inr=indicative_holdings_val_inr,
        constituent_coverage=getattr(state, "latest_scan_coverage", None),
        last_updated=effective_last_updated,
        last_scan_duration=getattr(state, "last_scan_duration", None),
        baseline_volatility=baseline_vol,
        target_volatility=target_vol
    )

@router.post("/portfolio/holdings")
async def update_portfolio_holdings(req: HoldingsUpdateRequest, state: AppState = Depends(get_state)):
    async with state.lock:
        # Validate constituent tickers
        for t in req.holdings:
            if t not in state.rebalancer.tickers:
                raise HTTPException(status_code=400, detail=f"Unknown constituent ticker: {t}")

        # Validate non-negative quantities and whole numbers
        for t, qty in req.holdings.items():
            if qty < 0:
                raise HTTPException(status_code=400, detail=f"Share quantity for {t} cannot be negative ({qty})")
            if not float(qty).is_integer():
                raise HTTPException(status_code=400, detail=f"Share quantity for {t} must be a whole number ({qty})")

        prices = state.rebalancer.fetch_current_prices()
        cat = state.catalog
        usd_invested = 0.0
        inr_invested = 0.0
        for t in state.rebalancer.tickers:
            qty = float(req.holdings.get(t, 0.0))
            p = prices.get(t)
            inst = cat.get_by_ticker(t)
            curr = inst.currency if inst else "USD"
            if p is None or p <= 0:
                p = 100.0 if curr == "USD" else 1000.0
            if curr == "USD":
                usd_invested += qty * p
            else:
                inr_invested += qty * p

        usd_invested = round_currency(usd_invested) or 0.0
        inr_invested = round_currency(inr_invested) or 0.0

        if usd_invested > float(state.initial_capital) + 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"Total invested USD market value (${usd_invested:,.2f}) exceeds available initial capital (${state.initial_capital:,.2f})."
            )

        new_shares = {t: float(req.holdings.get(t, 0.0)) for t in state.rebalancer.tickers}
        state.rebalancer.current_shares = new_shares
        state.db.save_holdings(new_shares)

        has_non_usd = any((cat.get_by_ticker(t).currency if cat.get_by_ticker(t) else "USD") != "USD" for t in state.rebalancer.tickers)
        if not has_non_usd and usd_invested > 0:
            state.rebalancer.current_weights = {
                t: (new_shares[t] * (prices.get(t) or 100.0)) / usd_invested
                for t in state.rebalancer.tickers
            }
        else:
            state.rebalancer.current_weights = {
                t: 1.0 / len(state.rebalancer.tickers) for t in state.rebalancer.tickers
            }

        # Clear simulated orders: editing holdings configures initial baseline, not an executed trade
        state.latest_orders = pd.DataFrame()
        state.db.save_latest_orders(state.latest_orders)

        remaining_cash_usd = max(0.0, round_currency(float(state.initial_capital) - usd_invested) or 0.0)
        state.cash_balances["USD"] = remaining_cash_usd
        if state.cash_inr > 0:
            state.cash_balances["INR"] = max(0.0, round_currency(state.cash_inr - inr_invested) or 0.0)
        state.db.save_cash_balances(state.cash_balances)

        return {
            "status": "ok",
            "message": "Holdings successfully updated.",
            "holdings": state.rebalancer.current_shares,
            "total_invested": usd_invested,
            "total_invested_usd": usd_invested,
            "total_invested_inr": inr_invested,
            "remaining_cash": remaining_cash_usd,
            "remaining_cash_usd": remaining_cash_usd,
            "remaining_cash_inr": state.cash_inr,
            "initial_capital": float(state.initial_capital)
        }

@router.post("/portfolio/reset-holdings")
async def reset_portfolio_holdings(state: AppState = Depends(get_state)):
    async with state.lock:
        state.rebalancer._initialize_shares()
        state.db.save_holdings(state.rebalancer.current_shares)
        prices = state.rebalancer.fetch_current_prices()
        cat = state.catalog
        usd_invested = sum(
            float(state.rebalancer.current_shares.get(t, 10.0)) * (prices.get(t) or 100.0)
            for t in state.rebalancer.tickers
            if (cat.get_by_ticker(t) and cat.get_by_ticker(t).currency == "USD") or not cat.get_by_ticker(t)
        )
        usd_invested = round_currency(usd_invested) or 0.0
        remaining_cash = max(0.0, round_currency(float(state.initial_capital) - usd_invested) or 0.0)
        state.cash_balances["USD"] = remaining_cash
        state.db.save_cash_balances(state.cash_balances)
        state.rebalancer.current_weights = {t: 1.0 / len(state.rebalancer.tickers) for t in state.rebalancer.tickers}
        state.latest_orders = pd.DataFrame()
        state.db.save_latest_orders(state.latest_orders)
        return {
            "status": "ok",
            "message": "Holdings reset to default 10 shares per constituent.",
            "holdings": state.rebalancer.current_shares,
            "total_invested": usd_invested,
            "remaining_cash": remaining_cash,
            "remaining_cash_usd": remaining_cash,
            "remaining_cash_inr": state.cash_inr,
            "initial_capital": float(state.initial_capital)
        }

@router.get("/fx/rate")
async def get_fx_rate(state: AppState = Depends(get_state)):
    """Inspect current FX rate and provenance metadata."""
    usd_inr = state.fx_provider.get_rate("USD", "INR")
    inr_usd = state.fx_provider.get_rate("INR", "USD")
    return {
        "base_currency": "USD",
        "quote_currency": "INR",
        "rate": usd_inr.rate,
        "reverse_rate": inr_usd.rate,
        "source": usd_inr.source,
        "as_of": usd_inr.as_of,
        "observation_time": usd_inr.observation_time,
        "is_fallback": usd_inr.is_fallback,
        "is_live": usd_inr.is_live,
        "is_stale": usd_inr.is_stale
    }

@router.post("/portfolio/convert-fx")
async def convert_portfolio_fx(
    req: FXConversionRequest,
    state: AppState = Depends(get_state)
):
    """Executes a real-time currency conversion with full provenance audit logging."""
    async with state.lock:
        try:
            result = state.execute_fx_conversion(
                from_currency=req.from_currency,
                to_currency=req.to_currency,
                amount=req.amount,
                notes=req.notes
            )
            return {"status": "ok", "conversion": result}
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

@router.get("/portfolio/fx-conversions")
async def get_fx_conversions(
    limit: int = Query(50, ge=1, le=500),
    state: AppState = Depends(get_state)
):
    """Retrieves chronological audit log of all FX conversions."""
    conversions = state.db.get_fx_conversions(limit=limit)
    return {
        "status": "ok",
        "count": len(conversions),
        "conversions": conversions
    }

@router.post("/portfolio/allocate-capital")
async def allocate_capital(
    req: CapitalAllocationRequest,
    state: AppState = Depends(get_state)
):
    """Explicitly allocates initial capital between USD and INR."""
    async with state.lock:
        try:
            result = state.allocate_capital(
                usd_ratio=req.usd_ratio,
                inr_ratio=req.inr_ratio,
                usd_amount=req.usd_amount,
                inr_amount_usd=req.inr_amount_usd
            )
            return {"status": "ok", "allocation": result}
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

@router.get("/stocks")
async def get_stocks(state: AppState = Depends(get_state)):
    return state.rebalancer.tickers

@router.get("/stocks/{ticker}/details")
async def get_stock_details(ticker: str, state: AppState = Depends(get_state)):
    cat = state.catalog
    inst = cat.get_by_id(ticker) or cat.get_by_ticker(ticker) or cat.get_by_provider_symbol(ticker)
    display_ticker = inst.display_ticker if inst else ticker.upper()
    if not inst and display_ticker not in state.rebalancer.tickers and ticker not in state.rebalancer.tickers:
        raise HTTPException(status_code=404, detail="Stock not found")

    target_ticker = display_ticker if display_ticker in state.rebalancer.tickers else (display_ticker if inst else ticker)
    is_in_portfolio = target_ticker in state.rebalancer.tickers

    prices = state.rebalancer.fetch_current_prices()
    price = prices.get(target_ticker) or state.rebalancer.price_provider.get_price(target_ticker)
    price_meta = state.rebalancer.price_provider.get_prices_with_metadata([target_ticker])
    t_meta = price_meta["constituents"].get(target_ticker, {})
    currency = t_meta.get("currency") or (inst.currency if inst else "USD")
    currency_sym = "$" if currency == "USD" else "₹"
    is_fallback = t_meta.get("is_fallback", price is None or price <= 0)
    price_source = t_meta.get("source", ("Live Market (Yahoo Finance)" if not is_fallback else f"Deterministic Reference ({currency_sym}100.00)"))
    display_price = price if (price is not None and price > 0) else t_meta.get("price", price)

    current_w = state.rebalancer.current_weights.get(target_ticker, 0.0)
    n_constituents = len(state.rebalancer.tickers) if state.rebalancer.tickers else 10
    baseline_w = 1.0 / n_constituents if is_in_portfolio else 0.0
    company_name = inst.name if inst else state.ingestor.get_company_name(target_ticker)

    # Filter signals matching this ticker from runtime signals and persistent DB
    ticker_upper = target_ticker.upper()
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

    delta_pp = round((current_w - baseline_w) * 100, 2) if is_in_portfolio else 0.0

    # Extract trade execution data for this stock if orders exist
    action = "HOLD"
    order_qty = 0.0
    signed_qty = 0.0
    trade_value = 0.0
    pre_shares = state.rebalancer.current_shares.get(target_ticker, 0.0)
    post_shares = pre_shares
    is_exec = False
    exec_status = "HOLD_NO_CHANGE"

    if not state.latest_orders.empty and "Ticker" in state.latest_orders.columns:
        matching_order = state.latest_orders[state.latest_orders["Ticker"] == target_ticker]
        if not matching_order.empty:
            row = matching_order.iloc[0]
            action = str(row.get("Action", "HOLD"))
            order_qty = float(row.get("Order Qty", 0.0) or 0.0)
            signed_qty = float(row.get("Signed Qty", 0.0) or 0.0)
            trade_value = float(row.get("Trade Value (Native)", row.get("Trade Value ($)", 0.0)) or 0.0)
            pre_shares = float(row.get("Current Shares", 0.0) or (pre_shares or 0.0))
            post_shares = float(row.get("Target Shares", 0.0) or (pre_shares or 0.0))
            is_exec = bool(row.get("Is Executable", False))
            exec_status = str(row.get("Execution Status", "HOLD_NO_CHANGE"))

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
            "ticker": display_ticker,
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

    # Build human-readable rationale explanation (consistent sign and execution status)
    if not is_in_portfolio:
        rationale_text = f"{company_name} ({display_ticker}) is a catalog instrument but not currently a monitored constituent in the active 10-stock portfolio. Target allocation is 0.00%."
    elif delta_pp > 0.05:
        if net_sentiment > 0.15:
            sent_phrase = f"Positive event sentiment (net score {net_sentiment:+.2f})"
        elif net_sentiment < -0.15:
            sent_phrase = f"Relative index rebalancing and constraint normalization despite adverse event sentiment ({net_sentiment:+.2f})"
        else:
            sent_phrase = "Relative index rebalancing and constraint normalization"

        if is_exec and order_qty > 0:
            rationale_text = f"Target allocation increased by {delta_pp:+.2f} percentage points to {current_w*100:.2f}%. Executed simulated BUY order for {order_qty:.2f} shares based on {sent_phrase}."
        elif order_qty > 0 or not is_exec:
            if "MISSING_PRICE" in exec_status:
                reason = "an eligible market price was unavailable"
            elif "FALLBACK_PRICE" in exec_status:
                reason = "only deterministic fallback reference prices are available"
            elif "INSUFFICIENT_CASH" in exec_status:
                reason = f"available {currency} cash is insufficient"
            elif "FALLBACK_FX" in exec_status:
                reason = "live USD/INR exchange rate is unavailable or stale"
            else:
                reason = "eligible market data was withheld"
            rationale_text = f"Target allocation increased by {delta_pp:.2f} percentage points. No trade was executed because {reason}."
        else:
            rationale_text = f"Target allocation increased by {delta_pp:.2f} percentage points. No trade was required."
    elif delta_pp < -0.05:
        if net_sentiment < -0.15:
            sent_phrase = f"Adverse risk signals and negative sentiment (net score {net_sentiment:+.2f})"
        elif net_sentiment > 0.15:
            sent_phrase = f"Relative index rebalancing and constraint normalization despite positive sentiment ({net_sentiment:+.2f})"
        else:
            sent_phrase = "Relative index rebalancing and constraint normalization"

        if is_exec and order_qty > 0:
            rationale_text = f"Target allocation decreased by {abs(delta_pp):.2f} percentage points to {current_w*100:.2f}%. Executed simulated SELL order for {order_qty:.2f} shares based on {sent_phrase}."
        elif order_qty > 0 or not is_exec:
            if "MISSING_PRICE" in exec_status:
                reason = "an eligible market price was unavailable"
            elif "FALLBACK_PRICE" in exec_status:
                reason = "only deterministic fallback reference prices are available"
            else:
                reason = "eligible market data was withheld"
            rationale_text = f"Target allocation decreased by {abs(delta_pp):.2f} percentage points. No trade was executed because {reason}."
        else:
            rationale_text = f"Target allocation decreased by {abs(delta_pp):.2f} percentage points. No trade was required."
    elif len(formatted_signals) > 0:
        rationale_text = f"Neutral balanced tilt: {len(formatted_signals)} signal(s) analyzed resulted in balanced sentiment ({net_sentiment:+.2f}), maintaining allocation near baseline ({current_w*100:.2f}%)."
    else:
        rationale_text = f"Baseline preservation: No active news signals in recent scans. Unaffected constituent retains equal-weight baseline ({baseline_w*100:.2f}%) with 0 order quantity (HOLD)."

    return {
        "ticker": display_ticker,
        "id": inst.id if inst else display_ticker,
        "instrument_id": inst.id if inst else display_ticker,
        "display_ticker": display_ticker,
        "provider_symbol": inst.provider_symbol if inst else target_ticker,
        "currency": currency,
        "currency_symbol": currency_sym,
        "market": inst.market if inst else "US",
        "exchange": inst.exchange if inst else "NASDAQ",
        "sector": inst.sector if inst else "",
        "company_name": company_name,
        "price": display_price,
        "reference_price": t_meta.get("price"),
        "is_fallback_price": is_fallback,
        "price_source": price_source,
        "current_weight": current_w,
        "baseline_weight": baseline_w,
        "delta_pp": delta_pp,
        "net_sentiment": net_sentiment,
        "avg_impact": avg_impact,
        "action": action,
        "is_executable": is_exec,
        "execution_status": exec_status,
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
    ticker_clean = ticker.strip()
    valid_periods = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "1Y": "1y"}
    yf_p = valid_periods.get(period, "1y")

    try:
        from src.engine.catalog import get_catalog
        cat = get_catalog()
        inst = cat.get_by_id(ticker_clean) or cat.get_by_ticker(ticker_clean) or cat.get_by_provider_symbol(ticker_clean)
        provider_symbol = inst.provider_symbol if inst is not None else ticker_clean.upper()
        is_indian = inst.market == "IN" if inst is not None else False

        t = yf.Ticker(provider_symbol)
        hist = t.history(period=yf_p)
        if hist.empty:
            return []

        benchmark_sym = "^NSEI" if is_indian else "SPY"
        benchmark_hist = yf.Ticker(benchmark_sym).history(period=yf_p)
        if benchmark_hist.empty and is_indian:
            benchmark_hist = yf.Ticker("SPY").history(period=yf_p)

        has_enough_data = len(hist) > 50
        sma20 = hist['Close'].rolling(window=20).mean() if has_enough_data else None
        sma50 = hist['Close'].rolling(window=50).mean() if has_enough_data else None

        result = []
        for date, row in hist.iterrows():
            d_str = date.strftime("%Y-%m-%d")
            bench_close = None
            if not benchmark_hist.empty and date in benchmark_hist.index:
                try:
                    bench_val = benchmark_hist.loc[date]['Close']
                    if hasattr(bench_val, "iloc"):
                        bench_val = bench_val.iloc[0]
                    bench_close = float(bench_val) if not pd.isna(bench_val) else None
                except Exception:
                    bench_close = None

            point = HistoryDataPoint(
                date=d_str,
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=int(row['Volume']),
                sma20=float(sma20[date]) if sma20 is not None and not pd.isna(sma20[date]) else None,
                sma50=float(sma50[date]) if sma50 is not None and not pd.isna(sma50[date]) else None,
                benchmark_close=bench_close
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
            force_fallback=is_offline,
            tickers=state.rebalancer.tickers,
            enforce_freshness=not is_offline,
            max_age_hours=72.0
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

        coverage = {
            t: {
                "ticker": t,
                "company_name": state.ingestor.get_company_name(t),
                "raw_retrieved": 0,
                "fresh_retained": 0,
                "rejected_stale": 0,
                "rejected_irrelevant": 0,
                "assigned_to_company": 0,
                "analyzed_count": 0,
                "signals_count": 0,
                "feed_status": "OK",
                "coverage_state": "PENDING"
            }
            for t in state.rebalancer.tickers
        }

        dedup_engine = SemanticDedup(time_window_hours=24)
        recent_docs = state.db.get_recent_documents(hours=24)
        batch_hashes = set()
        offline_run_id = str(uuid.uuid4())[:8] if is_offline else ""

        for item in raw_news:
            raw_hd = item["headline"]
            orig_ticker = item.get("ticker")
            if orig_ticker in coverage:
                coverage[orig_ticker]["raw_retrieved"] += 1

            # Ingestion filter for institutional fund-holdings & custody disclosures
            is_irrel, irrel_reason = is_irrelevant_or_seo_headline(raw_hd)
            if is_irrel:
                stats_filtered += 1
                if orig_ticker in coverage:
                    coverage[orig_ticker]["rejected_irrelevant"] += 1
                continue

            # Recency check: enforce maximum 72h freshness for live market scan
            is_stale = False
            if not is_offline:
                fresh_info = parse_publication_timestamp(item.get("published_at"), max_age_hours=168.0)
                if not fresh_info["is_fresh"]:
                    is_stale = True
                    stats_stale_filtered += 1
                    if orig_ticker in coverage:
                        coverage[orig_ticker]["rejected_stale"] += 1
                else:
                    item["published_at"] = fresh_info["published_at"]
                    item["article_age_days"] = fresh_info["article_age_days"]
                    item["has_reliable_timestamp"] = fresh_info["has_reliable_timestamp"]
                    if orig_ticker in coverage:
                        coverage[orig_ticker]["fresh_retained"] += 1
            else:
                if orig_ticker in coverage:
                    coverage[orig_ticker]["fresh_retained"] += 1

            norm_hd = EntityResolver.normalize_text(raw_hd)

            if is_offline:
                d_hash = f"replay-{offline_run_id}-{SemanticDedup.get_document_hash(norm_hd)}"
            else:
                d_hash = SemanticDedup.get_document_hash(norm_hd)

            if d_hash in batch_hashes:
                stats_duplicates += 1
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
                        if ent in coverage:
                            coverage[ent]["assigned_to_company"] += 1

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
                            if ent in coverage:
                                coverage[ent]["analyzed_count"] += 1
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
                            if ent in coverage:
                                coverage[ent]["signals_count"] += 1
                        else:
                            stats_already_processed += 1
                            sig_dict = state.db.get_signal(a_hash)
                            if sig_dict:
                                if not is_offline:
                                    sig_fresh = parse_publication_timestamp(sig_dict.get("published_at"), max_age_hours=72.0)
                                    if not sig_fresh["is_fresh"]:
                                        if ent in coverage:
                                            coverage[ent]["rejected_stale"] += 1
                                        continue
                                existing_hashes = {s.get("article_hash") for s in state.signals_log}
                                if a_hash not in existing_hashes:
                                    processed_any = True
                                    sig_dict["is_shared_headline"] = is_shared
                                    sig_dict["is_synthetic"] = is_synthetic
                                    sig_dict["is_stale"] = is_stale
                                    new_signals.append(sig_dict)
                                    stats_restored += 1
                                    if ent in coverage:
                                        coverage[ent]["signals_count"] += 1

                    if processed_any:
                        stats_processed += 1

        for t in state.rebalancer.tickers:
            cov = coverage[t]
            t_sigs = [s for s in new_signals if s.get("entity") == t or s.get("ticker") == t]
            if cov["signals_count"] > 0:
                if all(abs(float(s.get("sentiment_score", 0.0))) <= 0.15 for s in t_sigs):
                    cov["coverage_state"] = "NEUTRAL_SIGNALS_ONLY"
                else:
                    cov["coverage_state"] = "FRESH_NEWS_FOUND"
            elif cov["rejected_stale"] > 0 and cov["fresh_retained"] == 0:
                cov["coverage_state"] = "ARTICLES_REJECTED_AS_STALE"
            elif cov["rejected_irrelevant"] > 0 and cov["fresh_retained"] == 0:
                cov["coverage_state"] = "ARTICLES_REJECTED_AS_IRRELEVANT"
            elif cov["raw_retrieved"] == 0:
                cov["coverage_state"] = "NO_NEWS_RETRIEVED"
            else:
                cov["coverage_state"] = "NO_RELEVANT_FRESH_ARTICLES"

        state.latest_scan_coverage = coverage

        stats_skipped = stats_duplicates + stats_already_processed
        stats_new_signals = len(new_signals)

        if new_signals:
            state.signals_log.extend(new_signals)
            high_impact = [
                s for s in new_signals
                if float(s.get("impact_score", 0) or 0) >= 7.0
                and "unclassified" not in str(s.get("event_classification", "")).lower()
                and str(s.get("event_classification", "")).strip() not in ("", "Needs Review")
            ]
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
                    state.latest_orders = state.rebalancer.rebalance(signals_for_rebalance, cash_balances=state.cash_balances)
                    state.apply_executed_orders(state.latest_orders)
                    state.db.save_holdings(state.rebalancer.current_shares)
                    scan_iso = datetime.now(timezone.utc).isoformat()
                    state.db.save_target_weights_history(scan_iso, state.rebalancer.current_weights)
                    state.db.save_latest_orders(state.latest_orders)
                except ValueError as e:
                    pass
        elif state.latest_orders.empty and state.signals_log:
            signals_for_rebalance = [
                s for s in state.signals_log
                if not s.get("is_stale", False) and (is_offline or not s.get("is_synthetic", False))
            ]
            if signals_for_rebalance:
                try:
                    state.latest_orders = state.rebalancer.rebalance(signals_for_rebalance, cash_balances=state.cash_balances)
                    state.apply_executed_orders(state.latest_orders)
                    state.db.save_holdings(state.rebalancer.current_shares)
                    scan_iso = datetime.now(timezone.utc).isoformat()
                    state.db.save_target_weights_history(scan_iso, state.rebalancer.current_weights)
                    state.db.save_latest_orders(state.latest_orders)
                except ValueError as e:
                    pass

        scan_duration = round(time.time() - scan_start_time, 1)
        state.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state.last_scan_duration = scan_duration

        stats_target_changes = 0
        stats_executed_orders = 0
        stats_withheld_orders = 0
        latest_orders_summary = []
        if not state.latest_orders.empty:
            for idx, row in state.latest_orders.iterrows():
                try:
                    pw = float(str(row.get("Prev Weight", "0")).replace("%", ""))
                    nw = float(str(row.get("New Weight", "0")).replace("%", ""))
                    if abs(nw - pw) > 1e-3:
                        stats_target_changes += 1
                except Exception:
                    pass
                status = str(row.get("Execution Status", ""))
                is_exec = bool(row.get("Is Executable", False))
                if status == "EXECUTED_SIMULATED":
                    stats_executed_orders += 1
                elif status.startswith("WITHHELD_"):
                    stats_withheld_orders += 1

                latest_orders_summary.append({
                    "ticker": row["Ticker"],
                    "action": row["Action"],
                    "shares": float(row["Order Qty"]) if row["Order Qty"] is not None and not pd.isna(row["Order Qty"]) else 0.0,
                    "signed_qty": float(row.get("Signed Qty", 0.0) or 0.0),
                    "trade_value": float(row.get("Trade Value (Native)", row.get("Trade Value ($)", 0.0)) or 0.0),
                    "trade_value_reporting": float(row.get("Trade Value (Reporting)", row.get("Trade Value ($)", 0.0)) or 0.0),
                    "currency": str(row.get("Currency", "USD")),
                    "is_executable": is_exec,
                    "execution_status": status
                })

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
            stats_target_changes=stats_target_changes,
            stats_executed_orders=stats_executed_orders,
            stats_withheld_orders=stats_withheld_orders,
            new_signals=new_signals,
            latest_orders_summary=latest_orders_summary,
            constituent_coverage=coverage
        )

@router.get("/orders")
async def get_latest_orders(state: AppState = Depends(get_state)):
    """Returns the latest simulated rebalance orders."""
    if state.latest_orders.empty:
        return []
    out = []
    for _, row in state.latest_orders.iterrows():
        out.append({
            "Ticker": row.get("Ticker"),
            "Action": row.get("Action", "HOLD"),
            "Order Qty": float(row.get("Order Qty", 0.0) or 0.0),
            "Signed Qty": float(row.get("Signed Qty", 0.0) or 0.0),
            "Trade Value ($)": float(row.get("Trade Value ($)", 0.0) or 0.0),
            "Trade Value (Native)": float(row.get("Trade Value (Native)", 0.0) or 0.0),
            "Target Shares": float(row.get("Target Shares", 0.0) or 0.0),
            "Current Shares": float(row.get("Current Shares", 0.0) or 0.0),
            "Is Executable": bool(row.get("Is Executable", False)),
            "Execution Status": str(row.get("Execution Status", "HOLD_NO_CHANGE")),
            "Execution Rationale": str(row.get("Execution Rationale", "")),
        })
    return out

@router.get("/market-scan/coverage")
async def get_market_scan_coverage(state: AppState = Depends(get_state)):
    if not state.latest_scan_coverage:
        cov = {
            t: {
                "ticker": t,
                "company_name": state.ingestor.get_company_name(t),
                "raw_retrieved": 0,
                "fresh_retained": 0,
                "rejected_stale": 0,
                "rejected_irrelevant": 0,
                "assigned_to_company": 0,
                "analyzed_count": 0,
                "signals_count": 0,
                "feed_status": "OK",
                "coverage_state": "PENDING"
            }
            for t in state.rebalancer.tickers
        }
        return {
            "status": "pending",
            "message": "No market scan executed yet for current universe session",
            "total_constituents": len(state.rebalancer.tickers),
            "total_signals": 0,
            "coverage": list(cov.values())
        }

    total_sigs = sum(item.get("signals_count", 0) for item in state.latest_scan_coverage.values())
    return {
        "status": "ok",
        "total_constituents": len(state.rebalancer.tickers),
        "total_signals": total_sigs,
        "coverage": list(state.latest_scan_coverage.values())
    }

@router.get("/reporting-currency")
async def get_reporting_currency(state: AppState = Depends(get_state)):
    curr = state.reporting_currency or "INR"
    return {
        "reporting_currency": curr,
        "currency_symbol": "₹" if curr == "INR" else "$"
    }

@router.post("/reporting-currency")
async def set_reporting_currency(req: ReportingCurrencyRequest, state: AppState = Depends(get_state)):
    async with state.lock:
        curr = req.get_currency()
        if curr not in ("INR", "USD"):
            raise HTTPException(status_code=400, detail="Supported reporting currencies are 'INR' and 'USD'")
        state.reporting_currency = curr
        state.rebalancer.reporting_currency = curr
        state.db.save_reporting_currency(curr)
        return {
            "status": "ok",
            "reporting_currency": curr,
            "currency_symbol": "₹" if curr == "INR" else "$"
        }

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
    high_impact_signals = [
        s for s in state.signals_log
        if float(s.get("impact_score", 0) or 0) >= 7.0
        and "unclassified" not in str(s.get("event_classification", "")).lower()
        and str(s.get("event_classification", "")).strip() not in ("", "Needs Review")
    ]
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
    # Available cash = unallocated cash reserves minus cumulative trading fees
    raw_cash = getattr(state, "cash_balance", 0.0) or 0.0
    cash_bal = max(0.0, round_currency(raw_cash - est_txn_cost) or 0.0)
    total_val = round_currency(holdings_market_val + cash_bal)

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
    return {
        "status": "ok",
        "message": "Runtime signals, coverage, and orders successfully reset.",
        "last_updated": "No scan executed yet"
    }

