import { useState } from 'react'
import { compareScenarios } from '../api'
import type { FormState } from './TradeForm'
import { buildRequest } from './TradeForm'
import type { SizeResponse } from '../types'

// Clone the current scenario, tweak one thing per variant, compare in one
// round trip via /v1/scenarios/compare.

interface Variant { label: string; form: FormState }

const TWEAKABLE: [keyof FormState & string, string][] = [
  ['kelly_fraction', 'Kelly fraction'],
  ['stop_price', 'Stop price'],
  ['bankroll', 'Bankroll'],
  ['per_trade_risk_cap', 'Per-trade risk cap'],
  ['win_probability', 'Win probability'],
  ['market_price', 'Market price'],
]

export default function ScenarioCompare({ baseForm }: { baseForm: FormState }) {
  const [variants, setVariants] = useState<Variant[]>([{ label: 'base', form: baseForm }])
  const [results, setResults] = useState<{ label?: string; status_code: number; result: any }[] | null>(null)
  const [busy, setBusy] = useState(false)

  const clone = () => setVariants(v => [...v, {
    label: `variant ${v.length}`,
    form: { ...v[v.length - 1].form },
  }])

  const update = (i: number, k: string, val: string) =>
    setVariants(v => v.map((x, j) => (j === i ? { ...x, form: { ...x.form, [k]: val } } : x)))

  const run = async () => {
    setBusy(true)
    try {
      const out = await compareScenarios(variants.map(v => buildRequest(v.form)),
                                         variants.map(v => v.label))
      setResults(out.results)
    } finally { setBusy(false) }
  }

  return (
    <div className="card">
      <h2>Scenario comparison</h2>
      <p className="muted" style={{ fontSize: 12 }}>
        Starts from your current form. Clone it, tweak inputs, and compare — sizing runs
        server-side in one call.
      </p>
      {variants.map((v, i) => (
        <div key={i} className="row" style={{ margin: '8px 0', alignItems: 'flex-end' }}>
          <div className="field" style={{ width: 120 }}>
            <label>Label</label>
            <input value={v.label}
                   onChange={e => setVariants(vs => vs.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
          </div>
          {TWEAKABLE.map(([k, label]) => (
            <div key={k} className="field" style={{ width: 110 }}>
              <label>{label}</label>
              <input value={v.form[k] ?? ''} onChange={e => update(i, k, e.target.value)} />
            </div>
          ))}
        </div>
      ))}
      <div className="row">
        <button className="ghost" onClick={clone}>Clone last variant</button>
        <button className="primary" onClick={run} disabled={busy || variants.length < 1}>
          {busy ? 'Comparing…' : `Compare ${variants.length}`}
        </button>
      </div>

      {results && (
        <table className="plain" style={{ marginTop: 14 }}>
          <thead>
            <tr><th>Scenario</th><th>Size</th><th>$ at risk</th><th>% bankroll</th>
                <th>% full Kelly</th><th>Binding constraint</th><th>Warnings</th></tr>
          </thead>
          <tbody>
            {results.map((r, i) => {
              if (r.status_code !== 200) {
                const reason = r.result?.reasoning ?? r.result?.field_errors?.map((f: any) => f.field).join(', ')
                return (
                  <tr key={i}>
                    <td>{r.label ?? i}</td>
                    <td colSpan={5}>{r.status_code === 422 ? `⛔ refused: ${reason}` : `malformed: ${reason}`}</td>
                    <td /></tr>
                )
              }
              const b: SizeResponse = r.result
              const danger = b.diagnostics.warnings.filter(w => w.severity === 'danger').length
              return (
                <tr key={i}>
                  <td>{r.label ?? i}</td>
                  <td>{b.recommendation.size_units.toFixed(2)}</td>
                  <td>${Math.round(b.recommendation.risk_dollars).toLocaleString()}</td>
                  <td>{(b.recommendation.risk_pct_bankroll * 100).toFixed(2)}%</td>
                  <td>{(b.recommendation.pct_of_full_kelly * 100).toFixed(0)}%</td>
                  <td>{b.explanation.binding_constraint.replaceAll('_', ' ')}</td>
                  <td>{danger > 0 ? `⛔ ${danger}` : b.diagnostics.warnings.length || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
