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

const MIN = 1
const MAX = 7

interface CogLoadEntry { condition: string; mean: number; count: number }
interface Props { data: CogLoadEntry[] }

export default function CognitiveLoadBar({ data }: Props) {
  const entries = CONDITIONS.map((cond) => {
    const found = data.find((d) => d.condition === cond)
    const mean  = found && !isNaN(found.mean) ? found.mean : 0
    return { condition: cond, mean, count: found?.count ?? 0 }
  })

  return (
    <div className="flex flex-col gap-4 py-2">
      {entries.map(({ condition, mean, count }) => {
        const pct   = ((mean - MIN) / (MAX - MIN)) * 100
        const color = CONDITION_COLORS[condition]
        return (
          <div key={condition} className="flex items-center gap-3">
            <span className="text-xs font-medium text-slate-600 w-32 flex-shrink-0 text-right">
              {CONDITION_LABELS[condition]}
            </span>
            <div className="flex-1 bg-slate-100 rounded-full h-4 overflow-hidden">
              <div
                className="h-4 rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: color }}
              />
            </div>
            <span className="text-xs font-mono font-semibold text-slate-700 w-8 flex-shrink-0">
              {mean > 0 ? mean.toFixed(2) : '-'}
            </span>
          </div>
        )
      })}
      <div className="flex justify-between text-[10px] text-slate-400 px-36">
        <span>1 — Very Low</span>
        <span>7 — Very High</span>
      </div>
    </div>
  )
}
