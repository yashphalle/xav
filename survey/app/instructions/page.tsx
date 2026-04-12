'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

const SCALE_OPTIONS = [
  'Strongly Disagree',
  'Disagree',
  'Neutral',
  'Agree',
  'Strongly Agree',
]

export default function InstructionsPage() {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()
  const [submitted, setSubmitted] = useState(false)

  async function onSubmit(data: any) {
    const ac1 = SCALE_OPTIONS.indexOf(data.ac1) + 1 // 1-5
    const attn_fail_1 = ac1 !== 5
    setSurvey({ ac1, attn_fail_1 })
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ac1, attn_fail_1 }),
    }).catch(console.error)
    router.push('/scenario/0/video')
  }

  return (
    <PageWrapper title="Attention Check &amp; Instructions" step={3} totalSteps={10}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">

        {/* Attention check */}
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-5">
          <p className="text-sm font-medium text-amber-900 mb-1">Attention Check</p>
          <p className="text-sm text-amber-800 mb-4">
            To confirm you are reading carefully, please select{' '}
            <strong>"Strongly Agree"</strong> for the item below regardless of your personal opinion.
          </p>
          <p className="text-sm font-medium text-gray-800 mb-3">
            "I am paying careful attention to this survey."
          </p>
          <div className="space-y-2">
            {SCALE_OPTIONS.map((opt) => (
              <label key={opt} className="radio-row">
                <input
                  type="radio"
                  value={opt}
                  {...register('ac1')}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="text-sm text-gray-700">{opt}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Video instructions */}
        <div className="space-y-3">
          <h2 className="section-title text-base">Video Task Instructions</h2>
          <p className="text-sm text-gray-600">
            You are about to watch <strong>5 short driving clips</strong> showing an autonomous
            vehicle in different situations. You will answer questions after each clip.
          </p>
          <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 space-y-1 border border-gray-200">
            <p className="font-medium mb-2">For each clip you will:</p>
            <ol className="list-decimal list-inside space-y-1 ml-1">
              <li>Watch the full video (Continue button appears only when it ends)</li>
              <li>Answer comprehension questions about what you saw</li>
              <li>Rate your experience and share your thoughts</li>
            </ol>
            <div className="mt-3 pt-3 border-t border-gray-200 space-y-1">
              <p className="font-medium">Important:</p>
              <ul className="list-disc list-inside space-y-1 ml-1">
                <li>Keep this browser window active while the video plays</li>
                <li>Do not use the Back button</li>
                <li>There are no right or wrong answers</li>
              </ul>
            </div>
          </div>
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">I Understand, Start →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
