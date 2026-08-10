import { useEffect, useState } from "react";
import { api, type DashboardData, type DashboardSeries } from "../api";
import { card } from "../ui";

// Paleta validada contra el fondo del panel (#07090e) con el validador de la
// guía de visualización: banda de luminosidad, croma, separación CVD y contraste.
const SERIES_1 = "#3987e5";           // serie única de actividad
const INK_MUTED = "#898781";          // ejes y etiquetas (recesivos)
const GRID = "#2c2c2a";               // rejilla hairline

// Estado = paleta reservada. Nunca la usa una serie, y siempre va con icono
// y texto: el color jamás carga el significado solo.
const STATUS_STYLE: Record<string, { color: string; icon: string; label: string }> = {
  confirmed: { color: "#0ca30c", icon: "✓", label: "Confirmadas" },
  attended: { color: "#0ca30c", icon: "✓", label: "Atendidas" },
  pending: { color: "#fab219", icon: "•", label: "Pendientes" },
  no_show: { color: "#ec835a", icon: "!", label: "No asistió" },
  cancelled: { color: "#d03b3b", icon: "×", label: "Canceladas" },
};

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className={`${card} p-5`}>
      <h4 className="text-zinc-500 text-[10px] font-bold tracking-widest uppercase mb-2">{label}</h4>
      <span className="text-2xl font-bold text-white">{value}</span>
      {hint && <p className="text-[10px] text-zinc-500 mt-1">{hint}</p>}
    </div>
  );
}

/** Actividad diaria: una sola serie → sin leyenda, el título la nombra. */
function ActivityChart({ data }: { data: { date: string; count: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!data.length) return null;

  const W = 720, H = 180, PAD_L = 32, PAD_B = 26, PAD_T = 12, PAD_R = 8;
  const max = Math.max(4, ...data.map((d) => d.count));
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;
  const x = (i: number) => PAD_L + (data.length === 1 ? innerW / 2 : (i * innerW) / (data.length - 1));
  const y = (v: number) => PAD_T + innerH - (v / max) * innerH;

  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.count).toFixed(1)}`).join(" ");
  const area = `${line} L${x(data.length - 1).toFixed(1)},${PAD_T + innerH} L${x(0).toFixed(1)},${PAD_T + innerH} Z`;
  const ticks = [0, Math.round(max / 2), max];
  const total = data.reduce((a, d) => a + d.count, 0);

  const fmtDay = (iso: string) => {
    const [, m, d] = iso.split("-");
    return `${d}/${m}`;
  };

  return (
    <div className={`${card} p-5`}>
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="text-sm font-bold text-zinc-200">Mensajes de clientes por día</h3>
        <span className="text-xs text-zinc-500">{total} en {data.length} días</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-44" role="img"
        aria-label={`Mensajes entrantes por día: ${total} en total`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth="1" />
            <text x={PAD_L - 6} y={y(t) + 3} textAnchor="end" fontSize="9" fill={INK_MUTED}>{t}</text>
          </g>
        ))}
        <defs>
          <linearGradient id="actFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES_1} stopOpacity="0.28" />
            <stop offset="100%" stopColor={SERIES_1} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#actFill)" />
        <path d={line} fill="none" stroke={SERIES_1} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {data.map((d, i) => (
          <g key={d.date}>
            {/* zona de captura más grande que la marca */}
            <rect x={x(i) - innerW / data.length / 2} y={PAD_T} width={innerW / data.length} height={innerH}
              fill="transparent" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            {(hover === i || d.count === max) && d.count > 0 && (
              <circle cx={x(i)} cy={y(d.count)} r="4" fill={SERIES_1} stroke="#07090e" strokeWidth="2" />
            )}
          </g>
        ))}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD_T} y2={PAD_T + innerH} stroke={INK_MUTED} strokeWidth="1" strokeDasharray="3 3" />
            <text x={Math.min(x(hover) + 8, W - 90)} y={PAD_T + 12} fontSize="11" fill="#ffffff" fontWeight="600">
              {fmtDay(data[hover].date)}: {data[hover].count}
            </text>
          </g>
        )}
        {data.map((d, i) =>
          i % Math.ceil(data.length / 7) === 0 ? (
            <text key={d.date} x={x(i)} y={H - 8} textAnchor="middle" fontSize="9" fill={INK_MUTED}>
              {fmtDay(d.date)}
            </text>
          ) : null
        )}
      </svg>
    </div>
  );
}

/** Citas por estado: barras horizontales con icono + texto + valor. */
function StatusBars({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).filter(([, v]) => v > 0);
  if (!entries.length) return null;
  const max = Math.max(...entries.map(([, v]) => v));
  return (
    <div className={`${card} p-5`}>
      <h3 className="text-sm font-bold text-zinc-200 mb-4">Citas por estado</h3>
      <div className="space-y-3">
        {entries.map(([status, count]) => {
          const s = STATUS_STYLE[status] ?? { color: INK_MUTED, icon: "•", label: status };
          return (
            <div key={status} className="flex items-center gap-3">
              <span className="text-xs text-zinc-300 w-32 shrink-0 flex items-center gap-1.5">
                <span aria-hidden style={{ color: s.color }}>{s.icon}</span>
                {s.label}
              </span>
              <div className="flex-1 h-2.5 rounded-sm overflow-hidden bg-white/[0.04]">
                <div className="h-full rounded-sm" style={{ width: `${(count / max) * 100}%`, background: s.color }} />
              </div>
              <span className="text-xs font-mono text-zinc-200 w-8 text-right tabular-nums">{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DashboardView({ companyId }: { companyId: number }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [series, setSeries] = useState<DashboardSeries | null>(null);

  useEffect(() => {
    api.dashboard(companyId).then(setData).catch(() => setData(null));
    api.dashboardSeries(companyId).then(setSeries).catch(() => setSeries(null));
  }, [companyId]);

  if (!data) return <p className="text-zinc-500 text-sm">Cargando…</p>;
  const booking = series?.has_booking ?? data.company.vertical === "medical";

  const tiles = [
    booking
      ? { label: "Citas de hoy", value: String(data.appointments_today) }
      : { label: "Productos en catálogo", value: String(data.products ?? 0) },
    { label: "Conversaciones", value: String(data.conversations), hint: "clientes atendidos" },
    booking
      ? { label: "Profesionales", value: String(data.doctors) }
      : { label: "Servicios", value: String(data.services ?? 0) },
    { label: "Agentes activos", value: `${data.agents_active}/${data.agents_total}` },
  ];

  return (
    <div className="space-y-6">
      <div>
        <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest bg-cyan-500/10 px-2.5 py-1 rounded-full border border-cyan-500/20">
          {data.company.niche}
        </span>
        <h2 className="text-3xl font-bold text-white tracking-tight mt-2">{data.company.name}</h2>
        <p className="text-zinc-400 text-sm mt-1">Panel operativo con datos reales del sistema.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {tiles.map((t) => <StatTile key={t.label} {...t} />)}
      </div>

      {series && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <ActivityChart data={series.activity} />
          </div>
          {booking && <StatusBars counts={series.appointments_by_status} />}
        </div>
      )}
    </div>
  );
}
