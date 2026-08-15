import { useCallback, useEffect, useState } from "react";
import { Activity, Sliders } from "lucide-react";
import { api, type AgentDetail, type AgentSummary, type Company } from "../api";
import { AGENT_ICONS, btnPrimary, input, Interruptor, Modal, papelDe } from "../ui";
import { SupervisionPanel } from "./SupervisionPanel";

export function AgentEditModal({ agentId, onClose, onSaved }: { agentId: number; onClose: () => void; onSaved: () => void }) {
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
            <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-2">System prompt</label>
            <textarea className={`${input} min-h-36 font-mono text-xs`} value={agent.system_prompt}
              onChange={(e) => setAgent({ ...agent, system_prompt: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-2">
                Temperatura: {agent.temperature.toFixed(2)}
              </label>
              <input type="range" min={0} max={1} step={0.05} value={agent.temperature}
                onChange={(e) => setAgent({ ...agent, temperature: Number(e.target.value) })}
                className="w-full accent-cyan-500" />
            </div>
            <div>
              <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block mb-2">Modelo</label>
              <input className={input} value={agent.model} onChange={(e) => setAgent({ ...agent, model: e.target.value })} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-zinc-700 cursor-pointer">
            <input type="checkbox" checked={agent.active} className="accent-cyan-500"
              onChange={(e) => setAgent({ ...agent, active: e.target.checked })} />
            Agente activo
          </label>
          {error && <p className="text-red-600 text-xs">{error}</p>}
          <div className="flex justify-end gap-3 pt-3 border-t border-zinc-200">
            <button onClick={onClose} className="px-4 py-2 text-sm text-zinc-600 hover:text-zinc-900">Cancelar</button>
            <button onClick={save} disabled={saving} className={btnPrimary}>
              {saving ? "Guardando…" : "Guardar cambios"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

export function AgentsView({ company, onCompanyUpdated }: { company: Company; onCompanyUpdated: () => void }) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const load = useCallback(() => {
    api.listAgents(company.id).then(setAgents).catch(() => setAgents([]));
  }, [company.id]);
  useEffect(load, [load]);

  /**
   * El orden de las notas, guardado en el navegador.
   *
   * Va en localStorage y NO en el servidor a propósito: es una preferencia de
   * quien mira la pantalla, no un dato del negocio. Mandarla al backend
   * obligaría a una tabla, una migración y una decisión sobre qué pasa cuando
   * dos personas de la misma empresa la ordenan distinto.
   */
  const claveOrden = `metabot:orden-agentes:${company.id}`;
  const [orden, setOrden] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(claveOrden) || "[]"); }
    catch { return []; }
  });
  const [arrastrando, setArrastrando] = useState<string | null>(null);
  const [encima, setEncima] = useState<string | null>(null);

  const ordenados = [...agents].sort((x, y) => {
    const i = orden.indexOf(x.slug), j = orden.indexOf(y.slug);
    // Los que nunca se movieron van al final, en el orden que da el servidor.
    return (i === -1 ? 999 : i) - (j === -1 ? 999 : j);
  });

  const soltar = (destino: string) => {
    if (!arrastrando || arrastrando === destino) return;
    const base = ordenados.map((a) => a.slug);
    const desde = base.indexOf(arrastrando);
    base.splice(desde, 1);
    base.splice(base.indexOf(destino), 0, arrastrando);
    setOrden(base);
    localStorage.setItem(claveOrden, JSON.stringify(base));
    setArrastrando(null);
    setEncima(null);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-zinc-900 tracking-tight">Tus agentes</h2>
        <p className="text-zinc-600 text-sm mt-1">
          Cada uno es una nota: tocá para configurarlo y arrastrá para ordenarlas
          como te sirva. El interruptor lo prende o lo pausa sin entrar.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {ordenados.map((a, i) => {
          const Icon = AGENT_ICONS[a.slug] ?? Activity;
          const papel = papelDe(i);
          return (
            <div
              key={a.id}
              draggable
              onDragStart={() => setArrastrando(a.slug)}
              onDragEnd={() => { setArrastrando(null); setEncima(null); }}
              onDragOver={(e) => { e.preventDefault(); setEncima(a.slug); }}
              onDrop={() => soltar(a.slug)}
              onClick={() => setEditing(a.id)}
              className={`postit aparece flex cursor-pointer flex-col p-4 shadow-lg shadow-zinc-900/[0.07] ${papel.fondo} ${papel.texto} ${
                arrastrando === a.slug ? "arrastrando" : ""
              } ${encima === a.slug && arrastrando !== a.slug ? "destino" : ""}`}
              style={{ animationDelay: `${i * 40}ms` }}
            >
              <div className="mb-2 flex items-center gap-2.5">
                <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-[10px] ${papel.icono}`}>
                  <Icon size={16} />
                </span>
                <h3 className="min-w-0 flex-1 truncate text-sm font-extrabold">{a.name}</h3>
              </div>

              {/* Qué hace el agente, en el cuerpo y en dos renglones. Antes iba
                  en el encabezado, en mayúsculas y cortado con puntos
                  suspensivos: era el texto más útil de la nota y el menos
                  legible. */}
              <p className="mb-2 line-clamp-2 flex-1 text-[11.5px] leading-relaxed opacity-80">
                {a.role}
              </p>
              <p className="truncate font-mono text-[10px] opacity-55" title={`${a.model} · T=${a.temperature}`}>
                {a.model} · T {a.temperature.toFixed(2)}
              </p>

              <div className="mt-3 flex items-center justify-between border-t border-black/10 pt-2.5">
                <span className="text-[10px] font-extrabold uppercase tracking-wider opacity-70">
                  {a.active ? "Activo" : "En pausa"}
                </span>
                <div className="flex items-center gap-2">
                  <Sliders size={13} className="opacity-45" />
                  <Interruptor
                    activo={a.active}
                    titulo={a.active ? "Pausar este agente" : "Activar este agente"}
                    onToggle={async () => {
                      // Se pinta el cambio antes de que conteste el servidor:
                      // esperar medio segundo a un interruptor lo hace sentir
                      // roto. Si falla, `load()` lo devuelve a su estado real.
                      setAgents((prev) => prev.map((x) =>
                        x.id === a.id ? { ...x, active: !x.active } : x));
                      try { await api.updateAgent(a.id, { active: !a.active }); }
                      finally { load(); }
                    }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <SupervisionPanel company={company} onChanged={onCompanyUpdated} />
      {editing !== null && <AgentEditModal agentId={editing} onClose={() => setEditing(null)} onSaved={load} />}
    </div>
  );
}
