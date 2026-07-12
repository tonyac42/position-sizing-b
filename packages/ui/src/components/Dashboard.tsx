import { useEffect, useState } from 'react'
import { addPosition, deletePosition, getPortfolio, getTrackRecord, logTrades, putAccount } from '../api'

// Persistent account state: bankroll, open positions (heat & buckets), and
// per-strategy track records with exploration gate progress.

export default function Dashboard() {
  const [portfolio, setPortfolio] = useState<any>(null)
  const [bankroll, setBankroll] = useState('')
  const [pos, setPos] = useState({ instrument_id: '', open_risk: '', correlation_bucket: 'default', direction: 'long' })
  const [stratId, setStratId] = useState('')
  const [tradeLog, setTradeLog] = useState('')
  const [record, setRecord] = useState<any>(null)
  const [gate, setGate] = useState<any>(null)

  const refresh = async () => setPortfolio(await getPortfolio())
  useEffect(() => { refresh() }, [])

  const saveBankroll = async () => {
    await putAccount({ bankroll: Number(bankroll) })
    refresh()
  }

  const submitPosition = async () => {
    await addPosition({ ...pos, open_risk: Number(pos.open_risk) })
    setPos({ instrument_id: '', open_risk: '', correlation_bucket: 'default', direction: 'long' })
    refresh()
  }

  const submitTrades = async () => {
    const rs = tradeLog.split(/[\s,]+/).filter(Boolean).map(Number).filter(n => !Number.isNaN(n))
    if (!stratId || rs.length === 0) return
    const out = await logTrades(stratId, rs)
    setGate(out)
    setTradeLog('')
    lookup()
  }

  const lookup = async () => {
    if (!stratId) return
    setRecord(await getTrackRecord(stratId))
  }

  const heat = portfolio && portfolio.bankroll
    ? portfolio.open_risk_total / portfolio.bankroll : null

  return (
    <>
      <div className="card">
        <h2>Account</h2>
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <div className="field"><label>Bankroll ($)</label>
            <input value={bankroll} placeholder={portfolio?.bankroll ?? 'not set'}
                   onChange={e => setBankroll(e.target.value)} /></div>
          <button className="ghost" onClick={saveBankroll} disabled={!bankroll}>Save</button>
          {heat !== null && (
            <div className="stat" style={{ marginLeft: 20 }}>
              <span className="v">{(heat * 100).toFixed(1)}%</span>
              <span className="k">portfolio heat in use (of 20% default budget)</span>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Open positions (heat & correlation buckets)</h2>
        {portfolio?.positions?.length ? (
          <table className="plain">
            <thead><tr><th>Instrument</th><th>Dir</th><th>Open risk</th><th>Bucket</th><th /></tr></thead>
            <tbody>
              {portfolio.positions.map((p: any) => (
                <tr key={p.position_id}>
                  <td>{p.instrument_id}</td><td>{p.direction}</td>
                  <td>${Math.round(p.open_risk).toLocaleString()}</td>
                  <td>{p.correlation_bucket}</td>
                  <td><button className="linkish" onClick={async () => { await deletePosition(p.position_id); refresh() }}>close</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">No open positions on file.</p>}
        {portfolio?.open_risk_by_bucket && Object.keys(portfolio.open_risk_by_bucket).length > 0 && (
          <>
            <h3>Risk by bucket</h3>
            <div className="row" style={{ gap: 20 }}>
              {Object.entries(portfolio.open_risk_by_bucket).map(([b, v]) => (
                <div className="stat" key={b}>
                  <span className="v">${Math.round(v as number).toLocaleString()}</span>
                  <span className="k">{b}</span>
                </div>
              ))}
            </div>
          </>
        )}
        <h3>Add position</h3>
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <div className="field"><label>Instrument</label>
            <input value={pos.instrument_id} onChange={e => setPos({ ...pos, instrument_id: e.target.value })} /></div>
          <div className="field"><label>Open risk ($)</label>
            <input value={pos.open_risk} onChange={e => setPos({ ...pos, open_risk: e.target.value })} /></div>
          <div className="field"><label>Bucket</label>
            <input value={pos.correlation_bucket} onChange={e => setPos({ ...pos, correlation_bucket: e.target.value })} /></div>
          <button className="ghost" onClick={submitPosition}
                  disabled={!pos.instrument_id || !pos.open_risk}>Add</button>
        </div>
      </div>

      <div className="card">
        <h2>Track record & exploration gates</h2>
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <div className="field"><label>Strategy ID</label>
            <input value={stratId} onChange={e => setStratId(e.target.value)} placeholder="my-strategy" /></div>
          <button className="ghost" onClick={lookup} disabled={!stratId}>Look up</button>
          <div className="field" style={{ minWidth: 260 }}><label>Log results (R-multiples, comma/space separated)</label>
            <input value={tradeLog} onChange={e => setTradeLog(e.target.value)} placeholder="1.5, -1, 2.2, -1" /></div>
          <button className="ghost" onClick={submitTrades} disabled={!stratId || !tradeLog}>Log trades</button>
        </div>

        {gate && (
          <div style={{ marginTop: 12, maxWidth: 460 }}>
            <div className="row"><b>{gate.progress}</b>
              <span className="muted">stage: {gate.exploration_stage}</span></div>
            <div className="progress" style={{ marginTop: 4 }}>
              <div style={{ width: `${Math.min(100, (gate.realized.n_trades / 300) * 100)}%` }} />
            </div>
          </div>
        )}

        {record?.realized && (
          <div className="row" style={{ gap: 24, marginTop: 14 }}>
            <div className="stat"><span className="v">{record.realized.n_trades}</span><span className="k">trades logged</span></div>
            <div className="stat"><span className="v">{(record.realized.win_rate * 100).toFixed(0)}%</span><span className="k">realized win rate</span></div>
            <div className="stat"><span className="v">{record.realized.expectancy_r >= 0 ? '+' : ''}{record.realized.expectancy_r.toFixed(3)}R</span>
              <span className="k">realized expectancy</span></div>
            {record.claimed_edge && (
              <div className="stat">
                <span className="v">
                  {record.claimed_edge.win_probability != null
                    ? `${(record.claimed_edge.win_probability * 100).toFixed(0)}% @ ${record.claimed_edge.payoff_ratio ?? 1}R`
                    : `${record.claimed_edge.expectancy_r}R`}
                </span>
                <span className="k">claimed edge ({record.edge_source})</span>
              </div>
            )}
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          Calibration plots (claimed probability vs resolved outcome, for prediction-market
          strategies) need per-trade probability logging — planned; see DECISIONS.md.
        </p>
      </div>
    </>
  )
}
