'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData } from '@/lib/survey-store'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'

export default function MentalModelStep({ scenarioIndex }: { scenarioIndex: number }) {
  const router = useRouter()
  const { register, handleSubmit, watch } = useForm<{ mental_model_text: string; mental_model_text2: string }>()
  const survey = getSurvey()
  const charCount = watch('mental_model_text', '').length

  async function onSubmit(data: any) {
    const payload = {
      mental_model_text: data.mental_model_text,
      mental_model_text2: data.mental_model_text2 ?? '',
    }
    setScenarioData(scenarioIndex, payload)
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: survey.participant_id, scenario_index: scenarioIndex, ...payload }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 'mental-model'))
  }

  return (
    <PageWrapper
      title="Your Understanding"
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('mental-model'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <p className="text-gray-500 text-sm mb-6">
        There are no right or wrong answers. We want your genuine understanding.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div>
          <label className="section-title block mb-2">
            In your own words, explain why you think the vehicle acted the way it did in this clip.
          </label>
          <textarea
            {...register('mental_model_text')}
            rows={5}
            placeholder="Describe what you think the vehicle was 'thinking'…"
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
          <span className="block text-right text-xs text-gray-400 mt-1">{charCount} chars</span>
        </div>

        <div>
          <label className="section-title block mb-1">
            What information do you think the vehicle used to make this decision?
          </label>
          <p className="text-xs text-gray-400 mb-2">Optional</p>
          <textarea
            {...register('mental_model_text2')}
            rows={3}
            placeholder="Optional: sensor data, camera feeds, etc."
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
