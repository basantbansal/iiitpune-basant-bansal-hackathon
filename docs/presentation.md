---
marp: true
theme: default
paginate: true
---

# Financial Risk Engine
**S&P Global & CRISIL Campus Hackathon 2026**
**Candidate:** Basant Bansal
**Campus:** IIIT Pune

---

# 2. Problem and Approach
**The Challenge:**
Modern markets react to unstructured events faster than price tickers update. Traditional portfolio management often relies on lagging indicators, exposing portfolios to unseen risks.

**Our Approach:**
Build an event-driven risk-intelligence prototype that:
1. Ingests financial news in real-time.
2. Quantifies sentiment and calculates a heuristic risk score.
3. Dynamically rebalances a stock index based on real-time news constraints.
4. Stress tests portfolios across both trading and banking books.

---

# 3. System Architecture
**Data Sources:** Google News RSS + Synthetic Social Feeds
**Ingestion & Deduplication:** SQLite backend with hash-based entity resolution
**Core Engine:**
- **Risk NLP:** TF-IDF + Logistic Regression fallback generating quantifiable signals.
- **Module A:** Tactical Index Rebalancer (Constraint-based tilting).
- **Module B:** Stress Testing Engine (Macro sensitivities and Credit impacts).
**Presentation:** Streamlit + Plotly Dashboard

---

# 4. Data Sources and NLP Design
- **Engineering Trade-off (FinBERT vs. TF-IDF):** We considered FinBERT for domain-aware sentiment. However, due to large model sizes, memory constraints, and the need for reliable offline hackathon execution, we deliberately selected a lightweight **TF-IDF + Logistic Regression** model.
- **Social Media Limitations:** The fallback model is trained on formal financial news (`all-data.csv`). Social media text (slang/hashtags) is ingested but processed through this news-trained model; dedicated social preprocessing is a future iteration.
- **Source Provenance:** Strict delineation between live feeds (RSS/Social) and Offline Replay data, with accurate taxonomy deduplication preventing duplicate rebalancing.

---

# 5. Demonstration Results
**Working Validations:**
- Offline Crisis Replay successfully mocks historical shocks, generating immediate target allocation updates.
- Auto-triggered stress charts dynamically display when severe impact signals are detected (Impact > 7).
- Both primary Google RSS and secondary Synthetic Social data are demonstrably processed and uniquely tracked.
*Note: Outcomes rely on prototype algorithms and do not represent verified financial alpha.*

---

# 6. Domain Impact
- **Event-Driven Resilience:** Directly integrates unstructured NLP to mitigate risk faster than waiting for standard moving average crossovers.
- **Holistic View:** The dual inclusion of Trading Book (Equities) and Banking Book (Synthetic Credit Loans) demonstrates cross-asset maturity.
- **Auditability:** Transparent attribution trails (e.g. knowing whether a signal came from an LLM or Keyword Heuristic) are critical for regulatory compliance in modern fintech.

---

# 7. Limitations and Next Steps
- **Current Limitations:**
  - Heuristic score is not a calibrated statistical probability.
  - Stress approximations use first-order linear models and lack convexity.
  - Market liquidity impacts are assumed constant.
- **Next Steps:**
  - Introduce calibrated confidence scores via historical backtesting.
  - Implement full non-linear pricing models for complex credit derivatives.
  - Expand ingestion beyond top 10 tickers to universe-wide scans.
