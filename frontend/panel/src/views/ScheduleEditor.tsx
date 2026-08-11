import { useEffect, useState } from "react";
import { AlertTriangle, CalendarClock, Check, Copy, Plus, Trash2 } from "lucide-react";
import {
  api, type CitaFueraDeHorario, type Doctor, type Franja, type HorarioDoctor,
} from "../api";
import { btnPrimary, Modal } from "../ui";

/**
 * Carga del horario que el servidor usa para validar turnos.
 *
 * Sin esta pantalla el bot no puede confirmar disponibilidad: toma el turno
 * como PEDIDO y avisa que recepción confirma. Con el horario cargado deja de
 * aceptar un domingo a las 23:00 con un profesional que atiende de mañana.
 *
 * El texto libre que ya cargó la clínica se muestra AL LADO para transcribirlo.
 * No se interpreta solo a propósito: adivinar un horario con una regex y
 * después agendar sobre esa adivinanza es el problema que vinimos a arreglar.
 */

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

// Lo que carga casi todo el mundo. Tener el atajo evita nueve clics repetidos
// por profesional, que es la diferencia entre que la clínica lo haga y que no.
const ATAJOS: { nombre: string; dias: number[]; desde: string; hasta: string }[] = [
  { nombre: "Lun a Vie mañana", dias: [0, 1, 2, 3, 4], desde: "08:00", hasta: "12:00" },
  { nombre: "Lun a Vie tarde", dias: [0, 1, 2, 3, 4], desde: "14:00", hasta: "19:00" },
  { nombre: "Lun a Vie todo el día", dias: [0, 1, 2, 3, 4], desde: "08:00", hasta: "18:00" },
  { nombre: "Lun a Sáb mañana", dias: [0, 1, 2, 3, 4, 5], desde: "07:00", hasta: "12:00" },
];

const HORA_OK = /^([01]?\d|2[0-3]):[0-5]\d$/;

export function franjasValidas(franjas: Franja[]): string {
  for (const f of franjas) {
    if (!HORA_OK.test(f.desde) || !HORA_OK.test(f.hasta)) {
      return `Revisá la hora "${f.desde || "?"} a ${f.hasta || "?"}" del ${DIAS[f.weekday]}: usá formato HH:MM.`;
    }
    if (f.hasta <= f.desde) {
      return `El ${DIAS[f.weekday]} de ${f.desde} a ${f.hasta} termina antes de empezar.`;
    }
  }
  // Franjas que se pisan dentro del mismo día: el servidor no las rechaza,
  // pero cargarlas dos veces confunde a quien después lee la agenda.
  for (let i = 0; i < franjas.length; i++) {
    for (let j = i + 1; j < franjas.length; j++) {
      const a = franjas[i], b = franjas[j];
      if (a.weekday === b.weekday && a.desde < b.hasta && b.desde < a.hasta) {
        return `El ${DIAS[a.weekday]} tenés dos franjas superpuestas (${a.desde}-${a.hasta} y ${b.desde}-${b.hasta}).`;
      }
    }
  }
  return "";
}

export function EditorDeFranjas({ franjas, onChange }: {
  franjas: Franja[]; onChange: (f: Franja[]) => void;
}) {
  const porDia = (d: number) => franjas.filter((f) => f.weekday === d);

  const agregar = (weekday: number) => {
    const delDia = porDia(weekday);
    // La segunda franja del día arranca donde suele arrancar la tarde.
    const nueva: Franja = delDia.length
      ? { weekday, desde: "14:00", hasta: "18:00" }
      : { weekday, desde: "08:00", hasta: "12:00" };
    onChange([...franjas, nueva]);
  };

  const editar = (objetivo: Franja, campo: "desde" | "hasta", valor: string) =>
    onChange(franjas.map((f) => (f === objetivo ? { ...f, [campo]: valor } : f)));

  const quitar = (objetivo: Franja) => onChange(franjas.filter((f) => f !== objetivo));

  const aplicarAtajo = (a: typeof ATAJOS[number]) =>
    onChange([
      ...franjas.filter((f) => !a.dias.includes(f.weekday)),
      ...a.dias.map((weekday) => ({ weekday, desde: a.desde, hasta: a.hasta })),
    ]);

  const copiarADiasHabiles = (origen: Franja) =>
    onChange([
      ...franjas.filter((f) => f.weekday === origen.weekday || f.weekday > 4),
      ...[0, 1, 2, 3, 4]
        .filter((d) => d !== origen.weekday)
        .map((weekday) => ({ weekday, desde: origen.desde, hasta: origen.hasta })),
    ]);

  const error = franjasValidas(franjas);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {ATAJOS.map((a) => (
          <button key={a.nombre} type="button" onClick={() => aplicarAtajo(a)}
            className="text-[11px] bg-white/[0.04] hover:bg-cyan-500/10 hover:text-cyan-300 text-zinc-400 border border-white/10 px-2.5 py-1 rounded-lg">
            {a.nombre}
          </button>
        ))}
        {franjas.length > 0 && (
          <button type="button" onClick={() => onChange([])}
            className="text-[11px] text-zinc-500 hover:text-red-400 px-2.5 py-1">
            Vaciar
          </button>
        )}
      </div>

      <div className="space-y-1.5">
        {DIAS.map((nombre, d) => {
          const delDia = porDia(d);
          return (
            <div key={d} className={`flex items-start gap-3 rounded-xl px-3 py-2 ${
              delDia.length ? "bg-cyan-500/[0.06] border border-cyan-500/20" : "bg-white/[0.02] border border-white/5"
            }`}>
              <span className={`text-xs font-bold w-20 pt-2 shrink-0 ${
                delDia.length ? "text-cyan-300" : "text-zinc-600"
              }`}>
                {nombre}
              </span>
              <div className="flex-1 space-y-1.5">
                {delDia.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 flex-wrap">
                    <input type="time" value={f.desde} onChange={(e) => editar(f, "desde", e.target.value)}
                      className="bg-white/[0.03] border border-white/10 rounded-lg px-2 py-1 text-sm text-zinc-100 focus:outline-none focus:border-cyan-500" />
                    <span className="text-zinc-600 text-xs">a</span>
                    <input type="time" value={f.hasta} onChange={(e) => editar(f, "hasta", e.target.value)}
                      className="bg-white/[0.03] border border-white/10 rounded-lg px-2 py-1 text-sm text-zinc-100 focus:outline-none focus:border-cyan-500" />
                    <button type="button" onClick={() => quitar(f)} title="Quitar esta franja"
                      className="text-zinc-600 hover:text-red-400 p-1"><Trash2 size={13} /></button>
                    {d <= 4 && (
                      <button type="button" onClick={() => copiarADiasHabiles(f)}
                        title="Copiar este horario a los demás días hábiles"
                        className="text-zinc-600 hover:text-cyan-400 p-1"><Copy size={13} /></button>
                    )}
                  </div>
                ))}
                {!delDia.length && (
                  <span className="text-xs text-zinc-600 leading-8">No atiende</span>
                )}
              </div>
              <button type="button" onClick={() => agregar(d)}
                title={delDia.length ? "Agregar otra franja (ej. la tarde)" : "Agregar horario"}
                className="text-cyan-400 hover:text-cyan-300 p-1 pt-2 shrink-0"><Plus size={15} /></button>
            </div>
          );
        })}
      </div>

      {error && (
        <p className="text-xs text-amber-400 flex items-start gap-1.5">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" /> {error}
        </p>
      )}
    </div>
  );
}

function CitasQueQuedanAfuera({ citas }: { citas: CitaFueraDeHorario[] }) {
  if (!citas.length) return null;
  return (
    <div className="bg-amber-500/[0.07] border border-amber-500/25 rounded-xl p-3 space-y-2">
      <p className="text-xs text-amber-300 font-bold flex items-center gap-1.5">
        <AlertTriangle size={13} /> {citas.length} turno{citas.length > 1 ? "s" : ""} queda
        {citas.length > 1 ? "n" : ""} fuera del horario nuevo
      </p>
      <p className="text-[11px] text-zinc-400">
        Son personas que ya reservaron. <strong className="text-zinc-300">No se cancelaron</strong>:
        hay que llamarlas para reprogramar.
      </p>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {citas.map((c) => (
          <div key={c.id} className="text-xs bg-black/30 rounded-lg px-2.5 py-1.5">
            <span className="text-zinc-100 font-medium">{c.paciente}</span>
            <span className="text-zinc-500"> · {c.cuando}</span>
            {c.telefono && (
              <>
                <span className="text-zinc-600"> · </span>
                <a href={`https://wa.me/${c.telefono.replace(/\D/g, "")}`} target="_blank"
                  rel="noopener noreferrer" title="Escribirle por WhatsApp"
                  className="text-cyan-400 hover:text-cyan-300">{c.telefono}</a>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ScheduleModal({ companyId, doctor, onClose, onSaved }: {
  companyId: number; doctor: Doctor; onClose: () => void; onSaved: () => void;
}) {
  const [horario, setHorario] = useState<HorarioDoctor | null>(null);
  const [franjas, setFranjas] = useState<Franja[]>([]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [afuera, setAfuera] = useState<CitaFueraDeHorario[] | null>(null);

  useEffect(() => {
    api.verHorario(companyId, doctor.id)
      .then((h) => { setHorario(h); setFranjas(h.franjas); })
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, [companyId, doctor.id]);

  const guardar = async () => {
    const problema = franjasValidas(franjas);
    if (problema) { setError(problema); return; }
    setError(""); setGuardando(true);
    try {
      const r = await api.guardarHorario(companyId, doctor.id, franjas);
      onSaved();
      if (r.citas_fuera_de_horario.length) {
        // No se cierra: la lista de a quién llamar es lo más importante que
        // va a ver en toda la pantalla.
        setAfuera(r.citas_fuera_de_horario);
        setHorario((h) => (h ? { ...h, agenda_mode: r.agenda_mode as HorarioDoctor["agenda_mode"] } : h));
      } else {
        onClose();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Modal title={`Horario de ${doctor.name}`} onClose={onClose}>
      {!horario ? (
        <p className="text-sm text-zinc-500 py-8 text-center">Cargando…</p>
      ) : (
        <div className="space-y-4">
          <div className={`rounded-xl p-3 text-xs leading-relaxed ${
            horario.agenda_mode === "estructurado"
              ? "bg-emerald-500/[0.07] border border-emerald-500/25 text-emerald-200"
              : "bg-amber-500/[0.07] border border-amber-500/25 text-amber-200"
          }`}>
            {horario.agenda_mode === "estructurado" ? (
              <><Check size={13} className="inline mr-1" />El bot verifica los turnos contra este horario.</>
            ) : (
              <><AlertTriangle size={13} className="inline mr-1" />
                Todavía sin horario cargado: el bot toma los turnos como <strong>pedido</strong> y
                avisa que recepción confirma. No puede rechazar un domingo a las 23:00.</>
            )}
          </div>

          {horario.texto_libre && (
            <div className="bg-white/[0.02] border border-white/5 rounded-xl p-3">
              <p className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">
                Como está cargado hoy (texto libre)
              </p>
              <p className="text-sm text-zinc-200 font-mono">{horario.texto_libre}</p>
              <p className="text-[11px] text-zinc-500 mt-1.5">
                Pasalo abajo vos: el sistema no lo interpreta solo, porque agendar sobre una
                adivinanza es justo lo que queremos evitar.
              </p>
            </div>
          )}

          <EditorDeFranjas franjas={franjas} onChange={(f) => { setFranjas(f); setAfuera(null); }} />

          {afuera && <CitasQueQuedanAfuera citas={afuera} />}
          {error && <p className="text-red-400 text-xs">{error}</p>}

          <div className="flex justify-between items-center pt-3 border-t border-white/5">
            <span className="text-[11px] text-zinc-500">
              {franjas.length
                ? `${franjas.length} franja${franjas.length > 1 ? "s" : ""} en la semana`
                : "Sin franjas: vuelve a modo pedido"}
            </span>
            <div className="flex gap-3">
              <button onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">
                {afuera ? "Cerrar" : "Cancelar"}
              </button>
              <button onClick={guardar} disabled={guardando} className={btnPrimary}>
                <CalendarClock size={14} /> Guardar horario
              </button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

export function ClinicScheduleModal({ companyId, onClose, onSaved }: {
  companyId: number; onClose: () => void; onSaved: () => void;
}) {
  const [franjas, setFranjas] = useState<Franja[]>([]);
  const [nota, setNota] = useState("");
  const [cargado, setCargado] = useState(false);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    api.verHorarioClinica(companyId)
      .then((r) => { setFranjas(r.franjas); setNota(r.nota); setCargado(true); })
      .catch(() => setCargado(true));
  }, [companyId]);

  const guardar = async () => {
    const problema = franjasValidas(franjas);
    if (problema) { setError(problema); return; }
    setError(""); setGuardando(true);
    try {
      await api.guardarHorarioClinica(companyId, franjas);
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Modal title="Horario del centro" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-xs text-zinc-400 leading-relaxed">
          Cuándo abre la institución. Es lo primero que conviene cargar:{" "}
          <strong className="text-zinc-200">con esto solo, el bot ya deja de aceptar turnos
          un domingo a las 23:00</strong> para todos los profesionales, sin esperar a que cada
          uno cargue el suyo. {nota && <span className="text-zinc-500">{nota}</span>}
        </p>
        {!cargado ? (
          <p className="text-sm text-zinc-500 py-8 text-center">Cargando…</p>
        ) : (
          <EditorDeFranjas franjas={franjas} onChange={setFranjas} />
        )}
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <div className="flex justify-end gap-3 pt-3 border-t border-white/5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
          <button onClick={guardar} disabled={guardando} className={btnPrimary}>
            <CalendarClock size={14} /> Guardar
          </button>
        </div>
      </div>
    </Modal>
  );
}
