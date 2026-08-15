import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, Wallet } from "lucide-react";
import { api, esErrorApi, type Planilla } from "../api";

/**
 * Lo que la clínica le debe a sus profesionales.
 *
 * Marcar una planilla como cobrada NO puede hacerlo el profesional: sería
 * firmar que se pagó a sí mismo. El backend lo rechaza y esta pantalla es
 * la otra mitad del circuito.
 */

const gs = (n: number) => "₲ " + (n ?? 0).toLocaleString("es-PY").replace(/,/g, ".");
const dia = (iso: string) => iso.slice(0, 10).split("-").reverse().join("/");

export function HonorariosAPagarView({ companyId }: { companyId: number }) {
  const [planillas, setPlanillas] = useState<Planilla[] | null>(null);
  const [error, setError] = useState("");
  const [pagando, setPagando] = useState(0);

  const cargar = () => {
    api.honorariosAPagar(companyId)
      .then(setPlanillas)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  };
  useEffect(cargar, [companyId]);

  const pagar = async (id: number) => {
    setPagando(id); setError("");
    try {
      await api.avanzarPlanilla(companyId, id, "pagar");
      cargar();
    } catch (e) {
      const err = esErrorApi(e) ? e.detail?.motivo : null;
      setError(err ?? (e instanceof Error ? e.message : "No se pudo registrar"));
    } finally {
      setPagando(0);
    }
  };

  const total = (planillas ?? []).reduce((s, p) => s + p.total_honorario_gs, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold text-zinc-900 tracking-tight">Honorarios a pagar</h1>
        <p className="text-sm text-zinc-600 mt-1">
          Planillas que los profesionales cerraron y entregaron. Al registrar el pago quedan
          cerradas: quién lo hizo y cuándo va a la bitácora.
        </p>
      </div>

      {error && <p className="text-red-600 text-xs">{error}</p>}
      {planillas === null && <p className="text-sm text-zinc-500">Cargando…</p>}

      {planillas?.length === 0 && (
        <p className="text-sm text-zinc-500 py-10 text-center">
          No hay planillas pendientes de pago.
        </p>
      )}

      {!!planillas?.length && (
        <>
          <div className="bg-zinc-50 border border-zinc-200 rounded-xl p-4">
            <p className="text-xs text-zinc-600">
              {planillas.length} {planillas.length === 1 ? "planilla" : "planillas"} pendientes
            </p>
            <p className="text-2xl font-extrabold text-amber-700 mt-0.5">{gs(total)}</p>
          </div>

          <div className="space-y-2">
            {planillas.map((p) => (
              <div key={p.id}
                className="bg-zinc-50 border border-zinc-200 rounded-xl px-4 py-3
                           flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-zinc-900 font-medium truncate">{p.doctor}</p>
                  <p className="text-[11px] text-zinc-500">
                    {p.aseguradora} · {dia(p.desde)}–{dia(p.hasta)} · {p.atenciones ?? "?"} atenciones
                  </p>
                  {p.estado === "firmada" && (
                    <p className="text-[11px] text-amber-700 flex items-center gap-1 mt-0.5">
                      <AlertTriangle size={10} /> todavía no la entregó
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-4 shrink-0">
                  <span className="font-mono text-sm text-emerald-700">
                    {gs(p.total_honorario_gs)}
                  </span>
                  <button
                    onClick={() => pagar(p.id)}
                    disabled={pagando === p.id || p.estado !== "entregada"}
                    title={p.estado !== "entregada"
                      ? "Se registra el pago cuando el profesional la entrega"
                      : undefined}
                    className="text-xs px-3 py-1.5 rounded-lg border border-emerald-300 text-emerald-700
                               hover:bg-emerald-50 disabled:opacity-30 disabled:hover:bg-transparent
                               flex items-center gap-1.5">
                    {pagando === p.id
                      ? <Loader2 size={12} className="animate-spin" />
                      : <Wallet size={12} />}
                    Registrar pago
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
