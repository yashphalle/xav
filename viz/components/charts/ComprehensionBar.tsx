'use client'

import React from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'

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

interface CompEntry { condition: string; accuracy: number; count: number }
interface Props { data: CompEntry[] }

const CONDITIONS = ['none', 'vlm_descriptive', 'vlm_teleological']

export default function ComprehensionBar({ data }: Props) {
  const entries = CONDITIONS.map((cond) => {
    const found = data.find((d) => d.condition === cond)
    const accuracy = found && !isNaN(found.accuracy) ? found.accuracy : 0
    return { condition: cond, accuracy, count: found?.count ?? 0 }
  })

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="flex gap-8 justify-center w-full">
        {entries.map(({ condition, accuracy, count }) => {
          const correct   = parseFloat(accuracy.toFixed(1))
          const incorrect = parseFloat((100 - accuracy).toFixed(1))
          const color     = CONDITION_COLORS[condition]
          const pieData   = [
            { name: 'Correct',   value: correct   },
            { name: 'Incorrect', value: incorrect  },
          ]
          return (
            <div key={condition} className="flex flex-col items-center gap-1">
              <div style={{ width: 120, height: 120 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={36}
                      outerRadius={54}
                      startAngle={90}
                      endAngle={-270}
                      dataKey="value"
                      strokeWidth={0}
                    >
                      <Cell fill={color} />
                      <Cell fill="#e2e8f0" />
                    </Pie>
                    <Tooltip
                      formatter={(v: number) => [`${v.toFixed(1)}%`]}
                      contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #e2e8f0' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <p className="text-lg font-bold font-mono" style={{ color }}>{correct.toFixed(1)}%</p>
              <p className="text-xs font-medium text-slate-600 text-center">{CONDITION_LABELS[condition]}</p>
              {count > 0 && <p className="text-[10px] text-slate-400">N = {count}</p>}
            </div>
          )
        })}
      </div>
      <p className="text-[10px] text-slate-400">% comprehension questions answered correctly</p>
    </div>
  )
}
