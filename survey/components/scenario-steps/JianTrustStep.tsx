'use client'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData, getScenarioData } from '@/lib/survey-store'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'

// Jian et al. (2000) Trust in Automation scale — 7-item trust subscale only (items 6–12)
// Distrust subscale (items 1–5) omitted; trust subscale used standalone per Körber (2019)
const JIAN_ITEMS = [
  { id: 6,  text: 'I am confident in the system.'   },
  { id: 7,  text: 'The system provides security.'   },
  { id: 8,  text: 'The system has integrity.'        },
  { id: 9,  text: 'The system is dependable.'        },
  { id: 10, text: 'The system is reliable.'          },
  { id: 11, text: 'I can trust the system.'          },
  { id: 12, text: 'I am familiar with the system.'  },
]

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

const POINTS = [1, 2, 3, 4, 5, 6, 7]

export default function JianTrustStep({ scenarioIndex, condition }: { scenarioIndex: number; condition: string }) {
  const router = useRouter()
  const { register, handleSubmit } = useForm()
  const [orderedItems, setOrderedItems] = useState(JIAN_ITEMS)
  const survey = getSurvey()

  useEffect(() => {
    const existing = getScenarioData(scenarioIndex).jian_order
    if (existing && existing.length === 7) {
      setOrderedItems(existing.map((i) => JIAN_ITEMS[i]))
    } else {
      const shuffled = shuffle([...Array(7).keys()])
      setScenarioData(scenarioIndex, { jian_order: shuffled })
      setOrderedItems(shuffled.map((i) => JIAN_ITEMS[i]))
    }
  }, [scenarioIndex])

  async function onSubmit(data: any) {
    // Parse 7-item trust subscale responses (ids 6–12)
    const jianVals: Record<string, number> = {}
    for (const item of JIAN_ITEMS) {
      jianVals[`jian${item.id}`] = parseInt(data[`jian${item.id}`], 10)
    }

    // Trust mean — all 7 items are positive direction, no reversal needed
    const scores = JIAN_ITEMS.map(item => jianVals[`jian${item.id}`])
    const jian_trust_mean = parseFloat((scores.reduce((a, b) => a + b, 0) / 7).toFixed(3))
    const jian_composite  = jian_trust_mean   // composite = trust subscale mean
    const jian_distrust_mean = null            // distrust subscale not collected

    // Gyevnar calibration item
    const trust_calibration_item = parseInt(data.trust_calibration_item, 10)

    // Perceived safety
    const safety1 = parseInt(data.safety1, 10)
    const safety2 = parseInt(data.safety2, 10)
    // safety2 is reverse-scored ("risky") — average with reversal: (safety1 + (8 - safety2)) / 2
    const safety_mean = parseFloat(((safety1 + (8 - safety2)) / 2).toFixed(3))

    const jian_order = getScenarioData(scenarioIndex).jian_order

    const payload = {
      ...jianVals,
      jian_order,
      jian_composite,
      jian_trust_mean,
      jian_distrust_mean,
      trust_calibration_item,
      safety1,
      safety2,
      safety_mean,
    }

    setScenarioData(scenarioIndex, payload)
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: survey.participant_id, scenario_index: scenarioIndex, ...payload }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 'trust'))
  }

  const calibrationPrompt = condition !== 'none'
    ? "This explanation lets me judge when I should trust and not trust the vehicle."
    : "This clip lets me judge when I should trust and not trust the vehicle."

  return (
    <PageWrapper
      title="Trust in This System"
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('trust'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <p className="section-note mb-1">
        Thinking about the autonomous vehicle in the clip you just watched.
      </p>
      <p className="section-note mb-6">
        <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">

        {/* Jian 7-item trust subscale */}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b-2 border-gray-200">
                <th className="text-left font-medium text-gray-500 pb-3 pr-4 w-[55%]" />
                {POINTS.map((p) => (
                  <th key={p} className="text-center font-semibold text-gray-700 pb-3 px-1 w-10">{p}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orderedItems.map((item, idx) => {
                const fieldName = `jian${item.id}`
                return (
                  <tr key={item.id} className={`border-b border-gray-100 ${idx % 2 === 1 ? 'bg-gray-50/60' : ''}`}>
                    <td className="py-3 pr-4 text-gray-700 leading-snug">{idx + 1}.&nbsp;{item.text}</td>
                    {POINTS.map((p) => (
                      <td key={p} className="text-center py-3 px-1">
                        <input type="radio" value={String(p)}
                          {...register(fieldName)}
                          className="w-4 h-4 text-blue-600 cursor-pointer"
                        />
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Gyevnar calibration item */}
        <div>
          <p className="section-title mb-3">{calibrationPrompt}</p>
          <p className="section-note mb-3">
            <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[400px] text-sm">
              <thead>
                <tr className="border-b-2 border-gray-200">
                  <th className="text-left pb-3 pr-4 w-[55%]" />
                  {POINTS.map((p) => (
                    <th key={p} className="text-center font-semibold text-gray-700 pb-3 px-1 w-10">{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-gray-100">
                  <td className="py-3 pr-4 text-gray-700">{calibrationPrompt}</td>
                  {POINTS.map((p) => (
                    <td key={p} className="text-center py-3 px-1">
                      <input type="radio" value={String(p)}
                        {...register('trust_calibration_item')}
                        className="w-4 h-4 text-blue-600 cursor-pointer"
                      />
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Perceived Safety */}
        <div>
          <p className="section-title mb-3">About this specific situation</p>
          <p className="section-note mb-3">
            <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[400px] text-sm">
              <thead>
                <tr className="border-b-2 border-gray-200">
                  <th className="text-left pb-3 pr-4 w-[55%]" />
                  {POINTS.map((p) => (
                    <th key={p} className="text-center font-semibold text-gray-700 pb-3 px-1 w-10">{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { field: 'safety1', text: 'I felt safe during this clip.' },
                  { field: 'safety2', text: 'This situation seemed risky or dangerous to me.' },
                ].map(({ field, text }, idx) => (
                  <tr key={field} className={`border-b border-gray-100 ${idx % 2 === 1 ? 'bg-gray-50/60' : ''}`}>
                    <td className="py-3 pr-4 text-gray-700">{text}</td>
                    {POINTS.map((p) => (
                      <td key={p} className="text-center py-3 px-1">
                        <input type="radio" value={String(p)}
                          {...register(field)}
                          className="w-4 h-4 text-blue-600 cursor-pointer"
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
