import { useEffect, useRef, useState } from 'react'
import { formatMinuteAsClock, formatTournamentMinute } from '../utils/timeline'

export default function LiveDemoControls({
  currentMinute,
  onSetMinute,
  onAdvanceTime,
  onReset,
  onInjectDelay,
  eventLog = [],
  maxMinute = 480,
}) {
  const [playing, setPlaying] = useState(false)
  const [speedMs, setSpeedMs] = useState(1000)
  const [randomEnabled, setRandomEnabled] = useState(false)
  const [manualType, setManualType] = useState('medical_delay')
  const timerRef = useRef(null)

  function clearTimer() {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  useEffect(() => {
    clearTimer()
    if (!playing) return undefined
    timerRef.current = window.setInterval(() => {
      const next = onAdvanceTime
        ? onAdvanceTime(15, randomEnabled)
        : Math.min(maxMinute, currentMinute + 15)
      if (!onAdvanceTime) onSetMinute(next)
      if (next >= maxMinute) {
        setPlaying(false)
        clearTimer()
      }
    }, speedMs)
    return () => {
      clearTimer()
    }
  }, [playing, speedMs, currentMinute, maxMinute, randomEnabled, onAdvanceTime, onSetMinute])

  function handlePause() {
    setPlaying(false)
    clearTimer()
  }

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Live Demo</p>
          <h2 className="m-0 mt-1 text-xl font-semibold text-slate-950">Tournament Time</h2>
          <p className="mt-2 text-sm text-slate-600">
            {formatTournamentMinute(currentMinute)} · {formatMinuteAsClock(currentMinute)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100" type="button" onClick={() => onAdvanceTime ? onAdvanceTime(15, false) : onSetMinute(Math.min(maxMinute, currentMinute + 15))}>+15 min</button>
          <button className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100" type="button" onClick={() => onAdvanceTime ? onAdvanceTime(60, false) : onSetMinute(Math.min(maxMinute, currentMinute + 60))}>+1 hour</button>
          <button className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100" type="button" onClick={() => setPlaying(true)}>Play</button>
          <button className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100" type="button" onClick={handlePause}>Pause</button>
          <button
            className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100"
            type="button"
            onClick={() => {
              handlePause()
              setManualType('medical_delay')
              setRandomEnabled(false)
              if (onReset) onReset()
              else onSetMinute(0)
            }}
          >
            Reset
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Speed
          <select value={speedMs} onChange={(event) => setSpeedMs(Number(event.target.value))} className="mt-1 block w-full rounded border border-slate-200 px-2 py-2 text-sm normal-case text-slate-800">
            <option value={1500}>Slow</option>
            <option value={1000}>Normal</option>
            <option value={400}>Fast</option>
          </select>
        </label>
        <label className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
          <input type="checkbox" checked={randomEnabled} onChange={(event) => setRandomEnabled(event.target.checked)} />
          Random delays
        </label>
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Manual delay
          <select value={manualType} onChange={(event) => setManualType(event.target.value)} className="mt-1 block w-full rounded border border-slate-200 px-2 py-2 text-sm normal-case text-slate-800">
            <option value="medical_delay">Medical</option>
            <option value="coach_conflict">Coach</option>
            <option value="referee_shortage">Referee</option>
          </select>
        </label>
        <button type="button" onClick={() => onInjectDelay(manualType, currentMinute, false)} className="rounded-md bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700">
          Inject delay now
        </button>
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Event log</div>
        <div className="mt-2 max-h-32 space-y-1 overflow-y-auto text-sm text-slate-700">
          {eventLog.length === 0 ? <div>No live events yet.</div> : eventLog.map((item) => <div key={item.id}>{item.text}</div>)}
        </div>
      </div>
    </section>
  )
}

export function shouldTriggerRandomDelay(nextMinute, previousMinute = nextMinute) {
  // Only consider a delay at the current advance window — never in the past.
  if (nextMinute <= previousMinute) return null
  const bucket = Math.floor(nextMinute / 60)
  const draw = seededDraw(`${bucket}:${nextMinute}`)
  if (draw < 0.05) return 'medical_delay'
  if (draw < 0.15) return 'referee_shortage'
  if (draw < 0.30) return 'coach_conflict'
  return null
}

function seededDraw(input) {
  let total = 0
  for (let idx = 0; idx < input.length; idx += 1) total += input.charCodeAt(idx) * (idx + 1)
  return (total % 100) / 100
}
