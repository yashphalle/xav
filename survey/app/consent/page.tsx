'use client'
import { useRouter } from 'next/navigation'
import { v4 as uuidv4 } from 'uuid'
import { setSurvey } from '@/lib/survey-store'
import { CONDITIONS, shuffleIndices, SCENARIOS } from '@/lib/scenarios'
import Image from 'next/image'

const SECTIONS = [
  {
    label: 'Purpose',
    text: 'We are studying how explanations of autonomous vehicle actions affect passenger trust and understanding. The full purpose will be explained at the end.',
  },
  {
    label: 'Procedures',
    text: 'You will watch 5 short simulated driving clips showing an autonomous vehicle in different situations, and answer questions after each clip. The study takes approximately 20–25 minutes.',
  },
  {
    label: 'Risks',
    text: 'Minimal risk. The clips depict an autonomous vehicle navigating various driving situations and may be mildly surprising.',
  },
  {
    label: 'Confidentiality',
    text: 'Your responses are anonymous. Data are stored securely and accessible only to the research team at Northeastern University.',
  },
  {
    label: 'Voluntary',
    text: 'Participation is completely voluntary. You may withdraw at any time without penalty.',
  },
  {
    label: 'Deception Notice',
    text: 'This study involves partial concealment of its full purpose. A complete explanation will be provided at the end of the study.',
  },
]

export default function ConsentPage() {
  const router = useRouter()

  function handleAgree() {
    const participant_id = uuidv4()
    const start_time = new Date().toISOString()
    const condition = CONDITIONS[Math.floor(Math.random() * CONDITIONS.length)]
    const scenario_order = shuffleIndices(SCENARIOS.length)
    setSurvey({ participant_id, start_time, condition, scenario_order })
    fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id, start_time, condition, scenario_order }),
    }).catch(console.error)
    router.push('/tech-check')
  }

  function handleDecline() {
    router.push('/exit')
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">

      {/* Hero */}
      <div className="relative w-full h-56 overflow-hidden">
        <Image
          src="/ppt-images/image2.jpeg"
          alt="Autonomous vehicle sensor visualization"
          fill
          className="object-cover object-center opacity-60"
          priority
        />
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-b from-slate-950/30 via-slate-950/20 to-slate-950" />

        {/* Title over image */}
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4 pb-4">
          <p className="text-blue-400 text-xs uppercase tracking-widest font-medium mb-2">
            Northeastern University · CS 6170 · HRI Team
          </p>
          <h1 className="text-white text-2xl md:text-3xl font-semibold leading-snug max-w-xl">
            Explainability in Autonomous Vehicles
          </h1>
          <p className="text-slate-300 text-sm mt-1 max-w-md">
            Do Explanations of AV Actions Improve Passenger Trust Calibration?
          </p>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 flex justify-center px-4 py-8">
        <div className="w-full max-w-2xl space-y-5">

          {/* PI */}
          <div className="text-xs text-slate-500">
            <span>Meet Jain &amp; Yash Phalle</span>
          </div>

          {/* Consent card */}
          <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
              <div className="px-5 py-3 border-b border-white/10">
                <h2 className="text-white text-xs font-semibold uppercase tracking-widest">
                  Informed Consent
                </h2>
              </div>
              <div className="divide-y divide-white/5">
                {SECTIONS.map(({ label, text }) => (
                  <div key={label} className="px-5 py-3 flex gap-3">
                    <span className="text-slate-500 text-xs font-semibold uppercase tracking-wide w-24 shrink-0 pt-0.5">
                      {label}
                    </span>
                    <p className="text-slate-300 text-sm leading-relaxed">{text}</p>
                  </div>
                ))}
                <div className="px-5 py-3 flex gap-3">
                  <span className="text-slate-500 text-xs font-semibold uppercase tracking-wide w-24 shrink-0 pt-0.5">
                    Contact
                  </span>
                  <div className="text-slate-400 text-xs space-y-0.5">
                    <p>Meet Jain &amp; Yash Phalle</p>
                    <p>Northeastern University</p>
                    <p className="text-slate-600">IRB Protocol: [XXXX]</p>
                  </div>
                </div>
              </div>
          </div>

          {/* Consent buttons */}
          <div className="bg-white/5 border border-white/10 rounded-2xl px-5 py-4 space-y-3">
            <p className="text-white text-sm font-medium">
              Do you agree to participate in this study?
            </p>
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                onClick={handleAgree}
                className="flex-1 py-3 px-6 bg-blue-500 hover:bg-blue-400 text-white font-medium
                           rounded-xl text-sm transition-all focus:outline-none focus:ring-2
                           focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-slate-950
                           shadow-lg shadow-blue-500/20"
              >
                I agree to participate →
              </button>
              <button
                onClick={handleDecline}
                className="flex-1 py-3 px-6 bg-white/5 hover:bg-white/10 text-slate-400
                           font-medium rounded-xl text-sm border border-white/10 transition-colors"
              >
                I do not wish to participate
              </button>
            </div>
          </div>

          <p className="text-center text-slate-700 text-xs">
            Anonymous &amp; voluntary · Northeastern University
          </p>
        </div>
      </div>
    </div>
  )
}
