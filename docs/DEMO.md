# 5-Minute Demonstration Script — S&P Global & CRISIL Campus Hackathon

**Candidate Name:** Basant Bansal  
**College / Campus:** Indian Institute of Information Technology, Pune (IIIT Pune)  
**Demo Video Link:** [Demo Video Link]  
**Slide Deck:** [docs/presentation.pdf](docs/presentation.pdf)  
**Total Target Duration:** 4:45 – 5:00 Minutes  
**Application Stack:** FastAPI Backend (`http://localhost:8000`) + React 19 / TypeScript / Vite Dashboard (`http://localhost:5173`)  

---

## Demo Timing & Walkthrough Plan

| Timeline | Phase / Section | Screen / Component | Core Talking Points |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:45** | **1. Overview & Baseline State** | Dashboard Overview Tab | Platform purpose, S&P 10 universe, baseline equal weights ($2M AUM). |
| **0:45 – 1:45** | **2. Dual Ingestion & Deduplication** | Active Risk Signals Tab | Google News RSS + Yahoo Finance RSS, SHA-256 + 24h dedup, offline replay. |
| **1:45 – 2:45** | **3. Hybrid NLP Risk Engine** | Signals Table & Stock Detail | Groq LLaMA 3.3 70B + deterministic finance lexicon fallback, structured schema. |
| **2:45 – 3:45** | **4. Module A: Tactical Rebalancer** | Portfolio Allocation Tab | Bounded alpha tilt (±5 pp), absence of news invariant, fees, multi-scan chart. |
| **3:45 – 4:45** | **5. Module B: Stress Testing Engine** | Macro Stress Testing Tab | High-impact auto-trigger banner, wholesale banking book (14 positions), invariant. |
| **4:45 – 5:00** | **6. Engineering Rigor & Conclusion** | Terminal / Status Badge | Full test suite passing, production build, zero leaks, honest disclosures. |

---

## Detailed Step-by-Step Script

### Segment 1: Introduction & Baseline Architecture (0:00 – 0:45)
- **Visual:** Open browser at `http://localhost:5173`. Show the initial Dashboard screen.
- **Presenter:**
  > "Hello everyone. I am Basant Bansal from IIIT Pune, presenting our AI Financial Risk & Portfolio Intelligence Platform for the S&P Global & CRISIL Campus Hackathon 2026.
  > In volatile financial markets, textual events like regulatory investigations, supply disruptions, and interest rate hikes hit newsfeeds long before asset prices fully adjust.
  > Our platform bridges this gap by combining real-time dual-source news ingestion, structured hybrid AI/NLP event extraction, and two downstream financial applications: Module A, an institutional tactical index rebalancer, and Module B, a multi-asset wholesale banking book stress-testing engine.
  > Looking at the baseline dashboard: we manage a $2,000,000 portfolio invested across the top 10 S&P mega-cap constituents, equally weighted at 10.0% each with zero initial transaction fees."

---

### Segment 2: Dual-Source Ingestion & Enterprise Deduplication (0:45 – 1:45)
- **Visual:** Click **"Execute Market Scan"** (or switch between Live Mode and Offline Crisis Replay in Settings).
- **Presenter:**
  > "When we trigger a market scan, the pipeline ingests text simultaneously from two independent live sources:
  > 1. **Google News Financial RSS** for broad macroeconomic and publisher headlines.
  > 2. **Yahoo Finance Constituent RSS** for direct, ticker-specific corporate actions.
  > For guaranteed evaluation even in zero-network environments, our offline mode replays crisis datasets through the exact same pipeline contract.
  > Before text reaches the models, our preprocessing layer computes cryptographic SHA-256 hashes with a 24-hour temporal deduplication window to prevent double-counting. We also filter backward-looking institutional 13-F filings and discard stale articles older than 7 days."

---

### Segment 3: Hybrid NLP Risk Scoring Engine (1:45 – 2:45)
- **Visual:** Navigate to the **"Active Risk Signals"** tab. Click a headline to show evidence span and direction badge.
- **Presenter:**
  > "Each unique article is scored into a strictly typed `RiskSignal` contract.
  > We implement a dual-engine hybrid architecture:
  > - When configured with a Groq API key, it orchestrates LLaMA-3.3-70B using strict JSON mode for prompt-grounded, zero-shot entity extraction with sub-second latency.
  > - When offline or unconfigured, it seamlessly switches to our deterministic finance-aware lexicon rule engine. Unlike simple keyword matching, our fallback evaluates context negation (such as 'not guilty' or 'refuses bankruptcy') and contrastive clauses ('revenue beat but guidance cut').
  > Ambiguous signals abstain as 'Needs Review' rather than fabricating confidence. Every signal outputs an entity ticker, sentiment score clamped strictly between -1.0 and +1.0, an event classification from 8 financial taxonomies, an impact score from 1 to 10, confidence, and an auditable evidence span snippet."

---

### Segment 4: Module A — Tactical Index Rebalancing (2:45 – 3:45)
- **Visual:** Navigate to the **"Portfolio Allocation"** tab. Point out the Weight Distribution bar chart, the Multi-Scan Trajectory chart, and the Trader Execution View.
- **Presenter:**
  > "With structured signals in hand, Module A computes tactical active tilts.
  > We enforce fundamental institutional safety rules:
  > - First: Absence of news is NOT negative sentiment. Constituents without new signals strictly retain their 10.0% baseline weight.
  > - Second: Hard tracking error bounds. Constituent target weights are strictly bounded to Baseline ± 5 percentage points (between 5.0% and 15.0%), and renormalized to satisfy the simplex sum constraint of 1.0.
  > In the simulated order ledger below, every order satisfies exact share reconciliation: Post-Trade Shares equal Pre-Trade Shares plus Signed Order Quantity. Simulated broker transaction costs are deducted honestly at 10 bps using standard currency half-up rounding.
  > Additionally, our new Multi-Scan Trajectory chart visualizes constituent weights dynamically across successive market scans, stored persistently in SQLite."

---

### Segment 5: Module B — Multi-Asset Wholesale Banking Book Stress Testing (3:45 – 4:45)
- **Visual:** Navigate to the **"Macro Stress Testing"** tab. Show the High-Impact Trigger Banner and the By-Asset-Class summary table.
- **Presenter:**
  > "Moving to Module B: risk managers must evaluate portfolio resilience against severe tail-risk events.
  > Notice the top banner: whenever the risk engine identifies an event with Impact Score ≥ 7, it auto-arms a targeted stress scenario—such as macroeconomic rate hikes mapping to the 2022 Fed Tightening shock, or credit events mapping to a systemic credit crunch.
  > Here we evaluate a synthetic Wholesale Banking Book containing 14 institutional positions across four asset classes:
  > 1. Corporate Loans: modeled via Expected Loss ($\Delta \text{PD} \times \text{LGD}$) and credit spread duration.
  > 2. Fixed Income Bonds: modeled via modified duration and spread duration.
  > 3. Interest Rate Swaps: modeled via signed DV01 per basis point.
  > 4. Equity Holdings: modeled via market Beta.
  > Our By-Asset-Class summary table verifies the fundamental mathematical invariant: Post-Shock Valuation strictly equals Pre-Shock Valuation plus the algebraic sum of all position P&Ls."

---

### Segment 6: Engineering Rigor, Data Provenance & Conclusion (4:45 – 5:00)
- **Visual:** Return to Dashboard overview or terminal status.
- **Presenter:**
  > "To conclude, our platform delivers complete engineering rigor:
  > - Over 160 automated unit and integration tests passing with 100% success.
  > - Clean TypeScript compilation and Vite production bundle.
  > - Verified git hygiene with zero API keys or secrets committed.
  > - Transparent provenance: live feeds are public, synthetic positions are clearly documented as illustrative proxies, and research benchmarks are honestly disclosed.
  > Thank you for your time and consideration."

---

## Offline Crisis Replay Demonstration Guide
If presenting in an offline environment or experiencing internet latency:
1. Open the **Settings & Configuration** modal (or header toggle).
2. Switch **Data Mode** from `Live Market Mode` to `Offline Crisis Replay`.
3. Click **"⚡ Execute Market Scan"**.
4. The system will ingest the curated deterministic crisis news corpus (`data/synthetic_demo_data.csv` and `data/sample_news.json`), generate identical structured signals, execute rebalancing within bounded constraints, and trigger the macroeconomic stress testing engine without requiring internet connectivity.
