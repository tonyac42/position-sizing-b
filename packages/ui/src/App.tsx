import { useState } from 'react'
import { sizeTrade } from './api'
import type { SizeResult } from './types'
import TradeForm, { buildRequest, EMPTY_FORM, type FormState } from './components/TradeForm'
import ResultView, { RefusalView } from './components/ResultView'
import ScenarioCompare from './components/ScenarioCompare'
import Dashboard from './components/Dashboard'

// Saved templates live client-side; everything numeric comes from the API.
function loadTemplates(): Record<string, FormState> {
  try { return JSON.parse(localStorage.getItem('sizer.templates') || '{}') } catch { return {} }
}

export default function App() {
  const [tab, setTab] = useState<'size' | 'scenarios' | 'dashboard'>('size')
  const [mode, setMode] = useState<'wizard' | 'expert'>('wizard')
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM })
  const [accountMode, setAccountMode] = useState(false)
  const [result, setResult] = useState<SizeResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [templates, setTemplates] = useState(loadTemplates)

  const submit = async () => {
    setBusy(true)
    try {
      setResult(await sizeTrade(buildRequest(form), accountMode))
    } catch (err) {
      setResult({ kind: 'error', body: { error: String(err) } })
    } finally { setBusy(false) }
  }

  const saveTemplate = () => {
    const name = prompt('Template name?')
    if (!name) return
    const next = { ...templates, [name]: form }
    setTemplates(next)
    localStorage.setItem('sizer.templates', JSON.stringify(next))
  }

  // Map a defaults_applied string to the form field it overrides.
  const overrideDefault = (text: string) => {
    const map: [string, string][] = [
      ['kelly_fraction', 'kelly_fraction'],
      ['per_trade_risk_cap', 'per_trade_risk_cap'],
      ['volatility_cap', 'volatility_cap'],
      ['portfolio_heat_cap', 'portfolio_heat_cap'],
      ['correlation_bucket_cap', 'correlation_bucket_cap'],
    ]
    const hit = map.find(([k]) => text.includes(k))
    if (hit) {
      const el = document.querySelector<HTMLElement>('details.adv')
      if (el) (el as HTMLDetailsElement).open = true
      window.scrollTo({ top: 0, behavior: 'smooth' })
      setMode('expert')
    }
  }

  return (
    <div className="app">
      <div className="topbar">
        <h1>Sizer</h1>
        <span className="sub">how much should I bet? — sized by growth math, capped by reality</span>
        <span className="spacer" />
        <label className="row" style={{ fontSize: 12, color: 'var(--ink-2)' }}>
          <input type="checkbox" checked={accountMode} onChange={e => setAccountMode(e.target.checked)} />
          use stored account state
        </label>
      </div>

      <div className="tabs">
        <button className={tab === 'size' ? 'active' : ''} onClick={() => setTab('size')}>Size a trade</button>
        <button className={tab === 'scenarios' ? 'active' : ''} onClick={() => setTab('scenarios')}>Scenarios</button>
        <button className={tab === 'dashboard' ? 'active' : ''} onClick={() => setTab('dashboard')}>Dashboard</button>
      </div>

      {tab === 'size' && (
        <>
          <div className="card">
            <div className="row" style={{ marginBottom: 10 }}>
              <h2 style={{ margin: 0 }}>Describe the trade</h2>
              <span className="spacer" />
              <button className="ghost" onClick={() => setMode(mode === 'wizard' ? 'expert' : 'wizard')}>
                {mode === 'wizard' ? 'Expert mode' : 'Wizard mode'}
              </button>
              <button className="ghost" onClick={saveTemplate}>Save template</button>
              {Object.keys(templates).length > 0 && (
                <select onChange={e => { if (templates[e.target.value]) setForm(templates[e.target.value]) }}
                        defaultValue="">
                  <option value="" disabled>Load template…</option>
                  {Object.keys(templates).map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              )}
            </div>
            <TradeForm form={form} setForm={setForm} mode={mode} onSubmit={submit} busy={busy} />
          </div>

          {result?.kind === 'ok' && (
            <ResultView resp={result.body} bankroll={Number(form.bankroll) || 0}
                        onOverrideDefault={overrideDefault} />
          )}
          {result?.kind === 'refusal' && <RefusalView refusal={result.body} />}
          {result?.kind === 'error' && (
            <div className="card">
              <h2>Request problem</h2>
              {'field_errors' in result.body && result.body.field_errors ? (
                <ul>{result.body.field_errors.map((f, i) =>
                  <li key={i}><span className="mono">{f.field}</span>: {f.message}</li>)}</ul>
              ) : <p>{result.body.error}</p>}
            </div>
          )}
        </>
      )}

      {tab === 'scenarios' && <ScenarioCompare baseForm={form} />}
      {tab === 'dashboard' && <Dashboard />}

      <p className="muted" style={{ fontSize: 11 }}>
        All sizing math runs server-side; this UI renders API responses verbatim.
        Docs: <a href="/docs/index.md" style={{ color: 'var(--series-1)' }}>constraint concepts</a>.
      </p>
    </div>
  )
}
