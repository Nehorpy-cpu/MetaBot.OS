import { useEffect, useState } from "react";
import {
  AlertTriangle, Check, Clock, Copy, HelpCircle, Pill, Send, Sparkles,
} from "lucide-react";
import { api, type Doctor, type FichaPaciente, type Previsita } from "../api";
import { input, btnPrimary, Modal } from "../ui";

/**
 * El resumen que recibe el PROFESIONAL antes de atender.
 *
 * La agenda diaria le decía a quién iba a ver. Esto le dice lo que necesita
 * saber antes de que el paciente entre: si ya vino, qué se le recetó la vez
 * pasada, y qué se le va a hacer hoy.
 *
 * Va al doctor, nunca al paciente. Y se arma en el servidor con los datos
 * cargados: acá solo se muestran.
 */

function manana() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

function Ficha({ f }: { f: FichaPaciente }) {
  return (
    <div className="bg-white/[0.02] border border-white/5 rounded-xl p-3 space-y-1.5">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="font-mono text-cyan-400 text-sm font-bold">{f.hora}</span>
        <span className="text-sm text-zinc-100 font-medium">{f.paciente}</span>
        {f.primera_vez && (
          <span className="text-[10px] bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded-full font-bold flex items-center gap-1">
            <Sparkles size={10} /> Primera vez
          </span>
        )}
        {f.sin_confirmar && (
          <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/25 px-2 py-0.5 rounded-full">
            sin confirmar
          </span>
        )}
      </div>

      {(f.servicio || f.motivo) && (
        <p className="text-xs text-zinc-400">
          {[f.servicio, f.motivo].filter(Boolean).join(" · ")}
          {f.duracion_min !== 30 && (
            <span className="text-zinc-600"> · {f.duracion_min} min</span>
          )}
        </p>
      )}

      {!f.primera_vez && (
        <p className="text-xs text-zinc-500 flex items-center gap-1">
          {/* "veces", no "vez"+"ces": el plural cambia la z por c. */}
          <Clock size={11} /> Ya vino {f.visitas_previas} {f.visitas_previas === 1 ? "vez" : "veces"}
          {f.ultima_visita && ` · última: ${f.ultima_visita}`}
        </p>
      )}
      {f.faltas_previas > 0 && (
        <p className="text-xs text-amber-400 flex items-center gap-1">
          <AlertTriangle size={11} /> Faltó {f.faltas_previas}{" "}
          {f.faltas_previas === 1 ? "vez" : "veces"} sin avisar
        </p>
      )}
      {f.numero_compartido && (
        <p className="text-[11px] text-zinc-500 flex items-start gap-1.5"
          title="No se muestra el historial de la otra persona">
          <HelpCircle size={11} className="shrink-0 mt-0.5" />
          Con este mismo número hay registros a nombre de otra persona.
          Confirmá con quién estás hablando.
        </p>
      )}

      {f.ultima_receta && (
        <div className="bg-black/25 rounded-lg px-2.5 py-2 mt-1">
          <p className="text-[11px] text-zinc-400 flex items-center gap-1.5">
            <Pill size={11} className="text-emerald-400" />
            Receta del {f.ultima_receta.fecha}
            {f.ultima_receta.por && <span className="text-zinc-500">· {f.ultima_receta.por}</span>}
          </p>
          {f.ultima_receta.diagnostico && (
            <p className="text-xs text-zinc-300 mt-1">Dx: {f.ultima_receta.diagnostico}</p>
          )}
          {f.ultima_receta.medicacion.map((m, i) => (
            <p key={i} className="text-[11px] text-zinc-400 ml-2">• {m}</p>
          ))}
        </div>
      )}

      {f.preparacion_requerida && (
        <p className="text-[11px] text-amber-300 flex items-start gap-1.5">
          <AlertTriangle size={11} className="shrink-0 mt-0.5" /> {f.preparacion_requerida}
        </p>
      )}
      {f.turno_sin_verificar && (
        <p className="text-[11px] text-zinc-500 flex items-start gap-1.5"
          title="El turno se tomó sin poder validarlo contra el horario del profesional">
          <HelpCircle size={11} className="shrink-0 mt-0.5" /> Turno sin verificar contra el horario
        </p>
      )}
    </div>
  );
}

export function PreVisitModal({ companyId, doctors, onClose }: {
  companyId: number; doctors: Doctor[]; onClose: () => void;
}) {
  const [doctorId, setDoctorId] = useState(doctors[0]?.id ?? 0);
  const [fecha, setFecha] = useState(manana());
  const [datos, setDatos] = useState<Previsita | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");
  const [copiado, setCopiado] = useState(false);
  const [envio, setEnvio] = useState("");

  useEffect(() => {
    if (!doctorId) return;
    setCargando(true); setError(""); setEnvio("");
    api.previsita(companyId, doctorId, fecha)
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"))
      .finally(() => setCargando(false));
  }, [companyId, doctorId, fecha]);

  const copiar = async () => {
    if (!datos) return;
    try {
      await navigator.clipboard.writeText(datos.texto);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      /* clipboard no disponible */
    }
  };

  const enviar = async () => {
    setEnvio("");
    try {
      const r = await api.enviarPrevisita(companyId, doctorId, fecha);
      setEnvio(r.enviado
        ? `Enviado a ${datos?.doctor} (${r.pacientes} pacientes).`
        : `No se envió: ${r.motivo || "sin pacientes ese día"}`);
    } catch (e) {
      setEnvio(e instanceof Error ? e.message : "No se pudo enviar");
    }
  };

  const doctor = doctors.find((d) => d.id === doctorId);
  const sinTelefono = doctor && !doctor.phone;

  return (
    <Modal title="Resumen para el profesional" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-xs text-zinc-400 leading-relaxed">
          Lo que el profesional necesita saber <strong className="text-zinc-200">antes</strong> de
          que el paciente entre: si ya vino, qué se le recetó la vez pasada y qué se le va a hacer
          hoy. Se manda solo a las 20:00 de la noche anterior; acá podés verlo o adelantarlo.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <select className={input} value={doctorId}
            onChange={(e) => setDoctorId(Number(e.target.value))}>
            {doctors.map((d) => (
              <option key={d.id} value={d.id} className="bg-[#090b10]">{d.name}</option>
            ))}
          </select>
          <input type="date" className={input} value={fecha}
            onChange={(e) => setFecha(e.target.value)} />
        </div>

        {cargando && <p className="text-sm text-zinc-500 py-6 text-center">Cargando…</p>}
        {error && <p className="text-red-400 text-xs">{error}</p>}

        {datos && !cargando && (
          <>
            <div className="flex flex-wrap gap-3 text-xs text-zinc-400">
              <span><strong className="text-white">{datos.total}</strong> paciente{datos.total !== 1 ? "s" : ""}</span>
              {datos.primera_vez > 0 && (
                <span><strong className="text-indigo-300">{datos.primera_vez}</strong> por primera vez</span>
              )}
              {datos.sin_confirmar > 0 && (
                <span><strong className="text-amber-400">{datos.sin_confirmar}</strong> sin confirmar</span>
              )}
            </div>

            {datos.total === 0 ? (
              <p className="text-xs text-zinc-600 text-center py-6">
                {datos.doctor} no tiene pacientes el {datos.dia_de_la_semana}.
              </p>
            ) : (
              <div className="space-y-2 max-h-[45vh] overflow-y-auto">
                {datos.pacientes.map((f, i) => <Ficha key={i} f={f} />)}
              </div>
            )}

            {envio && <p className="text-xs text-cyan-300">{envio}</p>}
            {sinTelefono && datos.total > 0 && (
              <p className="text-[11px] text-amber-400 flex items-start gap-1.5">
                <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                {datos.doctor} no tiene teléfono cargado. Son datos clínicos: sin un número
                verificado no se manda a ningún lado.
              </p>
            )}

            <div className="flex justify-between items-center pt-3 border-t border-white/5">
              <button onClick={copiar} disabled={!datos.total}
                className="text-xs text-zinc-400 hover:text-white flex items-center gap-1.5 disabled:opacity-40">
                {copiado ? <><Check size={13} /> ¡Copiado!</> : <><Copy size={13} /> Copiar texto</>}
              </button>
              <div className="flex gap-3">
                <button onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">
                  Cerrar
                </button>
                <button onClick={enviar} disabled={!datos.total || !!sinTelefono} className={btnPrimary}>
                  <Send size={14} /> Enviar al profesional
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
