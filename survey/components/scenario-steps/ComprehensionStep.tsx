'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData } from '@/lib/survey-store'
import { getScenarioForIndex } from '@/lib/scenarios'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'

export default function ComprehensionStep({ scenarioIndex }: { scenarioIndex: number }) {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()

  const survey = getSurvey()
  const scenarioOrder = survey.scenario_order ?? [0, 1, 2, 3, 4]
  const scenario = getScenarioForIndex(scenarioOrder, scenarioIndex)

  async function onSubmit(data: any) {
    const q = scenario.comprehension
    const comp1_correct = data.comp1 === q[0].correct
    const comp2_correct = data.comp2 === q[1].correct
    const comp3_correct = data.comp3 === q[2].correct
    const comp_score = [comp1_correct, comp2_correct, comp3_correct].filter(Boolean).length
    const comp_fail = comp_score < 1

    const payload = {
      comp1: data.comp1, comp2: data.comp2, comp3: data.comp3,
      comp1_correct, comp2_correct, comp3_correct, comp_score, comp_fail,
    }
    setScenarioData(scenarioIndex, payload)
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: survey.participant_id, scenario_index: scenarioIndex, ...payload }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 'comprehension'))
  }

  return (
    <PageWrapper
      title="Comprehension Check"
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('comprehension'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <p className="text-gray-500 text-sm mb-6">
        Based on the clip you just watched, answer the following questions.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-7">
        {scenario.comprehension.map(({ name, question, options }) => (
          <div key={name}>
            <p className="section-title">{question}</p>
            <div className="mt-2 space-y-2">
              {options.map((opt) => (
                <label key={opt} className="radio-row">
                  <input
                    type="radio"
                    value={opt}
                    {...register(name)}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-gray-700">{opt}</span>
                </label>
              ))}
            </div>
          </div>
        ))}

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
