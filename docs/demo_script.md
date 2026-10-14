# Five-Minute Demonstration Script

## 1. Introduction (0:00 - 0:45)
**What to say:** "Hello, I'm presenting the S&P Global & CRISIL Financial Risk Engine. Our objective is to rapidly convert unstructured financial text into structured, actionable risk signals, and demonstrate how those signals dynamically alter portfolio allocations and stress test results. This prototype operates fully offline to guarantee reliability during the evaluation."
**What to click:** Open the dashboard. Ensure the sidebar is set to **"Offline Crisis Replay"**.
**What to point out:** Point to the top KPIs (Portfolio Value, Largest Target Allocation, Total Value Traded to Rebalance). Mention that we start with a clean equal-weight portfolio.

## 2. Risk Engine & Ingestion (0:45 - 2:15)
**What to click:** Look at the "News & Risk Signals" section.
**What to say:** "We ingest news and run it through our NLP engine. We considered FinBERT, but to ensure high offline reliability and low latency on standard hardware, we engineered a deterministic fallback using TF-IDF + Logistic Regression alongside regex heuristics. If a Groq API key is present, it will use an LLM, but here we demonstrate the robust fallback."
**What to point out:**
- The *Event* column showing classifications like "Macroeconomic", "Product Launch", or "Credit Event".
- The *Heuristic Score* (explaining this is our confidence model).
- The *Sentiment* column (ranging -1.0 to 1.0).
**Meaning to a non-trader:** "Instead of humans reading the news, the engine reads it, determines if it's good or bad, and grades the impact severity."

## 3. Module A: Tactical Index Rebalancer (2:15 - 3:30)
**What to click:** Scroll to the "Execution Ledger (Module A)" table.
**What to say:** "Once the signals are generated, the rebalancer shifts capital. It penalizes severe macroeconomic and credit events heavily. It mathematically guarantees that our new weights sum to 100% and respect our risk limits."
**What to point out:**
- The *Delta* column showing which assets were up-weighted or down-weighted.
- The *Action* and *Order Qty* columns showing the exact BUY/SELL orders.
- The *Estimated Trading Costs* KPI at the top.
**Meaning to a non-trader:** "This is the 'so what?' of the application. It automatically calculates exactly how many shares to buy or sell to protect the portfolio based on the news, factoring in trading costs."

## 4. Module B: Strategic Stress Testing (3:30 - 4:30)
**What to click:** Switch to the **Stress Testing** tab. Select the "2022 Fed Tightening Shock" scenario. Click **"Run Simulation"**.
**What to say:** "Beyond reactive trading, we proactively stress test. This module applies macroeconomic shocks—like severe interest rate hikes—to our specific portfolio allocation."
**What to point out:**
- The *Estimated Drawdown* showing both dollar value and percentage loss.
- The bar chart showing which assets lost the most.
**Meaning to a non-trader:** "If a major crisis hits tomorrow, this tells us exactly how much money we stand to lose, helping risk managers prepare today."

## 5. Limitations & Conclusion (4:30 - 5:00)
**What to say:** "To be fully transparent, this is a prototype.
- The replay data is deterministic for reproducibility, not live market data.
- The first-order Modified Duration used in stress testing is an approximation and doesn't capture complex non-linear convexity.
- The synthetic credit portfolio uses illustrative risk weights.
Despite these hackathon constraints, this architecture demonstrates a complete, auditable pipeline from raw text to institutional risk mitigation."
