import { formatTournamentMinute } from '../utils/timeline'

const PHASE_ORDER = ['warm_up_now', 'report_holding', 'report_staging', 'currently_competing', 'completed']

const PHASE_LABELS = {
  warm_up_now: 'Warm up now',
  report_holding: 'Report to holding',
  report_staging: 'Report to staging',
  currently_competing: 'Currently competing',
  completed: 'Finished / completed',
}

function urgencyTone(u) {
  if (u === 'now') return 'bg-rose-50 text-rose-900 ring-rose-200'
  if (u === 'soon') return 'bg-amber-50 text-amber-900 ring-amber-200'
  return 'bg-slate-50 text-slate-700 ring-slate-200'
}

function CoordinatorRow({ row, onSelectDivision }) {
  return (
    <button
      type="button"
      onClick={() =>
        onSelectDivision?.({
          division_id: row.division_id,
          division_name: row.division_name,
          focus_match_id: row.match_id,
        })
      }
      className="w-full rounded border border-slate-200 bg-white p-2 text-left text-[11px] shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50/40 focus:outline-none focus:ring-2 focus:ring-blue-400"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-slate-900">
          Match {row.match_number} · {row.division_name}
        </div>
        <span className={`rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide ring-1 ${urgencyTone(row.urgency)}`}>
          {row.urgency}
        </span>
      </div>
      <div className="mt-1 text-slate-600">
        {row.ring_name} • {formatTournamentMinute(row.start_minute)}
      </div>
      <div className="mt-1 font-medium text-blue-950">{(row.athlete_display || []).join(' · ') || 'Entries pending'}</div>
      <div className="mt-1 text-slate-500">Teams {(row.team_names || []).join(', ') || 'n/a'}</div>
      <div className="mt-1 text-slate-500">Coaches {(row.coach_labels || []).join(', ') || 'n/a'}</div>
      <span className="sr-only">Open division detail highlighting this contest</span>
    </button>
  )
}

function CoordinatorBuckets({ coordinationBoard, onSelectDivision }) {
  const rows = coordinationBoard?.rows || []
  const grouped = PHASE_ORDER.reduce((acc, phase) => {
    acc[phase] = rows.filter((row) => row.phase === phase)
    return acc
  }, {})

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
      {PHASE_ORDER.map((phase) => (
        <div key={phase} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-700">{PHASE_LABELS[phase]}</div>
          <div className="mt-2 max-h-80 space-y-2 overflow-auto">
            {grouped[phase].length === 0 ? (
              <div className="text-[11px] text-slate-500">Nothing queued.</div>
            ) : (
              grouped[phase].map((row) => <CoordinatorRow key={`${phase}-${row.match_id}`} row={row} onSelectDivision={onSelectDivision} />)
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function LiveReportsSection({
  coordinationBoard = null,
  scheduleChanges = [],
  refereeAdjustments = [],
  onCoordinatorSelect,
}) {
  return (
    <section className="space-y-5 rounded-xl bg-white p-5 shadow">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Event coordinator</p>
        <p className="mt-1 text-sm text-slate-600">
          Operational calls at tournament minute{' '}
          <span className="font-semibold text-slate-900">{formatTournamentMinute(coordinationBoard?.current_minute ?? 0)}</span>
        </p>
      </div>

      <CoordinatorBuckets coordinationBoard={coordinationBoard} onSelectDivision={onCoordinatorSelect} />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-4">
          <div className="text-sm font-semibold text-amber-950">Schedule changes</div>
          {scheduleChanges.length === 0 ? (
            <p className="mt-2 text-xs text-amber-900">No enumerated deltas for this view.</p>
          ) : (
            <div className="mt-3 max-h-72 space-y-3 overflow-auto text-xs">
              {scheduleChanges.map((row, idx) => (
                <div key={`sch-${idx}-${row.event_id}`} className="rounded-md border border-amber-200 bg-white p-3 shadow-sm">
                  <div className="font-semibold text-slate-900">
                    {row.affected_match_numbers?.length
                      ? `Matches ${row.affected_match_numbers.slice(0, 8).join(', ')} · `
                      : null}
                    {row.division_name}{' '}
                    <span className="font-normal text-slate-600">event {row.event_id}</span>
                  </div>
                  <div className="mt-1 text-[11px] uppercase tracking-wide text-slate-500">
                    {(row.match_breakdown || []).slice(0, 6).join(' · ') || 'Match detail via division panel'}
                  </div>
                  <div className="mt-1 text-slate-700">{(row.athlete_summaries || []).join(', ') || 'Athletes unspecified'}</div>
                  <div className="mt-1 text-slate-700">Coaches {(row.coach_names_involved || []).join(', ') || 'None listed'}</div>
                  <div className="mt-2 grid gap-1 sm:grid-cols-2">
                    <div className="text-slate-600">
                      Ring:{' '}
                      <span className="font-semibold">{row.original_ring_name || row.original_ring_id}</span> →{' '}
                      <span className="font-semibold">{row.new_ring_name || row.new_ring_id}</span>
                    </div>
                    <div className="text-slate-600">
                      Start T+{row.original_start_minute} → T+{row.new_start_minute}
                    </div>
                  </div>
                  <div className="mt-1 text-[11px] text-slate-600">
                    Ref crew {(row.original_referee_crew_name || row.original_referee_crew_id) || '?'} →{' '}
                    {row.new_referee_crew_name || row.new_referee_crew_id}
                  </div>
                  <div className="mt-1 font-mono text-[10px] text-slate-500">
                    Officials {JSON.stringify(row.original_assigned_referee_ids || [])} → {JSON.stringify(row.new_assigned_referee_ids || [])}
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">{row.summary_reason}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-4">
          <div className="text-sm font-semibold text-blue-950">Referee adjustments</div>
          {refereeAdjustments.length === 0 ? (
            <p className="mt-2 text-xs text-blue-900">No individual referee deltas for this simulation.</p>
          ) : (
            <div className="mt-3 max-h-72 space-y-2 overflow-auto text-xs">
              {refereeAdjustments.map((move) => (
                <div key={`${move.referee_id}-${move.ring_id}-${move.window_start_minute}`} className="rounded-md border border-blue-100 bg-white p-2 shadow-sm">
                  <div className="font-semibold text-slate-900">{move.referee_name}</div>
                  <div className="text-slate-600">
                    {move.from_crew_name || move.from_crew_id} → {move.to_crew_name || move.to_crew_id}
                  </div>
                  <div className="text-slate-600">
                    {move.ring_name} · T+
                    {move.window_start_minute ?? '?'} → T+
                    {move.window_end_minute ?? '?'}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    Scope <span className="font-semibold">{move.scope}</span> · {move.reason}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
