// Mirrors of the canonical engine schemas the UI consumes. The UI performs
// zero sizing logic — these types exist only to render API responses.

export type TradeType = 'lottery' | 'premium' | 'position' | 'shortterm' | 'prediction' | 'trading'
export type EdgeSource = 'exact_math' | 'live_track_record' | 'backtest' | 'related_experience' | 'guess'

export interface LayerCap {
  layer: string
  constraint: string
  risk_pct: number | null
  risk_dollars: number | null
  binding: boolean
  detail: string
  doc_slug: string
}

export interface WarningItem {
  code: string
  severity: 'info' | 'caution' | 'danger'
  message: string
  doc_slug: string
}

export interface DrawdownPaths {
  n_paths: number
  n_trades: number
  seed: number
  median_final_equity: number
  worst_5pct_path: number[]
  worst_1pct_path: number[]
  median_path: number[]
  worst_5pct_max_drawdown: number
  worst_1pct_max_drawdown: number
  prob_drawdown_over_20pct: number
}

export interface SizeResponse {
  status: 'ok'
  recommendation: {
    size_units: number
    size_pct_bankroll: number
    risk_pct_bankroll: number
    risk_dollars: number
    notional_dollars: number
    pct_of_full_kelly: number
  }
  explanation: {
    binding_constraint: string
    binding_layer: string
    full_kelly_risk_pct: number
    kelly_fraction_used: number
    cap_table: LayerCap[]
    working_edge: {
      expectancy_r: number
      win_probability: number | null
      payoff_ratio: number | null
      ci_expectancy_r: { low: number; high: number; confidence: number }
      shrinkage_applied: string
      raw_expectancy_r: number
    }
    defaults_applied: string[]
    ignored_fields: string[]
    tail_factor: number
    multipliers: Record<string, number>
  }
  diagnostics: {
    warnings: WarningItem[]
    suggestions: string[]
    drawdown_paths: DrawdownPaths | null
    losing_streaks: {
      expected_max_streak: number
      prob_streak_10: number
      equity_after_expected_streak_pct: number
      note: string
    } | null
  }
  meta: {
    trade_type_used: TradeType
    trade_type_declared: string
    type_mismatch: boolean
    type_mismatch_detail: string
    sizing_model_applied: string
    engine_version: string
    methodology_version: string
    timestamp: string
    input_hash: string
    exploration_stage: string | null
    confirm_fields: string[]
  }
  human_readable_summary: string
}

export interface Refusal {
  status: 'refusal'
  refusal_code: string
  reasoning: string
  what_is_needed: string[]
  partial_diagnostics: WarningItem[]
}

export type SizeResult =
  | { kind: 'ok'; body: SizeResponse }
  | { kind: 'refusal'; body: Refusal }
  | { kind: 'error'; body: { error: string; field_errors?: { field: string; message: string }[] } }
