'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

const POINTS = [1, 2, 3, 4, 5, 6, 7]

export default function OverallTrustPage() {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()

  async function onSubmit(data: any) {
    const overall_trust = parseInt(data.overall_trust, 10)
    const payload = {
      overall_trust,
      end_time: new Date().toISOString(),
      completed: true,
    }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/complete')
  }

  return (
    <PageWrapper title="Overall Trust" step={10} totalSteps={10}>
      <p className="text-gray-500 text-sm mb-8">
        Now that you have watched all 5 clips, answer one final question about the system overall.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div>
          <p className="section-title mb-4">
            Overall, how much do you trust this autonomous vehicle system?
          </p>
          <p className="section-note mb-4">
            <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
          </p>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[400px] text-sm">
              <thead>
                <tr className="border-b-2 border-gray-200">
                  <th className="text-left pb-3 pr-4 w-[45%]" />
                  {POINTS.map((p) => (
                    <th key={p} className="text-center font-semibold text-gray-700 pb-3 px-1 w-10">{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-gray-100">
                  <td className="py-3 pr-4 text-gray-700">Overall trust in this AV system</td>
                  {POINTS.map((p) => (
                    <td key={p} className="text-center py-3 px-1">
                      <input
                        type="radio"
                        value={String(p)}
                        {...register('overall_trust')}
                        className="w-4 h-4 text-blue-600 cursor-pointer"
                      />
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">Complete Study →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
