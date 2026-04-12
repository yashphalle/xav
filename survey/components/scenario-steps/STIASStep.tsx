'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData } from '@/lib/survey-store'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'
import LikertMatrix from '@/components/survey/LikertMatrix'

// Perceived Transparency items — distinct from Jian Trust
const STIAS_ITEMS = [
  'I understood what the vehicle was doing in this clip.',
  "The vehicle's actions were predictable.",
  'I had a clear sense of why the vehicle acted as it did.',
]

export default function STIASStep({ scenarioIndex }: { scenarioIndex: number }) {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()
  const survey = getSurvey()

  async function onSubmit(data: any) {
    const stias1 = parseInt(data.stias1, 10)
    const stias2 = parseInt(data.stias2, 10)
    const stias3 = parseInt(data.stias3, 10)
    const stias_mean = parseFloat(((stias1 + stias2 + stias3) / 3).toFixed(3))

    const payload = { stias1, stias2, stias3, stias_mean }
    setScenarioData(scenarioIndex, payload)
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: survey.participant_id, scenario_index: scenarioIndex, ...payload }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 's-tias'))
  }

  return (
    <PageWrapper
      title="Perceived Transparency"
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('s-tias'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <p className="section-note">
        Rate how clearly you understood the vehicle's behavior in this clip.
        <br />
        <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <LikertMatrix
          items={STIAS_ITEMS}
          scale={7}
          namePrefix="stias"
          register={register}
          errors={errors}
        />

        {Object.keys(errors).length > 0 && (
          <p className="text-red-600 text-sm">Please answer all items before continuing.</p>
        )}

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
