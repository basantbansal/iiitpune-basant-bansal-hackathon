from typing import List, Dict
from src.engine.schemas import CreditExposure, CreditStressResult
import pandas as pd

class StressEngine:
    """
    Module B: Macroeconomic Stress Testing Engine.
    Applies synthetic shocks to the portfolio using cross-asset sensitivities.
    Formula: P&L = (Equity Beta * Equity Shock) - (Rate DV01 * Rate Shock) - (Spread DV01 * Spread Shock)
    """
    def __init__(self):
        # Institutional Risk Profiles for the 10-stock universe
        # rate_dv01 and spread_dv01 represent the % change in asset price per 100bps move
        self.asset_profiles = {
            "AAPL":  {"beta": 1.2, "rate_dv01": 2.5, "spread_dv01": 1.5},
            "MSFT":  {"beta": 1.1, "rate_dv01": 2.0, "spread_dv01": 1.0},
            "NVDA":  {"beta": 2.2, "rate_dv01": 4.5, "spread_dv01": 2.0}, # High growth, high rate sensitivity
            "AMZN":  {"beta": 1.5, "rate_dv01": 3.0, "spread_dv01": 2.0},
            "GOOGL": {"beta": 1.1, "rate_dv01": 2.0, "spread_dv01": 1.0},
            "META":  {"beta": 1.4, "rate_dv01": 2.5, "spread_dv01": 1.5},
            "TSLA":  {"beta": 2.4, "rate_dv01": 5.0, "spread_dv01": 3.0},
            "JPM":   {"beta": 1.0, "rate_dv01": -3.0, "spread_dv01": 4.0}, # Banks benefit from rate hikes (negative DV01)
            "JNJ":   {"beta": 0.5, "rate_dv01": 1.0, "spread_dv01": 0.5},  # Defensive
            "XOM":   {"beta": 0.8, "rate_dv01": 0.5, "spread_dv01": 1.0},  # Value/Commodity
        }
        
        # Predefined Macro Scenarios
        self.scenarios = {
            "1. 2022 Fed Tightening Shock": {
                "equity_shock": -0.15, "rate_shock_bps": 150, "spread_shock_bps": 50,
                "desc": "Aggressive rate hikes crush growth multiples."
            },
            "2. Systemic Credit Crunch": {
                "equity_shock": -0.20, "rate_shock_bps": -50, "spread_shock_bps": 250,
                "desc": "Liquidity dries up. Flight to safety drops rates, but spreads blow out."
            },
            "3. Tech Bubble Burst": {
                "equity_shock": -0.30, "rate_shock_bps": -25, "spread_shock_bps": 25,
                "desc": "Severe tech selloff. Defensive assets outperform."
            }
        }

    def run_scenario(self, current_weights: dict, total_aum: float, scenario_name: str) -> pd.DataFrame:
        if scenario_name not in self.scenarios:
            raise ValueError("Scenario not found.")
            
        shock = self.scenarios[scenario_name]
        results = []
        
        for ticker, weight in current_weights.items():
            profile = self.asset_profiles.get(ticker, {"beta": 1.0, "rate_dv01": 1.0, "spread_dv01": 1.0})
            notional = total_aum * weight
            
            # P&L Math
            equity_pnL = notional * (profile["beta"] * shock["equity_shock"])
            rate_pnl = notional * (-profile["rate_dv01"] * (shock["rate_shock_bps"] / 10000.0))
            spread_pnl = notional * (-profile["spread_dv01"] * (shock["spread_shock_bps"] / 10000.0))
            
            total_pnl = equity_pnL + rate_pnl + spread_pnl
            stress_value = notional + total_pnl
            
            results.append({
                "Ticker": ticker,
                "Base Exposure": notional,
                "Equity P&L": equity_pnL,
                "Rate P&L": rate_pnl,
                "Spread P&L": spread_pnl,
                "Total P&L": total_pnl,
                "Stressed Value": stress_value,
                "Drawdown (%)": (total_pnl / notional) * 100 if notional > 0 else 0
            })
            
        return pd.DataFrame(results)

    def apply_credit_stress(
        self,
        exposures: List[CreditExposure],
        pd_multiplier: float,
        lgd_multiplier: float,
        initial_cet1_capital: float,
        exposure_multiplier: float = 1.0
    ) -> List[CreditStressResult]:
        """
        Applies a deterministic credit stress scenario.
        ECL = PD * LGD * EAD
        RWA = EAD * risk_weight
        CET1 Impact = Stressed ECL / Initial CET1 Capital
        """
        if initial_cet1_capital <= 0:
            raise ValueError("Initial CET1 capital must be positive.")
        if pd_multiplier < 0 or lgd_multiplier < 0 or exposure_multiplier < 0:
            raise ValueError("Multipliers cannot be negative.")

        results = []
        for exp in exposures:
            baseline_ecl = exp.pd * exp.lgd * exp.ead

            # Stressed parameters (probabilities capped at 1.0)
            stressed_pd = min(1.0, exp.pd * pd_multiplier)
            stressed_lgd = min(1.0, exp.lgd * lgd_multiplier)
            stressed_ead = exp.ead * exposure_multiplier

            stressed_ecl = stressed_pd * stressed_lgd * stressed_ead
            incremental_ecl = stressed_ecl - baseline_ecl

            # RWA approximation
            rwa = stressed_ead * exp.risk_weight

            # CET1 impact
            cet1_impact = stressed_ecl / initial_cet1_capital

            results.append(CreditStressResult(
                identifier=exp.identifier,
                baseline_pd=exp.pd,
                stressed_pd=stressed_pd,
                baseline_lgd=exp.lgd,
                stressed_lgd=stressed_lgd,
                ead=stressed_ead,
                risk_weight=exp.risk_weight,
                baseline_ecl=baseline_ecl,
                stressed_ecl=stressed_ecl,
                incremental_ecl=incremental_ecl,
                rwa=rwa,
                cet1_impact=cet1_impact
            ))

        return results

    def aggregate_credit_portfolio(self, results: List[CreditStressResult], initial_cet1_capital: float) -> Dict[str, float]:
        """
        Aggregates individual credit stress results into portfolio-level metrics.
        """
        if initial_cet1_capital <= 0:
            raise ValueError("Initial CET1 capital must be positive.")

        total_ead = sum(r.ead for r in results)
        total_baseline_ecl = sum(r.baseline_ecl for r in results)
        total_stressed_ecl = sum(r.stressed_ecl for r in results)
        total_incremental_ecl = sum(r.incremental_ecl for r in results)
        total_rwa = sum(r.rwa for r in results)

        cet1_impact = total_stressed_ecl / initial_cet1_capital

        return {
            "total_ead": total_ead,
            "total_baseline_ecl": total_baseline_ecl,
            "total_stressed_ecl": total_stressed_ecl,
            "total_incremental_ecl": total_incremental_ecl,
            "total_rwa": total_rwa,
            "cet1_impact": cet1_impact
        }
