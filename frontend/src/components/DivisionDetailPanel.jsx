function StatusBadge({ status }) {
  const className = {
    completed: 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200',
    in_progress: 'bg-blue-100 text-blue-800 ring-1 ring-blue-200',
    staging: 'bg-amber-100 text-amber-800 ring-1 ring-amber-200',
    waiting: 'bg-slate-100 text-slate-700 ring-1 ring-slate-200',
  }[status] || 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'

  return <span className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${className}`}>{status.replace('_', ' ')}</span>
}

function scoreLabel(match) {
  if (!match.score) {
    return 'Score pending'
  }
  const { score } = match
  if (score.competitor_1_points !== null && score.competitor_2_points !== null) {
    return `${score.competitor_1_points} - ${score.competitor_2_points}`
  }
  if (score.competitor_1_poomsae !== null) {
    return `${score.competitor_1_poomsae?.toFixed(1)}${score.competitor_2_poomsae !== null ? ` - ${score.competitor_2_poomsae?.toFixed(1)}` : ''}`
  }
  return score.winner_margin || 'Score pending'
}

function competitorLabel(competitor) {
  return competitor ? `${competitor.name} (${competitor.team_name})` : 'Bye'
}

export default function DivisionDetailPanel({ detail, loading, error, resourceLocations = [], onClose }) {
  if (!detail && !loading && !error) {
    return null
  }

  const division = detail?.division
  const matches = detail?.bracket?.matches || []

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/40 p-4">
      <section className="mt-6 w-full max-w-6xl rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Division detail</p>
            <h2 className="m-0 mt-1 text-2xl font-bold text-slate-950">
              {division?.name || 'Loading division'}
            </h2>
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
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_18rem]">
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  <SummaryCard label="Bracket" value={detail.bracket.bracket_type.replaceAll('_', ' ')} />
                  <SummaryCard label="Competitors" value={detail.competitors.length} />
                  <SummaryCard label="Completed matches" value={detail.completed_matches.length} />
                </div>

                {detail.current_match ? (
                  <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                    <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">Current match</div>
                    <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="font-semibold text-slate-950">
                        {competitorLabel(detail.current_match.competitor_1)} vs {competitorLabel(detail.current_match.competitor_2)}
                      </div>
                      <StatusBadge status={detail.current_match.status} />
                    </div>
                  </div>
                ) : null}

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
                          <div className="font-semibold capitalize text-slate-900">{match.round_name}</div>
                          <div className="text-xs text-slate-500">Position {match.bracket_position}</div>
                        </div>
                        <div className="min-w-0">
                          <MatchCompetitorLine competitor={match.competitor_1} winnerId={match.winner_id} />
                          <MatchCompetitorLine competitor={match.competitor_2} winnerId={match.winner_id} />
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
              </div>

              <aside className="space-y-4">
                <LocationList locations={resourceLocations} />
                <RosterList title="Staging" competitors={detail.staging_competitors} />
                <RosterList title="Waiting" competitors={detail.waiting_competitors} />
                <RosterList title="Advanced" competitors={detail.advanced_competitors} />
                <RosterList title="Competitors" competitors={detail.competitors} />
              </aside>
            </div>
          ) : null}
        </div>
      </section>
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
              {location.resource_type.replace('_', ' ')} {location.resource_id}
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
      <div className="mt-1 text-lg font-bold capitalize text-slate-950">{value}</div>
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

function RosterList({ title, competitors }) {
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
            </div>
          ))
        )}
      </div>
    </div>
  )
}
