import { useCallback, useEffect, useState } from "react";
import { Link2 } from "lucide-react";
import { AlertTriangle, Check, CircleHelp, Link2 as _L } from "lucide-react";
import { ALL_CAPABILITIES, CAPABILITY_ES, waApi, type Company, type DiagnosticoCanal, type WaStatus } from "../api";
import { card, input, btnPrimary } from "../ui";

export function ConnectionsView({ company, onCompanyUpdated }: { company: Company; onCompanyUpdated: (c: Company) => void }) {
  const [status, setStatus] = useState<WaStatus | null>(null);
  const [diag, setDiag] = useState<DiagnosticoCanal | null>(null);
  const [address, setAddress] = useState(company.address);
  const [pnid, setPnid] = useState(company.wa_phone_number_id ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    waApi.status(company.id).then((s) => { setStatus(s); setError(""); }).catch((e) => setError(e.message));
    // Qué falta para que este canal funcione. Sin esto, "el bot no responde"
    // es una adivinanza entre cinco causas que se arreglan en lugares
    // distintos.
    waApi.diagnostico(company.id).then(setDiag).catch(() => setDiag(null));
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
        <h2 className="text-3xl font-bold text-zinc-900 tracking-tight flex items-center gap-3">
          <Link2 className="text-violet-600" size={26} /> Centro de Conexiones — WhatsApp
        </h2>
        <p className="text-zinc-600 text-sm mt-1">Elegí cómo se conecta esta empresa a WhatsApp. El bot es el mismo en ambos canales.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {modes.map((m) => (
          <button key={m.id} disabled={busy} onClick={() => setMode(m.id)}
            className={`p-5 rounded-2xl border text-left transition-all ${company.wa_mode === m.id ? "bg-violet-50 border-cyan-500/50 text-zinc-900" : "bg-zinc-50 border-zinc-200 text-zinc-600 hover:bg-zinc-50"}`}>
            <p className="font-bold text-sm">{m.title}</p>
            <p className="text-[11px] text-zinc-500 mt-2">{m.desc}</p>
          </button>
        ))}
      </div>

      {/* Qué falta para que este canal funcione. Cada paso dice DÓNDE se
          arregla: el modo, el puente, el QR y los datos de Meta se cargan en
          cuatro lugares distintos, y "no anda" no distingue cuál es. */}
      {diag && (
        <div className={`${card} p-5 space-y-3`}>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest">
              Estado de la conexión
            </h3>
            <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full border ${
              diag.listo
                ? "bg-emerald-50 text-emerald-700 border-emerald-500/25"
                : "bg-amber-50 text-amber-700 border-amber-500/25"
            }`}>
              {diag.listo ? "Listo para recibir mensajes" : "Falta configurar"}
            </span>
          </div>

          <div className="space-y-2">
            {diag.pasos.map((p, i) => (
              <div key={i} className="flex items-start gap-2.5">
                <span className="shrink-0 mt-0.5">
                  {p.ok === true && <Check size={14} className="text-emerald-700" />}
                  {p.ok === false && <AlertTriangle size={14} className="text-amber-700" />}
                  {p.ok === null && <CircleHelp size={14} className="text-zinc-500" />}
                </span>
                <div className="min-w-0">
                  <p className={`text-xs font-medium ${p.ok === false ? "text-amber-800" : "text-zinc-800"}`}>
                    {p.paso}
                  </p>
                  <p className="text-[11px] text-zinc-500 leading-relaxed">{p.detalle}</p>
                  {p.ok !== true && p.donde && (
                    <p className="text-[11px] text-violet-600/80 mt-0.5">→ {p.donde}</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {diag.advertencia && (
            <p className="text-[11px] text-amber-700/90 leading-relaxed bg-amber-500/[0.06] border border-amber-500/20 rounded-xl p-3">
              {diag.advertencia}
            </p>
          )}
        </div>
      )}

      {status?.capabilities && (
        <div className={`${card} p-5 space-y-3`}>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest">
              {status.channel_name ?? "Canal"}
            </h3>
            <span className={`text-[9px] px-2 py-0.5 rounded-full border font-bold uppercase ${status.official ? "bg-emerald-50 text-emerald-700 border-emerald-500/20" : "bg-amber-50 text-amber-700 border-amber-500/20"}`}>
              {status.official ? "Oficial" : "Comunidad"}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1.5">
            {ALL_CAPABILITIES.map((cap) => {
              const has = status.capabilities?.includes(cap);
              return (
                <div key={cap} className={`text-xs flex items-center gap-2 ${has ? "text-zinc-700" : "text-zinc-500"}`}>
                  <span className={has ? "text-emerald-700" : "text-zinc-400"}>{has ? "✓" : "✕"}</span>
                  {CAPABILITY_ES[cap]}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {company.wa_mode === "qr" && (
        <div className={`${card} p-6 space-y-4`}>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest">Sesión QR</h3>
            <span className={`text-[10px] px-2.5 py-1 rounded-full border font-bold uppercase ${status?.status === "connected" ? "bg-emerald-50 text-emerald-700 border-emerald-500/20" : "bg-amber-50 text-amber-700 border-amber-500/20"}`}>
              {status?.status === "connected" ? `Conectado${status.phone ? ` (+${status.phone})` : ""}` : status?.status ?? "…"}
            </span>
          </div>
          <p className="text-xs text-amber-700/90 bg-amber-500/5 border border-amber-500/20 rounded-xl p-3">
            ⚠️ Canal no oficial: WhatsApp puede restringir números que automatizan respuestas.
            Este modo solo responde a quien escribe primero (menor riesgo), pero para clínicas
            con datos sensibles recomendamos la API oficial de Meta.
          </p>
          {status?.status === "qr" && status.qr && (
            <div className="flex flex-col items-center gap-3">
              <img src={status.qr} alt="QR de WhatsApp" className="rounded-xl border border-zinc-200 bg-white p-2 w-64" />
              <p className="text-xs text-zinc-600">WhatsApp → Dispositivos vinculados → Vincular dispositivo</p>
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
                className="px-5 py-2.5 bg-zinc-50 hover:bg-zinc-200 border border-zinc-200 text-zinc-700 rounded-xl text-sm font-semibold">
                Cerrar sesión
              </button>
            )}
          </div>
        </div>
      )}

      {company.wa_mode === "meta" && (
        <div className={`${card} p-6 space-y-4 max-w-xl`}>
          <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest">Meta Cloud API</h3>
          <p className="text-xs text-zinc-600">
            El token, verify token y app secret van en el <code className="text-violet-600">.env</code> del servidor.
            Acá solo se asigna el <b>phone_number_id</b> de esta empresa.
          </p>
          <div className="flex gap-2">
            <input className={input} placeholder="phone_number_id" value={pnid} onChange={(e) => setPnid(e.target.value)} />
            <button className={btnPrimary} disabled={busy}
              onClick={() => waApi.updateCompany(company.id, { wa_phone_number_id: pnid }).then(onCompanyUpdated).catch((e) => setError(e.message))}>
              Guardar
            </button>
          </div>
          <p className="text-xs text-zinc-500">Webhook a configurar en Meta: <code className="text-violet-600">https://TU-DOMINIO/api/webhooks/whatsapp</code></p>
        </div>
      )}

      <div className={`${card} p-6 space-y-3 max-w-xl`}>
        <h3 className="text-sm font-bold text-zinc-800 uppercase tracking-widest">Datos del negocio</h3>
        <p className="text-xs text-zinc-600">La dirección se incluye en los recordatorios de citas que reciben los clientes.</p>
        <div className="flex gap-2">
          <input className={input} placeholder="Ej. Av. España 1234 c/ Brasil, Asunción" value={address}
            onChange={(e) => setAddress(e.target.value)} />
          <button className={btnPrimary} disabled={busy}
            onClick={() => waApi.updateCompany(company.id, { address }).then(onCompanyUpdated).catch((e) => setError(e.message))}>
            Guardar
          </button>
        </div>
      </div>

      {error && <p className="text-red-600 text-xs">{error}</p>}
    </div>
  );
}
