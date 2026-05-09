export default function TournamentSetup({ snapshot }) {
  const tournament = snapshot?.tournament

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <h2 className="m-0 text-xl font-semibold">Tournament Setup</h2>
      <p className="mt-2 text-sm text-slate-600">
        Placeholder setup summary for the synthetic tournament source.
      </p>
      <div className="mt-4 grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
        <SetupCard label="Tournament" value={tournament?.name || 'TaekwonFlo Demo Open'} />
        <SetupCard label="Rings" value={tournament?.rings?.length || 0} />
        <SetupCard label="Divisions" value={tournament?.divisions?.length || 0} />
      </div>
    </section>
  )
}

function SetupCard({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-base font-semibold text-slate-900">{value}</div>
    </div>
  )
}
