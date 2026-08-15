import React from "react";
import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Video, Wand2, X } from "lucide-react";
import { campaignApi, creativeApi, type Campaign, type Creative } from "../api";
import { card, input, btnPrimary } from "../ui";

export const AUDIT_BADGE: Record<string, string> = {
  ok: "bg-emerald-50 text-emerald-700 border-emerald-500/20",
  info: "bg-violet-50 text-violet-600 border-cyan-500/20",
  warning: "bg-amber-50 text-amber-700 border-amber-500/20",
  critical: "bg-red-500/10 text-red-600 border-red-500/20",
};

export function CampaignCardView({ campaign, onDelete }: { campaign: Campaign; onDelete: () => void }) {
  return (
    <div className={`${card} p-5 space-y-3`}>
      <div className="flex justify-between items-start gap-3">
        <div>
          <h4 className="font-bold text-zinc-900 text-sm">{campaign.title}</h4>
          <p className="text-[10px] text-zinc-500 uppercase">
            {campaign.format === "carousel" ? "Carrusel" : campaign.format === "single" ? "Imagen única" : "Guion de video"} · {campaign.strategy.audience ?? ""}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-[9px] px-2 py-0.5 rounded-full border font-bold uppercase ${AUDIT_BADGE[campaign.audit_severity] ?? AUDIT_BADGE.info}`}
            title={campaign.audit_note}>
            Auditor: {campaign.audit_severity}
          </span>
          <button onClick={onDelete} className="text-zinc-500 hover:text-red-600 p-1"><X size={14} /></button>
        </div>
      </div>
      {campaign.audit_severity !== "ok" && campaign.audit_note && (
        <p className="text-xs text-amber-700/90 bg-amber-500/5 border border-amber-500/20 rounded-lg p-2">{campaign.audit_note}</p>
      )}
      <div className="flex gap-3 overflow-x-auto pb-2">
        {campaign.cards.map((c) => (
          <div key={c.position} className="w-52 shrink-0 bg-zinc-50 border border-zinc-200 rounded-xl overflow-hidden">
            {c.image_path && <img src={c.image_path} alt={c.headline} className="w-full aspect-square object-cover" />}
            <div className="p-3 space-y-1">
              <p className="text-xs font-bold text-violet-600">{c.headline}</p>
              <p className="text-xs text-zinc-700 whitespace-pre-wrap">{c.copy}</p>
              {c.visual && <p className="text-[10px] text-zinc-500 italic">🎬 {c.visual}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function StudioView({ companyId }: { companyId: number }) {
  const [creatives, setCreatives] = useState<Creative[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [brief, setBrief] = useState("");
  const [format, setFormat] = useState<"creative" | "carousel" | "video_script">("creative");
  const [nCards, setNCards] = useState(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    creativeApi.list(companyId).then(setCreatives).catch(() => setCreatives([]));
    campaignApi.list(companyId).then(setCampaigns).catch(() => setCampaigns([]));
  }, [companyId]);
  useEffect(load, [load]);

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (brief.trim().length < 5 || busy) return;
    setBusy(true);
    setError("");
    try {
      if (format === "creative") await creativeApi.create(companyId, brief.trim());
      else await campaignApi.create(companyId, brief.trim(), format, nCards);
      setBrief("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-zinc-900 tracking-tight flex items-center gap-3">
          <Video className="text-violet-600" size={26} /> Estudio Visual
        </h2>
        <p className="text-zinc-600 text-sm mt-1">
          El Director Creativo escribe el copy y el Estudio Visual genera la imagen. Un brief, un creativo listo.
        </p>
      </div>

      <form onSubmit={generate} className={`${card} p-5 space-y-3`}>
        <label className="text-xs font-bold text-zinc-600 uppercase tracking-widest block">Brief de la campaña</label>
        <textarea className={`${input} min-h-20`} value={brief} onChange={(e) => setBrief(e.target.value)}
          placeholder="Ej. Promo de blanqueamiento dental esta semana, 20% de descuento, público joven de Asunción" />
        <div className="flex flex-wrap gap-3 items-center">
          <select className={`${input} w-auto`} value={format} onChange={(e) => setFormat(e.target.value as typeof format)}>
            <option value="creative" className="bg-white">Creativo simple (copy + imagen)</option>
            <option value="carousel" className="bg-white">Carrusel para Meta</option>
            <option value="video_script" className="bg-white">Guion de video / reel</option>
          </select>
          {format !== "creative" && (
            <label className="text-xs text-zinc-600 flex items-center gap-2">
              {format === "carousel" ? "Tarjetas:" : "Escenas:"}
              <input type="number" min={2} max={8} value={nCards} onChange={(e) => setNCards(Number(e.target.value))}
                className={`${input} w-16`} />
            </label>
          )}
        </div>
        {error && <p className="text-red-600 text-xs">{error}</p>}
        <button type="submit" disabled={busy || brief.trim().length < 5} className={btnPrimary}>
          {busy ? <><RefreshCw className="animate-spin" size={15} /> Generando ({format === "creative" ? "copy + imagen" : "CEO → Creativo → Visual → Auditor"})…</> : <><Wand2 size={15} /> Generar</>}
        </button>
      </form>

      {campaigns.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest">Campañas en borrador ({campaigns.length})</h3>
          {campaigns.map((c) => (
            <CampaignCardView key={c.id} campaign={c} onDelete={() => campaignApi.remove(companyId, c.id).then(load)} />
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {creatives.map((c) => (
          <div key={c.id} className={`${card} overflow-hidden flex flex-col`}>
            <img src={c.image_path} alt={c.brief} className="w-full aspect-square object-cover" />
            <div className="p-4 space-y-2 flex-1 flex flex-col">
              <p className="text-sm text-zinc-900 whitespace-pre-wrap flex-1">{c.copy_text}</p>
              <div className="flex justify-between items-center pt-2 border-t border-zinc-200">
                <span className="text-[9px] text-zinc-500 font-mono uppercase">{c.provider}</span>
                <button onClick={() => creativeApi.remove(companyId, c.id).then(load)}
                  className="text-zinc-500 hover:text-red-600 p-1"><X size={14} /></button>
              </div>
            </div>
          </div>
        ))}
        {!creatives.length && <p className="text-xs text-zinc-500 col-span-full">Sin creativos todavía. Escribí un brief y generá el primero.</p>}
      </div>
    </div>
  );
}
