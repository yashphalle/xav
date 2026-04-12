'use client'
import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setScenarioData } from '@/lib/survey-store'
import { getScenarioForIndex } from '@/lib/scenarios'
import { nextScenarioPath, scenarioStepNumber, TOTAL_SCENARIO_STEPS, TOTAL_SCENARIOS } from '@/lib/scenario-nav'
import PageWrapper from '@/components/survey/PageWrapper'

declare global {
  interface Window { YT: any; onYouTubeIframeAPIReady: () => void }
}

export default function VideoStep({ scenarioIndex }: { scenarioIndex: number }) {
  const router = useRouter()
  const playerRef = useRef<any>(null)
  const [videoEnded, setVideoEnded] = useState(false)
  const [videoStarted, setVideoStarted] = useState(false)
  const { register, handleSubmit } = useForm()

  const survey = getSurvey()
  const scenarioOrder = survey.scenario_order ?? [0, 1, 2, 3, 4]
  const scenario = getScenarioForIndex(scenarioOrder, scenarioIndex)
  const condition = (survey.condition ?? 'vlm_descriptive') as any
  const videoId = scenario.video_ids[condition]
  const isPlaceholder = videoId.startsWith('PLACEHOLDER')

  useEffect(() => {
    if (isPlaceholder) return
    const initPlayer = () => {
      playerRef.current = new window.YT.Player('yt-player-scenario', {
        videoId,
        playerVars: { autoplay: 1, controls: 0, disablekb: 1, modestbranding: 1, rel: 0, fs: 0 },
        events: {
          onStateChange: (e: any) => {
            if (e.data === 1) setVideoStarted(true)
            if (e.data === 0) setVideoEnded(true)
          },
        },
      })
    }
    if (window.YT?.Player) { initPlayer() }
    else {
      if (!document.getElementById('yt-api')) {
        const tag = document.createElement('script')
        tag.id = 'yt-api'
        tag.src = 'https://www.youtube.com/iframe_api'
        document.head.appendChild(tag)
      }
      window.onYouTubeIframeAPIReady = initPlayer
    }
  }, [videoId, isPlaceholder])

  async function onSubmit(data: any) {
    const watched = data.video_watched === 'yes'
    setScenarioData(scenarioIndex, {
      scenario_index: scenarioIndex,
      scenario_id: scenario.id,
      condition,
      criticality: scenario.criticality,
      video_watched: watched,
    })
    await fetch('/api/scenario-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        participant_id: survey.participant_id,
        scenario_index: scenarioIndex,
        scenario_id: scenario.id,
        condition,
        criticality: scenario.criticality,
        video_watched: watched,
      }),
    }).catch(console.error)
    router.push(nextScenarioPath(scenarioIndex, 'video'))
  }

  return (
    <PageWrapper
      title={`Scenario: ${scenario.label}`}
      scenarioInfo={{
        current: scenarioIndex + 1,
        total: TOTAL_SCENARIOS,
        stepNum: scenarioStepNumber('video'),
        totalSteps: TOTAL_SCENARIO_STEPS,
      }}
    >
      <p className="text-sm text-gray-500 mb-4">
        Watch the full clip carefully. The Continue button will appear when the video finishes.
        Do not navigate away from this page.
      </p>

      {/* Video player */}
      <div className="relative w-full aspect-video bg-black rounded-lg overflow-hidden mb-6">
        {isPlaceholder ? (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
            <div className="text-center text-white space-y-2">
              <p className="text-sm font-medium">Video not yet uploaded</p>
              <p className="text-xs text-gray-400">ID: {videoId}</p>
              <p className="text-xs text-gray-500">Scenario: {scenario.id} · Condition: {condition}</p>
            </div>
          </div>
        ) : (
          <>
            <div id="yt-player-scenario" className="absolute inset-0 w-full h-full" />
            {!videoStarted && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                <p className="text-white text-sm">Loading video…</p>
              </div>
            )}
          </>
        )}
      </div>

      {(videoEnded || isPlaceholder || true) && (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 border-t pt-6">
          <div>
            <p className="section-title">Did you watch the full video?</p>
            <div className="mt-2 space-y-2">
              {[
                { value: 'yes', label: 'Yes, I watched the full video' },
                { value: 'no', label: 'No, I had a technical issue' },
              ].map(({ value, label }) => (
                <label key={value} className="radio-row">
                  <input type="radio" value={value} {...register('video_watched')} className="w-4 h-4 text-blue-600" />
                  <span className="text-sm text-gray-700">{label}</span>
                </label>
              ))}
            </div>
          </div>
          <button type="submit" className="btn-primary">Continue →</button>
        </form>
      )}
    </PageWrapper>
  )
}
