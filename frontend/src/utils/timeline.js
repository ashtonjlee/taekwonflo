export function formatMinuteAsClock(minuteOffset, tournamentStart = '09:00') {
  const [startHour, startMinute] = tournamentStart.split(':').map((value) => Number(value))
  const totalMinutes = startHour * 60 + startMinute + (Number(minuteOffset) || 0)
  const hour24 = Math.floor(totalMinutes / 60) % 24
  const minute = totalMinutes % 60
  const period = hour24 >= 12 ? 'PM' : 'AM'
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12
  return `${hour12}:${String(minute).padStart(2, '0')} ${period}`
}
