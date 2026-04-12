'use client'
import VideoStep from '@/components/scenario-steps/VideoStep'
import ComprehensionStep from '@/components/scenario-steps/ComprehensionStep'
import STIASStep from '@/components/scenario-steps/STIASStep'
import NasaTlxStep from '@/components/scenario-steps/NasaTlxStep'
import MentalModelStep from '@/components/scenario-steps/MentalModelStep'
import JianTrustStep from '@/components/scenario-steps/JianTrustStep'
import ReflectionStep from '@/components/scenario-steps/ReflectionStep'

export default function ScenarioStepPage({
  params,
}: {
  params: { scenarioIndex: string; step: string }
}) {
  const { scenarioIndex: indexStr, step } = params
  const idx = parseInt(indexStr, 10)

  if (isNaN(idx) || idx < 0 || idx > 4) {
    return <div className="p-8 text-red-600">Invalid scenario index: {indexStr}</div>
  }

  switch (step) {
    case 'video':         return <VideoStep scenarioIndex={idx} />
    case 'comprehension': return <ComprehensionStep scenarioIndex={idx} />
    case 's-tias':        return <STIASStep scenarioIndex={idx} />
    case 'nasa-tlx':      return <NasaTlxStep scenarioIndex={idx} />
    case 'mental-model':  return <MentalModelStep scenarioIndex={idx} />
    case 'jian-trust':    return <JianTrustStep scenarioIndex={idx} />
    case 'reflection':    return <ReflectionStep scenarioIndex={idx} />
    default:
      return <div className="p-8 text-red-600">Unknown step: {step}</div>
  }
}
