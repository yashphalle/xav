'use client'
import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

const VIDEO_ID = 'qwioQLk-JOM'

declare global {
  interface Window {
    YT: any
    onYouTubeIframeAPIReady: () => void
  }
}

export default function Video2Page() {
  const router = useRouter()
  const playerRef = useRef<any>(null)
  const [videoEnded, setVideoEnded] = useState(false)
  const [videoStarted, setVideoStarted] = useState(false)
  const { register, handleSubmit } = useForm()

  useEffect(() => {
    const initPlayer = () => {
      playerRef.current = new window.YT.Player('yt-player-2', {
        videoId: VIDEO_ID,
        playerVars: { autoplay: 1, controls: 0, disablekb: 1, modestbranding: 1, rel: 0, fs: 0 },
        events: {
          onStateChange: (event: any) => {
            if (event.data === 1) setVideoStarted(true)
            if (event.data === 0) setVideoEnded(true)
          },
        },
      })
    }

    if (window.YT?.Player) {
      initPlayer()
    } else {
      if (!document.getElementById('yt-api')) {
        const tag = document.createElement('script')
        tag.id = 'yt-api'
        tag.src = 'https://www.youtube.com/iframe_api'
        document.head.appendChild(tag)
      }
      window.onYouTubeIframeAPIReady = initPlayer
    }
  }, [])

  async function onSubmit() {
    setSurvey({ video_watched: true })
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, video_watched: true }),
    }).catch(console.error)
    router.push('/comprehension')
  }

  return (
    <PageWrapper title="Scenario — Part 2" step={4} totalSteps={10}>
      <p className="text-sm text-gray-500 mb-4">
        Watch this follow-up clip carefully. The Continue button will appear when the video finishes.
      </p>

      <div className="relative w-full aspect-video bg-black rounded-lg overflow-hidden mb-6">
        <div id="yt-player-2" className="absolute inset-0 w-full h-full" />
        {!videoStarted && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60">
            <p className="text-white text-sm">Loading video…</p>
          </div>
        )}
      </div>

      {(videoEnded || true) && (
        <form onSubmit={handleSubmit(onSubmit)} className="border-t pt-6">
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
