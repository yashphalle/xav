'use client'

interface ScenarioInfo {
  current: number   // 1-indexed scenario number
  total: number     // total scenarios
  stepNum: number   // step within scenario (1-indexed)
  totalSteps: number
}

interface PageWrapperProps {
  title: string
  step?: number
  totalSteps?: number
  scenarioInfo?: ScenarioInfo
  children: React.ReactNode
}

export default function PageWrapper({
  title,
  step,
  totalSteps,
  scenarioInfo,
  children,
}: PageWrapperProps) {
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
      <div className="max-w-3xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span>Northeastern University · CS 6170</span>
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
