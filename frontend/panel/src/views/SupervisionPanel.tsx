import { useCallback, useEffect, useState } from "react";
import { Eye, ShieldCheck, Power } from "lucide-react";
import { api, waApi, type Company, type SupervisionReport } from "../api";
import { card } from "../ui";

/** Cómo se explica cada disparador en el panel, sin jerga interna. */
const DISPARADORES: Record<string, string> = {
  compliance_risk: "La respuesta rozaba una indicación médica",
  escalation_requested: "El bot derivó a una persona",
  catalog_miss: "No encontró lo que el cliente pedía",
  booking_clash: "El horario pedido estaba ocupado",
  dead_end: "El turno terminó sin respuesta útil",
  stalled_sale: "Conversación larga sin cerrar",
};

const ACCIONES: Record<string, string> = {
  keep: "Dejó la respuesta como estaba",
  rewrite: "Reescribió la respuesta",
  directive: "Dejó una instrucción para el próximo mensaje",
  escalate: "Derivó a una persona",
};

const MODOS = [
  {
    valor: "off" as const,
    titulo: "Apagado",
    detalle: "El bot responde solo. Es como funciona hoy y no cuesta nada.",
    icono: Power,
  },
  {
    valor: "shadow" as const,
    titulo: "Observando",
    detalle:
      "El CEO revisa los turnos que salieron mal después de que el cliente ya recibió su respuesta, así no lo hace esperar. Deja instrucciones para el mensaje siguiente.",
    icono: Eye,
  },
  {
    valor: "inline" as const,
    titulo: "Interviniendo",
    detalle:
      "Además puede reescribir la respuesta antes de enviarla y derivar a una persona. Solo en los casos graves.",
    icono: ShieldCheck,
  },
];

export function SupervisionPanel({ company, onChanged }: { company: Company; onChanged: () => void }) {
  const [report, setReport] = useState<SupervisionReport | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.supervisionReport(company.id).then(setReport).catch(() => setReport(null));
  }, [company.id]);
  useEffect(load, [load]);

  const cambiarModo = async (supervision: string) => {
    setGuardando(true);
    setError("");
    try {
      await waApi.updateCompany(company.id, { supervision });
      onChanged();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  const modoActual = report?.supervision ?? company.supervision ?? "off";

  return (
    <div className={`${card} p-6 space-y-5`}>
      <div>
        <h3 className="text-lg font-bold text-zinc-900">Supervisión del CEO</h3>
        <p className="text-zinc-600 text-sm mt-1">
          El CEO no revisa cada mensaje: eso duplicaría lo que tarda el bot en contestar. Revisa
          solo los turnos que salieron mal, y siempre después de que el cliente ya recibió su
          respuesta.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {MODOS.map((m) => {
          const activo = modoActual === m.valor;
          const Icono = m.icono;
          return (
            <button
              key={m.valor}
              disabled={guardando}
              onClick={() => cambiarModo(m.valor)}
              className={`text-left p-4 rounded-xl border transition-all disabled:opacity-50 ${
                activo
                  ? "bg-violet-50 border-cyan-500/50"
                  : "bg-zinc-50 border-zinc-200 hover:border-zinc-300"
              }`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <Icono size={16} className={activo ? "text-violet-600" : "text-zinc-500"} />
                <span className={`text-sm font-bold ${activo ? "text-violet-600" : "text-zinc-800"}`}>
                  {m.titulo}
                </span>
              </div>
              <p className="text-[11px] leading-relaxed text-zinc-600">{m.detalle}</p>
            </button>
          );
        })}
      </div>
      {error && <p className="text-red-600 text-xs">{error}</p>}

      {report && report.total > 0 ? (
        <div className="space-y-4 pt-4 border-t border-zinc-200">
          <div className="grid grid-cols-3 gap-4">
            <Metrica etiqueta="Turnos revisados" valor={String(report.supervisadas)} />
            <Metrica
              etiqueta="Sin revisar (comparación)"
              valor={String(report.control)}
              nota="Se dejan a propósito sin supervisar para poder comparar"
            />
            <Metrica
              etiqueta="Tarda en revisar"
              valor={report.latencia_media_ms ? `${(report.latencia_media_ms / 1000).toFixed(1)} s` : "—"}
              nota="En modo Observando no lo espera el cliente"
            />
          </div>

          <div>
            <p className="text-xs font-bold text-zinc-600 uppercase tracking-widest mb-2">Qué encontró</p>
            <div className="space-y-1.5">
              {Object.entries(report.por_disparador)
                .sort((a, b) => b[1] - a[1])
                .map(([clave, cantidad]) => (
                  <div key={clave} className="flex items-center justify-between text-sm">
                    <span className="text-zinc-700">{DISPARADORES[clave] ?? clave}</span>
                    <span className="text-zinc-500 font-mono text-xs">{cantidad}</span>
                  </div>
                ))}
            </div>
          </div>

          {report.recientes.length > 0 && (
            <div>
              <p className="text-xs font-bold text-zinc-600 uppercase tracking-widest mb-2">Últimas revisiones</p>
              <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                {report.recientes.map((e) => (
                  <div key={e.id} className="text-xs bg-zinc-50 border border-zinc-200 rounded-lg p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-800 font-medium">{DISPARADORES[e.trigger] ?? e.trigger}</span>
                      <span className="text-[10px] text-zinc-500 shrink-0">
                        {new Date(e.creado).toLocaleString("es-PY", { dateStyle: "short", timeStyle: "short" })}
                      </span>
                    </div>
                    <p className="text-zinc-600 mt-1">
                      {e.brazo === "control" ? "Sin revisar (comparación)" : ACCIONES[e.accion] ?? e.accion}
                      {e.motivo && <span className="text-zinc-500"> — {e.motivo}</span>}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs text-zinc-500 pt-4 border-t border-zinc-200">
          {modoActual === "off"
            ? "Con la supervisión apagada no se registra nada."
            : "Todavía no hubo turnos que necesitaran revisión."}
        </p>
      )}
    </div>
  );
}

function Metrica({ etiqueta, valor, nota }: { etiqueta: string; valor: string; nota?: string }) {
  return (
    <div>
      <p className="text-2xl font-bold text-zinc-900 tabular-nums">{valor}</p>
      <p className="text-[11px] text-zinc-600 mt-0.5">{etiqueta}</p>
      {nota && <p className="text-[10px] text-zinc-500 mt-0.5 leading-tight">{nota}</p>}
    </div>
  );
}
