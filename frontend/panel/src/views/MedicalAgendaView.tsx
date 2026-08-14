import React from "react";
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, BadgeCheck, Building2, Calendar, CalendarClock, CalendarOff,
  ClipboardList, Clock, Plus, ShieldCheck, Smartphone, Upload, Users,
} from "lucide-react";
import { STATUS_ES, api, esErrorApi, type Appointment, type Doctor } from "../api";
import { card, input, btnPrimary, Modal } from "../ui";
import { DoctorImportModal } from "./DoctorImportModal";
import { ClinicScheduleModal, ScheduleModal } from "./ScheduleEditor";
import { AbsencesModal } from "./AbsencesModal";
import { PreVisitModal } from "./PreVisitModal";

export function MedicalAgendaView({ companyId }: { companyId: number }) {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [selectedDoctor, setSelectedDoctor] = useState<number | "all">("all");
  const [showAddDoctor, setShowAddDoctor] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showAddAppt, setShowAddAppt] = useState(false);
  const [horarioDe, setHorarioDe] = useState<Doctor | null>(null);
  const [showClinicSchedule, setShowClinicSchedule] = useState(false);
  const [showAbsences, setShowAbsences] = useState(false);
  const [showPreVisit, setShowPreVisit] = useState(false);
  const [clinicaTieneHorario, setClinicaTieneHorario] = useState<boolean | null>(null);

  const load = useCallback(() => {
    api.listDoctors(companyId).then(setDoctors).catch(() => setDoctors([]));
    api.listAppointments(companyId).then(setAppointments).catch(() => setAppointments([]));
    api.verHorarioClinica(companyId)
      .then((r) => setClinicaTieneHorario(r.franjas.length > 0))
      .catch(() => setClinicaTieneHorario(null));
  }, [companyId]);
  useEffect(load, [load]);

  // Cuántos profesionales todavía no cargaron su horario. Mientras estén así,
  // el bot toma sus turnos como pedido y no puede rechazar un horario imposible.
  const sinHorario = doctors.filter((d) => d.agenda_mode !== "estructurado");

  // El "resumen diario" que había acá era la misma lista de citas que ya se ve
  // abajo, sin nada clínico. Lo reemplaza el resumen pre-visita, que incluye
  // todo eso más el historial del paciente. El endpoint viejo sigue existiendo
  // para quien lo consuma por API.

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
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setShowClinicSchedule(true)}
            className="text-sm bg-white/[0.03] hover:bg-white/[0.06] text-zinc-300 border border-white/10 px-4 py-2.5 rounded-xl flex items-center gap-2">
            <Building2 size={15} /> Horario del centro
          </button>
          <button onClick={() => setShowAbsences(true)} disabled={!doctors.length}
            className="text-sm bg-white/[0.03] hover:bg-white/[0.06] text-zinc-300 border border-white/10 px-4 py-2.5 rounded-xl flex items-center gap-2 disabled:opacity-40">
            <CalendarOff size={15} /> Licencias
          </button>
          <button onClick={() => setShowPreVisit(true)} disabled={!doctors.length}
            className={btnPrimary}>
            <ClipboardList size={15} /> Resumen para el profesional
          </button>
        </div>
      </div>

      {/* Lo que hace que el bot pueda rechazar un turno imposible. Se avisa
          arriba de todo porque mientras falte, cada turno que toma es un
          pedido sin confirmar. */}
      {clinicaTieneHorario === false && (
        <button onClick={() => setShowClinicSchedule(true)}
          className="w-full text-left bg-amber-500/[0.07] hover:bg-amber-500/[0.11] border border-amber-500/25 rounded-2xl p-4 flex items-start gap-3 transition-colors">
          <AlertTriangle size={18} className="text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-amber-200">Cargá el horario del centro</p>
            <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
              Son cinco filas y cubren a todos los profesionales. Sin esto el bot acepta un
              turno un domingo a las 23:00, y después le manda al paciente el recordatorio de
              una cita que no existe.
            </p>
          </div>
        </button>
      )}
      {clinicaTieneHorario !== false && sinHorario.length > 0 && doctors.length > 0 && (
        <div className="bg-white/[0.02] border border-white/5 rounded-2xl p-3 flex items-center gap-3">
          <CalendarClock size={16} className="text-zinc-500 shrink-0" />
          <p className="text-xs text-zinc-400 flex-1">
            {sinHorario.length} de {doctors.length} profesionales todavía sin horario propio:
            sus turnos se toman como <strong className="text-zinc-300">pedido</strong> y el bot
            avisa que recepción confirma.
          </p>
          <button onClick={() => setHorarioDe(sinHorario[0])}
            className="text-xs text-cyan-400 hover:text-cyan-300 whitespace-nowrap">
            Cargar el de {sinHorario[0].name.split(",")[0].split(" ").slice(0, 2).join(" ")} →
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={`${card} p-5 space-y-3`}>
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest flex items-center gap-2">
              <Users size={15} className="text-indigo-400" /> Doctores ({doctors.length})
            </h3>
            <div className="flex items-center gap-1">
              <button onClick={() => setShowImport(true)} title="Buscar en el padrón o subir tu planilla"
                className="text-cyan-400 hover:text-cyan-300 p-1"><Upload size={15} /></button>
              <button onClick={() => setShowAddDoctor(true)} title="Cargar uno a mano"
                className="text-cyan-400 hover:text-cyan-300 p-1"><Plus size={16} /></button>
            </div>
          </div>
          {!doctors.length && (
            <button onClick={() => setShowImport(true)}
              className="w-full border-2 border-dashed border-white/10 hover:border-cyan-500/40 rounded-xl p-5 text-center transition-colors">
              <Upload size={20} className="mx-auto text-zinc-600 mb-2" />
              <span className="text-xs text-zinc-400 block">Cargá tus profesionales</span>
              <span className="text-[10px] text-zinc-600">desde el padrón del CPM o tu propia planilla</span>
            </button>
          )}
          <div onClick={() => setSelectedDoctor("all")}
            className={`p-3 rounded-xl border cursor-pointer text-sm font-bold ${selectedDoctor === "all" ? "bg-cyan-500/10 border-cyan-500/50 text-white" : "bg-white/[0.02] border-white/5 text-zinc-400"}`}>
            Todos los consultorios
          </div>
          {doctors.map((d) => (
            <div key={d.id} onClick={() => setSelectedDoctor(d.id)}
              className={`p-3 rounded-xl border cursor-pointer ${selectedDoctor === d.id ? "bg-cyan-500/10 border-cyan-500/50 text-white" : "bg-white/[0.02] border-white/5 text-zinc-400"}`}>
              <p className="font-bold text-sm text-zinc-100 flex items-center gap-1.5">
                {d.name}
                {d.verification === "verified" && (
                  <BadgeCheck size={13} className="text-emerald-400 shrink-0"
                    aria-label={`Certificación ${d.cert_number} vigente en el padrón del CPM`} />
                )}
                {d.verification === "expired" && (
                  <BadgeCheck size={13} className="text-amber-400 shrink-0"
                    aria-label={`Certificación ${d.cert_number} vencida`} />
                )}
              </p>
              <p className="text-[10px] text-cyan-300">{d.specialty}</p>
              {d.schedule && <p className="text-xs text-zinc-400 mt-1 flex items-center gap-1"><Clock size={11} /> {d.schedule}</p>}
              {d.phone && <p className="text-xs text-zinc-500 flex items-center gap-1"><Smartphone size={11} /> {d.phone}</p>}
              {/* Si el bot puede confirmar disponibilidad de este profesional
                  o solo tomar el pedido. Es lo que decide si le puede decir
                  "tenés turno" a un paciente. */}
              <button
                onClick={(e) => { e.stopPropagation(); setHorarioDe(d); }}
                title={d.agenda_mode === "estructurado"
                  ? "El bot verifica los turnos contra este horario"
                  : "Sin horario cargado: el bot toma el turno como pedido"}
                className={`mt-2 w-full text-[10px] font-bold px-2 py-1 rounded-lg border flex items-center justify-center gap-1 transition-colors ${
                  d.agenda_mode === "estructurado"
                    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20"
                    : "bg-amber-500/10 text-amber-400 border-amber-500/25 hover:bg-amber-500/20"
                }`}>
                {d.agenda_mode === "estructurado"
                  ? <><ShieldCheck size={11} /> Agenda verificada</>
                  : <><CalendarClock size={11} /> Cargar horario</>}
              </button>
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

      {showAddDoctor && (
        <AddDoctorModal companyId={companyId} onClose={() => setShowAddDoctor(false)} onSaved={load} />
      )}
      {showImport && (
        <DoctorImportModal companyId={companyId} onClose={() => setShowImport(false)} onSaved={load} />
      )}
      {horarioDe && (
        <ScheduleModal companyId={companyId} doctor={horarioDe}
          onClose={() => setHorarioDe(null)} onSaved={load} />
      )}
      {showClinicSchedule && (
        <ClinicScheduleModal companyId={companyId}
          onClose={() => setShowClinicSchedule(false)} onSaved={load} />
      )}
      {showAbsences && (
        <AbsencesModal companyId={companyId} doctors={doctors}
          onClose={() => setShowAbsences(false)} onSaved={load} />
      )}
      {showPreVisit && (
        <PreVisitModal companyId={companyId} doctors={doctors}
          onClose={() => setShowPreVisit(false)} />
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
  // El servidor rechazó el horario contra la agenda del profesional. No es un
  // error de la recepcionista: puede querer cargarlo igual (sobreturno), pero
  // tiene que ser una decisión y no un descuido.
  const [choque, setChoque] = useState<{ motivo: string; horarios_libres: string[] } | null>(null);

  const guardar = async (forzar: boolean) => {
    setError(""); setChoque(null);
    try {
      await api.createAppointment(companyId, form, forzar);
      onSaved();
      onClose();
    } catch (err) {
      if (esErrorApi(err) && err.status === 409 && err.detail?.se_puede_forzar) {
        setChoque({
          motivo: err.detail.motivo,
          horarios_libres: err.detail.horarios_libres ?? [],
        });
        return;
      }
      setError(err instanceof Error ? err.message : "Error");
    }
  };

  const submit = (e: React.FormEvent) => { e.preventDefault(); guardar(false); };

  const usarHorario = (hhmm: string) => {
    const dia = form.scheduled_at.slice(0, 10);
    if (dia) setForm({ ...form, scheduled_at: `${dia}T${hhmm}` });
    setChoque(null);
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

        {choque && (
          <div className="bg-amber-500/[0.07] border border-amber-500/25 rounded-xl p-3 space-y-2">
            <p className="text-xs text-amber-200 flex items-start gap-1.5">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" /> {choque.motivo}
            </p>
            {choque.horarios_libres.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                <span className="text-[11px] text-zinc-400 self-center">Libres ese día:</span>
                {choque.horarios_libres.map((h) => (
                  <button key={h} type="button" onClick={() => usarHorario(h)}
                    className="text-[11px] bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 px-2 py-0.5 rounded-lg">
                    {h}
                  </button>
                ))}
              </div>
            )}
            <button type="button" onClick={() => guardar(true)}
              className="text-[11px] text-zinc-400 hover:text-amber-300 underline underline-offset-2">
              Cargar igual (sobreturno fuera de horario)
            </button>
          </div>
        )}

        <div className="flex justify-end gap-3 pt-3 border-t border-white/5">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
          <button type="submit" className={btnPrimary}>Agendar</button>
        </div>
      </form>
    </Modal>
  );
}
