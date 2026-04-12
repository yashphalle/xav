'use client'
import { useRouter } from 'next/navigation'

interface ScenarioInfo {
  current: number
  total: number
  stepNum: number
  totalSteps: number
}

interface PageWrapperProps {
  title: string
  step?: number
  totalSteps?: number
  scenarioInfo?: ScenarioInfo
  wide?: boolean
  children: React.ReactNode
}

export default function PageWrapper({
  title,
  step,
  totalSteps,
  scenarioInfo,
  wide = false,
  children,
}: PageWrapperProps) {
  const router = useRouter()

  const pct = step && totalSteps
    ? Math.round((step / totalSteps) * 100)
    : scenarioInfo
    ? Math.round((scenarioInfo.current / scenarioInfo.total) * 100)
    : null

  const stepLabel = scenarioInfo
    ? `Scenario ${scenarioInfo.current} of ${scenarioInfo.total} · Step ${scenarioInfo.stepNum} of ${scenarioInfo.totalSteps}`
    : step && totalSteps
    ? `Step ${step} of ${totalSteps}`
    : null

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className={`${wide ? 'max-w-5xl' : 'max-w-3xl'} mx-auto space-y-4`}>

        {/* Header */}
        <div className="flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.back()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                         bg-gray-200 hover:bg-gray-300 text-gray-700 hover:text-gray-900
                         text-xs font-medium transition-colors"
            >
              ← Back
            </button>
            <span>Northeastern University · CS 6170</span>
          </div>
          {stepLabel && <span>{stepLabel}</span>}
        </div>

        {/* Progress bar */}
        {pct !== null && (
          <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
        )}

        {/* Card */}
        <div className="card">
          <h1 className="text-xl font-semibold text-gray-900 mb-6">{title}</h1>
          {children}
        </div>

        <p className="text-center text-xs text-gray-400">
          Autonomous Vehicle Passenger Study · Anonymous &amp; Voluntary
        </p>
      </div>
    </div>
  )
}
