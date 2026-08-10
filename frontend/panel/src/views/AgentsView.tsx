import { useCallback, useEffect, useState } from "react";
import { Activity, Sliders } from "lucide-react";
import { api, type AgentDetail, type AgentSummary } from "../api";
import { card, input, btnPrimary, AGENT_ICONS, Modal } from "../ui";

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

export function AgentsView({ companyId }: { companyId: number }) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const load = useCallback(() => {
    api.listAgents(companyId).then(setAgents).catch(() => setAgents([]));
  }, [companyId]);
  useEffect(load, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight">Enjambre de {agents.length || 7} Agentes IA</h2>
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
