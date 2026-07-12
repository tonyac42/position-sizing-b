import { useState } from 'react'
import type { LayerCap } from '../types'

// The signature pedagogical surface: every layer's cap as a horizontal bar,
// binding layer highlighted, so the user sees exactly WHAT constrained them
// and what loosening each layer would buy.
//
// Single measure (risk % of bankroll) -> single hue. Non-binding caps use a
// recessive step, the binding cap and the final size use the full series hue.
// Off-scale bars (e.g. a huge full-Kelly reference) are clipped with an
// explicit "off scale" marker rather than crushing every other bar.

const LAYER_LABELS: Record<string, string> = {
  full_kelly: 'Full Kelly (growth-optimal)',
  fractional_kelly: 'Fractional Kelly proposal',
  exploration: 'Exploration gate',
  per_trade_risk_cap: 'Per-trade risk cap',
  volatility_cap: 'Volatility cap',
  portfolio_heat: 'Portfolio heat headroom',
  correlation_bucket: 'Correlation bucket headroom',
  capacity: 'Market capacity',
  capacity_unresolved: 'Capacity (unresolved)',
  daily_loss_limit: 'Daily loss limit',
}

const LAYER_ORDER = ['layer1_kelly', 'layer0_exploration', 'layer2_risk', 'layer3_capacity']

interface Props {
  capTable: LayerCap[]
  finalRiskPct: number
  bankroll: number
}

export default function ConstraintWaterfall({ capTable, finalRiskPct, bankroll }: Props) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null)

  const rows = [...capTable].sort(
    (a, b) => LAYER_ORDER.indexOf(a.layer) - LAYER_ORDER.indexOf(b.layer),
  )
  const values = rows.map(r => r.risk_pct).filter((v): v is number => v !== null)
  if (values.length === 0) return null

  // Scale: generous enough to show headroom, clipped so one huge reference
  // value doesn't flatten the caps that actually matter.
  const sorted = [...values].sort((a, b) => a - b)
  const p75 = sorted[Math.floor((sorted.length - 1) * 0.75)]
  const xMax = Math.max(finalRiskPct * 2, Math.min(Math.max(...values), p75 * 3)) * 1.08

  const W = 760, ROW_H = 34, LABEL_W = 230, VAL_W = 88
  const plotW = W - LABEL_W - VAL_W
  const H = (rows.length + 1) * ROW_H + 26

  const x = (v: number) => Math.min(v / xMax, 1) * plotW

  const fmt = (v: number | null) =>
    v === null ? 'n/a' : v >= 10 ? `${v.toFixed(0)}x bankroll` : `${(v * 100).toFixed(2)}%`

  const gridSteps = [0.25, 0.5, 0.75, 1.0].map(f => xMax * f)

  return (
    <div className="chart-wrap" onMouseLeave={() => setTip(null)}>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Constraint stack: each layer's size cap, binding layer highlighted">
        {/* recessive grid */}
        {gridSteps.map((g, i) => (
          <g key={i}>
            <line x1={LABEL_W + x(g)} x2={LABEL_W + x(g)} y1={4} y2={H - 22}
                  stroke="var(--grid)" strokeWidth={1} />
            <text x={LABEL_W + x(g)} y={H - 8} fontSize={10} fill="var(--muted)" textAnchor="middle">
              {(g * 100).toFixed(g * 100 < 1 ? 2 : 1)}%
            </text>
          </g>
        ))}
        <line x1={LABEL_W} x2={LABEL_W} y1={4} y2={H - 22} stroke="var(--baseline)" strokeWidth={1} />

        {rows.map((r, i) => {
          const y = i * ROW_H + 8
          const clipped = r.risk_pct !== null && r.risk_pct / xMax > 1
          const barW = r.risk_pct === null ? 0 : Math.max(x(r.risk_pct), 2)
          const fill = r.binding ? 'var(--series-1)' : 'var(--seq-250)'
          return (
            <g key={r.constraint}
               onMouseMove={e => {
                 const host = (e.currentTarget.ownerSVGElement!.parentElement as HTMLElement).getBoundingClientRect()
                 setTip({ x: e.clientX - host.left + 12, y: e.clientY - host.top + 12,
                          text: `${LAYER_LABELS[r.constraint] ?? r.constraint}: ${fmt(r.risk_pct)}${r.risk_dollars != null ? ` ($${Math.round(r.risk_dollars).toLocaleString()})` : ''} — ${r.detail}` })
               }}>
              <rect x={0} y={y - 4} width={W} height={ROW_H - 6} fill="transparent" />
              <text x={0} y={y + 12} fontSize={12} fill={r.binding ? 'var(--ink)' : 'var(--ink-2)'}
                    fontWeight={r.binding ? 700 : 400}>
                {LAYER_LABELS[r.constraint] ?? r.constraint}
              </text>
              {r.risk_pct === null ? (
                <text x={LABEL_W + 6} y={y + 12} fontSize={11} fill="var(--muted)">not applicable</text>
              ) : (
                <>
                  <rect x={LABEL_W} y={y} width={barW} height={14} rx={4}
                        fill={fill} />
                  {clipped && (
                    <text x={LABEL_W + plotW - 4} y={y + 11} fontSize={11}
                          fill="var(--ink-2)" textAnchor="end">⇢ off scale</text>
                  )}
                  <text x={LABEL_W + plotW + 6} y={y + 12} fontSize={12}
                        fill={r.binding ? 'var(--ink)' : 'var(--ink-2)'}
                        fontWeight={r.binding ? 700 : 400}
                        style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {fmt(r.risk_pct)}
                  </text>
                </>
              )}
              {r.binding && (
                <text x={LABEL_W + barW + 8} y={y + 11} fontSize={10} fill="var(--series-1)"
                      fontWeight={700} letterSpacing={0.5}>◂ BINDING</text>
              )}
            </g>
          )
        })}

        {/* final recommendation row */}
        {(() => {
          const y = rows.length * ROW_H + 8
          return (
            <g>
              <line x1={LABEL_W} x2={LABEL_W + plotW} y1={y - 6} y2={y - 6}
                    stroke="var(--baseline)" strokeWidth={1} strokeDasharray="3 3" />
              <text x={0} y={y + 12} fontSize={12} fill="var(--ink)" fontWeight={700}>
                Final recommendation
              </text>
              <rect x={LABEL_W} y={y} width={Math.max(x(finalRiskPct), 2)} height={14} rx={4}
                    fill="var(--series-1)" />
              <text x={LABEL_W + plotW + 6} y={y + 12} fontSize={12} fill="var(--ink)"
                    fontWeight={700} style={{ fontVariantNumeric: 'tabular-nums' }}>
                {(finalRiskPct * 100).toFixed(2)}%
              </text>
            </g>
          )
        })()}
      </svg>
      {tip && <div className="chart-tooltip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
      <div className="muted" style={{ fontSize: 11 }}>
        Bars show each layer's independent cap as % of bankroll at risk (${bankroll.toLocaleString()} bankroll).
        The recommendation is the minimum across layers.
      </div>
    </div>
  )
}
