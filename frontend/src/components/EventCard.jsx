import { formatMinuteAsClock } from '../utils/timeline'

export default function EventCard({ event, changeInfo, currentMinute = 60, tournamentStartTime = '09:00' }) {
  const divisionName = event.division_name || event.division || 'Unknown division'
  const startLabel =
    event.start_time ?? `${formatMinuteAsClock(event.start_minute, tournamentStartTime)} (T+${event.start_minute})`
  const endLabel =
    event.end_time ?? `${formatMinuteAsClock(event.end_minute, tournamentStartTime)} (T+${event.end_minute})`
  const hasChanges = Boolean(changeInfo)
  const isCompleted = event.end_minute <= currentMinute
  const isInProgress = event.start_minute <= currentMinute && currentMinute < event.end_minute
  const isRescheduled = Boolean(changeInfo)
  const isDelayed = changeInfo && changeInfo.new_start_minute > changeInfo.original_start_minute

  let statusLabel = 'upcoming'
  let statusClass = 'bg-slate-100 text-slate-700'
  if (isCompleted) {
    statusLabel = 'completed'
    statusClass = 'bg-emerald-100 text-emerald-800'
  } else if (isInProgress) {
    statusLabel = 'in_progress'
    statusClass = 'bg-blue-100 text-blue-800'
  } else if (isDelayed) {
    statusLabel = 'delayed'
    statusClass = 'bg-rose-100 text-rose-800'
  } else if (isRescheduled) {
    statusLabel = 'rescheduled'
    statusClass = 'bg-amber-100 text-amber-800'
  }

  const changeLines = []
  if (changeInfo) {
    if (changeInfo.original_ring_id !== changeInfo.new_ring_id) {
      changeLines.push(`Moved: ${changeInfo.original_ring_id} → ${changeInfo.new_ring_id}`)
    }
    if (changeInfo.original_start_minute !== changeInfo.new_start_minute) {
      changeLines.push(`Start changed: ${changeInfo.original_start_minute} → ${changeInfo.new_start_minute}`)
    }
    if (changeInfo.original_referee_crew_id !== changeInfo.new_referee_crew_id) {
      changeLines.push(
        `Referee changed: ${changeInfo.original_referee_crew_id} → ${changeInfo.new_referee_crew_id}`,
      )
    }
  }

  return (
    <article
      className={`rounded-md border p-2 text-xs ${hasChanges ? 'border-amber-300 bg-amber-50' : 'border-blue-100 bg-blue-50'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-blue-800">{divisionName}</div>
        <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${statusClass}`}>
          {statusLabel}
        </span>
      </div>
      <div className="mt-1 text-slate-700">
        {startLabel} - {endLabel}
      </div>
      <div className="text-slate-600">{event.ring_name || event.ring_id}</div>
      <div className="text-slate-600">{event.referee_crew_name || event.referee_crew_id}</div>
      <div className="text-slate-600">Buffer: {event.buffer_minutes}m</div>
      {changeLines.length > 0 ? (
        <div className="mt-2 space-y-1 rounded border border-amber-300 bg-amber-100 p-2 text-amber-900 transition-all duration-300">
          {changeLines.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
      ) : null}
    </article>
  )
}
