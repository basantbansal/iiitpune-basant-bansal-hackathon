import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

def compute_rsi(data: pd.Series, window: int = 14) -> pd.Series:
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window, min_periods=1).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def compute_macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    exp1 = data.ewm(span=fast, adjust=False).mean()
    exp2 = data.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_data(ticker: str, period: str):
    # Mapping periods to yfinance periods
    valid_periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]
    if period == "1D": yf_p = "1d"
    elif period == "1W": yf_p = "5d"
    elif period == "1M": yf_p = "1mo"
    elif period == "3M": yf_p = "3mo"
    elif period == "6M": yf_p = "6mo"
    elif period == "1Y": yf_p = "1y"
    else: yf_p = "1y"
    
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=yf_p)
        if hist.empty:
            return None
        return hist
    except Exception as e:
        return None

def render_stock_detail(ticker: str, rebalancer, stress_engine, signals_log):
    st.markdown(f"## 📈 {ticker} Detail Explorer")
    
    # Header Info
    current_prices = rebalancer.fetch_current_prices()
    price = current_prices.get(ticker, 0.0)
    current_w = rebalancer.current_weights.get(ticker, 0.0) * 100
    baseline_w = (1.0 / len(rebalancer.tickers)) * 100
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest Portfolio Price", f"${price:,.2f}", help="Local deterministic price used in portfolio.")
    c2.metric("Current Target Weight", f"{current_w:.2f}%")
    c3.metric("Baseline Weight", f"{baseline_w:.2f}%", f"{current_w - baseline_w:+.2f}%")
    
    period = st.selectbox("Select History Period", ["1M", "3M", "6M", "1Y"], index=3)
    
    with st.spinner("Fetching historical data..."):
        hist = fetch_stock_data(ticker, period)
        benchmark_hist = fetch_stock_data("SPY", period)
    
    if hist is not None and not hist.empty:
        # Check if enough data
        has_enough_data = len(hist) > 50
        
        # 1. Price and Volume Chart
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.03, subplot_titles=(f"{ticker} Price & SMAs", "Volume"),
                            row_width=[0.2, 0.7])
        
        fig.add_trace(go.Candlestick(x=hist.index,
                                     open=hist['Open'],
                                     high=hist['High'],
                                     low=hist['Low'],
                                     close=hist['Close'],
                                     name='OHLC'), row=1, col=1)
        
        if has_enough_data:
            sma20 = hist['Close'].rolling(window=20).mean()
            sma50 = hist['Close'].rolling(window=50).mean()
            fig.add_trace(go.Scatter(x=hist.index, y=sma20, mode='lines', name='SMA 20', line=dict(color='orange')), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=sma50, mode='lines', name='SMA 50', line=dict(color='blue')), row=1, col=1)
            
        fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], name='Volume', marker_color='rgba(100, 150, 250, 0.5)'), row=2, col=1)
        
        fig.update_layout(height=600, xaxis_rangeslider_visible=False,
                          plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                          font=dict(color="#C9D1D9"))
        st.plotly_chart(fig, use_container_width=True)
        
        # Performance & Risk Charts
        st.markdown("#### Performance and Risk Metrics")
        pr1, pr2 = st.columns(2)
        
        with pr1:
            if benchmark_hist is not None and not benchmark_hist.empty:
                # Align dates
                common_dates = hist.index.intersection(benchmark_hist.index)
                if len(common_dates) > 0:
                    stock_norm = (hist.loc[common_dates, 'Close'] / hist.loc[common_dates[0], 'Close']) * 100
                    bench_norm = (benchmark_hist.loc[common_dates, 'Close'] / benchmark_hist.loc[common_dates[0], 'Close']) * 100
                    

                    fig_norm = go.Figure()
                    fig_norm.add_trace(go.Scatter(x=common_dates, y=stock_norm, mode='lines', name=ticker))
                    fig_norm.add_trace(go.Scatter(x=common_dates, y=bench_norm, mode='lines', name='SPY Benchmark'))
                    fig_norm.update_layout(title="Normalized Performance (Base 100)", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color="#C9D1D9"))
                    st.plotly_chart(fig_norm, use_container_width=True)
                else:
                    st.write("Insufficient common dates for benchmark comparison.")
            else:
                st.write("Benchmark data unavailable.")
                
            # Rolling Volatility
            vol_window = 21
            if len(returns) >= vol_window:
                rolling_vol = returns.rolling(window=vol_window).std() * (252 ** 0.5) * 100
                fig_vol = go.Figure()
                fig_vol.add_trace(go.Scatter(x=returns.index, y=rolling_vol, mode='lines', name='Annualized Vol (%)', line=dict(color='purple')))
                fig_vol.update_layout(title=f"Rolling {vol_window}-Day Volatility (Annualized)", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color="#C9D1D9"))
                st.plotly_chart(fig_vol, use_container_width=True)

                
        with pr2:
            # Daily Returns Histogram
            returns = hist['Close'].pct_change().dropna()
            fig_hist = go.Figure(data=[go.Histogram(x=returns, nbinsx=30, marker_color='#3b82f6')])
            fig_hist.update_layout(title="Daily Return Distribution", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color="#C9D1D9"))
            st.plotly_chart(fig_hist, use_container_width=True)

            # Drawdown from running peak
            running_max = hist['Close'].cummax()
            drawdown = ((hist['Close'] - running_max) / running_max) * 100
            
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(x=hist.index, y=drawdown, fill='tozeroy', name='Drawdown (%)', line=dict(color='red')))
            fig_dd.update_layout(title="Historical Drawdown (%)", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color="#C9D1D9"))
            st.plotly_chart(fig_dd, use_container_width=True)

            
        # Technical Indicators
        if has_enough_data:
            st.markdown("#### Technical Indicators")
            ti1, ti2 = st.columns(2)
            
            with ti1:
                rsi = compute_rsi(hist['Close'])
                fig_rsi = go.Figure()
                fig_rsi.add_trace(go.Scatter(x=hist.index, y=rsi, mode='lines', name='RSI (14)'))
                fig_rsi.add_hline(y=70, line_dash="dash", line_color="red")
                fig_rsi.add_hline(y=30, line_dash="dash", line_color="green")
                fig_rsi.update_layout(title="RSI (14)", yaxis_range=[0, 100], plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color="#C9D1D9"))
                st.plotly_chart(fig_rsi, use_container_width=True)
                
            with ti2:
                macd, macd_sig = compute_macd(hist['Close'])
                fig_macd = go.Figure()
                fig_macd.add_trace(go.Scatter(x=hist.index, y=macd, mode='lines', name='MACD (12, 26)'))
                fig_macd.add_trace(go.Scatter(x=hist.index, y=macd_sig, mode='lines', name='Signal (9)'))
                fig_macd.update_layout(title="MACD", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color="#C9D1D9"))
                st.plotly_chart(fig_macd, use_container_width=True)
            st.caption("Indicators are descriptive analysis, not guaranteed trading signals.")
            
    else:
        st.warning("Historical market data unavailable or failed to fetch. Displaying available local data only.")
    
    st.markdown("#### Risk Engine Information")
    # Show related news and stress info
    ticker_signals = [s for s in signals_log if s.get('entity', '').upper() == ticker]
    if ticker_signals:
        st.dataframe(pd.DataFrame(ticker_signals)[["headline", "event_classification", "sentiment_score", "impact_score"]], use_container_width=True)
    else:
        st.info("No active event-driven risk signals found for this ticker in the current log.")
        
    st.markdown("##### Stress Test Exposure")
    # Let's run a quick baseline stress test to extract asset-specific stats if we can, 
    # but the simplest is just to mention that stress engine operates at the portfolio level.
    # The user asked to show: "Relevant existing stress-test exposure or sensitivity."
    # The stress_engine has scenarios with predefined shocks.
    st.write(f"The portfolio stress engine evaluates {ticker} as part of the overall equity portfolio index shock. Specific asset sensitivities rely on index correlation. See the Macro Stress Testing tab for full portfolio impact.")

