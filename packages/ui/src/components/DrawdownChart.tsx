import { useState } from 'react'
import type { DrawdownPaths } from '../types'

// Monte Carlo equity paths at the recommended size: median, worst-5%, and
// worst-1% — so the user viscerally sees the drawdowns before trading.
// Three series: legend + direct labels at line ends; hover crosshair reads
// all three at the nearest trade index.

const SERIES = [
  { key: 'median_path' as const, label: 'Median', color: 'var(--series-1)' },
  { key: 'worst_5pct_path' as const, label: 'Worst 5%', color: 'var(--series-3)' },
  { key: 'worst_1pct_path' as const, label: 'Worst 1%', color: 'var(--series-6)' },
]

export default function DrawdownChart({ dd }: { dd: DrawdownPaths }) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 720, H = 260, PAD_L = 46, PAD_R = 84, PAD_T = 12, PAD_B = 28
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B

  const all = SERIES.flatMap(s => dd[s.key])
  const yMin = Math.min(...all, 1) * 0.97
  const yMax = Math.max(...all, 1) * 1.03
  const n = dd.median_path.length

  const x = (i: number) => PAD_L + (i / (n - 1)) * plotW
  const y = (v: number) => PAD_T + (1 - (v - yMin) / (yMax - yMin)) * plotH
  const tradeAt = (i: number) => Math.round((i / (n - 1)) * dd.n_trades)

  const path = (vals: number[]) =>
    vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')

  const yTicks = [yMin, (yMin + yMax) / 2, yMax]

  return (
    <div className="chart-wrap">
      <div className="legend">
        {SERIES.map(s => (
          <span key={s.key}><span className="swatch" style={{ background: s.color }} />{s.label}</span>
        ))}
        <span className="muted">{dd.n_paths} simulated paths · seed {dd.seed}</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Simulated equity paths at the recommended size"
           onMouseMove={e => {
             const svg = e.currentTarget
             const pt = svg.getBoundingClientRect()
             const px = ((e.clientX - pt.left) / pt.width) * W
             const i = Math.round(((px - PAD_L) / plotW) * (n - 1))
             setHover(i >= 0 && i < n ? i : null)
           }}
           onMouseLeave={() => setHover(null)}>
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={PAD_L + plotW} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={PAD_L - 6} y={y(t) + 4} fontSize={10} fill="var(--muted)" textAnchor="end">
              {(t * 100).toFixed(0)}%
            </text>
          </g>
        ))}
        <line x1={PAD_L} x2={PAD_L + plotW} y1={y(1)} y2={y(1)} stroke="var(--baseline)"
              strokeWidth={1} strokeDasharray="4 3" />
        {SERIES.map(s => (
          <path key={s.key} d={path(dd[s.key])} fill="none" stroke={s.color} strokeWidth={2} />
        ))}
        {/* direct labels at line ends */}
        {SERIES.map(s => {
          const vals = dd[s.key]
          return (
            <text key={s.key} x={PAD_L + plotW + 5} y={y(vals[vals.length - 1]) + 4}
                  fontSize={11} fill="var(--ink-2)">
              {s.label} {(vals[vals.length - 1] * 100).toFixed(0)}%
            </text>
          )
        })}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD_T} y2={PAD_T + plotH}
                  stroke="var(--baseline)" strokeWidth={1} />
            {SERIES.map(s => (
              <circle key={s.key} cx={x(hover)} cy={y(dd[s.key][hover])} r={4}
                      fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
            ))}
          </g>
        )}
        <text x={PAD_L + plotW / 2} y={H - 6} fontSize={10} fill="var(--muted)" textAnchor="middle">
          trades →
        </text>
      </svg>
      {hover !== null && (
        <div className="muted" style={{ fontSize: 12 }}>
          After ~{tradeAt(hover)} trades:{' '}
          {SERIES.map(s => `${s.label} ${(dd[s.key][hover] * 100).toFixed(1)}%`).join(' · ')}
        </div>
      )}
      <div className="row" style={{ marginTop: 8, gap: 24 }}>
        <div className="stat"><span className="v">{(dd.worst_5pct_max_drawdown * 100).toFixed(0)}%</span>
          <span className="k">max drawdown, worst-5% path</span></div>
        <div className="stat"><span className="v">{(dd.worst_1pct_max_drawdown * 100).toFixed(0)}%</span>
          <span className="k">max drawdown, worst-1% path</span></div>
        <div className="stat"><span className="v">{(dd.prob_drawdown_over_20pct * 100).toFixed(1)}%</span>
          <span className="k">chance of a &gt;20% drawdown over {dd.n_trades} trades</span></div>
      </div>
    </div>
  )
}
