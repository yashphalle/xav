'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

interface FormData {
  device: string
  audio_ok: string
}

function playTestTone() {
  const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
  if (!AudioCtx) return
  const ctx = new AudioCtx()
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.type = 'sine'
  osc.frequency.setValueAtTime(440, ctx.currentTime)
  gain.gain.setValueAtTime(0.4, ctx.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 1.2)
  osc.start(ctx.currentTime)
  osc.stop(ctx.currentTime + 1.2)
  osc.onended = () => ctx.close()
}

export default function TechCheckPage() {
  const router = useRouter()
  const { register, handleSubmit } = useForm<FormData>()
  const [tonePlayed, setTonePlayed] = useState(false)

  function onSubmit(data: FormData) {
    const isMobile = data.device === 'mobile'
    const survey = getSurvey()
    const payload = {
      participant_id:  survey.participant_id,
      start_time:      survey.start_time,
      group_number:    survey.group_number,
      scenario_order:  survey.scenario_order,
      audio_ok:        data.audio_ok === 'yes',
      exclude_mobile:  isMobile,
    }
    setSurvey({ audio_ok: payload.audio_ok, exclude_mobile: isMobile })
    fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch(console.error)
    router.push('/demographics')
  }

  return (
    <PageWrapper title="Before We Begin">
      <p className="text-gray-600 mb-6">Please confirm the following before we start.</p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">

        {/* Q1 — Device type */}
        <div>
          <p className="section-title">
            Q1. What device are you using to complete this study?
          </p>
          <div className="mt-2 space-y-2">
            {[
              { value: 'computer', label: 'Desktop or laptop computer' },
              { value: 'mobile',   label: 'Mobile phone or tablet'     },
              { value: 'other',    label: 'Other'                      },
            ].map(({ value, label }) => (
              <label key={value} className="radio-row">
                <input
                  type="radio"
                  value={value}
                  {...register('device')}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="text-sm text-gray-700">{label}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Q2 — Audio test */}
        <div>
          <p className="section-title">
            Q2. Can you hear audio through your speakers or headphones?
          </p>
          <p className="text-sm text-gray-500 mt-1 mb-3">
            Click the button below to play a short test tone, then confirm whether you heard it.
          </p>
          <button
            type="button"
            onClick={() => { playTestTone(); setTonePlayed(true) }}
            className="mb-4 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm
                       font-medium rounded-lg border border-gray-300 transition-colors"
          >
            {tonePlayed ? 'Play again' : 'Play test tone'}
          </button>
          <div className="space-y-2">
            {[
              { value: 'yes', label: 'Yes, I heard the tone' },
              { value: 'no',  label: 'No, I did not hear anything' },
            ].map(({ value, label }) => (
              <label key={value} className="radio-row">
                <input
                  type="radio"
                  value={value}
                  {...register('audio_ok')}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="text-sm text-gray-700">{label}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">
            Continue →
          </button>
        </div>
      </form>
    </PageWrapper>
  )
}
