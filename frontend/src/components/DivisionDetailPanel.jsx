import { useEffect, useMemo, useState } from 'react'

const TABS = [
  { id: 'summary', label: 'Summary' },
  { id: 'queue', label: 'Queue' },
  { id: 'bracket', label: 'Bracket' },
  { id: 'coaches', label: 'Coaches' },
]

function StatusBadge({ status }) {
  const className = {
    completed: 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200',
    in_progress: 'bg-blue-100 text-blue-800 ring-1 ring-blue-200',
    staging: 'bg-amber-100 text-amber-800 ring-1 ring-amber-200',
    waiting: 'bg-slate-100 text-slate-700 ring-1 ring-slate-200',
  }[status] || 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'

  return (
    <span className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${className}`}>
      {status.replaceAll('_', ' ')}
    </span>
  )
}

function CoachStatusBadge({ status }) {
  const tone = {
    report_now: 'bg-rose-100 text-rose-900 ring-1 ring-rose-200',
    in_holding: 'bg-amber-100 text-amber-900 ring-1 ring-amber-200',
    waiting: 'bg-slate-100 text-slate-800 ring-1 ring-slate-200',
    currently_coaching: 'bg-blue-100 text-blue-900 ring-1 ring-blue-200',
    done: 'bg-emerald-100 text-emerald-900 ring-1 ring-emerald-200',
  }[status] || 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'

  return (
    <span className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}>
      {status.replaceAll('_', ' ')}
    </span>
  )
}

function scoreLabel(match) {
  if (!match.score) {
    return 'Score pending'
  }
  const { score } = match
  if (score.competitor_1_points !== null && score.competitor_2_points !== null) {
    return `${score.competitor_1_points} — ${score.competitor_2_points}`
  }
  if (score.competitor_1_poomsae !== null) {
    const right = score.competitor_2_poomsae !== null ? ` — ${score.competitor_2_poomsae?.toFixed(1)}` : ''
    return `${score.competitor_1_poomsae?.toFixed(1)}${right}`
  }
  return score.winner_margin || 'Score pending'
}

function competitorLabel(competitor) {
  return competitor ? `${competitor.name} (${competitor.team_name})` : 'Bye'
}

function participantsLabel(match) {
  const names = []
  if (match.competitor_1) {
    names.push(competitorLabel(match.competitor_1))
  } else if (match.source_1_label) {
    names.push(match.source_1_label)
  }
  if (match.competitor_2) {
    names.push(competitorLabel(match.competitor_2))
  } else if (match.source_2_label) {
    names.push(match.source_2_label)
  }
  if ((!match.competitor_2 || match.bye) && match.participant_athlete_ids?.length && names.length < 2) {
    const extra = `${match.participant_athlete_ids.length} performer(s)`
    if (!names.includes(extra)) {
      names.push(extra)
    }
  }
  return names.length ? names.join(' · ') : 'Performers pending'
}

function currentMatchHeading(match, bracketType) {
  const isKyorugi = bracketType === 'single_elimination' || bracketType.includes('elimination')
  const left = match.competitor_1 ? competitorLabel(match.competitor_1) : match.source_1_label || 'TBD'
  const right =
    match.competitor_2 != null ? competitorLabel(match.competitor_2) : match.source_2_label || (match.bye ? 'Bye' : 'TBD')
  if (isKyorugi) {
    return `${left} vs ${right}`
  }
  return `On floor: ${participantsLabel(match)}`
}

export default function DivisionDetailPanel({ detail, loading, error, resourceLocations = [], onClose }) {
  const [tab, setTab] = useState('summary')

  const kyorugiRounds = detail?.kyorugi_rounds || []
  const rankedRounds = detail?.ranked_rounds || []

  const queueMatches = useMemo(() => {
    return detail?.bracket?.matches || []
  }, [detail])

  useEffect(() => {
    if (!detail?.division?.id) {
      return
    }
    setTab(detail.focused_match_id ? 'bracket' : 'summary')
    if (!detail.focused_match_id) {
      return
    }
    requestAnimationFrame(() => {
      document.getElementById(`match-focus-${detail.focused_match_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [detail?.division?.id, detail?.focused_match_id])

  if (!detail && !loading && !error) {
    return null
  }

  const division = detail?.division
  const bracketType = detail?.bracket?.bracket_type || ''
  const validation = detail?.detail_validation || { errors: [], warnings: [], valid: true }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/40 p-4">
      <section className="mt-6 w-full max-w-6xl rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Division detail</p>
            <h2 className="m-0 mt-1 text-2xl font-bold text-slate-950">{division?.name || 'Loading division'}</h2>
            {division ? (
              <p className="mt-2 text-sm text-slate-600">
                {division.age_group} / {division.gender} / {division.weight_class} / {division.belt_level}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Close
          </button>
        </div>

        <div className="p-5">
          {loading ? <div className="rounded border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">Loading bracket details...</div> : null}
          {error ? <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">{error}</div> : null}

          {detail ? (
            <>
              <nav className="-mt-1 mb-4 flex flex-wrap gap-2 border-b border-slate-200 pb-3" aria-label="Division sections">
                {TABS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setTab(item.id)}
                    className={`rounded-md px-3 py-1.5 text-sm font-semibold transition-colors ${
                      tab === item.id ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>

              <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_17rem]">
                <div className="space-y-4">
                  {tab === 'summary' ? (
                    <SummaryTab detail={detail} bracketType={bracketType} validation={validation} currentMatchHeading={currentMatchHeading} />
                  ) : null}
                  {tab === 'queue' ? <QueueTab matches={queueMatches} scoreLabel={scoreLabel} participantsLabel={participantsLabel} /> : null}
                  {tab === 'bracket' ? (
                    <BracketTab
                      kyorugiRounds={kyorugiRounds}
                      rankedRounds={rankedRounds}
                      fallbackMatches={queueMatches}
                      competitorLabel={competitorLabel}
                      scoreLabel={scoreLabel}
                      focusedMatchId={detail.focused_match_id || null}
                    />
                  ) : null}
                  {tab === 'coaches' ? <CoachesTab coachReport={detail.coach_report || []} roster={detail.competitors || []} /> : null}
                </div>

                <aside className="space-y-4">
                  <LocationList locations={resourceLocations} />
                  <RosterList title="Staging" competitors={detail.staging_competitors} />
                  <RosterList title="Waiting" competitors={detail.waiting_competitors} />
                  <RosterList title="Advanced" competitors={detail.advanced_competitors} />
                  <RosterList title="Competitors" competitors={detail.competitors} showCoaches />
                </aside>
              </div>
            </>
          ) : null}
        </div>
      </section>
    </div>
  )
}

function SummaryTab({ detail, bracketType, validation, currentMatchHeading }) {
  const matches = detail?.bracket?.matches || []
  return (
    <>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <SummaryCard label="Bracket" value={(detail.bracket?.bracket_type || '').replaceAll('_', ' ')} />
        <SummaryCard label="Competitors" value={detail.competitors?.length ?? 0} />
        <SummaryCard label="Completed matches" value={detail.completed_matches?.length ?? 0} />
      </div>

      <ValidationPanel validation={validation} />

      {detail.current_match ? (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">Current match</div>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="font-semibold text-slate-950">{currentMatchHeading(detail.current_match, bracketType)}</div>
            <StatusBadge status={detail.current_match.status} />
          </div>
          {!detail.current_match.competitor_2 && detail.current_match.participant_athlete_ids?.length ? (
            <p className="mt-2 text-xs text-blue-950">
              Ranked performance with {detail.current_match.participant_athlete_ids.length} mapped athlete ids on this slot (see Bracket tab for rostered
              names).
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="rounded-lg border border-slate-200 p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Schedule cue</div>
        <div className="mt-2 text-sm text-slate-700">{matches.length} ordered matches • ring {matches[0]?.ring_name || matches[0]?.ring_id || '—'}</div>
      </div>
    </>
  )
}

function ValidationPanel({ validation }) {
  const { errors = [], warnings = [], valid } = validation
  if (!errors.length && !warnings.length && valid !== false) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        Division graph audit passed — no structural issues reported.
      </div>
    )
  }

  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${valid === false ? 'border-rose-200 bg-rose-50 text-rose-950' : 'border-amber-200 bg-amber-50 text-amber-950'}`}>
      <div className="font-semibold">{valid === false ? 'Audit failed' : 'Audit warnings'}</div>
      {errors?.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-4">
          {errors.map((msg, i) => (
            <li key={`e-${i}`}>{msg}</li>
          ))}
        </ul>
      ) : null}
      {warnings?.length ? (
        <ul className={`mt-2 list-disc space-y-1 pl-4 ${errors?.length ? 'mt-3' : 'mt-2'}`}>
          {warnings.map((msg, i) => (
            <li key={`w-${i}`}>{msg}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function QueueTab({ matches, scoreLabel, participantsLabel }) {
  return (
    <div className="rounded-lg border border-slate-200">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="text-sm font-semibold text-slate-900">Match Queue</div>
        <div className="mt-0.5 text-xs text-slate-500">Bracket order, live status, and local repair notes.</div>
      </div>
      <div className="divide-y divide-slate-200">
        {matches.map((match) => (
          <div
            key={match.match_id}
            className={`grid grid-cols-1 gap-3 p-4 text-sm lg:grid-cols-[8rem_1fr_7rem_6rem] lg:items-center ${
              match.swapped_from_match_id ? 'bg-amber-50' : ''
            }`}
          >
            <div>
              <div className="font-semibold capitalize text-slate-900">
                #{match.match_number ?? '?'} — {match.round_name}
              </div>
              <div className="text-xs text-slate-500">
                Slot {match.bracket_position}
                {match.bye ? ' • bye lane' : ''}
                {match.next_match_id ? ` • feeds ${match.next_match_id}` : ''}
              </div>
            </div>
            <div className="min-w-0">
              <div className="space-y-1">
                <div className={`rounded px-2 py-1 text-xs ${match.winner_id === match.competitor_1?.competitor_id ? 'bg-emerald-50 font-semibold text-emerald-900' : ''}`}>
                  {match.competitor_1 ? <MatchCompetitorLine competitor={match.competitor_1} winnerId={match.winner_id} /> : <span>{match.source_1_label || 'TBD'}</span>}
                </div>
                <div className={`rounded px-2 py-1 text-xs ${match.winner_id === match.competitor_2?.competitor_id ? 'bg-emerald-50 font-semibold text-emerald-900' : ''}`}>
                  {match.competitor_2 ? (
                    <MatchCompetitorLine competitor={match.competitor_2} winnerId={match.winner_id} />
                  ) : (
                    <span>{match.source_2_label || (match.bye ? 'Bye' : 'TBD')}</span>
                  )}
                </div>
              </div>
              {match.repair_note ? (
                <div className="mt-2 rounded border border-amber-200 bg-amber-100 px-2 py-1 text-xs font-medium text-amber-900">
                  {match.repair_note}
                </div>
              ) : null}
            </div>
            <div className="font-semibold text-slate-900">{scoreLabel(match)}</div>
            <StatusBadge status={match.status} />
          </div>
        ))}
      </div>
    </div>
  )
}

function BracketTab({ kyorugiRounds, rankedRounds, fallbackMatches, competitorLabel, scoreLabel, focusedMatchId }) {
  if (kyorugiRounds.length) {
    return <KyorugiBracketColumns rounds={kyorugiRounds} scoreLabel={scoreLabel} focusedMatchId={focusedMatchId || null} competitorLabel={competitorLabel} />
  }

  if (rankedRounds.length) {
    return (
      <div className="space-y-8">
        {rankedRounds.map((panel) => (
          <div key={panel.round_name}>
            <h3 className="m-0 mb-3 text-sm font-semibold capitalize text-slate-900">{panel.round_name}</h3>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full min-w-[32rem] text-left text-xs">
                <thead className="bg-slate-50 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-3 py-2">Entry</th>
                    <th className="px-3 py-2">Team</th>
                    <th className="px-3 py-2">Athletes</th>
                    <th className="px-3 py-2">Rank</th>
                    <th className="px-3 py-2">Adv</th>
                    <th className="px-3 py-2">Score</th>
                    <th className="px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {(panel.entries || []).map((row) => (
                    <tr key={row.entry_id}>
                      <td className="px-3 py-2 font-semibold text-slate-950">{row.display_name}</td>
                      <td className="px-3 py-2 text-slate-700">{row.team_name}</td>
                      <td className="px-3 py-2 text-slate-700">
                        {(row.athlete_members || []).map((ath) => (
                          <div key={ath.competitor_id} className="truncate">
                            {competitorLabel(ath)}
                          </div>
                        ))}
                      </td>
                      <td className="px-3 py-2 font-semibold text-slate-900">{row.rank_in_round ?? '—'}</td>
                      <td className="px-3 py-2">{row.advanced ? 'yes' : 'no'}</td>
                      <td className="px-3 py-2">{row.score_value != null ? Number(row.score_value).toFixed(1) : '—'}</td>
                      <td className="px-3 py-2">
                        <StatusBadge status={row.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
      No layered bracket view supplied for this division. Showing flattened queue ({fallbackMatches.length} matches).
    </div>
  )
}

function KyorugiBracketColumns({ rounds, competitorLabel, scoreLabel, focusedMatchId }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/40 p-4">
      <div className="mb-4 text-xs text-slate-600">
        Horizontal knockout columns read earliest rounds on the left and later rounds toward the right.
      </div>
      <div className="flex min-h-[360px] min-w-max divide-x divide-slate-300">
        {rounds.map((panel) => (
          <div key={panel.round_name} className="flex min-w-[228px] flex-col justify-around px-4 py-3">
            <div className="mb-6 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-700">{panel.round_name}</div>
            {(panel.matches || [])
              .slice()
              .sort((left, right) => left.bracket_position - right.bracket_position)
              .map((match) => (
                <div key={match.match_id} className="relative flex flex-col items-center gap-8">
                  <KyorugiTreeCard
                    match={match}
                    competitorLabel={competitorLabel}
                    scoreLabel={scoreLabel}
                    focusedMatchId={focusedMatchId}
                  />
                  <span className="pointer-events-none absolute right-[-20px] top-1/2 hidden h-[2px] w-5 -translate-y-1/2 bg-slate-300 lg:block" />
                </div>
              ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function KyorugiTreeCard({ match, competitorLabel, scoreLabel, focusedMatchId }) {
  const left = match.competitor_1 ? competitorLabel(match.competitor_1) : match.source_1_label || 'TBD'
  const rightRaw = match.competitor_2 ? competitorLabel(match.competitor_2) : match.source_2_label
  const right = rightRaw || (match.bye ? 'Bye / walkover' : 'TBD')

  const focus = focusedMatchId && match.match_id === focusedMatchId
  const winnerLeft = match.winner_id && match.competitor_1 && match.winner_id === match.competitor_1.competitor_id
  const winnerRight = match.winner_id && match.competitor_2 && match.winner_id === match.competitor_2.competitor_id

  return (
    <div
      id={`match-focus-${match.match_id}`}
      className={`w-full max-w-xs rounded-xl border bg-white p-3 text-xs shadow-sm ${
        match.status === 'in_progress' ? 'border-blue-500 ring-2 ring-blue-200' : ''
      } ${focus ? 'border-amber-500 ring-2 ring-amber-200' : match.status !== 'in_progress' ? 'border-slate-200' : ''}`}
    >
      <div className="flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        <span>Match {match.match_number ?? '?'}</span>
        <StatusBadge status={match.status} />
      </div>
      <div
        className={`mt-2 rounded-md border px-2 py-2 ${
          winnerLeft ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'border-slate-100 bg-slate-50 text-slate-900'
        }`}
      >
        {left}
      </div>
      <div
        className={`mt-1 rounded-md border px-2 py-2 ${
          winnerRight ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'border-slate-100 bg-slate-50 text-slate-900'
        }`}
      >
        {right}
      </div>
      <div className="mt-2 text-[11px] text-slate-600">{scoreLabel(match)}</div>
      {match.next_match_id ? (
        <div className="mt-1 font-mono text-[10px] text-slate-500">Advances to {match.next_match_id}</div>
      ) : null}
    </div>
  )
}

function CoachesTab({ coachReport, roster }) {
  return (
    <div className="space-y-4">
      {coachReport.length ? (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[36rem] text-left text-xs">
            <thead className="bg-slate-50 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2">Coach</th>
                <th className="px-3 py-2">Team</th>
                <th className="px-3 py-2">Focus</th>
                <th className="px-3 py-2">Ring</th>
                <th className="px-3 py-2">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {coachReport.map((row) => (
                <tr key={`${row.coach_id}-${row.related_entry_id || row.related_display}-${row.ring_id}`}>
                  <td className="px-3 py-2 font-semibold text-slate-950">{row.coach_name}</td>
                  <td className="px-3 py-2">{row.team_name}</td>
                  <td className="px-3 py-2 text-slate-700">{row.related_display}</td>
                  <td className="px-3 py-2">{row.ring_name}</td>
                  <td className="px-3 py-2">
                    <CoachStatusBadge status={row.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">No coach movement sheet for this division.</div>
      )}

      <div className="rounded-lg border border-slate-200 p-3">
        <div className="text-sm font-semibold text-slate-900">Roster coaches</div>
        <div className="mt-2 space-y-2 text-xs">
          {(roster || [])
            .filter((human) => human.coach_names?.length)
            .map((human) => (
              <div key={`roster-coach-${human.competitor_id}`} className="rounded bg-slate-50 p-2">
                <div className="font-semibold text-slate-900">{human.name}</div>
                <div className="mt-0.5 text-slate-600">{human.coach_names.join(', ')}</div>
              </div>
            ))}
          {!(roster || []).some((h) => h.coach_names?.length) ? <div className="text-slate-500">No coach labels on roster for this demo.</div> : null}
        </div>
      </div>
    </div>
  )
}

function LocationList({ locations }) {
  if (!locations.length) {
    return null
  }

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
      <div className="text-sm font-semibold text-blue-950">Resource Locations</div>
      <div className="mt-2 space-y-2">
        {locations.map((location) => (
          <div key={`${location.resource_type}-${location.resource_id}`} className="rounded bg-white p-2 text-xs text-blue-950">
            <div className="font-semibold">
              {location.resource_type.replaceAll('_', ' ')} {location.resource_id}
            </div>
            <div className="mt-0.5">
              {location.location}
              {location.until_minute ? ` until T+${location.until_minute}` : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SummaryCard({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-bold capitalize text-slate-950">{String(value)}</div>
    </div>
  )
}

function MatchCompetitorLine({ competitor, winnerId }) {
  const isWinner = competitor && competitor.competitor_id === winnerId
  return (
    <div className={`flex items-center justify-between gap-3 rounded px-2 py-1 ${isWinner ? 'bg-emerald-50 text-emerald-900' : 'text-slate-700'}`}>
      <span className="truncate">{competitorLabel(competitor)}</span>
      {isWinner ? <span className="text-xs font-semibold uppercase">Advanced</span> : null}
    </div>
  )
}

function RosterList({ title, competitors = [], showCoaches = false }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-slate-900">{title}</div>
        <div className="text-xs font-semibold text-slate-500">{competitors.length}</div>
      </div>
      <div className="mt-2 space-y-2">
        {competitors.length === 0 ? (
          <div className="rounded bg-slate-50 p-2 text-xs text-slate-500">None</div>
        ) : (
          competitors.map((competitor) => (
            <div key={`${title}-${competitor.competitor_id}`} className="rounded bg-slate-50 p-2 text-xs">
              <div className="font-semibold text-slate-900">{competitor.name}</div>
              <div className="mt-0.5 text-slate-500">{competitor.team_name}</div>
              {showCoaches && competitor.coach_names?.length ? (
                <div className="mt-1 text-[10px] text-slate-600">Coach: {competitor.coach_names.join(', ')}</div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
