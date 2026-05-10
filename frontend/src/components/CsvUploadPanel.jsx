import { useEffect, useRef, useState } from 'react'

const CSV_STAGES = ['parsing data', 'building divisions', 'optimizing schedule', 'validating']

export default function CsvUploadPanel({ onImportCsv }) {
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState(null)
  const stageTimerRef = useRef(null)

  function startStageTicker() {
    let idx = 0
    setStage(CSV_STAGES[idx])
    stageTimerRef.current = window.setInterval(() => {
      idx = Math.min(idx + 1, CSV_STAGES.length - 1)
      setStage(CSV_STAGES[idx])
    }, 1500)
  }

  function stopStageTicker() {
    if (stageTimerRef.current !== null) {
      window.clearInterval(stageTimerRef.current)
      stageTimerRef.current = null
    }
  }

  useEffect(() => () => stopStageTicker(), [])

  async function submit(nextFile = file) {
    if (!nextFile) return
    setLoading(true)
    setStatus(null)
    startStageTicker()
    try {
      const result = await onImportCsv(nextFile)
      stopStageTicker()
      setStage('complete')
      setStatus({ type: 'ok', preview: result.preview, diagnostics: result.diagnostics })
    } catch (error) {
      stopStageTicker()
      setStage('error')
      setStatus({ type: 'error', message: error.message })
    } finally {
      setLoading(false)
    }
  }

  function handleDrop(event) {
    event.preventDefault()
    const dropped = event.dataTransfer.files?.[0]
    if (dropped) {
      setFile(dropped)
      void submit(dropped)
    }
  }

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">CSV Import</p>
          <h2 className="m-0 mt-1 text-xl font-semibold text-slate-950">Upload Existing Tournament</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Drop a CSV with athlete, team, coach, division, belt, age, weight, and event columns. Missing optional fields use safe demo defaults.
          </p>
        </div>
        <button
          type="button"
          disabled={!file || loading}
          onClick={() => submit()}
          className="w-fit rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? 'Generating...' : 'Generate Schedule from CSV'}
        </button>
      </div>

      <label
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-center hover:border-blue-300 hover:bg-blue-50"
      >
        <input
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(event) => {
            const selected = event.target.files?.[0]
            if (selected) setFile(selected)
          }}
        />
        <span className="text-sm font-semibold text-slate-800">{file ? file.name : 'Drop CSV here or select a file'}</span>
        <span className="mt-1 text-xs text-slate-500">Expected columns include athlete_name, team_name, coach_name, gender, age_group, belt_rank, weight_class, event_type, division_name.</span>
      </label>

      {loading ? <ProgressBar stages={CSV_STAGES} stage={stage} /> : null}

      {status?.type === 'error' ? (
        <div className="mt-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">{status.message}</div>
      ) : null}
      {status?.type === 'ok' ? <CsvPreview preview={status.preview} diagnostics={status.diagnostics} /> : null}
    </section>
  )
}

function ProgressBar({ stages, stage }) {
  const idx = Math.max(0, stages.indexOf(stage))
  const pct = Math.round(((idx + 1) / stages.length) * 100)
  return (
    <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
      <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide">
        <span>{stage || stages[0]}</span>
        <span>{pct}%</span>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-blue-100">
        <div className="h-full rounded-full bg-blue-500 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {stages.map((label, position) => (
          <span
            key={label}
            className={`rounded-full px-2 py-0.5 ${
              position <= idx ? 'bg-blue-200 text-blue-900' : 'bg-white text-slate-500 border border-slate-200'
            }`}
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}

function CsvPreview({ preview, diagnostics }) {
  const fallbackUsed = Boolean(preview?.fallback_used ?? diagnostics?.fallback_used)
  const solverStatus = preview?.solver_status || diagnostics?.solver_status || 'OK'
  return (
    <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm">
      <div className="font-semibold text-emerald-950">
        CSV schedule generated{fallbackUsed ? ' (relaxed_import_mode)' : ''}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <PreviewMetric label="Athletes" value={preview?.athlete_count || 0} />
        <PreviewMetric label="Teams" value={preview?.team_count || 0} />
        <PreviewMetric label="Divisions" value={preview?.division_count || 0} />
        <PreviewMetric label="Solver" value={solverStatus} />
      </div>
      {preview?.detected_columns?.length ? (
        <div className="mt-3 text-xs text-emerald-900">Detected: {preview.detected_columns.join(', ')}</div>
      ) : null}
      {preview?.warnings?.length ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-900">
          {preview.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {fallbackUsed ? (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
          Strict CP-SAT scheduling failed; a relaxed greedy schedule was produced. Ring/athlete/coach overlap is still
          enforced. Referee shortages and judge counts are warned about above.
        </div>
      ) : null}
    </div>
  )
}

function PreviewMetric({ label, value }) {
  return (
    <div className="rounded-md border border-emerald-200 bg-white p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">{label}</div>
      <div className="mt-1 text-lg font-bold text-emerald-950">{value}</div>
    </div>
  )
}
