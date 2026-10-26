/**
 * Financial Formatting Utilities for INR-First & Multi-Currency UX
 */

export type SupportedCurrency = 'INR' | 'USD' | string;

export interface CurrencyFormatOptions {
  decimals?: number;
  compact?: boolean;
  showSymbol?: boolean;
}

/**
 * Formats a monetary amount in the specified currency with proper locale grouping (en-IN for INR, en-US for USD).
 */
export function formatCurrency(
  amount: number | null | undefined,
  currency: SupportedCurrency = 'INR',
  options: CurrencyFormatOptions = {}
): string {
  if (amount === null || amount === undefined || isNaN(amount)) {
    return '—';
  }

  const curr = currency.toUpperCase();
  const decimals = options.decimals !== undefined ? options.decimals : 2;
  const showSymbol = options.showSymbol !== undefined ? options.showSymbol : true;
  const symbol = curr === 'INR' ? '₹' : curr === 'USD' ? '$' : `${curr} `;

  if (options.compact) {
    if (curr === 'INR') {
      const abs = Math.abs(amount);
      const sign = amount < 0 ? '-' : '';
      if (abs >= 10000000) {
        return `${sign}${showSymbol ? symbol : ''}${(abs / 10000000).toFixed(decimals)} Cr`;
      }
      if (abs >= 100000) {
        return `${sign}${showSymbol ? symbol : ''}${(abs / 100000).toFixed(decimals)} L`;
      }
    } else {
      const abs = Math.abs(amount);
      const sign = amount < 0 ? '-' : '';
      if (abs >= 1000000000) {
        return `${sign}${showSymbol ? symbol : ''}${(abs / 1000000000).toFixed(decimals)}B`;
      }
      if (abs >= 1000000) {
        return `${sign}${showSymbol ? symbol : ''}${(abs / 1000000).toFixed(decimals)}M`;
      }
      if (abs >= 1000) {
        return `${sign}${showSymbol ? symbol : ''}${(abs / 1000).toFixed(decimals)}k`;
      }
    }
  }

  const locale = curr === 'INR' ? 'en-IN' : 'en-US';
  const formattedNumber = amount.toLocaleString(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

  return showSymbol ? `${symbol}${formattedNumber}` : formattedNumber;
}

/**
 * Formats a percentage value.
 */
export function formatPercent(value: number | null | undefined, decimals: number = 2): string {
  if (value === null || value === undefined || isNaN(value)) {
    return '0.00%';
  }
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}

/**
 * Formats a share quantity.
 */
export function formatShares(shares: number | null | undefined, decimals: number = 2): string {
  if (shares === null || shares === undefined || isNaN(shares)) {
    return '0.00';
  }
  return shares.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export interface ExecutionStatusInfo {
  label: string;
  badgeClass: string;
  description: string;
}

/**
 * Maps trade and execution statuses to clear visual badges and explanations.
 */
export function getExecutionStatusInfo(status: string | null | undefined): ExecutionStatusInfo {
  const s = (status || '').toUpperCase().trim();
  switch (s) {
    case 'EXECUTED_SIMULATED':
    case 'EXECUTED':
      return {
        label: 'Executed (Simulated)',
        badgeClass: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40',
        description: 'Order fully executed against simulated live quotes and debited from cash reserves.',
      };
    case 'WITHHELD_FALLBACK_PRICE':
      return {
        label: 'Withheld (Fallback Price)',
        badgeClass: 'bg-amber-500/20 text-amber-400 border border-amber-500/40',
        description: 'Trade withheld because execution requires verified live market quotes rather than reference prices.',
      };
    case 'WITHHELD_INSUFFICIENT_CASH':
      return {
        label: 'Withheld (Insufficient Cash)',
        badgeClass: 'bg-red-500/20 text-red-400 border border-red-500/40',
        description: 'Trade withheld because the portfolio cash balance cannot cover the required buy order notional.',
      };
    case 'WITHHELD_MISSING_PRICE':
    case 'MISSING_PRICE':
      return {
        label: 'Withheld (Missing Quote)',
        badgeClass: 'bg-rose-500/20 text-rose-400 border border-rose-500/40',
        description: 'Trade withheld because the instrument lacks an active market quote.',
      };
    case 'WITHHELD_NO_TRADE':
    case 'HOLD_NO_CHANGE':
    case 'HOLD':
    default:
      return {
        label: 'Hold (No Order)',
        badgeClass: 'bg-slate-700/40 text-slate-400 border border-slate-600/40',
        description: 'No trade proposed or target allocation matches current position.',
      };
  }
}
