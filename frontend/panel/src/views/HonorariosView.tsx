import { useEffect, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Check, Copy, FileSignature, Loader2, Pencil, Printer,
  Send, ShieldCheck, Trash2, Wallet, X,
} from "lucide-react";
import {
  api, esErrorApi, type EstadoPlanilla, type PreviewHonorarios, type Planilla,
} from "../api";
import { input, btnPrimary } from "../ui";

/**
 * Honorarios del profesional, separados por aseguradora.
 *
 * El circuito real: junta las atenciones del período, las separa por
 * aseguradora —cada una tiene su formato y su circuito—, firma cada planilla
 * y la entrega. Recién después cobra.
 *
 * "Firmar" acá NO es una firma digital y la pantalla no le dice así: es que
 * el profesional revisó y congeló los montos. La firma de puño va en la hoja
 * que se imprime.
 */

const gs = (n: number) => "₲ " + (n ?? 0).toLocaleString("es-PY").replace(/,/g, ".");
const dia = (iso: string) => iso.slice(0, 10).split("-").reverse().join("/");

function primerDiaDelMesPasado() {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 10);
}

function ultimoDiaDelMesPasado() {
  const d = new Date();
  d.setDate(0); // día 0 del mes actual = último del anterior
  return d.toISOString().slice(0, 10);
}

const COLOR: Record<EstadoPlanilla, string> = {
  borrador: "text-zinc-600 border-zinc-200",
  firmada: "text-violet-600 border-violet-300",
  entregada: "text-indigo-700 border-indigo-500/30",
  cobrada: "text-emerald-700 border-emerald-300",
};

function Estado({ e }: { e: EstadoPlanilla }) {
  return (
    <span className={`text-[10px] border px-2 py-0.5 rounded-full ${COLOR[e]}`}>{e}</span>
  );
}

/** Una planilla abierta: sus atenciones y los pasos del circuito. */
function Detalle({ companyId, id, onVolver, onCambio }: {
  companyId: number; id: number; onVolver: () => void; onCambio: () => void;
}) {
  const [p, setP] = useState<Planilla | null>(null);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [copiado, setCopiado] = useState(false);
  // Qué renglón se está corrigiendo a mano. El camino normal es cargar el
  // arancel del convenio, que se aplica solo; esto es la excepción.
  const [editando, setEditando] = useState<number | null>(null);
  const [monto, setMonto] = useState(0);
  const [motivo, setMotivo] = useState("");

  const cargar = () => {
    api.verHonorarios(companyId, id).then(setP)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  };
  useEffect(cargar, [companyId, id]);

  const paso = async (a: "firmar" | "entregar") => {
    setOcupado(true); setError("");
    try {
      await api.avanzarPlanilla(companyId, id, a);
      cargar();
      onCambio();
    } catch (e) {
      const err = esErrorApi(e) ? e.detail?.motivo : null;
      setError(err ?? (e instanceof Error ? e.message : "No se pudo"));
    } finally {
      setOcupado(false);
    }
  };

  const borrar = async () => {
    setOcupado(true); setError("");
    try {
      await api.borrarHonorarios(companyId, id);
      onCambio();
      onVolver();
    } catch (e) {
      const err = esErrorApi(e) ? e.detail?.motivo : null;
      setError(err ?? (e instanceof Error ? e.message : "No se pudo borrar"));
      setOcupado(false);
    }
  };

  const ajustar = async () => {
    if (editando === null) return;
    setOcupado(true); setError("");
    try {
      setP(await api.ajustarRenglon(companyId, id, editando, monto, motivo));
      setEditando(null); setMotivo("");
      onCambio();
    } catch (e) {
      const err = esErrorApi(e) ? e.detail?.motivo : null;
      setError(err ?? (e instanceof Error ? e.message : "No se pudo ajustar"));
    } finally {
      setOcupado(false);
    }
  };

  const imprimir = () => {
    if (!p?.texto) return;
    // Se abre una ventana con el texto tal cual lo armó el servidor. No se
    // re-arma en el navegador: lo que se firma tiene que ser lo que se
    // guardó, no una versión que armó otra máquina.
    const w = window.open("", "_blank", "width=760,height=900");
    if (!w) return;
    w.document.write(
      `<pre style="font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap">${
        p.texto.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c] as string))
      }</pre>`
    );
    w.document.close();
    w.print();
  };

  const copiar = async () => {
    if (!p?.texto) return;
    try {
      await navigator.clipboard.writeText(p.texto);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch { /* clipboard no disponible */ }
  };

  if (!p) {
    return (
      <div className="space-y-4">
        <button onClick={onVolver} className="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5">
          <ArrowLeft size={14} /> Volver
        </button>
        <p className="text-sm text-zinc-500">{error || "Cargando…"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <button onClick={onVolver} className="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5">
        <ArrowLeft size={14} /> Volver a mis planillas
      </button>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-zinc-900 tracking-tight flex items-center gap-3">
            {p.aseguradora} <Estado e={p.estado} />
          </h1>
          <p className="text-sm text-zinc-500">
            {dia(p.desde)} al {dia(p.hasta)} · {p.items?.length ?? 0} atenciones
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-extrabold text-emerald-700">{gs(p.total_honorario_gs)}</p>
          <p className="text-[11px] text-zinc-500">
            tu {p.honorario_pct}% de {gs(p.total_facturado_gs)} facturados
          </p>
        </div>
      </div>

      {error && <p className="text-red-600 text-xs">{error}</p>}

      <div className="border border-zinc-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-zinc-50 text-zinc-600">
              <tr>
                <th className="text-left font-semibold px-3 py-2">Fecha</th>
                <th className="text-left font-semibold px-3 py-2">Paciente</th>
                <th className="text-left font-semibold px-3 py-2">Prestación</th>
                <th className="text-right font-semibold px-3 py-2">Facturado</th>
                <th className="text-right font-semibold px-3 py-2">Tu honorario</th>
                <th className="w-8"></th>
              </tr>
            </thead>
            <tbody>
              {p.items?.map((it, i) => (
                <tr key={i} className="border-t border-zinc-200">
                  <td className="px-3 py-2 font-mono text-zinc-500">{dia(it.fecha)}</td>
                  <td className="px-3 py-2 text-zinc-800">{it.paciente}</td>
                  <td className="px-3 py-2 text-zinc-600">
                    {it.servicio || <span className="text-amber-700">sin prestación cargada</span>}
                    {it.ajustado_a_mano && (
                      <span className="block text-[10px] text-amber-700">
                        ajustado a mano · calculado {gs(it.facturado_calculado_gs ?? 0)}
                        {it.ajuste_motivo && ` · ${it.ajuste_motivo}`}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-zinc-700 font-mono">{gs(it.facturado_gs)}</td>
                  <td className="px-3 py-2 text-right text-emerald-700 font-mono">{gs(it.honorario_gs)}</td>
                  <td className="px-2 py-2">
                    {p.estado === "borrador" && it.id && (
                      <button
                        onClick={() => {
                          setEditando(it.id!);
                          setMonto(it.facturado_gs);
                          setMotivo(it.ajuste_motivo ?? "");
                        }}
                        title="Corregir el monto de esta atención"
                        className="text-zinc-500 hover:text-violet-700">
                        <Pencil size={12} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {editando !== null && (
        <div className="bg-violet-600/[0.04] border border-violet-300 rounded-xl p-4 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <p className="text-xs text-zinc-700">
              Corregir lo que se factura por esta atención. Se guarda lo que el sistema
              había calculado y sale impreso en la planilla: un monto cambiado sin rastro
              es indistinguible de un error de cálculo.
            </p>
            <button onClick={() => setEditando(null)} className="text-zinc-500 hover:text-zinc-900 shrink-0">
              <X size={14} />
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <input className={`${input} w-40 text-right tabular-nums`} type="number" min={0}
              value={monto} onChange={(e) => setMonto(Number(e.target.value))} />
            <input className={`${input} flex-1 min-w-[12rem]`} placeholder="Motivo (queda en la planilla)"
              value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={200} />
            <button onClick={ajustar} disabled={ocupado} className={btnPrimary}>
              {ocupado ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Guardar
            </button>
          </div>
          <p className="text-[10px] text-zinc-500">
            Si esto pasa seguido con la misma práctica, cargá el arancel del convenio en
            Recetas y Convenios: se aplica solo a todas las liquidaciones siguientes.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-zinc-200">
        <div className="flex gap-4">
          <button onClick={imprimir} disabled={!p.texto}
            className="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5 disabled:opacity-40">
            <Printer size={13} /> Imprimir para firmar
          </button>
          <button onClick={copiar} disabled={!p.texto}
            className="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5 disabled:opacity-40">
            {copiado ? <><Check size={13} /> ¡Copiado!</> : <><Copy size={13} /> Copiar</>}
          </button>
          {p.estado === "borrador" && (
            <button onClick={borrar} disabled={ocupado}
              className="text-xs text-zinc-500 hover:text-red-600 flex items-center gap-1.5 disabled:opacity-40">
              <Trash2 size={13} /> Descartar borrador
            </button>
          )}
        </div>
        <div className="flex gap-3">
          {p.estado === "borrador" && (
            <button onClick={() => paso("firmar")} disabled={ocupado} className={btnPrimary}>
              {ocupado ? <Loader2 size={14} className="animate-spin" /> : <FileSignature size={14} />}
              Dar por buena y cerrar
            </button>
          )}
          {p.estado === "firmada" && (
            <button onClick={() => paso("entregar")} disabled={ocupado} className={btnPrimary}>
              <Send size={14} /> Marcar como entregada
            </button>
          )}
          {p.estado === "entregada" && (
            <p className="text-xs text-zinc-500 flex items-center gap-1.5">
              <ShieldCheck size={13} /> Entregada. La administración registra el pago.
            </p>
          )}
          {p.estado === "cobrada" && (
            <p className="text-xs text-emerald-700 flex items-center gap-1.5">
              <Wallet size={13} /> Cobrada el {p.cobrada_at ? dia(p.cobrada_at) : ""}
            </p>
          )}
        </div>
      </div>

      {p.estado === "borrador" && (
        <p className="text-[11px] text-zinc-500 leading-relaxed">
          Al cerrarla, los montos quedan congelados: aunque después cambie el precio de una
          prestación o el convenio, esta planilla no se mueve. Después imprimila y firmala
          de puño — el sistema no firma por vos.
        </p>
      )}
    </div>
  );
}

export function HonorariosView({ companyId }: { companyId: number }) {
  const [desde, setDesde] = useState(primerDiaDelMesPasado());
  const [hasta, setHasta] = useState(ultimoDiaDelMesPasado());
  const [prev, setPrev] = useState<PreviewHonorarios | null>(null);
  const [planillas, setPlanillas] = useState<Planilla[]>([]);
  const [abierta, setAbierta] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [armando, setArmando] = useState(false);

  const cargarPlanillas = () => {
    api.listarHonorarios(companyId).then(setPlanillas).catch(() => setPlanillas([]));
  };
  useEffect(cargarPlanillas, [companyId]);

  useEffect(() => {
    if (abierta) return;
    setPrev(null); setError("");
    api.previewHonorarios(companyId, desde, hasta)
      .then(setPrev)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo calcular"));
  }, [companyId, desde, hasta, abierta]);

  const armar = async () => {
    setArmando(true); setError("");
    try {
      await api.armarHonorarios(companyId, desde, hasta);
      cargarPlanillas();
      setPrev(null);
      api.previewHonorarios(companyId, desde, hasta).then(setPrev).catch(() => {});
    } catch (e) {
      const err = esErrorApi(e) ? e.detail?.motivo : null;
      setError(err ?? (e instanceof Error ? e.message : "No se pudieron armar"));
    } finally {
      setArmando(false);
    }
  };

  if (abierta) {
    return (
      <Detalle companyId={companyId} id={abierta}
        onVolver={() => setAbierta(null)} onCambio={cargarPlanillas} />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold text-zinc-900 tracking-tight">Mis honorarios</h1>
        <p className="text-sm text-zinc-600 mt-1">
          Tus atenciones del período, separadas por aseguradora: una planilla para cada una,
          lista para firmar y entregar.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[11px] text-zinc-500">
          Desde
          <input type="date" className={`${input} mt-1`} value={desde}
            onChange={(e) => setDesde(e.target.value)} />
        </label>
        <label className="text-[11px] text-zinc-500">
          Hasta
          <input type="date" className={`${input} mt-1`} value={hasta}
            onChange={(e) => setHasta(e.target.value)} />
        </label>
      </div>

      {error && <p className="text-red-600 text-xs">{error}</p>}

      {prev && (
        <>
          {prev.atenciones === 0 ? (
            <p className="text-sm text-zinc-500 py-6">
              No hay atenciones sin liquidar en ese período.
              {prev.ya_liquidadas > 0 && ` (${prev.ya_liquidadas} ya están en una planilla.)`}
            </p>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-4 bg-zinc-50 border border-zinc-200 rounded-xl p-4">
                <div>
                  <p className="text-xs text-zinc-600">
                    {prev.atenciones} atenciones en {prev.grupos.length}{" "}
                    {prev.grupos.length === 1 ? "planilla" : "planillas"}
                  </p>
                  <p className="text-2xl font-extrabold text-emerald-700 mt-0.5">
                    {gs(prev.total_honorario_gs)}
                  </p>
                  <p className="text-[11px] text-zinc-500">
                    tu {prev.honorario_pct}% de {gs(prev.total_facturado_gs)} facturados
                  </p>
                </div>
                <button onClick={armar} disabled={armando} className={btnPrimary}>
                  {armando ? <Loader2 size={14} className="animate-spin" /> : <FileSignature size={14} />}
                  Armar las planillas
                </button>
              </div>

              {(prev.sin_marcar_como_atendido > 0 || prev.sin_arancel > 0) && (
                <div className="bg-amber-500/[0.04] border border-amber-500/20 rounded-xl p-4 space-y-1.5">
                  {prev.sin_marcar_como_atendido > 0 && (
                    <p className="text-xs text-amber-700 flex items-start gap-2">
                      <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                      Hay <strong>{prev.sin_marcar_como_atendido}</strong> turno(s) del período
                      sin marcar como atendidos. No entran en la planilla: si el paciente vino,
                      marcalos en la agenda antes de armarla o vas a cobrar de menos.
                    </p>
                  )}
                  {prev.sin_arancel > 0 && (
                    <p className="text-xs text-amber-700 flex items-start gap-2">
                      <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                      <strong>{prev.sin_arancel}</strong> atención(es) sin prestación cargada:
                      van en cero porque no hay precio del que sacar el honorario.
                    </p>
                  )}
                </div>
              )}

              <div className="space-y-4">
                {prev.grupos.map((g) => (
                  <div key={g.aseguradora} className="border border-zinc-200 rounded-xl overflow-hidden">
                    <div className="flex items-center justify-between gap-3 px-4 py-2.5 bg-zinc-50">
                      <span className="text-sm font-bold text-zinc-900">{g.aseguradora}</span>
                      <span className="text-xs text-zinc-600">
                        {g.items.length} · <strong className="text-emerald-700">{gs(g.total_honorario_gs)}</strong>
                      </span>
                    </div>
                    <div className="divide-y divide-zinc-200">
                      {g.items.map((it, i) => (
                        <div key={i} className="flex items-center justify-between gap-3 px-4 py-2 text-xs">
                          <span className="font-mono text-zinc-500 w-14 shrink-0">{dia(it.fecha)}</span>
                          <span className="text-zinc-800 flex-1 truncate">{it.paciente}</span>
                          <span className="text-zinc-500 flex-1 truncate hidden sm:block">
                            {it.servicio || <span className="text-amber-700">sin prestación</span>}
                          </span>
                          <span className="font-mono text-emerald-700 shrink-0">{gs(it.honorario_gs)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      <section className="pt-6 border-t border-zinc-200 space-y-2">
        <h2 className="text-xs font-bold text-zinc-600 uppercase tracking-widest">
          Mis planillas ({planillas.length})
        </h2>
        {planillas.length === 0 && (
          <p className="text-xs text-zinc-500">Todavía no armaste ninguna.</p>
        )}
        {planillas.map((p) => (
          <button key={p.id} onClick={() => setAbierta(p.id)}
            className="w-full text-left bg-zinc-50 hover:bg-zinc-100 border border-zinc-200
                       rounded-xl px-4 py-3 flex items-center justify-between gap-3 transition-colors">
            <span className="flex items-center gap-2.5 min-w-0">
              <Estado e={p.estado} />
              <span className="text-sm text-zinc-800 truncate">{p.aseguradora}</span>
              <span className="text-[11px] text-zinc-500 hidden sm:inline">
                {dia(p.desde)}–{dia(p.hasta)}
              </span>
            </span>
            <span className="font-mono text-sm text-emerald-700 shrink-0">
              {gs(p.total_honorario_gs)}
            </span>
          </button>
        ))}
      </section>
    </div>
  );
}
