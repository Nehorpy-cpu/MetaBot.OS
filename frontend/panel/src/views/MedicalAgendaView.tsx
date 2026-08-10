import React from "react";
import { useCallback, useEffect, useState } from "react";
import { Calendar, Clock, Plus, Send, Smartphone, Users } from "lucide-react";
import { STATUS_ES, api, type Appointment, type DailySummary, type Doctor } from "../api";
import { card, input, btnPrimary, Modal } from "../ui";

export function MedicalAgendaView({ companyId }: { companyId: number }) {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [selectedDoctor, setSelectedDoctor] = useState<number | "all">("all");
  const [summaries, setSummaries] = useState<DailySummary[]>([]);
  const [showSummaries, setShowSummaries] = useState(false);
  const [copiedDoctor, setCopiedDoctor] = useState<string | null>(null);
  const [showAddDoctor, setShowAddDoctor] = useState(false);
  const [showAddAppt, setShowAddAppt] = useState(false);

  const load = useCallback(() => {
    api.listDoctors(companyId).then(setDoctors).catch(() => setDoctors([]));
    api.listAppointments(companyId).then(setAppointments).catch(() => setAppointments([]));
  }, [companyId]);
  useEffect(load, [load]);

  const openSummaries = async () => {
    const results = await Promise.all(doctors.map((d) => api.dailySummary(companyId, d.id)));
    setSummaries(results);
    setShowSummaries(true);
  };

  const copySummary = async (s: DailySummary) => {
    try {
      await navigator.clipboard.writeText(s.text);
      setCopiedDoctor(s.doctor);
      setTimeout(() => setCopiedDoctor(null), 2000);
    } catch {
      /* clipboard no disponible */
    }
  };

  const cycleStatus = async (a: Appointment) => {
    const order = ["pending", "confirmed", "attended", "no_show", "cancelled"];
    const next = order[(order.indexOf(a.status) + 1) % order.length];
    await api.updateAppointmentStatus(companyId, a.id, next);
    load();
  };

  const visible = appointments.filter((a) => selectedDoctor === "all" || a.doctor_id === selectedDoctor);

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <Calendar className="text-cyan-400" size={26} /> Agenda de Doctores & Citas
          </h2>
          <p className="text-zinc-400 text-sm mt-1">Citas reales desde la base de datos, resumen diario por doctor.</p>
        </div>
        <button onClick={openSummaries} disabled={!doctors.length} className={btnPrimary}>
          <Send size={15} /> Resumen diario (WhatsApp)
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={`${card} p-5 space-y-3`}>
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest flex items-center gap-2">
              <Users size={15} className="text-indigo-400" /> Doctores ({doctors.length})
            </h3>
            <button onClick={() => setShowAddDoctor(true)} className="text-cyan-400 hover:text-cyan-300 p-1"><Plus size={16} /></button>
          </div>
          <div onClick={() => setSelectedDoctor("all")}
            className={`p-3 rounded-xl border cursor-pointer text-sm font-bold ${selectedDoctor === "all" ? "bg-cyan-500/10 border-cyan-500/50 text-white" : "bg-white/[0.02] border-white/5 text-zinc-400"}`}>
            Todos los consultorios
          </div>
          {doctors.map((d) => (
            <div key={d.id} onClick={() => setSelectedDoctor(d.id)}
              className={`p-3 rounded-xl border cursor-pointer ${selectedDoctor === d.id ? "bg-cyan-500/10 border-cyan-500/50 text-white" : "bg-white/[0.02] border-white/5 text-zinc-400"}`}>
              <p className="font-bold text-sm text-zinc-100">{d.name}</p>
              <p className="text-[10px] text-cyan-300">{d.specialty}</p>
              {d.schedule && <p className="text-xs text-zinc-400 mt-1 flex items-center gap-1"><Clock size={11} /> {d.schedule}</p>}
              {d.phone && <p className="text-xs text-zinc-500 flex items-center gap-1"><Smartphone size={11} /> {d.phone}</p>}
            </div>
          ))}
        </div>

        <div className={`lg:col-span-2 ${card} p-5`}>
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest flex items-center gap-2">
              <Clock size={15} className="text-cyan-400" /> Turnos programados
            </h3>
            <button onClick={() => setShowAddAppt(true)} disabled={!doctors.length}
              className="text-xs bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 px-3 py-1.5 rounded-lg flex items-center gap-1 disabled:opacity-40">
              <Plus size={13} /> Nueva cita
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-zinc-300">
              <thead className="text-[10px] uppercase text-zinc-500 border-b border-white/5">
                <tr><th className="pb-3">Fecha / Hora</th><th className="pb-3">Paciente</th><th className="pb-3">Doctor</th><th className="pb-3">Estado</th></tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {visible.map((a) => (
                  <tr key={a.id} className="hover:bg-white/[0.02]">
                    <td className="py-3 font-mono text-cyan-400 text-xs">
                      {new Date(a.scheduled_at).toLocaleString("es-PY", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="py-3 text-white">
                      {a.patient_name}
                      <span className="block text-[10px] text-zinc-500">{a.patient_phone}</span>
                    </td>
                    <td className="py-3 text-xs">{doctors.find((d) => d.id === a.doctor_id)?.name ?? "—"}</td>
                    <td className="py-3">
                      <button onClick={() => cycleStatus(a)} title="Click para cambiar estado"
                        className={`text-[10px] px-2.5 py-1 rounded-full border font-bold uppercase ${a.status === "confirmed" || a.status === "attended" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : a.status === "cancelled" || a.status === "no_show" ? "bg-red-500/10 text-red-400 border-red-500/20" : "bg-amber-500/10 text-amber-400 border-amber-500/20"}`}>
                        {STATUS_ES[a.status] ?? a.status}
                      </button>
                    </td>
                  </tr>
                ))}
                {!visible.length && (
                  <tr><td colSpan={4} className="py-8 text-center text-zinc-600 text-xs">Sin citas registradas.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {showSummaries && (
        <Modal title="Resumen diario por doctor" onClose={() => setShowSummaries(false)}>
          <div className="space-y-4">
            {summaries.map((s) => (
              <div key={s.doctor} className="bg-white/[0.02] border border-white/5 rounded-xl p-4 space-y-2">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-sm text-white">{s.doctor} <span className="text-xs text-zinc-500">({s.count} citas)</span></span>
                  <button onClick={() => copySummary(s)}
                    className="text-xs bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 px-3 py-1.5 rounded-lg">
                    {copiedDoctor === s.doctor ? "¡Copiado!" : "Copiar"}
                  </button>
                </div>
                <pre className="bg-[#040609] p-3 rounded-lg text-xs font-mono text-zinc-300 whitespace-pre-wrap border border-white/5">{s.text}</pre>
              </div>
            ))}
          </div>
        </Modal>
      )}

      {showAddDoctor && (
        <AddDoctorModal companyId={companyId} onClose={() => setShowAddDoctor(false)} onSaved={load} />
      )}
      {showAddAppt && (
        <AddAppointmentModal companyId={companyId} doctors={doctors} onClose={() => setShowAddAppt(false)} onSaved={load} />
      )}
    </div>
  );
}

export function AddDoctorModal({ companyId, onClose, onSaved }: { companyId: number; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ name: "", specialty: "", schedule: "", phone: "", email: "" });
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createDoctor(companyId, form);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  };
  return (
    <Modal title="Nuevo doctor" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {([["name", "Nombre *"], ["specialty", "Especialidad"], ["schedule", "Horario (ej. 08:00 - 12:00)"], ["phone", "Teléfono"], ["email", "Email"]] as const).map(([k, label]) => (
          <div key={k}>
            <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-1">{label}</label>
            <input className={input} required={k === "name"} value={form[k]}
              onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
          </div>
        ))}
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <div className="flex justify-end gap-3 pt-3 border-t border-white/5">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
          <button type="submit" className={btnPrimary}>Guardar</button>
        </div>
      </form>
    </Modal>
  );
}

export function AddAppointmentModal({ companyId, doctors, onClose, onSaved }: {
  companyId: number; doctors: Doctor[]; onClose: () => void; onSaved: () => void;
}) {
  const [form, setForm] = useState({
    doctor_id: doctors[0]?.id ?? 0, patient_name: "", patient_phone: "", scheduled_at: "", notes: "",
  });
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createAppointment(companyId, form);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  };
  return (
    <Modal title="Nueva cita" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-1">Doctor</label>
          <select className={input} value={form.doctor_id} onChange={(e) => setForm({ ...form, doctor_id: Number(e.target.value) })}>
            {doctors.map((d) => <option key={d.id} value={d.id} className="bg-[#090b10]">{d.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-1">Paciente *</label>
          <input className={input} required value={form.patient_name} onChange={(e) => setForm({ ...form, patient_name: e.target.value })} />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-1">Teléfono</label>
          <input className={input} value={form.patient_phone} onChange={(e) => setForm({ ...form, patient_phone: e.target.value })} />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-1">Fecha y hora *</label>
          <input type="datetime-local" className={input} required value={form.scheduled_at}
            onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })} />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-1">Motivo</label>
          <input className={input} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <div className="flex justify-end gap-3 pt-3 border-t border-white/5">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
          <button type="submit" className={btnPrimary}>Agendar</button>
        </div>
      </form>
    </Modal>
  );
}
