import React from "react";
import { useCallback, useEffect, useState } from "react";
import { Coins, Pill, ShieldCheck, Plus, X, AlertTriangle } from "lucide-react";
import {
  clinicalApi, api,
  type Company, type Doctor, type Insurer, type Prescription, type PrescriptionItemIn,
} from "../api";
import { card, input, btnPrimary } from "../ui";
import { ArancelesModal } from "./ArancelesModal";

const ITEM_VACIO: PrescriptionItemIn = {
  medication: "", dose: "", route: "vía oral", frequency: "",
  every_hours: 0, duration_days: 0, instructions: "",
};

export function ClinicalView({ company }: { company: Company }) {
  const [insurers, setInsurers] = useState<Insurer[]>([]);
  const [prescriptions, setPrescriptions] = useState<Prescription[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  const load = useCallback(() => {
    clinicalApi.listInsurers(company.id).then(setInsurers).catch(() => setInsurers([]));
    clinicalApi.listPrescriptions(company.id).then(setPrescriptions).catch(() => setPrescriptions([]));
    api.listDoctors(company.id).then(setDoctors).catch(() => setDoctors([]));
  }, [company.id]);
  useEffect(load, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight">Recetas y Convenios</h2>
        <p className="text-zinc-400 text-sm mt-1">
          Lo que el profesional carga acá es lo que el bot le entrega al paciente,
          palabra por palabra. El bot nunca redacta ni interpreta una indicación médica.
        </p>
      </div>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {aviso && <p className="text-amber-300 text-sm">{aviso}</p>}

      <NuevaReceta
        company={company} doctors={doctors}
        onCreated={(msg) => { setAviso(msg); load(); }}
        onError={setError}
      />
      <ListaRecetas
        company={company} prescriptions={prescriptions}
        onChanged={load} onError={setError}
      />
      <Convenios
        company={company} insurers={insurers}
        onChanged={load} onError={setError}
      />
    </div>
  );
}

function NuevaReceta({ company, doctors, onCreated, onError }: {
  company: Company; doctors: Doctor[];
  onCreated: (msg: string) => void; onError: (e: string) => void;
}) {
  const [abierto, setAbierto] = useState(false);
  const [form, setForm] = useState({
    doctor_id: 0, patient_name: "", patient_phone: "",
    diagnosis: "", indications: "", reminders_enabled: false, consent_by: "",
  });
  const [items, setItems] = useState<PrescriptionItemIn[]>([{ ...ITEM_VACIO }]);
  const [guardando, setGuardando] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setGuardando(true);
    onError("");
    try {
      const r = await clinicalApi.createPrescription(company.id, { ...form, items });
      // El backend dice SIEMPRE si quedaron programados los recordatorios y,
      // cuando no, por qué. Que la clínica crea que el paciente va a recibir
      // avisos que nunca van a salir es peor que no ofrecer la función.
      const rec = r.recordatorios;
      onCreated(
        rec.programadas > 0
          ? `Receta guardada. Se programaron ${rec.programadas} recordatorios de toma.`
          : `Receta guardada, SIN recordatorios: ${rec.motivo}`
      );
      setForm({ doctor_id: 0, patient_name: "", patient_phone: "", diagnosis: "",
                indications: "", reminders_enabled: false, consent_by: "" });
      setItems([{ ...ITEM_VACIO }]);
      setAbierto(false);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Error");
    } finally {
      setGuardando(false);
    }
  };

  const setItem = (i: number, campo: keyof PrescriptionItemIn, valor: string | number) =>
    setItems(items.map((it, n) => (n === i ? { ...it, [campo]: valor } : it)));

  if (!abierto) {
    return (
      <button onClick={() => setAbierto(true)} className={btnPrimary}>
        <Plus size={16} /> Cargar receta
      </button>
    );
  }

  return (
    <form onSubmit={submit} className={`${card} p-6 space-y-4`}>
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-white flex items-center gap-2"><Pill size={18} /> Nueva receta</h3>
        <button type="button" onClick={() => setAbierto(false)} className="text-zinc-500 hover:text-white">
          <X size={18} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <select className={input} required value={form.doctor_id}
          onChange={(e) => setForm({ ...form, doctor_id: Number(e.target.value) })}>
          <option value={0}>Profesional…</option>
          {doctors.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}{d.specialty ? ` — ${d.specialty}` : ""}
            </option>
          ))}
        </select>
        <input className={input} required placeholder="Nombre del paciente" value={form.patient_name}
          onChange={(e) => setForm({ ...form, patient_name: e.target.value })} />
        <input className={input} required placeholder="WhatsApp del paciente (+595…)"
          value={form.patient_phone}
          onChange={(e) => setForm({ ...form, patient_phone: e.target.value })} />
      </div>

      <input className={input} placeholder="Diagnóstico (opcional)" value={form.diagnosis}
        onChange={(e) => setForm({ ...form, diagnosis: e.target.value })} />

      <div className="space-y-3">
        {items.map((it, i) => (
          <div key={i} className="bg-white/[0.02] border border-white/10 rounded-xl p-3 space-y-2">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <input className={input} required placeholder="Medicamento (ej. Amoxicilina 500 mg)"
                value={it.medication} onChange={(e) => setItem(i, "medication", e.target.value)} />
              <input className={input} required placeholder="Dosis (ej. 1 comprimido)"
                value={it.dose} onChange={(e) => setItem(i, "dose", e.target.value)} />
              <input className={input} placeholder="Vía (ej. vía oral)"
                value={it.route} onChange={(e) => setItem(i, "route", e.target.value)} />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] text-zinc-500 block mb-1">Cada cuántas horas (0 = a demanda)</label>
                <input className={input} type="number" min={0} max={24} value={it.every_hours}
                  onChange={(e) => setItem(i, "every_hours", Number(e.target.value))} />
              </div>
              <div>
                <label className="text-[10px] text-zinc-500 block mb-1">Por cuántos días</label>
                <input className={input} type="number" min={0} max={365} value={it.duration_days}
                  onChange={(e) => setItem(i, "duration_days", Number(e.target.value))} />
              </div>
              <input className={`${input} self-end`} placeholder="Pauta en palabras (ej. si tenés dolor)"
                value={it.frequency} onChange={(e) => setItem(i, "frequency", e.target.value)} />
            </div>
            <input className={input} placeholder="Instrucciones (ej. tomar con las comidas)"
              value={it.instructions} onChange={(e) => setItem(i, "instructions", e.target.value)} />
            {it.every_hours === 0 && (
              <p className="text-[11px] text-amber-300/80">
                Sin horario fijo: no se programan recordatorios de toma. Una pauta a demanda
                no se convierte en horario, sería inventar una indicación que no diste.
              </p>
            )}
            {items.length > 1 && (
              <button type="button" onClick={() => setItems(items.filter((_, n) => n !== i))}
                className="text-xs text-zinc-500 hover:text-red-400">Quitar medicamento</button>
            )}
          </div>
        ))}
        <button type="button" onClick={() => setItems([...items, { ...ITEM_VACIO }])}
          className="text-xs text-cyan-400 hover:text-cyan-300">+ Agregar otro medicamento</button>
      </div>

      <input className={input} placeholder="Indicaciones generales (reposo, dieta, control)"
        value={form.indications}
        onChange={(e) => setForm({ ...form, indications: e.target.value })} />

      <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-3 space-y-2">
        <label className="flex items-start gap-2 text-sm text-zinc-200 cursor-pointer">
          <input type="checkbox" className="accent-cyan-500 mt-0.5" checked={form.reminders_enabled}
            onChange={(e) => setForm({ ...form, reminders_enabled: e.target.checked })} />
          <span>
            El paciente <b>pidió</b> recibir recordatorios de cada toma por WhatsApp.
            <span className="block text-[11px] text-zinc-400 mt-0.5">
              Solo se envían si el número escribió antes a la clínica, nunca entre las
              22:00 y las 07:00, y el paciente puede cortarlos respondiendo STOP.
            </span>
          </span>
        </label>
        {form.reminders_enabled && (
          <input className={input} placeholder="Quién registró el consentimiento"
            value={form.consent_by}
            onChange={(e) => setForm({ ...form, consent_by: e.target.value })} />
        )}
      </div>

      <div className="flex justify-end gap-3">
        <button type="button" onClick={() => setAbierto(false)}
          className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
        <button type="submit" disabled={guardando} className={btnPrimary}>
          {guardando ? "Guardando…" : "Guardar receta"}
        </button>
      </div>
    </form>
  );
}

function ListaRecetas({ company, prescriptions, onChanged, onError }: {
  company: Company; prescriptions: Prescription[];
  onChanged: () => void; onError: (e: string) => void;
}) {
  const cancelar = async (id: number) => {
    try {
      await clinicalApi.cancelPrescription(company.id, id);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Error");
    }
  };

  if (!prescriptions.length) {
    return <p className="text-sm text-zinc-500">Todavía no hay recetas cargadas.</p>;
  }
  return (
    <div className="space-y-3">
      {prescriptions.map((r) => (
        <div key={r.id} className={`${card} p-4`}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-white font-semibold text-sm">
                {r.patient_name}
                <span className="text-zinc-500 font-normal"> · {r.patient_phone}</span>
              </p>
              <p className="text-[11px] text-zinc-500">
                {r.doctor} · {new Date(r.issued_at).toLocaleDateString("es-PY")}
                {r.version > 1 && ` · versión ${r.version}`}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {r.reminders_enabled && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                  con recordatorios
                </span>
              )}
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${
                r.status === "active"
                  ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                  : "bg-zinc-500/10 text-zinc-400 border-zinc-500/20"}`}>
                {r.status === "active" ? "activa" : "suspendida"}
              </span>
            </div>
          </div>
          {r.diagnosis && <p className="text-xs text-zinc-400 mt-2">{r.diagnosis}</p>}
          <ul className="mt-2 space-y-1">
            {r.items.map((it) => (
              <li key={it.id} className="text-xs text-zinc-300">
                • <b>{it.medication}</b> — {it.dose}
                {it.every_hours > 0
                  ? ` · cada ${it.every_hours} h por ${it.duration_days} días`
                  : ` · ${it.frequency || "a demanda"}`}
              </li>
            ))}
          </ul>
          {r.status === "active" && (
            <button onClick={() => cancelar(r.id)}
              className="mt-3 text-xs text-zinc-500 hover:text-red-400">
              Suspender tratamiento
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function Convenios({ company, insurers, onChanged, onError }: {
  company: Company; insurers: Insurer[];
  onChanged: () => void; onError: (e: string) => void;
}) {
  const [form, setForm] = useState({ name: "", plan: "", coverage_pct: 0, copay_gs: 0 });
  // Qué convenio se está mirando práctica por práctica.
  const [aranceles, setAranceles] = useState<Insurer | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    onError("");
    try {
      await clinicalApi.createInsurer(company.id, form);
      setForm({ name: "", plan: "", coverage_pct: 0, copay_gs: 0 });
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Error");
    }
  };

  return (
    <div className={`${card} p-6 space-y-4`}>
      {aranceles && (
        <ArancelesModal companyId={company.id} insurer={aranceles}
          onClose={() => { setAranceles(null); onChanged(); }} />
      )}
      <div>
        <h3 className="font-bold text-white flex items-center gap-2">
          <ShieldCheck size={18} /> Convenios con seguros
        </h3>
        <p className="text-xs text-zinc-400 mt-1">
          Los que <b>esta</b> empresa tiene firmados. El bot los usa para responder
          cuánto le sale un estudio al paciente con su seguro; el cálculo lo hace el
          servidor, no el modelo. Tocá un convenio para cargar el <b>arancel</b> que
          paga por cada práctica según su nomenclador.
        </p>
      </div>

      {insurers.length > 0 && (
        <div className="space-y-2">
          {insurers.map((i) => (
            <button key={i.id} onClick={() => setAranceles(i)}
              className="w-full text-left flex items-center justify-between gap-3 text-sm
                         bg-white/[0.02] hover:bg-white/[0.05] border border-white/5
                         rounded-lg px-3 py-2 transition-colors">
              <span className="text-zinc-200">
                {i.name} <span className="text-zinc-500">{i.plan}</span>
              </span>
              <span className="text-xs text-zinc-400 tabular-nums flex items-center gap-2">
                cubre {i.coverage_pct}%
                {i.copay_gs > 0 && ` · copago ₲ ${i.copay_gs.toLocaleString("es-PY")}`}
                <span className="text-cyan-400 flex items-center gap-1">
                  <Coins size={12} /> aranceles
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-5 gap-2">
        <input className={input} required placeholder="Aseguradora" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input className={input} placeholder="Plan" value={form.plan}
          onChange={(e) => setForm({ ...form, plan: e.target.value })} />
        <input className={input} type="number" min={0} max={100} placeholder="% cobertura"
          value={form.coverage_pct}
          onChange={(e) => setForm({ ...form, coverage_pct: Number(e.target.value) })} />
        <input className={input} type="number" min={0} placeholder="Copago ₲"
          value={form.copay_gs}
          onChange={(e) => setForm({ ...form, copay_gs: Number(e.target.value) })} />
        <button type="submit" className={btnPrimary}>Agregar</button>
      </form>

      {insurers.length === 0 && (
        <p className="text-[11px] text-zinc-500 flex items-start gap-1.5">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          Sin convenios cargados el bot va a responder, con honestidad, que no hay
          convenio con la prepaga que mencione el paciente.
        </p>
      )}
    </div>
  );
}
