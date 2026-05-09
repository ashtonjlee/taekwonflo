export default function NotificationsPanel({ notifications = [] }) {

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <h2 className="m-0 text-xl font-semibold">Mock Notifications</h2>
      <p className="mt-2 text-sm text-slate-600">
        Placeholder SMS/email/push messages generated from schedule state.
      </p>
      <div className="mt-4 space-y-2">
        {notifications.map((message) => (
          <div key={message.id} className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
            <div className="font-medium text-slate-800">{message.channel.toUpperCase()}</div>
            <div className="text-slate-700">{message.text}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
