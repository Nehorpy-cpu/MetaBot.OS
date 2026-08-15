import React from "react";
import { useState } from "react";
import { BarChart3, RefreshCw, Sparkles, Stethoscope } from "lucide-react";
import { api, type Company } from "../api";
import { input, btnPrimary, Modal } from "../ui";

export function NewCompanyModal({ onClose, onCreated }: { onClose: () => void; onCreated: (c: Company) => void }) {
  const [mode, setMode] = useState<"smart" | "template">("smart");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [website, setWebsite] = useState("");
  const [vertical, setVertical] = useState<"medical" | "ecommerce">("medical");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const company =
        mode === "smart"
          ? await api.createCompanySmart(name, description, website.trim())
          : await api.createCompany(name, vertical);
      onCreated(company);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Nueva Empresa (cualquier rubro)" onClose={onClose}>
      <div className="flex gap-2 mb-4">
        <button type="button" onClick={() => setMode("smart")}
          className={`px-4 py-2 rounded-xl text-xs font-bold border ${mode === "smart" ? "bg-violet-50 border-cyan-500/50 text-violet-600" : "bg-zinc-50 border-zinc-200 text-zinc-600"}`}>
          <Sparkles size={13} className="inline mr-1" /> Con IA (detecta el rubro)
        </button>
        <button type="button" onClick={() => setMode("template")}
          className={`px-4 py-2 rounded-xl text-xs font-bold border ${mode === "template" ? "bg-violet-50 border-cyan-500/50 text-violet-600" : "bg-zinc-50 border-zinc-200 text-zinc-600"}`}>
          Plantilla clásica
        </button>
      </div>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-2">Nombre</label>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} required
            placeholder="Ej. Ferretería El Tornillo" />
        </div>

        {mode === "smart" ? (
          <>
            <div>
              <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-2">
                ¿Qué hace el negocio? (productos, servicios, clientes)
              </label>
              <textarea className={`${input} min-h-24`} value={description} required minLength={10}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Ej. Vendemos herramientas, pinturas y materiales eléctricos, con delivery en Asunción. Clientes: constructores y hogares." />
            </div>
            <div>
              <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-2">Web o red social (opcional)</label>
              <input className={input} value={website} onChange={(e) => setWebsite(e.target.value)}
                placeholder="https://…" />
            </div>
            <div className="bg-violet-600/5 border border-cyan-500/20 rounded-xl p-3 text-xs text-violet-600 flex items-start gap-2">
              <Sparkles size={15} className="shrink-0 mt-0.5" />
              <p>El Arquitecto de Negocio detecta rubro, productos y audiencia, y escribe los prompts de los 7 agentes a medida. Después podés ajustarlos en el Super-Configurator.</p>
            </div>
          </>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {([["medical", "Consultorio / Sanatorio", Stethoscope], ["ecommerce", "E-Commerce / Retail", BarChart3]] as const).map(
              ([v, label, Icon]) => (
                <button key={v} type="button" onClick={() => setVertical(v)}
                  className={`p-4 rounded-xl border text-left transition-all ${vertical === v ? "bg-violet-50 border-cyan-500/50 text-zinc-900" : "bg-zinc-50 border-zinc-200 text-zinc-600 hover:bg-zinc-50"}`}>
                  <Icon className="text-violet-600 mb-2" size={22} />
                  <p className="font-bold text-sm">{label}</p>
                </button>
              )
            )}
          </div>
        )}

        {error && <p className="text-red-600 text-xs">{error}</p>}
        <div className="flex justify-end gap-3 pt-3 border-t border-zinc-200">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-900">Cancelar</button>
          <button type="submit" disabled={saving} className={btnPrimary}>
            {saving ? <><RefreshCw className="animate-spin" size={15} /> {mode === "smart" ? "Perfilando negocio…" : "Creando…"}</> : "Crear enjambre y empresa"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
