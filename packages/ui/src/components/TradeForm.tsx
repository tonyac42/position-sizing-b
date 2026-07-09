import { useEffect, useState } from 'react'
import { getInstrument } from '../api'

// Progressive disclosure: trade-type selection first, then only the fields
// relevant to that type. Wizard mode walks novices through; expert mode is
// the dense single form. Zero sizing logic — this just builds the canonical
// request object.

export const TYPES = [
  { id: 'trading', name: 'Trading', blurb: 'Continuous market, stop-based. The classic case.' },
  { id: 'shortterm', name: 'Day trading', blurb: 'Many small-edge trades, intraday. Daily loss limit.' },
  { id: 'prediction', name: 'Prediction market', blurb: 'Binary contracts. Max loss = price paid.' },
  { id: 'premium', name: 'Premium selling', blurb: 'Short options. High win rate, tail risk.' },
  { id: 'lottery', name: 'Long convexity', blurb: 'Long options. Low win rate, big payoffs.' },
  { id: 'position', name: 'Thesis position', blurb: 'Months-long holds. Portfolio construction.' },
  { id: 'auto', name: 'Not sure', blurb: 'Describe the trade; the engine classifies it.' },
] as const

export type FormState = Record<string, string>

export const EMPTY_FORM: FormState = {
  trade_type: '', bankroll: '', bankroll_segregated: '', kelly_fraction: '',
  drawdown_pct: '', edge_format: 'winprob', win_probability: '', payoff_ratio: '',
  expectancy_r: '', win_rate: '', edge_source: 'guess', sample_size: '',
  similarity: '', market_price: '', user_calibration_data: '',
  strategy_id: '', direction: 'long', entry_price: '', stop_price: '', target_price: '',
  time_days: '', structural_max_loss: '', hold_to_resolution: '',
  instrument_id: '', point_value: '', volatility_atr: '', adv: '', max_fill: '',
  liquidity_tier: '', correlation_bucket: '', tail_profile: '', gap_risk: '',
  per_trade_risk_cap: '', volatility_cap: '', portfolio_heat_cap: '',
  correlation_bucket_cap: '', capacity_policy: '', daily_loss_limit: '',
  intraday_pnl: '', peak_equity: '',
}

const num = (s: string) => (s.trim() === '' ? undefined : Number(s))
const bool = (s: string) => (s === '' ? undefined : s === 'yes')

export function buildRequest(f: FormState): Record<string, unknown> {
  const edge: Record<string, unknown> = {}
  if (f.edge_format === 'winprob') {
    edge.win_probability = num(f.win_probability)
    edge.payoff_ratio = num(f.payoff_ratio)
  } else {
    edge.expectancy_r = num(f.expectancy_r)
    edge.win_rate = num(f.win_rate)
  }
  const req: Record<string, unknown> = {
    bankroll: num(f.bankroll),
    trade_type: f.trade_type || 'auto',
    edge_estimate: edge,
    edge_source: f.edge_source,
    sample_size: num(f.sample_size) ?? 0,
    trade: prune({
      direction: f.direction || undefined,
      entry_price: num(f.entry_price),
      stop_price: num(f.stop_price),
      target_price: num(f.target_price),
      expected_time_in_trade_days: num(f.time_days),
      structural_max_loss: num(f.structural_max_loss),
      hold_to_resolution: bool(f.hold_to_resolution),
      payoff_structure: f.trade_type === 'prediction' ? 'binary' : undefined,
    }),
    instrument: prune({
      instrument_id: f.instrument_id || 'unspecified',
      point_value: num(f.point_value),
      volatility_atr: num(f.volatility_atr),
      adv: num(f.adv),
      max_fill: num(f.max_fill),
      liquidity_tier: f.liquidity_tier || undefined,
      correlation_bucket: f.correlation_bucket || undefined,
      tail_profile: f.tail_profile || undefined,
      gap_risk: bool(f.gap_risk),
    }),
    constraints: prune({
      per_trade_risk_cap: num(f.per_trade_risk_cap),
      volatility_cap: num(f.volatility_cap),
      portfolio_heat_cap: num(f.portfolio_heat_cap),
      correlation_bucket_cap: num(f.correlation_bucket_cap),
      capacity_policy: f.capacity_policy || undefined,
      daily_loss_limit: num(f.daily_loss_limit),
    }),
  }
  // A live track record's stated stats ARE realized results: pass them so the
  // engine's Bayesian blend sees the sample instead of discounting the claim.
  const n = num(f.sample_size)
  if (f.edge_source === 'live_track_record' && n && n > 0) {
    if (f.edge_format === 'winprob' && num(f.win_probability) != null) {
      req.realized_results = prune({
        n_trades: n, win_rate: num(f.win_probability),
        avg_win_r: num(f.payoff_ratio) ?? 1.0, avg_loss_r: 1.0,
      })
    } else if (num(f.expectancy_r) != null) {
      req.realized_results = { n_trades: n, expectancy_r: num(f.expectancy_r) }
    }
  }
  if (f.bankroll_segregated) req.bankroll_segregated = f.bankroll_segregated === 'yes'
  if (f.kelly_fraction) req.kelly_fraction = num(f.kelly_fraction)
  else if (f.drawdown_pct) req.drawdown_tolerance = { max_drawdown_pct: num(f.drawdown_pct) }
  if (f.strategy_id) req.strategy_id = f.strategy_id
  if (f.market_price) req.market_price = num(f.market_price)
  if (f.user_calibration_data) req.user_calibration_data = f.user_calibration_data === 'yes'
  if (f.similarity) req.similarity = num(f.similarity)
  if (f.intraday_pnl) req.intraday_pnl = num(f.intraday_pnl)
  if (f.peak_equity) req.peak_equity = num(f.peak_equity)
  return req
}

function prune(o: Record<string, unknown>) {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== '') out[k] = v
  return Object.keys(out).length ? out : undefined
}

// Which optional sections matter per type (progressive disclosure).
const SHOW: Record<string, { stop: boolean; prediction: boolean; structural: boolean;
                             atr: boolean; daily: boolean; time: boolean }> = {
  trading: { stop: true, prediction: false, structural: false, atr: true, daily: false, time: true },
  shortterm: { stop: true, prediction: false, structural: false, atr: true, daily: true, time: true },
  prediction: { stop: false, prediction: true, structural: false, atr: false, daily: false, time: true },
  premium: { stop: false, prediction: false, structural: true, atr: true, daily: false, time: true },
  lottery: { stop: false, prediction: false, structural: true, atr: false, daily: false, time: true },
  position: { stop: false, prediction: false, structural: true, atr: false, daily: false, time: true },
  auto: { stop: true, prediction: true, structural: true, atr: true, daily: true, time: true },
  '': { stop: true, prediction: true, structural: true, atr: true, daily: true, time: true },
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}

function Txt({ f, k, set, ph }: { f: FormState; k: string; set: (k: string, v: string) => void; ph?: string }) {
  return <input value={f[k] ?? ''} placeholder={ph} onChange={e => set(k, e.target.value)} />
}

function Sel({ f, k, set, opts }: { f: FormState; k: string; set: (k: string, v: string) => void;
               opts: [string, string][] }) {
  return (
    <select value={f[k] ?? ''} onChange={e => set(k, e.target.value)}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

interface Props {
  form: FormState
  setForm: React.Dispatch<React.SetStateAction<FormState>>
  mode: 'wizard' | 'expert'
  onSubmit: () => void
  busy: boolean
}

export default function TradeForm({ form, setForm, mode, onSubmit, busy }: Props) {
  const [step, setStep] = useState(0)
  const set = (k: string, v: string) => setForm({ ...form, [k]: v })
  const show = SHOW[form.trade_type] ?? SHOW['']

  // Instrument catalog enrichment: fill blanks when a known id is typed.
  useEffect(() => {
    const id = form.instrument_id
    if (!id) return
    const t = setTimeout(async () => {
      const inst = await getInstrument(id)
      if (!inst) return
      setForm(prev => ({
        ...prev,
        point_value: prev.point_value || String(inst.point_value ?? ''),
        volatility_atr: prev.volatility_atr || String(inst.volatility_atr ?? ''),
        adv: prev.adv || String(inst.adv ?? ''),
        liquidity_tier: prev.liquidity_tier || (inst.liquidity_tier ?? ''),
        correlation_bucket: prev.correlation_bucket || (inst.correlation_bucket ?? ''),
        tail_profile: prev.tail_profile || (inst.tail_profile ?? ''),
      }))
    }, 400)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.instrument_id])

  const typePicker = (
    <div className="type-cards">
      {TYPES.map(t => (
        <button key={t.id} className={`type-card ${form.trade_type === t.id ? 'selected' : ''}`}
                onClick={() => { set('trade_type', t.id); if (mode === 'wizard') setStep(1) }}>
          <b>{t.name}</b><span>{t.blurb}</span>
        </button>
      ))}
    </div>
  )

  const bankrollEdge = (
    <>
      <h3>Bankroll & risk appetite</h3>
      <div className="grid">
        <Field label="Bankroll ($)" hint="total risk capital"><Txt f={form} k="bankroll" set={set} ph="50000" /></Field>
        <Field label="Segregated bankroll?" hint="play-money walled off from living funds">
          <Sel f={form} k="bankroll_segregated" set={set}
               opts={[['', 'no (default)'], ['yes', 'yes'], ['no', 'no']]} /></Field>
        <Field label="Kelly fraction" hint="blank = 0.25 default, or set drawdown tolerance">
          <Txt f={form} k="kelly_fraction" set={set} ph="0.25" /></Field>
        <Field label="…or max tolerable drawdown" hint="e.g. 0.2 = 20%; engine derives the fraction">
          <Txt f={form} k="drawdown_pct" set={set} ph="0.20" /></Field>
        <Field label="Peak equity ($)" hint="high-water mark, for the equity throttle">
          <Txt f={form} k="peak_equity" set={set} /></Field>
      </div>
      <h3>Your edge</h3>
      <div className="grid">
        <Field label="Edge format">
          <Sel f={form} k="edge_format" set={set}
               opts={[['winprob', 'win probability + payoff'], ['expectancy', 'expectancy (R)']]} /></Field>
        {form.edge_format === 'winprob' ? (
          <>
            <Field label="Win probability" hint="0–1"><Txt f={form} k="win_probability" set={set} ph="0.55" /></Field>
            <Field label="Payoff ratio" hint="avg win ÷ avg loss, in R">
              <Txt f={form} k="payoff_ratio" set={set} ph="1.5" /></Field>
          </>
        ) : (
          <>
            <Field label="Expectancy (R)" hint="EV per unit risked"><Txt f={form} k="expectancy_r" set={set} ph="0.4" /></Field>
            <Field label="Win rate" hint="optional, for distribution shape"><Txt f={form} k="win_rate" set={set} ph="0.4" /></Field>
          </>
        )}
        <Field label="Where does this edge come from?" hint="be honest — it changes the shrinkage">
          <Sel f={form} k="edge_source" set={set} opts={[
            ['guess', 'a guess / intuition'],
            ['related_experience', 'related experience'],
            ['backtest', 'a backtest'],
            ['live_track_record', 'live track record (this strategy)'],
            ['exact_math', 'exact math (known probabilities)'],
          ]} /></Field>
        <Field label="Sample size" hint="trades behind the claim"><Txt f={form} k="sample_size" set={set} ph="0" /></Field>
        {form.edge_source === 'related_experience' && (
          <Field label="Similarity (0–1)" hint="how close is the prior domain?">
            <Txt f={form} k="similarity" set={set} ph="0.5" /></Field>
        )}
        <Field label="Strategy ID" hint="links to stored track record & gates">
          <Txt f={form} k="strategy_id" set={set} ph="my-strategy" /></Field>
      </div>
    </>
  )

  const structure = (
    <>
      <h3>Trade structure</h3>
      <div className="grid">
        <Field label="Direction"><Sel f={form} k="direction" set={set}
              opts={[['long', 'long'], ['short', 'short']]} /></Field>
        <Field label="Entry price"><Txt f={form} k="entry_price" set={set} /></Field>
        {show.stop && <Field label="Stop price" hint="blank = no stop">
          <Txt f={form} k="stop_price" set={set} /></Field>}
        <Field label="Target price"><Txt f={form} k="target_price" set={set} /></Field>
        {show.time && <Field label="Expected time in trade (days)">
          <Txt f={form} k="time_days" set={set} /></Field>}
        {(show.structural || show.prediction) && (
          <Field label="Structural max loss (per unit)"
                 hint={form.trade_type === 'prediction' ? 'blank = price paid' : 'worst case per unit — required without a stop'}>
            <Txt f={form} k="structural_max_loss" set={set} /></Field>
        )}
        {show.prediction && (
          <>
            <Field label="Market price" hint="current market-implied probability (0–1)">
              <Txt f={form} k="market_price" set={set} ph="0.30" /></Field>
            <Field label="Hold to resolution?"><Sel f={form} k="hold_to_resolution" set={set}
                  opts={[['', '—'], ['yes', 'yes'], ['no', 'no, managed with a stop']]} /></Field>
            <Field label="Documented calibration data?" hint="past probability estimates vs outcomes">
              <Sel f={form} k="user_calibration_data" set={set}
                   opts={[['', 'no'], ['yes', 'yes']]} /></Field>
          </>
        )}
      </div>
      <h3>Instrument</h3>
      <div className="grid">
        <Field label="Instrument ID" hint="known IDs autofill from the catalog (try ES, CL, BTC-USD)">
          <Txt f={form} k="instrument_id" set={set} ph="ES" /></Field>
        <Field label="Point value ($/pt/unit)"><Txt f={form} k="point_value" set={set} ph="1" /></Field>
        {show.atr && <Field label="ATR (volatility)"><Txt f={form} k="volatility_atr" set={set} /></Field>}
        <Field label="ADV ($/day)" hint="average daily volume"><Txt f={form} k="adv" set={set} /></Field>
        <Field label="Max fill ($)" hint="book limit / counterparty cap / depth">
          <Txt f={form} k="max_fill" set={set} /></Field>
        <Field label="Liquidity tier"><Sel f={form} k="liquidity_tier" set={set} opts={[
          ['', '—'], ['deep', 'deep'], ['moderate', 'moderate'], ['thin', 'thin'], ['micro', 'micro']]} /></Field>
        <Field label="Correlation bucket" hint="same theme = same bucket">
          <Txt f={form} k="correlation_bucket" set={set} ph="default" /></Field>
        <Field label="Tail profile"><Sel f={form} k="tail_profile" set={set} opts={[
          ['', 'normal'], ['normal', 'normal'], ['moderate', 'moderate'], ['heavy', 'heavy'], ['extreme', 'extreme']]} /></Field>
        <Field label="Gap/event risk?"><Sel f={form} k="gap_risk" set={set}
              opts={[['', 'no'], ['yes', 'yes'], ['no', 'no']]} /></Field>
      </div>
    </>
  )

  const constraints = (
    <details className="adv" open={mode === 'expert'}>
      <summary>Constraint preferences (defaults shown in the result; override here)</summary>
      <div className="grid">
        <Field label="Per-trade risk cap" hint="default 0.02 (2%)"><Txt f={form} k="per_trade_risk_cap" set={set} /></Field>
        <Field label="Volatility cap" hint="default 0.01 per ATR"><Txt f={form} k="volatility_cap" set={set} /></Field>
        <Field label="Portfolio heat cap" hint="default 0.20"><Txt f={form} k="portfolio_heat_cap" set={set} /></Field>
        <Field label="Bucket cap" hint="default 0.06"><Txt f={form} k="correlation_bucket_cap" set={set} /></Field>
        <Field label="Heat policy"><Sel f={form} k="capacity_policy" set={set} opts={[
          ['', 'downsize (default)'], ['downsize', 'downsize'], ['reject', 'reject'], ['queue', 'queue']]} /></Field>
        {show.daily && (
          <>
            <Field label="Daily loss limit ($)"><Txt f={form} k="daily_loss_limit" set={set} /></Field>
            <Field label="Today's P&L ($)"><Txt f={form} k="intraday_pnl" set={set} /></Field>
          </>
        )}
      </div>
    </details>
  )

  if (mode === 'expert') {
    return (
      <div>
        <h3>Trade type</h3>
        {typePicker}
        {bankrollEdge}
        {structure}
        {constraints}
        <div style={{ marginTop: 14 }}>
          <button className="primary" onClick={onSubmit} disabled={busy}>
            {busy ? 'Sizing…' : 'Size it'}
          </button>
        </div>
      </div>
    )
  }

  const steps = [
    { title: 'What kind of trade is this?', body: typePicker, ready: !!form.trade_type },
    { title: 'Bankroll & edge', body: bankrollEdge, ready: !!form.bankroll },
    { title: 'Trade & instrument', body: structure, ready: true },
    { title: 'Constraints (optional)', body: constraints, ready: true },
  ]
  const s = steps[step]
  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        {steps.map((st, i) => (
          <button key={i} className="linkish"
                  style={{ fontWeight: i === step ? 700 : 400, color: i === step ? 'var(--series-1)' : 'var(--muted)' }}
                  onClick={() => setStep(i)}>
            {i + 1}. {st.title}
          </button>
        ))}
      </div>
      {s.body}
      <div className="row" style={{ marginTop: 14 }}>
        {step > 0 && <button className="ghost" onClick={() => setStep(step - 1)}>Back</button>}
        {step < steps.length - 1 && (
          <button className="ghost" onClick={() => setStep(step + 1)} disabled={!s.ready}>Next</button>
        )}
        {step >= 1 && (
          <button className="primary" onClick={onSubmit} disabled={busy || !form.bankroll}>
            {busy ? 'Sizing…' : 'Size it'}
          </button>
        )}
      </div>
    </div>
  )
}
