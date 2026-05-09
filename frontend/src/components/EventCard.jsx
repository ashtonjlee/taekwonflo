import { formatDuration, formatMinuteRange } from '../utils/timeline'

export default function EventCard({ event, changeInfo, currentMinute = 60, tournamentStartTime = '09:00' }) {
  const divisionName = event.division_name || event.division || 'Unknown division'
  const timeLabel =
    event.start_time && event.end_time
      ? `${event.start_time} - ${event.end_time}`
      : formatMinuteRange(event.start_minute, event.end_minute, tournamentStartTime)
  const minuteLabel = `T+${event.start_minute} - T+${event.end_minute}`
  const hasChanges = Boolean(changeInfo)
  const isCompleted = event.end_minute <= currentMinute
  const isInProgress = event.start_minute <= currentMinute && currentMinute < event.end_minute
  const isRescheduled = Boolean(changeInfo)
  const isDelayed = changeInfo && changeInfo.new_start_minute > changeInfo.original_start_minute

  let statusLabel = 'upcoming'
  let statusClass = 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'
  let dotClass = 'bg-slate-400'
  if (isCompleted) {
    statusLabel = 'completed'
    statusClass = 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200'
    dotClass = 'bg-emerald-500'
  } else if (isInProgress) {
    statusLabel = 'live'
    statusClass = 'bg-blue-100 text-blue-800 ring-1 ring-blue-200'
    dotClass = 'bg-blue-500'
  } else if (isDelayed) {
    statusLabel = 'delayed'
    statusClass = 'bg-rose-100 text-rose-800 ring-1 ring-rose-200'
    dotClass = 'bg-rose-500'
  } else if (isRescheduled) {
    statusLabel = 'rescheduled'
    statusClass = 'bg-amber-100 text-amber-800 ring-1 ring-amber-200'
    dotClass = 'bg-amber-500'
  }

  const changeLines = []
  if (changeInfo) {
    if (changeInfo.original_ring_id !== changeInfo.new_ring_id) {
      changeLines.push(`Moved: ${changeInfo.original_ring_id} → ${changeInfo.new_ring_id}`)
    }
    if (changeInfo.original_start_minute !== changeInfo.new_start_minute) {
      changeLines.push(`Start changed: T+${changeInfo.original_start_minute} -> T+${changeInfo.new_start_minute}`)
    }
    if (changeInfo.original_referee_crew_id !== changeInfo.new_referee_crew_id) {
      changeLines.push(
        `Referee changed: ${changeInfo.original_referee_crew_id} → ${changeInfo.new_referee_crew_id}`,
      )
    }
  }

  return (
    <article
      className={`rounded-md border p-3 text-xs transition-all duration-300 ${
        hasChanges ? 'border-amber-300 bg-amber-50 shadow-sm shadow-amber-100' : 'border-slate-200 bg-slate-50'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dotClass}`} />
            <div className="truncate font-semibold text-slate-900">{divisionName}</div>
          </div>
          <div className="mt-1 text-[11px] font-medium text-slate-500">
            {formatDuration(event.start_minute, event.end_minute)}
          </div>
        </div>
        <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${statusClass}`}>
          {statusLabel}
        </span>
      </div>
      <div className="mt-2 rounded border border-white bg-white/80 p-2 text-slate-700">
        <div className="font-medium text-slate-900">{timeLabel}</div>
        <div className="mt-0.5 text-[11px] text-slate-500">{minuteLabel}</div>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-1 text-slate-600 sm:grid-cols-2">
        <div>{event.ring_name || event.ring_id}</div>
        <div>{event.referee_crew_name || event.referee_crew_id}</div>
        <div className="sm:col-span-2">Buffer: {event.buffer_minutes}m</div>
      </div>
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
