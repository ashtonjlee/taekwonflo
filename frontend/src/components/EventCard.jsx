import { formatDuration, formatMinuteRange, formatTournamentMinute, getEventStatus } from '../utils/timeline'

export default function EventCard({
  event,
  changeInfo,
  currentMinute = 60,
  isPaused = false,
  onSelectDivision,
  tournamentStartTime = '09:00',
  coordinationMatchNumber,
}) {
  const divisionName = event.division_name || event.division || 'Unknown division'
  const timeLabel =
    event.start_time && event.end_time
      ? `${event.start_time} - ${event.end_time}`
      : formatMinuteRange(event.start_minute, event.end_minute, tournamentStartTime)
  const minuteLabel = `${formatTournamentMinute(event.start_minute)} - ${formatTournamentMinute(event.end_minute)}`
  const hasChanges = Boolean(changeInfo)
  const statusLabel = getEventStatus(event, currentMinute, changeInfo, isPaused)
  const statusStyle = {
    completed: {
      badge: 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200',
      dot: 'bg-emerald-500',
    },
    'in progress': {
      badge: 'bg-blue-100 text-blue-800 ring-1 ring-blue-200',
      dot: 'bg-blue-500',
    },
    upcoming: {
      badge: 'bg-slate-100 text-slate-700 ring-1 ring-slate-200',
      dot: 'bg-slate-400',
    },
    rescheduled: {
      badge: 'bg-amber-100 text-amber-800 ring-1 ring-amber-200',
      dot: 'bg-amber-500',
    },
    paused: {
      badge: 'bg-purple-100 text-purple-800 ring-1 ring-purple-200',
      dot: 'bg-purple-500',
    },
  }[statusLabel]

  const changeLines = []
  if (changeInfo) {
    if (changeInfo.original_ring_id !== changeInfo.new_ring_id) {
      changeLines.push(`Moved: ${changeInfo.original_ring_id} -> ${changeInfo.new_ring_id}`)
    }
    if (changeInfo.original_start_minute !== changeInfo.new_start_minute) {
      changeLines.push(`Start changed: T+${changeInfo.original_start_minute} -> T+${changeInfo.new_start_minute}`)
    }
    if (changeInfo.original_referee_crew_id !== changeInfo.new_referee_crew_id) {
      changeLines.push(
        `Referee changed: ${changeInfo.original_referee_crew_id} -> ${changeInfo.new_referee_crew_id}`,
      )
    }
  }

  return (
    <button
      type="button"
      onClick={() => onSelectDivision?.(event)}
      className={`rounded-md border p-3 text-xs transition-all duration-300 ${
        hasChanges ? 'border-amber-300 bg-amber-50 shadow-sm shadow-amber-100' : 'border-slate-200 bg-slate-50'
      } w-full text-left hover:border-blue-300 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusStyle.dot}`} />
            <div className="truncate font-semibold text-slate-900">{divisionName}</div>
          </div>
          {coordinationMatchNumber !== undefined ? (
            <div className="mt-1 text-[11px] font-semibold text-slate-700">Match {coordinationMatchNumber}</div>
          ) : null}
          <div className="mt-1 text-[11px] font-medium text-slate-500">
            {formatDuration(event.start_minute, event.end_minute)}
          </div>
        </div>
        <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${statusStyle.badge}`}>
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
    </button>
  )
}
