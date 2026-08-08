import { useCallback, useEffect, useState } from "react";
import {
  Activity, BarChart3, Bot, Building2, Calendar, ChevronDown, Clock,
  Command, LayoutDashboard, Link2, MessageSquare, PenTool, Plus, RefreshCw,
  Send, ShieldCheck, Sliders, Smartphone, Stethoscope, Users, Video, X, Zap,
} from "lucide-react";
import {
  api, chatApi, waApi, type AgentDetail, type AgentSummary, type Appointment,
  type ChatMessage, type Company, type Conversation, type DailySummary,
  type DashboardData, type Doctor, type WaStatus, STATUS_ES,
} from "./api";

const AGENT_ICONS: Record<string, typeof Command> = {
  ceo: Command, quant: BarChart3, guard: ShieldCheck,
  creative: PenTool, visual: Video, cx: MessageSquare,
};

const card = "bg-[#07090e] border border-white/10 rounded-2xl shadow-md";
const input =
  "w-full bg-white/[0.03] border border-white/10 rounded-xl p-2.5 text-sm text-zinc-100 focus:outline-none focus:border-cyan-500 transition-colors";
const btnPrimary =
  "bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white font-semibold rounded-xl text-sm px-5 py-2.5 flex items-center gap-2 shadow-lg transition-all disabled:opacity-50";

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="bg-[#090b10] border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-lg font-bold text-white">{title}</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white p-1"><X size={20} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function NewCompanyModal({ onClose, onCreated }: { onClose: () => void; onCreated: (c: Company) => void }) {
  const [name, setName] = useState("");
  const [vertical, setVertical] = useState<"medical" | "ecommerce">("medical");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      onCreated(await api.createCompany(name, vertical));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Nueva Empresa / Consultorio" onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-2">Nombre</label>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} required
            placeholder="Ej. Centro Médico San Roque" />
        </div>
        <div className="grid grid-cols-2 gap-4">
          {([["medical", "Consultorio / Sanatorio", Stethoscope], ["ecommerce", "E-Commerce / Retail", BarChart3]] as const).map(
            ([v, label, Icon]) => (
              <button key={v} type="button" onClick={() => setVertical(v)}
                className={`p-4 rounded-xl border text-left transition-all ${vertical === v ? "bg-cyan-500/10 border-cyan-500/50 text-white" : "bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/[0.04]"}`}>
                <Icon className="text-cyan-400 mb-2" size={22} />
                <p className="font-bold text-sm">{label}</p>
              </button>
            )
          )}
        </div>
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <div className="flex justify-end gap-3 pt-3 border-t border-white/5">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
          <button type="submit" disabled={saving} className={btnPrimary}>
            {saving ? <><RefreshCw className="animate-spin" size={15} /> Creando…</> : "Crear enjambre y empresa"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DashboardView({ companyId }: { companyId: number }) {
  const [data, setData] = useState<DashboardData | null>(null);
  useEffect(() => {
    api.dashboard(companyId).then(setData).catch(() => setData(null));
  }, [companyId]);
  if (!data) return <p className="text-zinc-500 text-sm">Cargando…</p>;
  const medical = data.company.vertical === "medical";
  const kpis = [
    { label: medical ? "Citas de hoy" : "Campañas activas", value: medical ? String(data.appointments_today) : "—", color: "text-white" },
    { label: medical ? "Doctores" : "ROAS", value: medical ? String(data.doctors) : "—", color: "text-cyan-400" },
    { label: "Conversaciones", value: String(data.conversations), color: "text-emerald-400" },
    { label: "Agentes activos", value: `${data.agents_active}/${data.agents_total}`, color: "text-indigo-400" },
  ];
  return (
    <div className="space-y-6">
      <div>
        <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest bg-cyan-500/10 px-2.5 py-1 rounded-full border border-cyan-500/20">{data.company.niche}</span>
        <h2 className="text-3xl font-bold text-white tracking-tight mt-2">{data.company.name}</h2>
        <p className="text-zinc-400 text-sm mt-1">Panel operativo con datos reales del sistema.</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {kpis.map((k) => (
          <div key={k.label} className={`${card} p-5`}>
            <h4 className="text-zinc-500 text-[10px] font-bold tracking-widest uppercase mb-2">{k.label}</h4>
            <span className={`text-2xl font-bold ${k.color}`}>{k.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentEditModal({ agentId, onClose, onSaved }: { agentId: number; onClose: () => void; onSaved: () => void }) {
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getAgent(agentId).then(setAgent).catch(() => setError("No se pudo cargar el agente"));
  }, [agentId]);

  const save = async () => {
    if (!agent) return;
    setSaving(true);
    setError("");
    try {
      await api.updateAgent(agent.id, {
        system_prompt: agent.system_prompt,
        temperature: agent.temperature,
        model: agent.model,
        active: agent.active,
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={agent ? `Configurar: ${agent.name}` : "Cargando…"} onClose={onClose}>
      {agent && (
        <div className="space-y-4">
          <div>
            <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-2">System prompt</label>
            <textarea className={`${input} min-h-36 font-mono text-xs`} value={agent.system_prompt}
              onChange={(e) => setAgent({ ...agent, system_prompt: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-2">
                Temperatura: {agent.temperature.toFixed(2)}
              </label>
              <input type="range" min={0} max={1} step={0.05} value={agent.temperature}
                onChange={(e) => setAgent({ ...agent, temperature: Number(e.target.value) })}
                className="w-full accent-cyan-500" />
            </div>
            <div>
              <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-2">Modelo</label>
              <input className={input} value={agent.model} onChange={(e) => setAgent({ ...agent, model: e.target.value })} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
            <input type="checkbox" checked={agent.active} className="accent-cyan-500"
              onChange={(e) => setAgent({ ...agent, active: e.target.checked })} />
            Agente activo
          </label>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex justify-end gap-3 pt-3 border-t border-white/5">
            <button onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
            <button onClick={save} disabled={saving} className={btnPrimary}>
              {saving ? "Guardando…" : "Guardar cambios"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function AgentsView({ companyId }: { companyId: number }) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const load = useCallback(() => {
    api.listAgents(companyId).then(setAgents).catch(() => setAgents([]));
  }, [companyId]);
  useEffect(load, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight">Enjambre de 6 Agentes IA</h2>
        <p className="text-zinc-400 text-sm mt-1">Super-Configurator: prompts, temperatura y modelo por agente. Los prompts viven en el servidor.</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((a) => {
          const Icon = AGENT_ICONS[a.slug] ?? Activity;
          return (
            <div key={a.id} className={`${card} p-5 space-y-4 hover:border-cyan-500/40 transition-all`}>
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20"><Icon size={20} /></div>
                <div>
                  <h3 className="font-bold text-white text-sm">{a.name}</h3>
                  <p className="text-[10px] text-zinc-500 uppercase">{a.role}</p>
                </div>
              </div>
              <div className="flex justify-between items-center text-[10px] font-mono text-zinc-400">
                <span className="truncate max-w-[60%]" title={a.model}>{a.model}</span>
                <span>T={a.temperature.toFixed(2)}</span>
                <span className={a.active ? "text-emerald-400 font-bold" : "text-zinc-600 font-bold"}>
                  {a.active ? "ACTIVO" : "PAUSADO"}
                </span>
              </div>
              <button onClick={() => setEditing(a.id)}
                className="w-full py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-200 rounded-xl text-xs font-semibold flex items-center justify-center gap-2">
                <Sliders size={14} /> Configurar
              </button>
            </div>
          );
        })}
      </div>
      {editing !== null && <AgentEditModal agentId={editing} onClose={() => setEditing(null)} onSaved={load} />}
    </div>
  );
}

function MedicalAgendaView({ companyId }: { companyId: number }) {
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

function AddDoctorModal({ companyId, onClose, onSaved }: { companyId: number; onClose: () => void; onSaved: () => void }) {
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

function AddAppointmentModal({ companyId, doctors, onClose, onSaved }: {
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

function ConnectionsView({ company, onCompanyUpdated }: { company: Company; onCompanyUpdated: (c: Company) => void }) {
  const [status, setStatus] = useState<WaStatus | null>(null);
  const [pnid, setPnid] = useState(company.wa_phone_number_id);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    waApi.status(company.id).then((s) => { setStatus(s); setError(""); }).catch((e) => setError(e.message));
  }, [company.id]);

  useEffect(() => {
    refresh();
    if (company.wa_mode !== "qr") return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [company.wa_mode, refresh]);

  const setMode = async (mode: "none" | "meta" | "qr") => {
    setBusy(true);
    setError("");
    try {
      onCompanyUpdated(await waApi.updateCompany(company.id, { wa_mode: mode }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  };

  const modes = [
    { id: "none" as const, title: "Sin canal", desc: "Solo simulador interno." },
    { id: "qr" as const, title: "QR — WhatsApp Web (Baileys)", desc: "Escaneás un QR con el WhatsApp Business existente. Sin verificación de Meta. Solo responde a clientes que escriben." },
    { id: "meta" as const, title: "Meta Cloud API (oficial)", desc: "Para empresas con verificación de Meta. Requiere token en el servidor y phone_number_id." },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
          <Link2 className="text-cyan-400" size={26} /> Centro de Conexiones — WhatsApp
        </h2>
        <p className="text-zinc-400 text-sm mt-1">Elegí cómo se conecta esta empresa a WhatsApp. El bot es el mismo en ambos canales.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {modes.map((m) => (
          <button key={m.id} disabled={busy} onClick={() => setMode(m.id)}
            className={`p-5 rounded-2xl border text-left transition-all ${company.wa_mode === m.id ? "bg-cyan-500/10 border-cyan-500/50 text-white" : "bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/[0.04]"}`}>
            <p className="font-bold text-sm">{m.title}</p>
            <p className="text-[11px] text-zinc-500 mt-2">{m.desc}</p>
          </button>
        ))}
      </div>

      {company.wa_mode === "qr" && (
        <div className={`${card} p-6 space-y-4`}>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest">Sesión QR</h3>
            <span className={`text-[10px] px-2.5 py-1 rounded-full border font-bold uppercase ${status?.status === "connected" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "bg-amber-500/10 text-amber-400 border-amber-500/20"}`}>
              {status?.status === "connected" ? `Conectado${status.phone ? ` (+${status.phone})` : ""}` : status?.status ?? "…"}
            </span>
          </div>
          <p className="text-xs text-amber-300/90 bg-amber-500/5 border border-amber-500/20 rounded-xl p-3">
            ⚠️ Canal no oficial: WhatsApp puede restringir números que automatizan respuestas.
            Este modo solo responde a quien escribe primero (menor riesgo), pero para clínicas
            con datos sensibles recomendamos la API oficial de Meta.
          </p>
          {status?.status === "qr" && status.qr && (
            <div className="flex flex-col items-center gap-3">
              <img src={status.qr} alt="QR de WhatsApp" className="rounded-xl border border-white/10 bg-white p-2 w-64" />
              <p className="text-xs text-zinc-400">WhatsApp → Dispositivos vinculados → Vincular dispositivo</p>
            </div>
          )}
          <div className="flex gap-3">
            {status?.status !== "connected" && (
              <button onClick={() => waApi.start(company.id).then(setStatus).catch((e) => setError(e.message))} className={btnPrimary}>
                Conectar / Generar QR
              </button>
            )}
            {(status?.status === "connected" || status?.status === "qr") && (
              <button onClick={() => waApi.logout(company.id).then(setStatus).catch((e) => setError(e.message))}
                className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-300 rounded-xl text-sm font-semibold">
                Cerrar sesión
              </button>
            )}
          </div>
        </div>
      )}

      {company.wa_mode === "meta" && (
        <div className={`${card} p-6 space-y-4 max-w-xl`}>
          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest">Meta Cloud API</h3>
          <p className="text-xs text-zinc-400">
            El token, verify token y app secret van en el <code className="text-cyan-300">.env</code> del servidor.
            Acá solo se asigna el <b>phone_number_id</b> de esta empresa.
          </p>
          <div className="flex gap-2">
            <input className={input} placeholder="phone_number_id" value={pnid} onChange={(e) => setPnid(e.target.value)} />
            <button className={btnPrimary} disabled={busy}
              onClick={() => waApi.updateCompany(company.id, { wa_phone_number_id: pnid }).then(onCompanyUpdated).catch((e) => setError(e.message))}>
              Guardar
            </button>
          </div>
          <p className="text-xs text-zinc-500">Webhook a configurar en Meta: <code className="text-cyan-300">https://TU-DOMINIO/api/webhooks/whatsapp</code></p>
        </div>
      )}

      {error && <p className="text-red-400 text-xs">{error}</p>}
    </div>
  );
}

function ChatView({ companyId }: { companyId: number }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newName, setNewName] = useState("");

  const loadConversations = useCallback(() => {
    chatApi.listConversations(companyId).then(setConversations).catch(() => setConversations([]));
  }, [companyId]);
  useEffect(loadConversations, [loadConversations]);

  const loadMessages = useCallback((conv: Conversation) => {
    chatApi.listMessages(companyId, conv.id).then(setMessages).catch(() => setMessages([]));
  }, [companyId]);

  useEffect(() => {
    if (selected) loadMessages(selected);
    else setMessages([]);
  }, [selected, loadMessages]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const phone = selected?.contact_phone ?? newPhone.trim();
    if (!phone || !draft.trim() || sending) return;
    const text = draft.trim();
    setDraft("");
    setSending(true);
    setError("");
    setMessages((prev) => [
      ...prev,
      { id: -1, direction: "in", body: text, created_at: new Date().toISOString() },
    ]);
    try {
      const resp = await chatApi.send(companyId, phone, selected?.contact_name ?? newName, text);
      if (resp.error) setError(resp.error);
      loadConversations();
      const conv = selected ?? {
        id: resp.conversation_id, channel: "whatsapp", contact_phone: phone,
        contact_name: newName, status: resp.status,
      };
      if (!selected) setSelected(conv);
      chatApi.listMessages(companyId, resp.conversation_id).then(setMessages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
          <MessageSquare className="text-cyan-400" size={26} /> CX Bot — Simulador de WhatsApp
        </h2>
        <p className="text-zinc-400 text-sm mt-1">
          Probá el bot con IA real. Puede consultar la agenda, agendar citas de verdad y escalar a humano.
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={`${card} p-4 space-y-3`}>
          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest">Conversaciones</h3>
          <div className="space-y-2 border-b border-white/5 pb-3">
            <input className={input} placeholder="Teléfono (ej. +595 981 000000)" value={newPhone}
              onChange={(e) => setNewPhone(e.target.value)} />
            <input className={input} placeholder="Nombre del contacto" value={newName}
              onChange={(e) => setNewName(e.target.value)} />
            <button onClick={() => setSelected(null)}
              className="w-full py-2 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 rounded-xl text-xs font-bold">
              + Nueva conversación con estos datos
            </button>
          </div>
          {conversations.map((c) => (
            <div key={c.id} onClick={() => setSelected(c)}
              className={`p-3 rounded-xl border cursor-pointer ${selected?.id === c.id ? "bg-cyan-500/10 border-cyan-500/50" : "bg-white/[0.02] border-white/5 hover:bg-white/[0.04]"}`}>
              <div className="flex justify-between items-center">
                <p className="font-bold text-sm text-zinc-100">{c.contact_name || c.contact_phone}</p>
                {c.status === "needs_human" && (
                  <span className="text-[9px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold uppercase">Humano</span>
                )}
              </div>
              <p className="text-[10px] text-zinc-500">{c.contact_phone}</p>
            </div>
          ))}
        </div>

        <div className={`lg:col-span-2 ${card} flex flex-col h-[560px]`}>
          <div className="flex-1 overflow-y-auto p-4 space-y-2">
            {messages.map((m, i) => (
              <div key={`${m.id}-${i}`} className={`flex ${m.direction === "in" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[75%] px-3.5 py-2 rounded-2xl text-sm whitespace-pre-wrap ${m.direction === "in" ? "bg-cyan-600/30 text-cyan-50 rounded-br-sm" : "bg-white/[0.06] text-zinc-200 rounded-bl-sm"}`}>
                  {m.body}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-white/[0.06] text-zinc-500 px-3.5 py-2 rounded-2xl text-sm italic">escribiendo…</div>
              </div>
            )}
            {!messages.length && !sending && (
              <p className="text-center text-zinc-600 text-xs pt-24">
                {selected ? "Sin mensajes." : "Cargá teléfono y nombre a la izquierda y escribí el primer mensaje como si fueras el cliente."}
              </p>
            )}
          </div>
          {error && <p className="text-red-400 text-xs px-4 pb-1">{error}</p>}
          <form onSubmit={send} className="p-3 border-t border-white/5 flex gap-2">
            <input className={input} placeholder="Escribí como el cliente…" value={draft}
              onChange={(e) => setDraft(e.target.value)} />
            <button type="submit" disabled={sending || !draft.trim()} className={btnPrimary}>
              <Send size={15} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [view, setView] = useState<"dashboard" | "agents" | "medical" | "chat" | "connections">("dashboard");
  const [showNewCompany, setShowNewCompany] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    api.listCompanies()
      .then((list) => {
        setCompanies(list);
        if (list.length && activeId === null) setActiveId(list[0].id);
      })
      .catch(() => setLoadError("No se pudo conectar con el backend (¿está corriendo uvicorn?)"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const active = companies.find((c) => c.id === activeId) ?? null;

  const navBtn = (id: typeof view, label: string, Icon: typeof LayoutDashboard) => (
    <button onClick={() => setView(id)}
      className={`w-full flex items-center px-3 py-2.5 rounded-xl text-xs font-semibold transition-all ${view === id ? "text-white bg-white/5 border border-white/10" : "text-zinc-400 hover:bg-white/[0.02] hover:text-zinc-200"}`}>
      <Icon size={16} className={`mr-3 ${view === id ? "text-cyan-400" : "text-zinc-500"}`} /> {label}
    </button>
  );

  return (
    <div className="min-h-screen bg-[#040609] font-sans text-zinc-300 flex">
      <aside className="w-72 bg-[#06080d] border-r border-white/5 flex-col z-20 hidden md:flex shrink-0">
        <div className="p-6 border-b border-white/5">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-500 flex items-center justify-center">
              <Zap size={18} className="text-white fill-current" />
            </div>
            <div>
              <span className="font-extrabold text-base tracking-tight text-white">MetaBot<span className="text-cyan-400">.OS</span></span>
              <p className="text-[9px] text-zinc-500 uppercase tracking-widest font-mono">Py • Enterprise & Medical</p>
            </div>
          </div>
          <div className="space-y-2">
            <div className="relative">
              <select value={activeId ?? ""} onChange={(e) => setActiveId(Number(e.target.value))}
                className="w-full bg-white/[0.03] border border-white/10 rounded-xl py-2.5 px-3 text-xs text-zinc-200 font-semibold focus:outline-none focus:border-cyan-500 appearance-none cursor-pointer">
                {companies.map((c) => (
                  <option key={c.id} value={c.id} className="bg-[#06080d]">
                    {c.name} ({c.vertical === "medical" ? "Médico" : "E-Comm"})
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-3.5 text-zinc-500 pointer-events-none" />
            </div>
            <button onClick={() => setShowNewCompany(true)}
              className="w-full py-2 bg-gradient-to-r from-cyan-500/10 to-indigo-500/10 border border-cyan-500/30 hover:border-cyan-500 text-cyan-300 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5">
              <Plus size={14} /> Agregar empresa
            </button>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          <div className="text-[9px] font-bold text-zinc-500 uppercase tracking-widest px-3 py-2">Módulos</div>
          {navBtn("dashboard", "Dashboard", LayoutDashboard)}
          {active?.vertical === "medical" && navBtn("medical", "Agenda de Doctores", Calendar)}
          {navBtn("chat", "CX Bot (Simulador)", MessageSquare)}
          {navBtn("connections", "Conexiones (WhatsApp)", Link2)}
          {navBtn("agents", "Enjambre de Agentes", Bot)}
        </nav>
      </aside>

      <main className="flex-1 h-screen overflow-y-auto">
        <div className="p-8 md:p-12 max-w-6xl mx-auto w-full pb-24">
          {loadError && (
            <div className="mb-6 bg-red-500/10 border border-red-500/30 text-red-300 text-sm rounded-xl p-4 flex items-center gap-2">
              <Building2 size={16} /> {loadError}
            </div>
          )}
          {!active && !loadError && (
            <div className="text-center py-24 space-y-4">
              <Building2 size={48} className="mx-auto text-zinc-600" />
              <h2 className="text-xl font-bold text-white">Sin empresas todavía</h2>
              <button onClick={() => setShowNewCompany(true)} className={`${btnPrimary} mx-auto`}>
                <Plus size={15} /> Crear la primera empresa
              </button>
            </div>
          )}
          {active && view === "dashboard" && <DashboardView companyId={active.id} />}
          {active && view === "agents" && <AgentsView companyId={active.id} />}
          {active && view === "medical" && active.vertical === "medical" && <MedicalAgendaView companyId={active.id} />}
          {active && view === "chat" && <ChatView companyId={active.id} />}
          {active && view === "connections" && (
            <ConnectionsView
              company={active}
              onCompanyUpdated={(c) => setCompanies((prev) => prev.map((x) => (x.id === c.id ? c : x)))}
            />
          )}
        </div>
      </main>

      {showNewCompany && (
        <NewCompanyModal
          onClose={() => setShowNewCompany(false)}
          onCreated={(c) => {
            setCompanies((prev) => [...prev, c]);
            setActiveId(c.id);
            setView("dashboard");
          }}
        />
      )}
    </div>
  );
}
