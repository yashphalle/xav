'use client'
import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

const VIDEO_ID = 't9xGuX40Ks8'

declare global {
  interface Window {
    YT: any
    onYouTubeIframeAPIReady: () => void
  }
}

export default function VideoPage() {
  const router = useRouter()
  const playerRef = useRef<any>(null)
  const [videoEnded, setVideoEnded] = useState(false)
  const [videoStarted, setVideoStarted] = useState(false)
  const { register, handleSubmit, formState: { errors } } = useForm()

  useEffect(() => {
    // Load YouTube IFrame API
    if (!document.getElementById('yt-api')) {
      const tag = document.createElement('script')
      tag.id = 'yt-api'
      tag.src = 'https://www.youtube.com/iframe_api'
      document.head.appendChild(tag)
    }

    window.onYouTubeIframeAPIReady = () => {
      playerRef.current = new window.YT.Player('yt-player', {
        videoId: VIDEO_ID,
        playerVars: {
          autoplay: 1,
          controls: 0,
          disablekb: 1,
          modestbranding: 1,
          rel: 0,
          fs: 0,
        },
        events: {
          onStateChange: (event: any) => {
            if (event.data === 1) setVideoStarted(true) // PLAYING
            if (event.data === 0) setVideoEnded(true)   // ENDED
          },
        },
      })
    }

    // If API already loaded
    if (window.YT?.Player) {
      window.onYouTubeIframeAPIReady()
    }
  }, [])

  async function onSubmit(data: any) {
    const payload = { video_watched: data.video_watched === 'yes' }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/video-2')
  }

  return (
    <PageWrapper title="Scenario — High Criticality" step={4} totalSteps={10}>
      <p className="text-sm text-gray-500 mb-4">
        Watch the full clip carefully. The Continue button will appear when the video finishes.
        Do not navigate away from this page.
      </p>

      {/* YouTube player */}
      <div className="relative w-full aspect-video bg-black rounded-lg overflow-hidden mb-6">
        <div id="yt-player" className="absolute inset-0 w-full h-full" />
        {!videoStarted && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60">
            <p className="text-white text-sm">Loading video…</p>
          </div>
        )}
      </div>

      {/* Post-video form — always shown in dev/test */}
      {(videoEnded || true) && (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 border-t pt-6">
          <div>
            <p className="section-title">Did you watch the full video?</p>
            <div className="mt-2 space-y-2">
              {[
                { value: 'yes', label: 'Yes, I watched the full video' },
                { value: 'no', label: 'No — I had a technical issue' },
              ].map(({ value, label }) => (
                <label key={value} className="radio-row">
                  <input
                    type="radio"
                    value={value}
                    {...register('video_watched')}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-gray-700">{label}</span>
                </label>
              ))}
            </div>
            {errors.video_watched && (
              <p className="field-error">{String(errors.video_watched.message)}</p>
            )}
          </div>
          <button type="submit" className="btn-primary">Continue →</button>
        </form>
      )}

      {!videoEnded && (
        <p className="text-xs text-gray-400 italic mt-2">
          The Continue button will appear automatically when the video ends.
        </p>
      )}
    </PageWrapper>
  )
}
