'use client'

import React from 'react'

const CONDITION_COLORS: Record<string, string> = {
  none:             '#64748b',
  vlm_descriptive:  '#8b5cf6',
  vlm_teleological: '#06b6d4',
}

const CONDITION_LABELS: Record<string, string> = {
  none:             'None',
  vlm_descriptive:  'VLM Descriptive',
  vlm_teleological: 'VLM Teleological',
}

const CONDITIONS = ['none', 'vlm_descriptive', 'vlm_teleological']

interface IntentEntry { condition: string; mean: number }
interface Props { data: IntentEntry[] }

export default function AnthroBar({ data }: Props) {
  const entries = CONDITIONS.map((cond) => {
    const found = data.find((d) => d.condition === cond)
    const mean  = found && !isNaN(found.mean) ? parseFloat(found.mean.toFixed(3)) : null
    return { condition: cond, mean }
  })

  const validEntries = entries.filter((e) => e.mean !== null)

  // Chart dimensions
  const W       = 460
  const H       = 200
  const padL    = 90
  const padR    = 90
  const padT    = 30
  const padB    = 30
  const chartW  = W - padL - padR
  const chartH  = H - padT - padB
  const MIN     = 1
  const MAX     = 7
  const toX     = (v: number) => padL + ((v - MIN) / (MAX - MIN)) * chartW

  // Y positions for each condition row
  const rowH = chartH / (CONDITIONS.length - 1)

  // Points for slope lines
  const points: Record<string, { x: number; y: number }> = {}
  CONDITIONS.forEach((cond, i) => {
    const entry = entries.find((e) => e.condition === cond)
    if (entry?.mean != null) {
      points[cond] = { x: toX(entry.mean), y: padT + i * rowH }
    }
  })

  return (
    <div className="flex flex-col items-center gap-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 220 }}>
        {/* Grid lines */}
        {[1, 2, 3, 4, 5, 6, 7].map((tick) => (
          <g key={tick}>
            <line
              x1={toX(tick)} y1={padT - 10}
              x2={toX(tick)} y2={H - padB + 10}
              stroke="#f1f5f9" strokeWidth={1}
            />
            <text x={toX(tick)} y={padT - 14} textAnchor="middle" fontSize={10} fill="#94a3b8">{tick}</text>
          </g>
        ))}

        {/* Slope lines connecting conditions */}
        {CONDITIONS.slice(0, -1).map((cond, i) => {
          const next = CONDITIONS[i + 1]
          const p1   = points[cond]
          const p2   = points[next]
          if (!p1 || !p2) return null
          return (
            <line
              key={`line-${i}`}
              x1={p1.x} y1={p1.y}
              x2={p2.x} y2={p2.y}
              stroke="#cbd5e1" strokeWidth={1.5} strokeDasharray="4 3"
            />
          )
        })}

        {/* Dots + labels per condition */}
        {CONDITIONS.map((cond, i) => {
          const entry = entries.find((e) => e.condition === cond)
          const p     = points[cond]
          const color = CONDITION_COLORS[cond]
          const y     = padT + i * rowH
          if (!p) return null
          return (
            <g key={cond}>
              {/* Condition label left */}
              <text x={padL - 8} y={y + 4} textAnchor="end" fontSize={11} fill="#475569" fontWeight={500}>
                {CONDITION_LABELS[cond]}
              </text>
              {/* Horizontal track */}
              <line
                x1={padL} y1={y} x2={padL + chartW} y2={y}
                stroke="#f1f5f9" strokeWidth={1}
              />
              {/* Dot */}
              <circle cx={p.x} cy={y} r={8} fill={color} />
              {/* Value label right */}
              <text x={padL + chartW + 10} y={y + 4} textAnchor="start" fontSize={11} fill={color} fontWeight={700}>
                {entry?.mean != null ? entry.mean.toFixed(2) : '-'}
              </text>
            </g>
          )
        })}

        {/* X axis label */}
        <text x={W / 2} y={H - 2} textAnchor="middle" fontSize={10} fill="#94a3b8">
          Intentionality Attribution (1–7)
        </text>
      </svg>

      {/* Delta callout if desc and teleo both present */}
      {(() => {
        const desc = entries.find((e) => e.condition === 'vlm_descriptive')?.mean
        const tele = entries.find((e) => e.condition === 'vlm_teleological')?.mean
        if (desc == null || tele == null) return null
        const delta = (tele - desc).toFixed(2)
        return (
          <p className="text-xs text-slate-500">
            Descriptive → Teleological:{' '}
            <span className="font-semibold font-mono text-cyan-600">+{delta} pts</span>
          </p>
        )
      })()}
    </div>
  )
}
