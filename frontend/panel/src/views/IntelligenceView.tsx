import { useCallback, useEffect, useState } from "react";
import { Activity, BarChart3, Globe2, RefreshCw, ShieldCheck, Users, Wand2, X } from "lucide-react";
import { intelApi, type Competitor, type Finding, type PromptSuggestion, type Report } from "../api";
import { card, input, btnPrimary, Modal } from "../ui";

export const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-red-500/10 text-red-400 border-red-500/20",
  warning: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  info: "bg-cyan-500/10 text-cyan-300 border-cyan-500/20",
};

export function IntelligenceView({ companyId }: { companyId: number }) {
  const [reports, setReports] = useState<Report[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [suggestions, setSuggestions] = useState<PromptSuggestion[]>([]);
  const [openSuggestion, setOpenSuggestion] = useState<PromptSuggestion | null>(null);
  const [openReport, setOpenReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [segWebsite, setSegWebsite] = useState("");

  const load = useCallback(() => {
    intelApi.listReports(companyId).then(setReports).catch(() => setReports([]));
    intelApi.listAudits(companyId).then(setFindings).catch(() => setFindings([]));
    intelApi.listCompetitors(companyId).then(setCompetitors).catch(() => setCompetitors([]));
    intelApi.listSuggestions(companyId).then(setSuggestions).catch(() => setSuggestions([]));
  }, [companyId]);
  useEffect(load, [load]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError("");
    try {
      await fn();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
          <Activity className="text-cyan-400" size={26} /> Inteligencia del Enjambre
        </h2>
        <p className="text-zinc-400 text-sm mt-1">
          Informes del Analista Quant, auditoría del Guard y escaneo de competencia. También corren
          solos: informe los lunes 07:00, auditoría diaria 20:00, competencia los domingos.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <button disabled={!!busy} onClick={() => run("weekly", () => intelApi.generateWeekly(companyId))} className={btnPrimary}>
          {busy === "weekly" ? <RefreshCw className="animate-spin" size={15} /> : <BarChart3 size={15} />} Generar informe semanal
        </button>
        <button disabled={!!busy} onClick={() => run("audit", () => intelApi.runAudit(companyId))} className={btnPrimary}>
          {busy === "audit" ? <RefreshCw className="animate-spin" size={15} /> : <ShieldCheck size={15} />} Auditar conversaciones
        </button>
        <button disabled={!!busy || !competitors.length} onClick={() => run("comp", () => intelApi.generateCompetitive(companyId))} className={btnPrimary}>
          {busy === "comp" ? <RefreshCw className="animate-spin" size={15} /> : <Globe2 size={15} />} Escanear competencia
        </button>
        <button disabled={!!busy} onClick={() => run("opt", () => intelApi.runOptimizer(companyId))} className={btnPrimary}>
          {busy === "opt" ? <RefreshCw className="animate-spin" size={15} /> : <Wand2 size={15} />} Optimizar prompts
        </button>
        <div className="flex gap-2 items-center">
          <input className={`${input} w-64`} placeholder="Web del negocio (para scraping)" value={segWebsite}
            onChange={(e) => setSegWebsite(e.target.value)} />
          <button disabled={!!busy} onClick={() => run("seg", () => intelApi.researchSegments(companyId, segWebsite.trim()))} className={btnPrimary}>
            {busy === "seg" ? <RefreshCw className="animate-spin" size={15} /> : <Users size={15} />} Investigar segmentos
          </button>
        </div>
      </div>
      {error && <p className="text-red-400 text-xs">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={`lg:col-span-2 ${card} p-5 space-y-3`}>
          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest">Informes ({reports.length})</h3>
          {!reports.length && <p className="text-xs text-zinc-600">Todavía no hay informes. Generá el primero.</p>}
          {reports.map((r) => (
            <div key={r.id} onClick={() => setOpenReport(r)}
              className="p-3 rounded-xl border bg-white/[0.02] border-white/5 hover:bg-white/[0.04] cursor-pointer flex justify-between items-center">
              <div>
                <p className="font-bold text-sm text-zinc-100">{r.title}</p>
                <p className="text-[10px] text-zinc-500">{new Date(r.created_at).toLocaleString("es-PY")}</p>
              </div>
              <span className="text-[9px] px-2 py-0.5 rounded-full border border-white/10 bg-white/5 text-zinc-400 font-bold uppercase">
                {r.kind === "weekly" ? "Quant" : "Competencia"}
              </span>
            </div>
          ))}

          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest pt-4">
            Mejoras de prompts propuestas ({suggestions.filter((s) => s.status === "pending").length} pendientes)
          </h3>
          {suggestions.filter((s) => s.status === "pending").map((s) => (
            <div key={s.id} className="p-3 rounded-xl border bg-white/[0.02] border-white/5 space-y-2">
              <div className="flex justify-between items-center">
                <p className="font-bold text-sm text-zinc-100">{s.agent_name}</p>
                <div className="flex gap-2">
                  <button onClick={() => setOpenSuggestion(s)}
                    className="text-xs bg-white/5 hover:bg-white/10 border border-white/10 px-3 py-1 rounded-lg text-zinc-300">Ver</button>
                  <button onClick={() => run("apply", () => intelApi.applySuggestion(companyId, s.id))}
                    className="text-xs bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 px-3 py-1 rounded-lg text-emerald-300">Aplicar</button>
                  <button onClick={() => run("reject", () => intelApi.rejectSuggestion(companyId, s.id))}
                    className="text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-3 py-1 rounded-lg text-red-300">Rechazar</button>
                </div>
              </div>
              <p className="text-xs text-zinc-400">{s.rationale}</p>
            </div>
          ))}
          {!suggestions.filter((s) => s.status === "pending").length && (
            <p className="text-xs text-zinc-600">Sin mejoras pendientes. El Optimizador corre solo los sábados o con el botón de arriba.</p>
          )}

          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest pt-4">Hallazgos del Auditor ({findings.length})</h3>
          {!findings.length && <p className="text-xs text-zinc-600">Sin hallazgos. El Guard no encontró problemas (o aún no corrió).</p>}
          {findings.map((f) => (
            <div key={f.id} className="p-3 rounded-xl border bg-white/[0.02] border-white/5">
              <div className="flex justify-between items-center mb-1">
                <span className={`text-[9px] px-2 py-0.5 rounded-full border font-bold uppercase ${SEVERITY_STYLE[f.severity] ?? SEVERITY_STYLE.info}`}>
                  {f.severity}
                </span>
                <span className="text-[10px] text-zinc-500">conversación #{f.conversation_id}</span>
              </div>
              <p className="text-xs text-zinc-300">{f.note}</p>
            </div>
          ))}
        </div>

        <div className={`${card} p-5 space-y-3`}>
          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest">Competidores ({competitors.length})</h3>
          <input className={input} placeholder="https://competidor.com.py" value={newUrl} onChange={(e) => setNewUrl(e.target.value)} />
          <input className={input} placeholder="Nombre (opcional)" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
          <button disabled={!newUrl.trim() || !!busy}
            onClick={() => run("addcomp", async () => { await intelApi.addCompetitor(companyId, newUrl.trim(), newLabel.trim()); setNewUrl(""); setNewLabel(""); })}
            className="w-full py-2 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 rounded-xl text-xs font-bold disabled:opacity-40">
            + Agregar competidor
          </button>
          {competitors.map((c) => (
            <div key={c.id} className="p-2.5 rounded-xl border bg-white/[0.02] border-white/5 flex justify-between items-center">
              <div className="min-w-0">
                <p className="text-xs font-bold text-zinc-200 truncate">{c.label || c.url}</p>
                <p className="text-[10px] text-zinc-500 truncate">{c.url}</p>
              </div>
              <button onClick={() => run("delcomp", () => intelApi.deleteCompetitor(companyId, c.id))}
                className="text-zinc-500 hover:text-red-400 p-1 shrink-0"><X size={14} /></button>
            </div>
          ))}
        </div>
      </div>

      {openReport && (
        <Modal title={openReport.title} onClose={() => setOpenReport(null)}>
          <pre className="whitespace-pre-wrap text-sm text-zinc-200 font-sans leading-relaxed">{openReport.content}</pre>
        </Modal>
      )}
      {openSuggestion && (
        <Modal title={`Mejora propuesta: ${openSuggestion.agent_name}`} onClose={() => setOpenSuggestion(null)}>
          <div className="space-y-4 text-sm">
            <div>
              <p className="text-xs font-bold text-zinc-400 uppercase tracking-widest mb-2">Motivo</p>
              <p className="text-zinc-300">{openSuggestion.rationale}</p>
            </div>
            <div>
              <p className="text-xs font-bold text-zinc-400 uppercase tracking-widest mb-2">Prompt actual</p>
              <pre className="whitespace-pre-wrap text-xs bg-[#040609] p-3 rounded-lg border border-white/5 text-zinc-400">{openSuggestion.old_prompt}</pre>
            </div>
            <div>
              <p className="text-xs font-bold text-zinc-400 uppercase tracking-widest mb-2">Prompt propuesto</p>
              <pre className="whitespace-pre-wrap text-xs bg-[#040609] p-3 rounded-lg border border-cyan-500/20 text-cyan-100">{openSuggestion.suggested_prompt}</pre>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
