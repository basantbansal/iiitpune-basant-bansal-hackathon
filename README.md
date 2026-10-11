# AI Financial Risk & Portfolio Intelligence Platform - S&P Global & Crisil Campus Hackathon

- **Candidate Name:** Basant Bansal
- **College Email ID:** 112416017@ece.iiitp.ac.in
- **College / Campus:** Indian Institute of Information Technology, Pune (IIIT Pune)
- **Demo Video Link:** https://www.youtube.com/watch?v=2eu3-yfpeB4
- **Slide Deck Link:** [docs/presentation.pdf](docs/presentation.pdf)

---

## 1. Project Overview / Problem Statement & Approach

### Problem Statement
Traditional equity portfolio management relies heavily on backward-looking indicators such as moving averages, historical covariance estimates, and quarterly financial filings. However, capital markets react rapidly to new information and macro-financial events, making lagging indicators insufficient for proactive risk management.

Conventional indices often rely on equal-weight or cap-weight methodologies without a forward-looking understanding of event-driven risk. This leaves portfolios vulnerable to asymmetric drawdowns, concentrated exposures, and sudden deterioration during systemic crises.

### Our Approach
We developed an institutional-grade, event-driven risk analytics and portfolio intelligence platform combining:
1. **Real-Time Dual-Source Ingestion**: Simultaneously ingests unstructured financial news from Google News RSS and Yahoo Finance RSS, with publisher attribution, timestamp parsing, and cryptographic deduplication to minimize noise and duplicate reporting.
2. **Explainable Hybrid NLP Risk Engine**: Uses an ultra-fast Groq LLaMA 3.3 70B model in structured JSON mode with deterministic finance-aware fallback rules when cloud inference is unavailable or an API key is not configured.
3. **Module A — Tactical Index Rebalancer**: Applies alpha tilts to a 10-constituent mega-cap universe with a $2,000,000 baseline AUM and strict tracking-error constraints.
4. **Module B — Macro & Credit Stress Testing Engine**: Evaluates portfolio resilience across historical and hypothetical macro scenarios, including Fed tightening shocks, systemic credit crunches, and technology-driven drawdowns.

> **Regulatory Disclaimer:** This application is an academic prototype developed exclusively for the S&P Global & CRISIL Campus Hackathon 2026 for demonstration and architectural evaluation. It is intended for educational and research use only.

---

## 2. Architecture & Tech Stack

![System Architecture](docs/architecture.png)

### Architecture Highlights
The platform follows a clean separation of concerns across six decoupled layers:
- **Data Ingestion Layer**: Asynchronous fetching from Google News RSS and Yahoo Finance RSS with publisher attribution and timestamp parsing.
- **Preprocessing & Deduplication Layer**: Cryptographic SHA-256 fingerprinting (`ticker:headline`), a 24-hour temporal deduplication window, and institutional disclosure filtering to retain usable event signals.
- **Hybrid NLP Risk Layer**: Primary cloud inference via Groq LLaMA 3.3 70B with prompt grounding; deterministic finance-aware rule-based fallback with grammar negation handling for resilience and explainability.
- **Persistence & Audit Trail Layer**: Single-file SQLite database (`data/risk_data.db`) storing `risk_signals`, `documents`, `configuration`, `holdings`, and `target_weight_history`.
- **Downstream Financial Modules**:
  - *Module A*: Constrained quadratic/linear rebalancing with simplex renormalization and share order accounting.
  - *Module B*: Multi-asset wholesale banking book stress engine with factor sensitivity channels (Beta, Modified Duration, Spread Duration, Signed DV01, and Expected Loss).
- **Presentation Layer**: High-performance FastAPI backend (Python 3.14) paired with a modern React 19 + TypeScript + Vite + Tailwind CSS + Recharts dashboard.

### Tech Stack
| Component | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Backend Framework** | FastAPI / Uvicorn | 0.115+ | High-throughput asynchronous REST API |
| **Language** | Python | 3.14 | Core risk engine, optimization & stress math |
| **Primary LLM** | Groq LLaMA 3.3 70B | `llama-3.3-70b-versatile` | Low-latency JSON structured entity extraction |
| **Persistence** | SQLite3 | 3.x | Lightweight, zero-configuration local ACID audit storage |
| **Frontend Framework** | React / TypeScript | React 19, TS 5.x | Reactive trader dashboard & risk control panel |
| **Build Tooling** | Vite | 6.x | Instant HMR and optimized production bundle |
| **Charting Library** | Recharts | 2.15+ | Responsive allocation deltas, drawdown & trajectory charts |
| **Styling** | Tailwind CSS | 3.4+ | Institutional dark-mode financial UI |
| **Testing** | Pytest / AnyIO | Pytest 9.x | Comprehensive unit and integration regression suite |

### Model Selection and Engineering Constraints

FinBERT was evaluated as a potential sentiment model for financial text analysis. However, due to limited internet bandwidth and the practical difficulty of downloading large PyTorch model dependencies within the available development window, direct FinBERT integration was not feasible in this iteration.

Instead, the project uses a hybrid approach: **Groq-hosted LLaMA 3.3 70B** for structured financial news analysis, paired with a deterministic, finance-aware rule-based fallback when the API is unavailable or no API key is configured. This keeps the prototype demonstrable and robust without requiring a large local model download.

This design balances **operational reliability**, **explainability**, and **deployment simplicity** during a time-constrained hackathon environment. It also ensures the system remains functional in offline or low-connectivity scenarios without any proprietary dependency on external APIs.

**Future improvement:** Integrate and benchmark FinBERT against the existing pipeline on a labeled financial sentiment dataset, comparing sentiment accuracy, inference latency, and resource requirements before selecting the production model. This will help determine whether a local transformer-based model is worth adopting for long-term deployment or whether the hybrid cloud-plus-rule approach remains the stronger operational choice.

---

## 3. Dataset Used

All prototype datasets reside in the `data/` directory. Their contents, formats, and provenance disclosures are detailed below:

| File Name | Format & Size | Description & Schema | Runtime Usage & Provenance |
| :--- | :--- | :--- | :--- |
| `data/synthetic_banking_book.json` | JSON (14 records, 3.6 KB) | 14 institutional wholesale banking positions across Corporate Loans (4), Fixed Income Bonds (4), Interest Rate Swaps (3), and Equities (3). | **Runtime (Stress Module)**: Used for multi-asset portfolio and credit scenario evaluation. |
| `data/synthetic_demo_data.csv` | CSV (36 rows, 2.7 KB) | Pre-curated crisis news headlines across all 10 monitored constituents with sentiment, impact, and evidence labels. | **Runtime (Offline Mode)**: Demo inference and validation data. |
| `data/sample_news.json` | JSON (10 records, 2.1 KB) | Multi-constituent sample news headlines for quickstart verification. | **Runtime (Replay Fallback)**: Initial baseline seed for testing and demos. |
| `data/synthetic_credit_portfolio.json` | JSON (5 records, 796 B) | Illustrative regulatory banking credit exposures (EAD, PD, LGD, Risk Weight). | **Module B Validation**: Baseline credit-risk stress scenario inputs. |
| `data/reference_prices.json` | JSON (3 records, 265 B) | Offline market reference prices for fallback execution. | **Fallback Pricing**: Used when live Yahoo Finance ticker pricing is unreachable. |
| `data/historical_backtest.csv` | CSV (12 rows, 1.3 KB) | Historical monthly return and turnover backtest validation dataset. | **Validation**: Backtest validation script inputs. |
| `data/all-data.csv` | CSV (4,846 rows, 672 KB, Latin-1) | Standard Financial PhraseBank benchmark dataset (`[sentiment, text]`, Malo et al., 2014). | **Research Reference Only**: Used as a benchmark and comparison reference. |

---

## 4. Quickstart & Installation

### Running Locally on VSCode

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Node.js 18+ and npm
- Optional: Groq Cloud API Key (`GROQ_API_KEY`) for LLaMA 3.3 70B cloud inference (falls back gracefully to deterministic rule engine if unset)

### 1. Clone the Repository
```bash
git clone https://github.com/basantbansal/iiitpune-basant-bansal-hackathon.git
cd iiitpune-basant-bansal-hackathon
```

### 2. Backend Setup
```bash
# Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip

# Install backend dependencies
pip install -r requirements.txt

# (Optional) Configure environment variables
cp .env.example .env
# Edit .env to set GROQ_API_KEY if desired
```

### 3. Frontend Setup
```bash
cd src/frontend
npm install
npm run build   # Verifies TypeScript compilation and creates production bundle
cd ../..
```

### 4. Running the Application
Open two terminal windows:

**Terminal 1 — Backend (FastAPI):**
```bash
source venv/bin/activate
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend (Vite):**
```bash
cd src/frontend
npm run dev
```

Open your browser at **`http://localhost:5173`**. The backend API documentation is accessible at **`http://localhost:8000/docs`**.

### 5. Running Automated Tests
```bash
# Run complete automated pytest regression suite
pytest tests/ -v
```

---

## 5. Key Results & Domain Impact

### Key Technical Results
1. **Mathematical Invariant Guarantees**:
   - **Absence of News Is Not Negative Sentiment**: Constituents with no new usable signals strictly preserve their `10.0%` baseline weight.
   - **Strict Hard Bounds**: Target allocations are strictly bounded to `[5.0%, 15.0%]` (Baseline ± 5 percentage points) with simplex renormalization (`sum of weights = 1.0`).
   - **Execution Reconciliation**: **Post-Trade Shares = Pre-Trade Shares + Signed Order Qty**.
   - **Transparent Fee Accounting**: 10 bps applied to gross traded volume using standard financial half-up rounding (`$88,445 × 0.0010 = $88.45`).
   - **Stress Testing Balance Invariant**: **Post-Shock Value = Pre-Shock Value + Total Position-Level P&L** verified across all asset classes and scenarios.
2. **Multi-Asset Wholesale Banking Book**:
   - Evaluates 14 positions across Corporate Loans (ECL + spread), Fixed Income Bonds (duration + spread), Interest Rate Swaps (DV01), and Equities (Beta).
   - Provides an auditable by-asset-class summary table directly on the user interface.
3. **High-Impact Trigger Logic**:
   - Automatically detects signals with `Impact >= 7` and arms targeted macro scenarios (Macro -> Fed Tightening Shock; Credit/Geopolitical -> Systemic Credit Crunch; Tech -> Tech Bubble Burst) with scenario-specific risk overlays.
4. **Persistent Weight Trajectory Over Scans**:
   - Stores each scan's constituent weights in SQLite (`target_weight_history`) and renders a real-time multi-scan trajectory line chart in the trader dashboard.
5. **Zero Secret Leaks & Comprehensive Test Pass Rate**:
   - Clean git history with zero API keys or private tokens committed.
   - Over 160 automated tests passing with zero failures.

### Domain & Business Impact
- **Institutional Agility**: Bridges qualitative unstructured newsflow with quantitative portfolio management, enabling asset managers to react to systemic risks within seconds rather than waiting for quarterly filings or lagging indicators.
- **Explainable & Auditable**: Every allocation tilt and stress drawdown is attributed to exact evidence snippets, calibrated confidence, and transparent factor sensitivities, improving trust and governance.
- **Operational Resilience**: Operates seamlessly in live dual-source market conditions or offline crisis environments without proprietary API dependencies.

---

## 6. Additional Notes

This project was built as an academic-grade prototype for the S&P Global & CRISIL Campus Hackathon, with a focus on building a usable risk intelligence workflow, a transparent decision engine, and a portfolio dashboard that combines modern web tooling with financial domain reasoning.
