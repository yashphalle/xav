'use client'
import { UseFormRegister } from 'react-hook-form'

interface LikertMatrixProps {
  items: string[]
  scale: 5 | 7
  namePrefix: string
  register: UseFormRegister<any>
  errors?: Record<string, any>
}

export default function LikertMatrix({
  items,
  scale,
  namePrefix,
  register,
  errors,
}: LikertMatrixProps) {
  const points = Array.from({ length: scale }, (_, i) => i + 1)

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="border-b-2 border-gray-200">
            <th className="text-left font-medium text-gray-500 pb-3 pr-4 w-[55%]" />
            {points.map((p) => (
              <th key={p} className="text-center font-semibold text-gray-700 pb-3 px-1 w-10">
                {p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            const name = `${namePrefix}${idx + 1}`
            const hasError = !!errors?.[name]
            return (
              <tr
                key={idx}
                className={`border-b border-gray-100 ${
                  hasError ? 'bg-red-50' : idx % 2 === 1 ? 'bg-gray-50/60' : ''
                }`}
              >
                <td className="py-3 pr-4 text-gray-700 leading-snug">
                  {idx + 1}.&nbsp;{item}
                </td>
                {points.map((p) => (
                  <td key={p} className="text-center py-3 px-1">
                    <input
                      type="radio"
                      value={String(p)}
                      {...register(name)}
                      className="w-4 h-4 text-blue-600 cursor-pointer"
                    />
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
