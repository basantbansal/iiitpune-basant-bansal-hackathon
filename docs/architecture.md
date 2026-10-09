# System Architecture

```mermaid
flowchart TD
    subgraph Data Sources
        RSS(Google News RSS)
        Social(Synthetic Social Data)
        Replay(Local JSON Replay)
    end

    subgraph Core Engine
        Ingest(Ingestion Module)
        Store[(SQLite Deduplication DB)]
        NLP(Risk Engine / NLP)
        Rebalance(Index Rebalancer - Module A)
        Stress(Stress Testing Engine - Module B)
    end

    subgraph UI
        Dash(Streamlit Dashboard)
    end

    RSS --> Ingest
    Social --> Ingest
    Replay -. Offline Mode .-> Ingest

    Ingest --> Store
    Store --> NLP

    NLP -- "Event Sentiments & Confidence" --> Rebalance
    NLP -- "Shock Parameters" --> Stress

    Rebalance -- "Target Portfolio Weights" --> Dash
    Stress -- "Trading & Banking Book Capital Impact" --> Dash
```

This diagram illustrates the separation of concerns between data ingestion, semantic event tracking, algorithmic portfolio rebalancing (Module A), and stress testing (Module B).
