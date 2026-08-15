import React from "react";
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, BadgeCheck, Building2, Calendar, CalendarClock, CalendarOff,
  ClipboardList, Clock, KeyRound, Plus, ShieldCheck, Smartphone, Upload, Users,
} from "lucide-react";
import {
  STATUS_ES, api, clinicalApi, esErrorApi, type Appointment, type Doctor, type Insurer,
} from "../api";
import { card, input, btnPrimary, Modal } from "../ui";
import { DoctorImportModal } from "./DoctorImportModal";
import { ClinicScheduleModal, ScheduleModal } from "./ScheduleEditor";
import { AbsencesModal } from "./AbsencesModal";
import { PreVisitModal } from "./PreVisitModal";
import { AccessModal } from "./AccessModal";

export function MedicalAgendaView(
  { companyId, modules = [] }: { companyId: number; modules?: string[] },
) {
  // El resumen pre-visita es del bloque 4 (Portal del Profesional), que se
  // vende aparte. Sin él, el backend contesta 402: mostrar el botón sería
  // prometer algo que no va a pasar.
  const tienePrevisita = modules.includes("previsita");
  // El alta de logins es del mismo bloque 4, pero la hace la clínica.
  const tienePortal = modules.includes("portal");
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
  const [showAccesos, setShowAccesos] = useState(false);
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
          <h2 className="text-3xl font-bold text-zinc-900 tracking-tight flex items-center gap-3">
            <Calendar className="text-violet-600" size={26} /> Agenda de Doctores & Citas
          </h2>
          <p className="text-zinc-600 text-sm mt-1">Citas reales desde la base de datos, resumen diario por doctor.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setShowClinicSchedule(true)}
            className="text-sm bg-zinc-50 hover:bg-zinc-100 text-zinc-700 border border-zinc-200 px-4 py-2.5 rounded-xl flex items-center gap-2">
            <Building2 size={15} /> Horario del centro
          </button>
          <button onClick={() => setShowAbsences(true)} disabled={!doctors.length}
            className="text-sm bg-zinc-50 hover:bg-zinc-100 text-zinc-700 border border-zinc-200 px-4 py-2.5 rounded-xl flex items-center gap-2 disabled:opacity-40">
            <CalendarOff size={15} /> Licencias
          </button>
          {tienePortal && (
            <button onClick={() => setShowAccesos(true)} disabled={!doctors.length}
              className="text-sm bg-zinc-50 hover:bg-zinc-100 text-zinc-700 border border-zinc-200 px-4 py-2.5 rounded-xl flex items-center gap-2 disabled:opacity-40">
              <KeyRound size={15} /> Accesos al portal
            </button>
          )}
          {tienePrevisita && (
            <button onClick={() => setShowPreVisit(true)} disabled={!doctors.length}
              className={btnPrimary}>
              <ClipboardList size={15} /> Resumen para el profesional
            </button>
          )}
        </div>
      </div>

      {/* Lo que hace que el bot pueda rechazar un turno imposible. Se avisa
          arriba de todo porque mientras falte, cada turno que toma es un
          pedido sin confirmar. */}
      {clinicaTieneHorario === false && (
        <button onClick={() => setShowClinicSchedule(true)}
          className="w-full text-left bg-amber-500/[0.07] hover:bg-amber-500/[0.11] border border-amber-500/25 rounded-2xl p-4 flex items-start gap-3 transition-colors">
          <AlertTriangle size={18} className="text-amber-700 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-amber-800">Cargá el horario del centro</p>
            <p className="text-xs text-zinc-600 mt-0.5 leading-relaxed">
              Son cinco filas y cubren a todos los profesionales. Sin esto el bot acepta un
              turno un domingo a las 23:00, y después le manda al paciente el recordatorio de
              una cita que no existe.
            </p>
          </div>
        </button>
      )}
      {clinicaTieneHorario !== false && sinHorario.length > 0 && doctors.length > 0 && (
        <div className="bg-zinc-50 border border-zinc-200 rounded-2xl p-3 flex items-center gap-3">
          <CalendarClock size={16} className="text-zinc-500 shrink-0" />
          <p className="text-xs text-zinc-600 flex-1">
            {sinHorario.length} de {doctors.length} profesionales todavía sin horario propio:
            sus turnos se toman como <strong className="text-zinc-700">pedido</strong> y el bot
            avisa que recepción confirma.
          </p>
          <button onClick={() => setHorarioDe(sinHorario[0])}
            className="text-xs text-violet-600 hover:text-violet-700 whitespace-nowrap">
            Cargar el de {sinHorario[0].name.split(",")[0].split(" ").slice(0, 2).join(" ")} →
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={`${card} p-5 space-y-3`}>
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest flex items-center gap-2">
              <Users size={15} className="text-indigo-700" /> Doctores ({doctors.length})
            </h3>
            <div className="flex items-center gap-1">
              <button onClick={() => setShowImport(true)} title="Buscar en el padrón o subir tu planilla"
                className="text-violet-600 hover:text-violet-700 p-1"><Upload size={15} /></button>
              <button onClick={() => setShowAddDoctor(true)} title="Cargar uno a mano"
                className="text-violet-600 hover:text-violet-700 p-1"><Plus size={16} /></button>
            </div>
          </div>
          {!doctors.length && (
            <button onClick={() => setShowImport(true)}
              className="w-full border-2 border-dashed border-zinc-200 hover:border-violet-400 rounded-xl p-5 text-center transition-colors">
              <Upload size={20} className="mx-auto text-zinc-500 mb-2" />
              <span className="text-xs text-zinc-600 block">Cargá tus profesionales</span>
              <span className="text-[10px] text-zinc-500">desde el padrón del CPM o tu propia planilla</span>
            </button>
          )}
          <div onClick={() => setSelectedDoctor("all")}
            className={`p-3 rounded-xl border cursor-pointer text-sm font-bold ${selectedDoctor === "all" ? "bg-violet-50 border-cyan-500/50 text-zinc-900" : "bg-zinc-50 border-zinc-200 text-zinc-600"}`}>
            Todos los consultorios
          </div>
          {doctors.map((d) => (
            <div key={d.id} onClick={() => setSelectedDoctor(d.id)}
              className={`p-3 rounded-xl border cursor-pointer ${selectedDoctor === d.id ? "bg-violet-50 border-cyan-500/50 text-zinc-900" : "bg-zinc-50 border-zinc-200 text-zinc-600"}`}>
              <p className="font-bold text-sm text-zinc-900 flex items-center gap-1.5">
                {d.name}
                {d.verification === "verified" && (
                  <BadgeCheck size={13} className="text-emerald-700 shrink-0"
                    aria-label={`Certificación ${d.cert_number} vigente en el padrón del CPM`} />
                )}
                {d.verification === "expired" && (
                  <BadgeCheck size={13} className="text-amber-700 shrink-0"
                    aria-label={`Certificación ${d.cert_number} vencida`} />
                )}
              </p>
              <p className="text-[10px] text-violet-600">{d.specialty}</p>
              {d.schedule && <p className="text-xs text-zinc-600 mt-1 flex items-center gap-1"><Clock size={11} /> {d.schedule}</p>}
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
                    ? "bg-emerald-50 text-emerald-700 border-emerald-500/20 hover:bg-emerald-100"
                    : "bg-amber-50 text-amber-700 border-amber-500/25 hover:bg-amber-100"
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
            <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest flex items-center gap-2">
              <Clock size={15} className="text-violet-600" /> Turnos programados
            </h3>
            <button onClick={() => setShowAddAppt(true)} disabled={!doctors.length}
              className="text-xs bg-violet-50 hover:bg-violet-100 text-violet-600 border border-violet-300 px-3 py-1.5 rounded-lg flex items-center gap-1 disabled:opacity-40">
              <Plus size={13} /> Nueva cita
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-zinc-700">
              <thead className="text-[10px] uppercase text-zinc-500 border-b border-zinc-200">
                <tr><th className="pb-3">Fecha / Hora</th><th className="pb-3">Paciente</th><th className="pb-3">Doctor</th><th className="pb-3">Estado</th></tr>
              </thead>
              <tbody className="divide-y divide-zinc-200">
                {visible.map((a) => (
                  <tr key={a.id} className="hover:bg-zinc-100">
                    <td className="py-3 font-mono text-violet-600 text-xs">
                      {new Date(a.scheduled_at).toLocaleString("es-PY", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="py-3 text-zinc-900">
                      {a.patient_name}
                      <span className="block text-[10px] text-zinc-500">{a.patient_phone}</span>
                    </td>
                    <td className="py-3 text-xs">{doctors.find((d) => d.id === a.doctor_id)?.name ?? "—"}</td>
                    <td className="py-3">
                      <button onClick={() => cycleStatus(a)} title="Click para cambiar estado"
                        className={`text-[10px] px-2.5 py-1 rounded-full border font-bold uppercase ${a.status === "confirmed" || a.status === "attended" ? "bg-emerald-50 text-emerald-700 border-emerald-500/20" : a.status === "cancelled" || a.status === "no_show" ? "bg-red-500/10 text-red-600 border-red-500/20" : "bg-amber-50 text-amber-700 border-amber-500/20"}`}>
                        {STATUS_ES[a.status] ?? a.status}
                      </button>
                    </td>
                  </tr>
                ))}
                {!visible.length && (
                  <tr><td colSpan={4} className="py-8 text-center text-zinc-500 text-xs">Sin citas registradas.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {showAddDoctor && (
        <AddDoctorModal companyId={companyId} modules={modules} onClose={() => setShowAddDoctor(false)} onSaved={load} />
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
      {showAccesos && tienePortal && (
        <AccessModal companyId={companyId} doctors={doctors}
          onClose={() => setShowAccesos(false)} />
      )}
      {showPreVisit && tienePrevisita && (
        <PreVisitModal companyId={companyId} doctors={doctors}
          onClose={() => setShowPreVisit(false)} />
      )}
      {showAddAppt && (
        <AddAppointmentModal companyId={companyId} doctors={doctors} onClose={() => setShowAddAppt(false)} onSaved={load} />
      )}
    </div>
  );
}

export function AddDoctorModal({ companyId, modules = [], onClose, onSaved }: {
  companyId: number; modules?: string[]; onClose: () => void; onSaved: () => void;
}) {
  const [form, setForm] = useState({ name: "", specialty: "", schedule: "", phone: "", email: "" });
  // Qué parte de lo facturado le queda al profesional. Solo aparece si la
  // clínica compró el bloque que liquida honorarios: sin él, el número no
  // afecta nada y preguntarlo es ruido.
  const [honorarioPct, setHonorarioPct] = useState(100);
  const liquidaHonorarios = modules.includes("portal");
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createDoctor(companyId, { ...form, honorario_pct: honorarioPct });
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
            <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">{label}</label>
            <input className={input} required={k === "name"} value={form[k]}
              onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
          </div>
        ))}
        {liquidaHonorarios && (
          <div>
            <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">
              Honorario del profesional (%)
            </label>
            <input className={input} type="number" min={0} max={100} value={honorarioPct}
              onChange={(e) => setHonorarioPct(Number(e.target.value))} />
            <p className="text-[10px] text-zinc-500 mt-1">
              Qué parte de lo facturado le queda a él. 100 = cobra todo (consultorio propio);
              en un sanatorio suele ser menos porque la institución retiene una parte.
            </p>
          </div>
        )}
        {error && <p className="text-red-600 text-xs">{error}</p>}
        <div className="flex justify-end gap-3 pt-3 border-t border-zinc-200">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-900">Cancelar</button>
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
    doctor_id: doctors[0]?.id ?? 0, patient_name: "", patient_phone: "", scheduled_at: "",
    insurer_id: null as number | null, notes: "",
  });
  // Los convenios de ESTA empresa. Si la clínica no compró el bloque de
  // salud la llamada da 402 y el campo simplemente no aparece.
  const [convenios, setConvenios] = useState<Insurer[]>([]);
  useEffect(() => {
    clinicalApi.listInsurers(companyId).then(setConvenios).catch(() => setConvenios([]));
  }, [companyId]);
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
          <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">Doctor</label>
          <select className={input} value={form.doctor_id} onChange={(e) => setForm({ ...form, doctor_id: Number(e.target.value) })}>
            {doctors.map((d) => <option key={d.id} value={d.id} className="bg-white">{d.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">Paciente *</label>
          <input className={input} required value={form.patient_name} onChange={(e) => setForm({ ...form, patient_name: e.target.value })} />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">Teléfono</label>
          <input className={input} value={form.patient_phone} onChange={(e) => setForm({ ...form, patient_phone: e.target.value })} />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">Fecha y hora *</label>
          <input type="datetime-local" className={input} required value={form.scheduled_at}
            onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })} />
        </div>
        {convenios.length > 0 && (
          <div>
            <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">
              Viene por
            </label>
            <select className={input} value={form.insurer_id ?? ""}
              onChange={(e) => setForm({
                ...form,
                insurer_id: e.target.value ? Number(e.target.value) : null,
              })}>
              <option value="" className="bg-white">Particular</option>
              {convenios.map((c) => (
                <option key={c.id} value={c.id} className="bg-white">
                  {c.name} {c.plan}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-zinc-500 mt-1">
              Define en qué planilla de honorarios cae esta atención.
            </p>
          </div>
        )}
        <div>
          <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-1">Motivo</label>
          <input className={input} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        {error && <p className="text-red-600 text-xs">{error}</p>}

        {choque && (
          <div className="bg-amber-500/[0.07] border border-amber-500/25 rounded-xl p-3 space-y-2">
            <p className="text-xs text-amber-800 flex items-start gap-1.5">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" /> {choque.motivo}
            </p>
            {choque.horarios_libres.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                <span className="text-[11px] text-zinc-600 self-center">Libres ese día:</span>
                {choque.horarios_libres.map((h) => (
                  <button key={h} type="button" onClick={() => usarHorario(h)}
                    className="text-[11px] bg-violet-50 hover:bg-violet-100 text-violet-600 border border-violet-300 px-2 py-0.5 rounded-lg">
                    {h}
                  </button>
                ))}
              </div>
            )}
            <button type="button" onClick={() => guardar(true)}
              className="text-[11px] text-zinc-600 hover:text-amber-700 underline underline-offset-2">
              Cargar igual (sobreturno fuera de horario)
            </button>
          </div>
        )}

        <div className="flex justify-end gap-3 pt-3 border-t border-zinc-200">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-900">Cancelar</button>
          <button type="submit" className={btnPrimary}>Agendar</button>
        </div>
      </form>
    </Modal>
  );
}
