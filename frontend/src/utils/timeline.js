export function buildTimelineTicks(minMinute, maxMinute, spanMinutes) {
  if (spanMinutes <= 0) return []
  const minorEvery = spanMinutes <= 120 ? 10 : 15
  const majorEvery = spanMinutes <= 240 ? 30 : 60
  const start = Math.ceil(minMinute / minorEvery) * minorEvery
  const ticks = []
  for (let m = start; m <= maxMinute + minorEvery; m += minorEvery) {
    const major = m === 0 || m % majorEvery === 0
    ticks.push({ minute: m, major })
  }
  return ticks
}

export function formatMinuteAsClock(minuteOffset, tournamentStart = '09:00') {
  const [startHour, startMinute] = tournamentStart.split(':').map((value) => Number(value))
  const totalMinutes = startHour * 60 + startMinute + (Number(minuteOffset) || 0)
  const hour24 = Math.floor(totalMinutes / 60) % 24
  const minute = totalMinutes % 60
  const period = hour24 >= 12 ? 'PM' : 'AM'
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12
  return `${hour12}:${String(minute).padStart(2, '0')} ${period}`
}

export function formatMinuteRange(startMinute, endMinute, tournamentStart = '09:00') {
  return `${formatMinuteAsClock(startMinute, tournamentStart)} - ${formatMinuteAsClock(endMinute, tournamentStart)}`
}

export function formatDuration(startMinute, endMinute) {
  const duration = Math.max(0, Number(endMinute) - Number(startMinute))
  return `${duration} min`
}

export function formatTournamentMinute(minuteOffset) {
  return `T+${Number(minuteOffset) || 0}`
}

export function getScheduleEvents(schedule = []) {
  return schedule
    .flatMap((ring) =>
      (ring.events || []).map((event) => ({
        ...event,
        ring_id: event.ring_id || ring.ring_id,
        ring_name: event.ring_name || ring.ring_name,
      })),
    )
    .sort((first, second) => (first.start_minute ?? 0) - (second.start_minute ?? 0))
}

export function getMakespan(schedule = []) {
  const allEvents = getScheduleEvents(schedule)
  if (allEvents.length === 0) {
    return 0
  }
  return Math.max(...allEvents.map((event) => event.end_minute ?? 0))
}

export function isEventCompleted(event, currentMinute) {
  return Number(event.end_minute) <= Number(currentMinute)
}

export function isEventInProgress(event, currentMinute) {
  return Number(event.start_minute) <= Number(currentMinute) && Number(currentMinute) < Number(event.end_minute)
}

export function getEventStatus(event, currentMinute, changeInfo = null, isPaused = false) {
  if (isEventCompleted(event, currentMinute)) {
    return 'completed'
  }
  if (isPaused) {
    return 'paused'
  }
  if (isEventInProgress(event, currentMinute)) {
    return 'in progress'
  }
  if (changeInfo) {
    return 'rescheduled'
  }
  return 'upcoming'
}

export function getStagingGroups(events = [], currentMinute, limits = { warmUp: 10, holding: 25, onDeck: 45 }) {
  const futureEvents = events
    .filter((event) => Number(event.start_minute) >= Number(currentMinute))
    .sort((first, second) => (first.start_minute ?? 0) - (second.start_minute ?? 0))

  return [
    {
      id: 'warm-up',
      label: 'Warm Up Now',
      events: futureEvents.filter((event) => event.start_minute - currentMinute <= limits.warmUp).slice(0, 4),
    },
    {
      id: 'holding',
      label: 'In Holding',
      events: futureEvents
        .filter((event) => {
          const minutesUntilStart = event.start_minute - currentMinute
          return minutesUntilStart > limits.warmUp && minutesUntilStart <= limits.holding
        })
        .slice(0, 4),
    },
    {
      id: 'on-deck',
      label: 'On Deck',
      events: futureEvents
        .filter((event) => {
          const minutesUntilStart = event.start_minute - currentMinute
          return minutesUntilStart > limits.holding && minutesUntilStart <= limits.onDeck
        })
        .slice(0, 4),
    },
  ]
}
