import { useEffect, useState } from "react";
import {
  AlertTriangle, ArrowLeft, CalendarDays, Clock, HelpCircle, LogOut, Pill,
  KeyRound, Receipt, Search, Sparkles, Stethoscope, User,
} from "lucide-react";
import {
  api, auth, type FichaCompleta, type FichaPaciente, type PortalMe,
  type PortalPaciente, type Previsita,
} from "../api";
import { input, btnPrimary, Modal } from "../ui";
import { HonorariosView } from "./HonorariosView";

/**
 * El portal del profesional (bloque 4).
 *
 * Es una aplicación distinta del panel de la clínica, no una vista más: el
 * médico entra con su usuario y lo único que ve son SUS pacientes. El backend
 * lo encierra en /portal; acá ni siquiera existe el resto.
 *
 * La pantalla principal son post-it: una tarjeta por paciente del día con lo
 * mínimo que hace falta saber antes de que entre al consultorio. Tocar una
 * abre la ficha completa.
 */

function hoyISO() {
  return new Date().toISOString().slice(0, 10);
}

function soloFecha(iso: string) {
  return iso.slice(0, 10).split("-").reverse().join("/");
}

function soloHora(iso: string) {
  return iso.slice(11, 16);
}

/** Un post-it. Papel amarillo, apenas rotado, con lo justo. */
function PostIt({ f, onAbrir }: { f: FichaPaciente; onAbrir: () => void }) {
  return (
    <button
      onClick={onAbrir}
      // La rotación alterna por índice desde el contenedor: acá solo se
      // declara el papel. `text-left` porque un <button> centra por defecto.
      className="text-left w-full bg-[#fdf6b2] hover:bg-[#fef9c3] text-zinc-900 rounded-sm p-4
                 shadow-[0_6px_16px_rgba(0,0,0,0.45)] transition-transform hover:-translate-y-1
                 hover:rotate-0 flex flex-col gap-2 min-h-[10rem]">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-sm font-bold text-amber-800">{f.hora}</span>
        <span className="font-bold text-sm leading-tight">{f.paciente}</span>
      </div>

      {(f.servicio || f.motivo) && (
        <p className="text-xs text-zinc-400 leading-snug">
          {[f.servicio, f.motivo].filter(Boolean).join(" · ")}
        </p>
      )}

      <div className="flex flex-wrap gap-1.5">
        {f.primera_vez ? (
          <span className="text-[10px] bg-indigo-900/10 text-indigo-900 px-1.5 py-0.5 rounded font-bold flex items-center gap-1">
            <Sparkles size={9} /> Primera vez
          </span>
        ) : (
          <span className="text-[10px] text-zinc-500 flex items-center gap-1">
            {/* "veces", no "vez"+"ces": el plural cambia la z por c. */}
            <Clock size={9} /> {f.visitas_previas} {f.visitas_previas === 1 ? "visita" : "visitas"}
          </span>
        )}
        {f.sin_confirmar && (
          <span className="text-[10px] text-amber-900/80 border border-amber-900/25 px-1.5 py-0.5 rounded">
            sin confirmar
          </span>
        )}
        {f.faltas_previas > 0 && (
          <span className="text-[10px] text-red-900/80 flex items-center gap-1">
            <AlertTriangle size={9} /> faltó {f.faltas_previas}
          </span>
        )}
      </div>

      {f.ultima_receta && (
        <div className="mt-auto pt-2 border-t border-amber-900/15">
          <p className="text-[11px] text-zinc-400 flex items-center gap-1 font-medium">
            <Pill size={10} /> {f.ultima_receta.diagnostico || "Receta previa"}
          </p>
          {f.ultima_receta.medicacion.slice(0, 2).map((m, i) => (
            <p key={i} className="text-[10px] text-zinc-500 leading-tight">• {m}</p>
          ))}
        </div>
      )}

      {f.preparacion_requerida && (
        <p className="text-[10px] text-amber-900 flex items-start gap-1 mt-auto">
          <AlertTriangle size={10} className="shrink-0 mt-0.5" /> {f.preparacion_requerida}
        </p>
      )}
      {f.numero_compartido && (
        <p className="text-[10px] text-zinc-500 flex items-start gap-1"
          title="No se muestra el historial de la otra persona">
          <HelpCircle size={10} className="shrink-0 mt-0.5" />
          Hay registros de otra persona con este número.
        </p>
      )}
    </button>
  );
}

/** La ficha completa: todas las visitas y todo lo recetado por este médico. */
function Ficha({ companyId, paciente, telefono, onVolver }: {
  companyId: number; paciente: string; telefono: string; onVolver: () => void;
}) {
  const [datos, setDatos] = useState<FichaCompleta | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.portalFicha(companyId, telefono, paciente)
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, [companyId, telefono, paciente]);

  return (
    <div className="space-y-5">
      <button onClick={onVolver}
        className="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5">
        <ArrowLeft size={14} /> Volver
      </button>

      <div>
        <h1 className="text-2xl font-extrabold text-zinc-900 tracking-tight">{paciente}</h1>
        <p className="text-sm text-zinc-500 font-mono">{telefono}</p>
      </div>

      {error && <p className="text-red-600 text-xs">{error}</p>}
      {!datos && !error && <p className="text-zinc-500 text-sm">Cargando…</p>}

      {datos?.numero_compartido && (
        <p className="text-xs text-amber-700 bg-amber-500/5 border border-amber-500/20 rounded-xl p-3 flex items-start gap-2">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          Con este número hay registros a nombre de otra persona. No se muestran acá:
          confirmá con quién estás hablando antes de dar por suya cualquier indicación.
        </p>
      )}

      {datos && (
        <>
          <section className="space-y-2">
            <h2 className="text-xs font-bold text-zinc-600 uppercase tracking-widest">
              Lo que le receté ({datos.recetas.length})
            </h2>
            {datos.recetas.length === 0 && (
              <p className="text-sm text-zinc-500">Todavía no le recetaste nada.</p>
            )}
            {datos.recetas.map((r) => (
              <div key={r.id} className="bg-zinc-50 border border-zinc-200 rounded-xl p-4 space-y-2">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-bold text-zinc-900">
                    {r.diagnostico || "Sin diagnóstico anotado"}
                  </span>
                  <span className="text-xs text-zinc-500 font-mono shrink-0">
                    {soloFecha(r.fecha)}
                  </span>
                </div>
                {r.medicacion.map((m, i) => (
                  <p key={i} className="text-xs text-zinc-700">
                    <Pill size={11} className="inline text-emerald-700 mr-1.5" />
                    <strong>{m.nombre}</strong> — {m.dosis}
                    {m.cada_horas > 0 && ` cada ${m.cada_horas} h`}
                    {m.dias > 0 && ` por ${m.dias} días`}
                    {m.frecuencia && !m.cada_horas && ` — ${m.frecuencia}`}
                    {m.indicaciones && (
                      <span className="text-zinc-500"> ({m.indicaciones})</span>
                    )}
                  </p>
                ))}
                {r.indicaciones && (
                  <p className="text-xs text-zinc-600 border-t border-zinc-200 pt-2">
                    {r.indicaciones}
                  </p>
                )}
              </div>
            ))}
          </section>

          <section className="space-y-2">
            <h2 className="text-xs font-bold text-zinc-600 uppercase tracking-widest">
              Visitas ({datos.visitas.length})
            </h2>
            {datos.visitas.map((v, i) => (
              <p key={i} className="text-xs text-zinc-600 flex items-center gap-2">
                <span className="font-mono text-zinc-500">
                  {soloFecha(v.fecha)} {soloHora(v.fecha)}
                </span>
                <span className="text-zinc-500">·</span> {v.estado}
                {v.motivo && <span className="text-zinc-500">— {v.motivo}</span>}
              </p>
            ))}
          </section>
        </>
      )}
    </div>
  );
}

/** Cambiar la propia clave. La temporal la generó otra persona. */
function CambiarClave({ onClose }: { onClose: () => void }) {
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [estado, setEstado] = useState("");
  const [listo, setListo] = useState(false);

  const guardar = async () => {
    setEstado("");
    if (nueva !== repetida) { setEstado("Las dos claves nuevas no coinciden."); return; }
    try {
      const r = await auth.cambiarClave(actual, nueva);
      setListo(true);
      setEstado(
        r.sesiones_cerradas > 0
          ? `Listo. Se cerraron ${r.sesiones_cerradas} sesión(es) abierta(s) en otros dispositivos.`
          : "Listo, tu clave quedó cambiada."
      );
    } catch (e) {
      setEstado(e instanceof Error ? e.message : "No se pudo cambiar");
    }
  };

  return (
    <Modal title="Cambiar mi contraseña" onClose={onClose}>
      <div className="space-y-3">
        <p className="text-xs text-zinc-600">
          Si entraste con una clave que te pasó la clínica, cambiala: esa la conoce
          quien te la dio. Al cambiarla se cierran tus sesiones en otros dispositivos.
        </p>
        <input className={input} type="password" placeholder="Clave actual"
          value={actual} onChange={(e) => setActual(e.target.value)} />
        <input className={input} type="password" placeholder="Clave nueva (mínimo 10)"
          value={nueva} onChange={(e) => setNueva(e.target.value)} />
        <input className={input} type="password" placeholder="Repetí la clave nueva"
          value={repetida} onChange={(e) => setRepetida(e.target.value)} />
        {estado && (
          <p className={`text-xs ${listo ? "text-emerald-700" : "text-red-600"}`}>{estado}</p>
        )}
        {!listo && (
          <button onClick={guardar}
            disabled={!actual || nueva.length < 10}
            className={`${btnPrimary} w-full justify-center disabled:opacity-40`}>
            Cambiar contraseña
          </button>
        )}
      </div>
    </Modal>
  );
}

export function PortalView({ companyId, onSalir }: {
  companyId: number; onSalir: () => void;
}) {
  const [yo, setYo] = useState<PortalMe | null>(null);
  const [dia, setDia] = useState(hoyISO());
  const [agenda, setAgenda] = useState<Previsita | null>(null);
  const [error, setError] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [encontrados, setEncontrados] = useState<PortalPaciente[]>([]);
  const [abierto, setAbierto] = useState<{ nombre: string; telefono: string } | null>(null);
  const [cambiando, setCambiando] = useState(false);
  // El portal tiene dos pantallas: los pacientes de hoy y lo que hay que
  // cobrar. Son dos momentos distintos del día del profesional.
  const [pantalla, setPantalla] = useState<"dia" | "honorarios">("dia");

  useEffect(() => {
    api.portalMe(companyId).then(setYo)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo entrar"));
  }, [companyId]);

  useEffect(() => {
    setAgenda(null);
    api.portalAgenda(companyId, dia).then(setAgenda).catch(() => setAgenda(null));
  }, [companyId, dia]);

  useEffect(() => {
    if (busqueda.trim().length < 2) { setEncontrados([]); return; }
    const t = setTimeout(() => {
      api.portalPacientes(companyId, busqueda.trim()).then(setEncontrados).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [companyId, busqueda]);

  const salir = () => { auth.logout().finally(onSalir); };

  return (
    <div className="min-h-screen bg-[#f6f4ff] font-sans text-zinc-700">
      <header className="border-b border-zinc-200 bg-white">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-600 to-cyan-500 flex items-center justify-center">
              <Stethoscope size={17} className="text-zinc-900" />
            </div>
            <div>
              <p className="font-bold text-zinc-900 text-sm leading-tight">
                {yo?.nombre ?? "Portal del profesional"}
              </p>
              <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-mono">
                {yo?.especialidad || yo?.empresa || ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <button onClick={() => setPantalla(pantalla === "dia" ? "honorarios" : "dia")}
              className="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5">
              {pantalla === "dia"
                ? <><Receipt size={13} /> Mis honorarios</>
                : <><CalendarDays size={13} /> Mi día</>}
            </button>
            <button onClick={() => setCambiando(true)}
              className="text-xs text-zinc-500 hover:text-zinc-800 flex items-center gap-1.5">
              <KeyRound size={13} /> Mi clave
            </button>
            <button onClick={salir}
              className="text-xs text-zinc-500 hover:text-zinc-800 flex items-center gap-1.5">
              <LogOut size={13} /> Salir
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 pb-24">
        {error && (
          <p className="text-red-600 bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-sm">
            {error}
          </p>
        )}

        {pantalla === "honorarios" ? (
          <HonorariosView companyId={companyId} />
        ) : abierto ? (
          <Ficha companyId={companyId} paciente={abierto.nombre} telefono={abierto.telefono}
            onVolver={() => setAbierto(null)} />
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h1 className="text-2xl font-extrabold text-zinc-900 tracking-tight">Mi día</h1>
                <p className="text-sm text-zinc-500">
                  {agenda
                    ? `${agenda.total} paciente${agenda.total !== 1 ? "s" : ""} el ${agenda.dia_de_la_semana}`
                    : "Cargando…"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <CalendarDays size={15} className="text-zinc-500" />
                <input type="date" className={`${input} w-auto`} value={dia}
                  onChange={(e) => setDia(e.target.value)} />
              </div>
            </div>

            {agenda && agenda.total === 0 && (
              <p className="text-sm text-zinc-500 py-16 text-center">
                No tenés pacientes agendados ese día.
              </p>
            )}

            {agenda && agenda.total > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {agenda.pacientes.map((f, i) => (
                  // La rotación alterna para que parezcan pegados a mano.
                  <div key={i} className={i % 3 === 0 ? "rotate-[-1.2deg]"
                    : i % 3 === 1 ? "rotate-[0.8deg]" : "rotate-[-0.4deg]"}>
                    <PostIt f={f}
                      onAbrir={() => setAbierto({ nombre: f.paciente, telefono: f.telefono })} />
                  </div>
                ))}
              </div>
            )}

            <section className="pt-6 border-t border-zinc-200 space-y-3">
              <h2 className="text-xs font-bold text-zinc-600 uppercase tracking-widest">
                Buscar un paciente mío
              </h2>
              <div className="relative">
                <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                <input className={`${input} pl-9`} placeholder="Nombre del paciente…"
                  value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
              </div>
              {encontrados.map((p) => (
                <button key={p.telefono + p.nombre}
                  onClick={() => setAbierto({ nombre: p.nombre, telefono: p.telefono })}
                  className="w-full text-left bg-zinc-50 hover:bg-zinc-100 border border-zinc-200
                             rounded-xl px-4 py-3 flex items-center justify-between gap-3 transition-colors">
                  <span className="text-sm text-zinc-800 flex items-center gap-2">
                    <User size={13} className="text-zinc-500" /> {p.nombre}
                  </span>
                  <span className="text-[11px] text-zinc-500">
                    {p.visitas} {p.visitas === 1 ? "visita" : "visitas"} · última {soloFecha(p.ultima_visita)}
                  </span>
                </button>
              ))}
            </section>
          </div>
        )}
      </main>

      {cambiando && <CambiarClave onClose={() => setCambiando(false)} />}
    </div>
  );
}
