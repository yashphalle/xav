'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData } from '@/lib/survey-store'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'
import LikertMatrix from '@/components/survey/LikertMatrix'

const EXPL_ITEMS = [
  'The explanation was clear.',
  "The explanation helped me understand the vehicle's action.",
  "The explanation made me feel more informed about the vehicle's decision.",
]

const POINTS = [1, 2, 3, 4, 5, 6, 7]

export default function ReflectionStep({ scenarioIndex }: { scenarioIndex: number }) {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()
  const survey = getSurvey()
  const condition = survey.condition ?? 'none'
  const showExplanation = condition !== 'none'

  async function onSubmit(data: any) {
    const anthropomorphism = parseInt(data.anthropomorphism, 10)

    const payload: Record<string, any> = { anthropomorphism }

    if (showExplanation) {
      // LikertMatrix uses namePrefix="expl" → fields: expl1, expl2, expl3
      const expl_clear    = parseInt(data.expl1, 10)
      const expl_helpful  = parseInt(data.expl2, 10)
      const expl_informed = parseInt(data.expl3, 10)
      const expl_mean = parseFloat(((expl_clear + expl_helpful + expl_informed) / 3).toFixed(3))
      Object.assign(payload, { expl_clear, expl_helpful, expl_informed, expl_mean })
    }

    setScenarioData(scenarioIndex, payload)
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: survey.participant_id, scenario_index: scenarioIndex, ...payload }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 'reflection'))
  }

  return (
    <PageWrapper
      title="Reflection"
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('reflection'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">

        {/* Explanation helpfulness — only for non-none conditions */}
        {showExplanation && (
          <div>
            <p className="section-title mb-1">About the explanation you received</p>
            <p className="section-note mb-4">
              <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
            </p>
            <LikertMatrix
              items={EXPL_ITEMS}
              scale={7}
              namePrefix="expl"
              register={register}
              errors={errors}
            />
          </div>
        )}

        {/* Anthropomorphism — all conditions */}
        <div>
          <p className="section-title mb-3">
            "The vehicle seemed to be acting with intention."
          </p>
          <p className="section-note mb-4">
            <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[400px] text-sm">
              <thead>
                <tr className="border-b-2 border-gray-200">
                  <th className="text-left pb-3 pr-4 w-[50%]" />
                  {POINTS.map((p) => (
                    <th key={p} className="text-center font-semibold text-gray-700 pb-3 px-1 w-10">{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-gray-100">
                  <td className="py-3 pr-4 text-gray-700">The vehicle seemed to be acting with intention.</td>
                  {POINTS.map((p) => (
                    <td key={p} className="text-center py-3 px-1">
                      <input
                        type="radio"
                        value={String(p)}
                        {...register('anthropomorphism')}
                        className="w-4 h-4 text-blue-600 cursor-pointer"
                      />
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">
            {scenarioIndex < TOTAL_SCENARIOS - 1 ? 'Next Scenario →' : 'Finish Scenarios →'}
          </button>
        </div>
      </form>
    </PageWrapper>
  )
}
