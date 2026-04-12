'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData } from '@/lib/survey-store'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'

const SLIDERS = [
  { name: 'tlx_mental',      label: 'Mental Demand',  sublabel: 'How mentally demanding was evaluating this clip?', left: 'Very Low', right: 'Very High', reverse: false },
  { name: 'tlx_physical',    label: 'Physical Demand', sublabel: 'How physically demanding was this task?',          left: 'Very Low', right: 'Very High', reverse: false },
  { name: 'tlx_temporal',    label: 'Temporal Demand', sublabel: 'How hurried or rushed did you feel?',              left: 'Very Low', right: 'Very High', reverse: false },
  { name: 'tlx_performance', label: 'Performance',     sublabel: 'How successful were you in understanding this clip?', left: 'Perfect', right: 'Failure', reverse: true },
  { name: 'tlx_effort',      label: 'Effort',          sublabel: 'How hard did you work to understand this clip?',   left: 'Very Low', right: 'Very High', reverse: false },
  { name: 'tlx_frustration', label: 'Frustration',     sublabel: 'How irritated or stressed did you feel?',          left: 'Very Low', right: 'Very High', reverse: false },
]

const DEFAULTS: Record<string, number> = {
  tlx_mental: 50, tlx_physical: 50, tlx_temporal: 50,
  tlx_performance: 50, tlx_effort: 50, tlx_frustration: 50,
}

export default function NasaTlxStep({ scenarioIndex }: { scenarioIndex: number }) {
  const router = useRouter()
  const { register, handleSubmit, watch } = useForm({ defaultValues: DEFAULTS })
  const survey = getSurvey()

  async function onSubmit(data: any) {
    const vals: Record<string, number> = {}
    for (const [k, v] of Object.entries(data)) vals[k] = Number(v)
    const perfReversed = 100 - vals.tlx_performance
    const tlx_composite = parseFloat(
      ((vals.tlx_mental + vals.tlx_physical + vals.tlx_temporal + perfReversed + vals.tlx_effort + vals.tlx_frustration) / 6).toFixed(3)
    )
    const payload = { ...vals, tlx_composite }
    setScenarioData(scenarioIndex, payload)
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: survey.participant_id, scenario_index: scenarioIndex, ...payload }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 'nasa-tlx'))
  }

  return (
    <PageWrapper
      title="Task Experience (NASA-TLX)"
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('nasa-tlx'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <p className="section-note mb-6">
        Rate your experience watching and evaluating this clip. Drag each slider to your answer.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-7">
        {SLIDERS.map(({ name, label, sublabel, left, right, reverse }) => {
          const val = Number(watch(name as any) ?? 50)
          return (
            <div key={name} className="space-y-1">
              <p className="font-medium text-gray-800 text-sm">
                {label}
                {reverse && <span className="ml-2 text-xs font-normal text-gray-400">(reverse-scored)</span>}
              </p>
              <p className="text-xs text-gray-500">{sublabel}</p>
              <div className="flex items-center gap-3 mt-2">
                <span className="text-xs text-gray-500 w-16 text-right shrink-0">{left}</span>
                <input type="range" min={0} max={100} step={5} {...register(name as any)}
                  className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600" />
                <span className="text-xs text-gray-500 w-16 shrink-0">{right}</span>
              </div>
              <p className="text-center text-sm font-semibold text-blue-700">{val}</p>
            </div>
          )
        })}

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
