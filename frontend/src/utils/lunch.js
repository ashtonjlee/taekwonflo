import { formatMinuteAsClock } from './timeline'

/** Per-ring synthetic lunch corridor after whichever event overlaps lunch anchor is done. */
export function ringLunchSpan(eventsSorted, tournament) {
  if (!eventsSorted?.length || !tournament) {
    return null
  }
  const ls = Number(tournament.lunch_start_minute ?? 180)
  const dur = Number(tournament.lunch_duration_minutes ?? 60)
  if (!dur) {
    return null
  }

  const anchor = eventsSorted.find((evt) => evt.start_minute <= ls && evt.end_minute > ls)

  let segStart
  if (anchor) {
    segStart = anchor.end_minute
  } else {
    segStart = ls
  }

  return {
    anchorEventId: anchor?.event_id || null,
    segStart,
    segEnd: segStart + dur,
    lunchWindowStart: ls,
    lunchWindowEnd: ls + dur,
  }
}

export function ringIsInsideLunch(currentMinute, lunchSpan) {
  if (!lunchSpan) {
    return false
  }
  return currentMinute >= lunchSpan.segStart && currentMinute < lunchSpan.segEnd
}

export function formatLunchWindowLabel(tournament, startClock = '09:00') {
  if (!tournament) {
    return ''
  }
  const ls = Number(tournament.lunch_start_minute ?? 180)
  const lend = ls + Number(tournament.lunch_duration_minutes ?? 60)
  return `${formatMinuteAsClock(ls, startClock)} – ${formatMinuteAsClock(lend, startClock)}`
}
