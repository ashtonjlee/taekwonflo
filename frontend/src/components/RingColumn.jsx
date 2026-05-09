import EventCard from './EventCard'

export default function RingColumn({
  ringId,
  ringName,
  events = [],
  changedEventMap = {},
  currentMinute = 60,
  emergencySummary = null,
  tournamentStartTime = '09:00',
}) {
  const hasInProgress = events.some((event) => event.start_minute <= currentMinute && currentMinute < event.end_minute)
  const hasDelayed = events.some((event) => {
    const changeInfo = changedEventMap[event.event_id]
    return changeInfo && changeInfo.new_start_minute > changeInfo.original_start_minute
  })
  const isRingEmergency = ['medical_delay', 'ring_pause'].includes(emergencySummary?.emergency_type)
  const isPaused = isRingEmergency && emergencySummary?.affectedResource === ringId
  const hasChangedEvents = events.some((event) => changedEventMap[event.event_id])
  const nextEvent = events.find((event) => event.start_minute >= currentMinute)

  let ringStatus = 'idle'
  let ringStatusClass = 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'
  if (isPaused) {
    ringStatus = 'paused'
    ringStatusClass = 'bg-purple-100 text-purple-800 ring-1 ring-purple-200'
  } else if (hasDelayed) {
    ringStatus = 'delayed'
    ringStatusClass = 'bg-rose-100 text-rose-800 ring-1 ring-rose-200'
  } else if (hasInProgress) {
    ringStatus = 'active'
    ringStatusClass = 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200'
  }

  return (
    <div
      className={`min-h-64 rounded-xl border bg-white p-3 shadow-sm transition-all duration-300 hover:shadow-md ${
        hasChangedEvents ? 'border-amber-300 shadow-amber-100' : 'border-slate-200'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div>
          <h4 className="m-0 text-sm font-semibold text-slate-900">{ringName}</h4>
          <p className="mt-0.5 text-xs text-slate-500">
            {nextEvent
              ? `Next: ${nextEvent.division_name || nextEvent.division || 'event'} at T+${nextEvent.start_minute}`
              : 'No future calls'}
          </p>
        </div>
        <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${ringStatusClass}`}>
          {ringStatus}
        </span>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {events.length === 0 ? (
          <p className="text-xs text-slate-500">No events assigned yet.</p>
        ) : (
          events.map((event) => (
            <EventCard
              key={event.event_id || event.id}
              event={event}
              changeInfo={changedEventMap[event.event_id]}
              currentMinute={currentMinute}
              tournamentStartTime={tournamentStartTime}
            />
          ))
        )}
      </div>
    </div>
  )
}
