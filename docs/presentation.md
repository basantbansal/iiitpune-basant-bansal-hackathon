---
marp: true
theme: default
paginate: true
title: "Event-Driven Financial Risk Intelligence"
author: "Basant Bansal"
style: |
  section {
    font-size: 22px;
    padding: 35px 45px;
  }
  h1 {
    font-size: 32px;
    color: #1e3a8a;
  }
  h2 {
    font-size: 26px;
    color: #2563eb;
  }
  table {
    font-size: 18px;
  }
---

<!-- _paginate: false -->
![bg](assets/title-slide.png)

---

# 1. Problem Statement & Solution Overview

### The Challenge
Financial markets absorb unstructured textual events (earnings releases, geopolitical tensions, credit shocks) before pricing models adjust. Traditional equal-weight or market-cap indices react with significant lag, amplifying drawdowns.

### Our Solution
An end-to-end institutional financial risk intelligence platform:
1. **Dual Live Ingestion**: Live Google News RSS & Yahoo Finance RSS feeds with semantic deduplication.
2. **Explainable AI/NLP Risk Engine**: Groq LLaMA 3.3 70B (JSON mode) + deterministic financial lexicon fallback producing structured `RiskSignal` records.
3. **Module A (Tactical Rebalancer)**: Mean sentiment tilting bounded strictly to $10\% \pm 5\%$ ($[5\%, 15\%]$) with exact trade & fee accounting.
4. **Module B (Stress Engine)**: Multi-factor stress testing across equities & a 14-position Wholesale Banking Book with auto-triggering on high-impact signals.

---

# 2. System Architecture & Dual Ingestion

```
[Google News RSS]   [Yahoo Finance RSS]   [Offline Crisis Replay]
        │                   │                        │
        └─────────────┬─────┴────────────────────────┘
                      ▼
     [Entity Resolver & Semantic Dedup] ──► SQLite Persistence
                      ▼
   [Hybrid NLP: Groq LLM / Finance Lexicon] ──► Structured RiskSignal
                      ▼
        ┌─────────────┴─────────────┐
        ▼                           ▼
[Module A: Rebalancer]     [Module B: Stress Engine]
 (±5 pp Hard Bounds)       (14 Banking Book Positions)
        │                           │
        └─────────────┬─────────────┘
                      ▼
   [FastAPI REST API] ◄──► [React 19 + TypeScript + Vite Dashboard]
```

- **Dual Independent Feeds**: Google News RSS + Yahoo Finance RSS without proprietary vendor lock-in.
- **Enterprise Deduplication**: Cryptographic SHA-256 + 24-hour temporal deduplication window.

---

# 3. Structured NLP Risk Engine

### Hybrid Architecture for High Reliability & Zero Hallucination
- **Primary LLM**: Groq API (`llama-3.3-70b-versatile`) with strict JSON schema and prompt grounding.
- **Deterministic Lexicon Scorer**: Finance-aware dictionary with negation detection, contrastive handling ("despite", "but"), and systemic risk weighting.
- **Abstention Policy**: Ambiguous or single-word matches output `Unclassified / Needs Review` to avoid false triggers.

### Structured Output Schema (`RiskSignal`)
| Field | Domain / Range | Example Output | Purpose |
| :--- | :--- | :--- | :--- |
| `entity` | Monitored ticker | `AAPL` | Constituent entity assignment |
| `sentiment_score` | Float $[-1.0, +1.0]$ | `-0.65` | Tactical weight tilting factor |
| `event_classification`| 8 Taxonomy categories | `Supply Chain / Operations` | Domain classification |
| `impact_score` | Integer $[1, 10]$ | `8` | Tail risk & trigger prioritization |
| `confidence` | Float $[0.0, 1.0]$ | `0.85` | Signal certainty filter |
| `evidence_span` | Snippet from headline | `"cuts component orders"` | Auditable attribution |

---

# 4. Module A: Tactical Index Rebalancer

### Algorithmic Rebalancing with Simplex Constraints
- **Universe**: S&P Top 10 constituents (`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`, `JPM`, `JNJ`, `XOM`) with $10.0\%$ baseline weight.
- **Strict Bounds**: Tracking error bounded to $\text{Baseline} \pm 5\%$ ($[5\%, 15\%]$); simplex constraint $\sum w_i = 1.0$.
- **Neutrality Invariant**: Constituents with no new usable signals strictly preserve baseline weights (absence of news $\neq$ negative sentiment).

### Exact Accounting & Persistent Trajectory
- **Order Reconciliation**:
  $$\text{Post-Trade Shares} = \text{Pre-Trade Shares} + \text{Signed Trade Quantity}$$
  $$\text{Simulated Fees} = \text{Gross Traded Value} \times 10\text{ bps (half-up rounded to \$0.01)}$$
- **Multi-Scan History**: SQLite persistence (`target_weight_history`) tracking weight trajectories over successive rebalance scans.

---

# 5. Module B: Macroeconomic & Credit Stress Testing

### Multi-Asset Wholesale Banking Book (14 Positions)
- **Corporate Loans (4)**: Expected Loss $\Delta \text{EL} = -\text{Notional} \cdot \Delta \text{PD} \cdot \text{LGD}$ plus Credit Spread term.
- **Fixed Income Bonds (4)**: Price Change $= -\text{ModDur} \cdot \Delta \text{Rate} - \text{SpreadDur} \cdot \Delta \text{Spread}$.
- **Interest Rate Swaps (3)**: P&L $= \text{Signed DV01} \cdot \Delta \text{Rate bps}$ (Payer vs Receiver hedges).
- **Equity Holdings (3)**: Factor shock $= \text{Notional} \cdot (\beta \cdot \Delta \text{Equity})$.

### Guaranteed Reconciliation & Auto-Trigger Logic
- **Exact Invariant**: $\text{Post-Shock Value} \equiv \text{Pre-Shock Value} + \sum \text{Position P\&L}$ across all asset classes.
- **Auto-Trigger**: Any signal with $\text{Impact} \ge 7$ auto-recommends a targeted stress scenario:
  - *Macroeconomic* $\rightarrow$ 2022 Fed Tightening Shock
  - *Credit / Geopolitical* $\rightarrow$ Systemic Credit Crunch
  - *Tech / Product* $\rightarrow$ Tech Bubble Burst

---

# 6. Validation, Data Provenance & Domain Impact

### Engineering Rigor & Test Suite
- **Full Test Suite Passing**: Automated pytest verification across risk engine, order accounting, fee rounding, and banking book math.
- **Production Bundle**: Clean TypeScript compilation (`tsc -b`) and Vite production bundle.
- **Zero Secret Leaks**: Verified git history with no API keys or credentials committed.

### Data Provenance Disclosures
- **Live Market News**: Real-time Google News RSS & Yahoo Finance RSS feeds.
- **Synthetic Banking Book**: 14 institutional positions (`data/synthetic_banking_book.json`).
- **Research Benchmark (`data/all-data.csv`)**: Financial PhraseBank dataset (4,846 rows, Latin-1); not required at runtime (runtime uses live feeds + Groq / deterministic rule engine).
- **Domain Impact**: Bridges qualitative news intelligence with quantitative risk management, providing institutional risk officers with auditable, real-time portfolio resilience.
