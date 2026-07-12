import type { Refusal, SizeResponse } from '../types'
import ConstraintWaterfall from './ConstraintWaterfall'
import DrawdownChart from './DrawdownChart'

const SEV_ICON = { danger: '⛔', caution: '⚠️', info: 'ℹ️' } as const

export function Warnings({ warnings }: { warnings: SizeResponse['diagnostics']['warnings'] }) {
  if (!warnings.length) return null
  const order = { danger: 0, caution: 1, info: 2 }
  const sorted = [...warnings].sort((a, b) => order[a.severity] - order[b.severity])
  return (
    <div>
      {sorted.map((w, i) => (
        <div key={i} className={`warning ${w.severity}`} role={w.severity === 'danger' ? 'alert' : undefined}>
          <span className="icon" aria-hidden>{SEV_ICON[w.severity]}</span>
          <span className="code">{w.code.replaceAll('_', ' ')}</span>
          <div>{w.message}</div>
          {w.doc_slug && <a href={`/docs/${w.doc_slug}.md`} target="_blank" rel="noreferrer">Why? →</a>}
        </div>
      ))}
    </div>
  )
}

export function RefusalView({ refusal }: { refusal: Refusal }) {
  return (
    <div className="card">
      <h2>⛔ The engine declined to give a number</h2>
      <p style={{ maxWidth: 720 }}>{refusal.reasoning}</p>
      <h3>What's needed to proceed</h3>
      <ul>{refusal.what_is_needed.map((n, i) => <li key={i}>{n}</li>)}</ul>
      <p className="muted" style={{ fontSize: 12 }}>
        A refusal beats a confident-looking number with nothing behind it —
        code <span className="mono">{refusal.refusal_code}</span>.
      </p>
      <Warnings warnings={refusal.partial_diagnostics ?? []} />
    </div>
  )
}

interface Props {
  resp: SizeResponse
  bankroll: number
  onOverrideDefault: (text: string) => void
}

export default function ResultView({ resp, bankroll, onOverrideDefault }: Props) {
  const r = resp.recommendation
  const e = resp.explanation
  return (
    <>
      <div className="card">
        <div className="headline">
          <div>
            <div className="big">{r.size_units >= 100 ? Math.round(r.size_units).toLocaleString() : r.size_units.toFixed(2)}
              <span className="unit"> units</span></div>
          </div>
          <div className="stat"><span className="v">${Math.round(r.risk_dollars).toLocaleString()}</span>
            <span className="k">at risk ({(r.risk_pct_bankroll * 100).toFixed(2)}% of bankroll)</span></div>
          <div className="stat"><span className="v">{(r.pct_of_full_kelly * 100).toFixed(0)}%</span>
            <span className="k">of full Kelly</span></div>
          <div className="stat"><span className="v">${Math.round(r.notional_dollars).toLocaleString()}</span>
            <span className="k">notional exposure</span></div>
          <div className="stat"><span className="v">{e.binding_constraint.replaceAll('_', ' ')}</span>
            <span className="k">binding constraint</span></div>
        </div>
        <p className="summary" style={{ marginTop: 12 }}>{resp.human_readable_summary}</p>
        <Warnings warnings={resp.diagnostics.warnings} />
      </div>

      <div className="card">
        <h2>The constraint stack — what limited you</h2>
        <ConstraintWaterfall capTable={e.cap_table} finalRiskPct={r.risk_pct_bankroll}
                             bankroll={bankroll} />
      </div>

      <div className="card">
        <h2>Working edge (after shrinkage)</h2>
        <div className="row" style={{ gap: 24 }}>
          <div className="stat"><span className="v">{e.working_edge.expectancy_r >= 0 ? '+' : ''}{e.working_edge.expectancy_r.toFixed(3)}R</span>
            <span className="k">per trade (claimed {e.working_edge.raw_expectancy_r >= 0 ? '+' : ''}{e.working_edge.raw_expectancy_r.toFixed(3)}R)</span></div>
          <div className="stat"><span className="v">
            [{e.working_edge.ci_expectancy_r.low.toFixed(2)}, {e.working_edge.ci_expectancy_r.high.toFixed(2)}]R</span>
            <span className="k">{Math.round(e.working_edge.ci_expectancy_r.confidence * 100)}% confidence interval</span></div>
          {e.tail_factor > 1 && (
            <div className="stat"><span className="v">{e.tail_factor.toFixed(1)}×</span>
              <span className="k">tail stress on risk caps</span></div>
          )}
        </div>
        <p className="muted" style={{ fontSize: 12 }}>{e.working_edge.shrinkage_applied}</p>

        {e.defaults_applied.length > 0 && (
          <>
            <h3>Defaults applied — click to override</h3>
            <div className="defaults">
              {e.defaults_applied.map((d, i) => (
                <button key={i} className="default-chip" onClick={() => onOverrideDefault(d)}
                        title="edit this value in the form">
                  {d} <span aria-hidden>✎</span>
                </button>
              ))}
            </div>
          </>
        )}
        {e.ignored_fields.length > 0 && (
          <>
            <h3>Ignored for this trade type</h3>
            <ul className="muted" style={{ fontSize: 12, margin: 0 }}>
              {e.ignored_fields.map((f, i) => <li key={i}>{f}</li>)}
            </ul>
          </>
        )}
        {resp.diagnostics.suggestions.length > 0 && (
          <>
            <h3>What would permit larger sizing</h3>
            <ul style={{ margin: 0 }}>
              {resp.diagnostics.suggestions.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          </>
        )}
      </div>

      {resp.diagnostics.drawdown_paths && (
        <div className="card">
          <h2>What this size feels like — simulated equity paths</h2>
          <DrawdownChart dd={resp.diagnostics.drawdown_paths} />
          {resp.diagnostics.losing_streaks && (
            <p className="summary" style={{ marginTop: 10 }}>{resp.diagnostics.losing_streaks.note}</p>
          )}
        </div>
      )}

      <p className="muted mono" style={{ fontSize: 11 }}>
        {resp.meta.sizing_model_applied} · engine {resp.meta.engine_version} · methodology{' '}
        {resp.meta.methodology_version} · input {resp.meta.input_hash}
        {resp.meta.exploration_stage && ` · exploration stage: ${resp.meta.exploration_stage}`}
        {resp.meta.type_mismatch && ` · type mismatch: ${resp.meta.type_mismatch_detail}`}
      </p>
    </>
  )
}
