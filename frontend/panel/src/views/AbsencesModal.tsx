import React from "react";
import { useEffect, useState } from "react";
import { AlertTriangle, CalendarOff, Plus, Trash2 } from "lucide-react";
import { api, type Ausencia, type CitaFueraDeHorario, type Doctor } from "../api";
import { input, btnPrimary, Modal } from "../ui";

/**
 * Licencias, vacaciones y feriados.
 *
 * Sin esto el bot le da turnos a un profesional que está de vacaciones dos
 * semanas, y el paciente se entera el día que viaja hasta la clínica.
 */

function hoyISO() {
  return new Date().toISOString().slice(0, 10);
}

export function AbsencesModal({ companyId, doctors, onClose, onSaved }: {
  companyId: number; doctors: Doctor[]; onClose: () => void; onSaved: () => void;
}) {
  const [ausencias, setAusencias] = useState<Ausencia[]>([]);
  const [form, setForm] = useState({
    doctor_id: "" as string, desde: hoyISO(), hasta: hoyISO(), motivo: "",
  });
  const [error, setError] = useState("");
  const [afectadas, setAfectadas] = useState<CitaFueraDeHorario[]>([]);
  const [guardando, setGuardando] = useState(false);

  const cargar = () =>
    api.listarAusencias(companyId).then(setAusencias).catch(() => setAusencias([]));
  useEffect(() => { cargar(); }, [companyId]);

  const agregar = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.hasta < form.desde) {
      setError("La fecha de vuelta es anterior a la de salida.");
      return;
    }
    setError(""); setGuardando(true);
    try {
      const r = await api.crearAusencia(companyId, {
        doctor_id: form.doctor_id ? Number(form.doctor_id) : null,
        desde: form.desde, hasta: form.hasta, motivo: form.motivo,
      });
      setAfectadas(r.citas_afectadas);
      setForm({ ...form, motivo: "" });
      cargar();
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  const borrar = async (id: number) => {
    await api.borrarAusencia(companyId, id);
    cargar();
    onSaved();
  };

  const nombreDe = (id: number | null) =>
    id ? (doctors.find((d) => d.id === id)?.name ?? `#${id}`) : "Todo el centro";

  return (
    <Modal title="Licencias y feriados" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-xs text-zinc-400 leading-relaxed">
          Días en los que no se atiende. El bot deja de dar turnos ahí — sin esto, le agenda
          pacientes a alguien que está de vacaciones y se enteran cuando llegan a la clínica.
        </p>

        <form onSubmit={agregar} className="bg-white/[0.02] border border-white/5 rounded-xl p-3 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest block mb-1">
                Quién
              </label>
              <select className={input} value={form.doctor_id}
                onChange={(e) => setForm({ ...form, doctor_id: e.target.value })}>
                <option value="" className="bg-[#090b10]">Todo el centro (feriado)</option>
                {doctors.map((d) => (
                  <option key={d.id} value={d.id} className="bg-[#090b10]">{d.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest block mb-1">
                Motivo
              </label>
              <input className={input} placeholder="vacaciones, congreso, feriado…"
                value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} />
            </div>
            <div>
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest block mb-1">
                Desde
              </label>
              <input type="date" className={input} value={form.desde}
                onChange={(e) => setForm({ ...form, desde: e.target.value })} />
            </div>
            <div>
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest block mb-1">
                Hasta (inclusive)
              </label>
              <input type="date" className={input} value={form.hasta}
                onChange={(e) => setForm({ ...form, hasta: e.target.value })} />
            </div>
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex justify-end">
            <button type="submit" disabled={guardando} className={btnPrimary}>
              <Plus size={14} /> Agregar
            </button>
          </div>
        </form>

        {afectadas.length > 0 && (
          <div className="bg-amber-500/[0.07] border border-amber-500/25 rounded-xl p-3 space-y-2">
            <p className="text-xs text-amber-300 font-bold flex items-center gap-1.5">
              <AlertTriangle size={13} /> {afectadas.length} turno
              {afectadas.length > 1 ? "s" : ""} caen en esos días
            </p>
            <p className="text-[11px] text-zinc-400">
              <strong className="text-zinc-300">No se cancelaron.</strong> Hay que avisarles.
            </p>
            {afectadas.map((c) => (
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
        )}

        <div className="space-y-1.5 max-h-64 overflow-y-auto">
          {ausencias.map((a) => (
            <div key={a.id} className="flex items-center gap-3 bg-white/[0.02] border border-white/5 rounded-xl px-3 py-2">
              <CalendarOff size={14} className={a.doctor_id ? "text-zinc-500" : "text-amber-400"} />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-zinc-100 truncate">{nombreDe(a.doctor_id)}</p>
                <p className="text-[11px] text-zinc-500">
                  {new Date(a.desde + "T00:00:00").toLocaleDateString("es-PY")} al{" "}
                  {new Date(a.hasta + "T00:00:00").toLocaleDateString("es-PY")}
                  {a.motivo && ` · ${a.motivo}`}
                </p>
              </div>
              <button onClick={() => borrar(a.id)} title="Quitar"
                className="text-zinc-600 hover:text-red-400 p-1"><Trash2 size={14} /></button>
            </div>
          ))}
          {!ausencias.length && (
            <p className="text-xs text-zinc-600 text-center py-4">
              Sin licencias cargadas para los próximos días.
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
