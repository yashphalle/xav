'use client'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData, getScenarioData } from '@/lib/survey-store'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'

const JIAN_ITEMS = [
  { id: 1, text: 'The system is deceptive.',                             reverse: true },
  { id: 2, text: 'The system behaves in an underhanded manner.',         reverse: true },
  { id: 3, text: "I am suspicious of the system's intent or output.",    reverse: true },
  { id: 4, text: 'I am wary of the system.',                             reverse: true },
  { id: 5, text: "The system's action will have a harmful outcome.",     reverse: true },
  { id: 6, text: 'I am confident in the system.',                        reverse: false },
  { id: 7, text: 'The system provides security.',                        reverse: false },
  { id: 8, text: 'The system has integrity.',                            reverse: false },
  { id: 9, text: 'The system is dependable.',                            reverse: false },
  { id: 10, text: 'The system is reliable.',                             reverse: false },
  { id: 11, text: 'I can trust the system.',                             reverse: false },
  { id: 12, text: 'I am familiar with the system.',                      reverse: false },
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

export default function JianTrustStep({ scenarioIndex }: { scenarioIndex: number }) {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()
  const [orderedItems, setOrderedItems] = useState(JIAN_ITEMS)
  const survey = getSurvey()

  useEffect(() => {
    // Each scenario gets its own jian shuffle — prevents position effects across scenarios
    const existing = getScenarioData(scenarioIndex).jian_order
    if (existing && existing.length === 12) {
      setOrderedItems(existing.map((i) => JIAN_ITEMS[i]))
    } else {
      const shuffled = shuffle([...Array(12).keys()])
      setScenarioData(scenarioIndex, { jian_order: shuffled })
      setOrderedItems(shuffled.map((i) => JIAN_ITEMS[i]))
    }
  }, [scenarioIndex])

  async function onSubmit(data: any) {
    const jianVals: Record<string, number> = {}
    for (const item of JIAN_ITEMS) {
      jianVals[`jian${item.id}`] = parseInt(data[`jian${item.id}`], 10)
    }
    const scores = JIAN_ITEMS.map((item) => {
      const raw = jianVals[`jian${item.id}`]
      return item.reverse ? 8 - raw : raw
    })
    const jian_composite = parseFloat((scores.reduce((a, b) => a + b, 0) / 12).toFixed(3))
    const jian_order = getScenarioData(scenarioIndex).jian_order

    const payload = { ...jianVals, jian_composite, jian_order }
    setScenarioData(scenarioIndex, payload)
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: survey.participant_id, scenario_index: scenarioIndex, ...payload }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 'jian-trust'))
  }

  return (
    <PageWrapper
      title="Trust in This System"
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('jian-trust'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <p className="section-note mb-1">
        Thinking about the autonomous vehicle system, based on the clip you just watched.
      </p>
      <p className="section-note mb-6">
        <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
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

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
