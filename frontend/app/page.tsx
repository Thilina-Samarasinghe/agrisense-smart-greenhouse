import { getHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

const zones = [
  { id: "A", crop: "Tomato" },
  { id: "B", crop: "Chilli" },
  { id: "C", crop: "Lettuce" },
];

export default async function Home() {
  const health = await getHealth();

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 font-sans">
      <h1 className="text-3xl font-semibold">AgriSense</h1>
      <p className="mt-1 text-sm opacity-70">
        Smart greenhouse simulation &amp; automation platform (dashboard arrives in Phase 3)
      </p>

      <section className="mt-6 rounded-lg border border-black/10 p-4 dark:border-white/15">
        <h2 className="font-medium">Backend status</h2>
        <p className="mt-1 text-sm">
          {health ? (
            <span className="text-green-600">
              ● {health.app} API v{health.version} is {health.status}
            </span>
          ) : (
            <span className="text-red-600">● Backend unreachable: start it with uvicorn</span>
          )}
        </p>
      </section>

      <section className="mt-6 grid gap-4 sm:grid-cols-3">
        {zones.map((z) => (
          <div key={z.id} className="rounded-lg border border-black/10 p-4 dark:border-white/15">
            <div className="text-sm opacity-70">Zone {z.id}</div>
            <div className="text-lg font-medium">{z.crop}</div>
            <div className="mt-2 text-xs opacity-60">Live telemetry arrives in Phase 3</div>
          </div>
        ))}
      </section>
    </main>
  );
}
