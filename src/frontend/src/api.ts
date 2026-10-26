const API_BASE = "/api";

export const api = {
  getHealth: () => fetch(`${API_BASE}/health`, { cache: "no-store" }).then(r => r.json()),
  getHealthDetails: () => fetch(`${API_BASE}/health?details=true`, { cache: "no-store" }).then(r => r.json()),
  
  getConfig: () => fetch(`${API_BASE}/config`, { cache: "no-store" }).then(r => r.json()),
  
  getPortfolio: (currency?: string) => fetch(`${API_BASE}/portfolio${currency ? `?currency=${currency}` : ''}`, { cache: "no-store" }).then(r => r.json()),
  
  getPortfolioMetrics: (currency?: string) => fetch(`${API_BASE}/portfolio/metrics${currency ? `?currency=${currency}` : ''}`, { cache: "no-store" }).then(r => r.json()),
  
  getStocks: () => fetch(`${API_BASE}/stocks`, { cache: "no-store" }).then(r => r.json()),
  
  getStockDetails: (ticker: string) => fetch(`${API_BASE}/stocks/${ticker}/details`, { cache: "no-store" }).then(r => r.json()),
  
  getStockHistory: (ticker: string, period: string = "1Y") => fetch(`${API_BASE}/stocks/${ticker}/history?period=${period}`, { cache: "no-store" }).then(r => r.json()),
  
  getRiskSignals: () => fetch(`${API_BASE}/risk-signals`, { cache: "no-store" }).then(r => r.json()),
  
  scanMarket: () => fetch(`${API_BASE}/market-scan`, { method: "POST", cache: "no-store" }).then(r => r.json()),
  
  getMarketScanCoverage: () => fetch(`${API_BASE}/market-scan/coverage`, { cache: "no-store" }).then(r => r.json()),
  
  getStressScenarios: () => fetch(`${API_BASE}/stress-scenarios`, { cache: "no-store" }).then(r => r.json()),
  
  runStressTest: (scenario_name: string) => fetch(`${API_BASE}/stress-test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_name }),
    cache: "no-store"
  }).then(r => r.json()),

  getPortfolioHistory: () => fetch(`${API_BASE}/portfolio/history`, { cache: "no-store" }).then(r => r.json()),

  getStressTrigger: () => fetch(`${API_BASE}/stress-trigger`, { cache: "no-store" }).then(r => r.json()),
  
  updateConfig: (config: any) => fetch(`${API_BASE}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    cache: "no-store"
  }).then(r => r.json()),
  
  resetData: () => fetch(`${API_BASE}/reset`, { method: "POST", cache: "no-store" }).then(r => r.json()),

  updateHoldings: (holdings: Record<string, number>) => fetch(`${API_BASE}/portfolio/holdings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ holdings }),
    cache: "no-store"
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: "Failed to update holdings" }));
      throw new Error(err.detail || "Failed to update holdings");
    }
    return r.json();
  }),

  resetHoldings: () => fetch(`${API_BASE}/portfolio/reset-holdings`, {
    method: "POST",
    cache: "no-store"
  }).then(r => r.json()),

  getUniverse: (): Promise<UniverseInstrument[]> =>
    fetch(`${API_BASE}/universe`, { cache: "no-store" }).then(async r => {
      if (!r.ok) throw new Error("Failed to load catalog universe");
      return r.json();
    }),

  getUniverseSelection: (): Promise<UniverseSelectionResponse> =>
    fetch(`${API_BASE}/universe/selection`, { cache: "no-store" }).then(async r => {
      if (!r.ok) throw new Error("Failed to load universe selection");
      return r.json();
    }),

  updateUniverseSelection: (selection: string[]): Promise<any> =>
    fetch(`${API_BASE}/universe/selection`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selection }),
      cache: "no-store"
    }).then(async r => {
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: "Failed to update universe selection" }));
        throw new Error(err.detail || "Failed to update universe selection");
      }
      return r.json();
    }),

  getFxRate: () => fetch(`${API_BASE}/fx/rate`, { cache: "no-store" }).then(r => r.json()),

  convertFx: (req: { from_currency: string; to_currency: string; amount: number; notes?: string }) =>
    fetch(`${API_BASE}/portfolio/convert-fx`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      cache: "no-store"
    }).then(async r => {
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: "FX conversion failed" }));
        throw new Error(err.detail || "FX conversion failed");
      }
      return r.json();
    }),

  getFxConversions: () => fetch(`${API_BASE}/portfolio/fx-conversions`, { cache: "no-store" }).then(r => r.json()),

  allocateCapital: (req: { usd_ratio?: number; inr_ratio?: number; usd_amount?: number; inr_amount_usd?: number }) =>
    fetch(`${API_BASE}/portfolio/allocate-capital`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      cache: "no-store"
    }).then(async r => {
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: "Capital allocation failed" }));
        throw new Error(err.detail || "Capital allocation failed");
      }
      return r.json();
    }),

  getReportingCurrency: () => fetch(`${API_BASE}/reporting-currency`, { cache: "no-store" }).then(r => r.json()),

  setReportingCurrency: (currency: string) => fetch(`${API_BASE}/reporting-currency`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ currency }),
    cache: "no-store"
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: "Failed to update reporting currency" }));
      throw new Error(err.detail || "Failed to update reporting currency");
    }
    return r.json();
  }),
};

export interface UniverseInstrument {
  id: string;
  name: string;
  display_ticker: string;
  market: 'US' | 'IN' | string;
  exchange: string;
  provider_symbol: string;
  currency: 'USD' | 'INR' | string;
  sector: string;
  aliases?: string[];
}

export interface UniverseSelectionResponse {
  selection: string[];
  default_selection: string[];
  selected_instruments: UniverseInstrument[];
  default_instruments: UniverseInstrument[];
}
