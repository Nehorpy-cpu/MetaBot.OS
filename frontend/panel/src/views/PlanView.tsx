/**
 * El plan del cliente y lo que lleva consumido este mes.
 *
 * Esto se le muestra a CUALQUIERA de la empresa, no solo a quien administra.
 * Ocultarle a un cliente lo que consume es cómo se llega a una discusión por
 * la factura: cuando ve el número todos los días, la factura no sorprende.
 *
 * El costo de IA se muestra siempre, incluso mientras lo paga la plataforma.
 * Un cliente que ve lo que gasta entiende por qué el plan grande cuesta más;
 * y el que puso su propia clave necesita el número para controlar su factura.
 *
 * Cambiar de plan NO se hace desde acá: lo hace el administrador de la
 * plataforma. La pantalla lo dice y ofrece el contacto, en vez de mostrar un
 * botón que va a devolver 403.
 */
import { useEffect, useState } from "react";
import { AlertTriangle, Check, KeyRound, TrendingUp } from "lucide-react";

import {
  ApiError, Consumo, formatGs, PlanCatalogo, planesApi,
} from "../api";
import { card } from "../ui";

function motivoDe(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { motivo?: string } | string;
    if (typeof d === "string") return d;
    if (d?.motivo) return d.motivo;
  }
  return e instanceof Error ? e.message : "Algo salió mal.";
}

/** Una barra de uso. Se pone ámbar al 80% y roja al llegar. */
function Barra({ usados, tope }: { usados: number; tope: number }) {
  const pct = tope > 0 ? Math.min(100, Math.round((usados / tope) * 100)) : 0;
  const color =
    pct >= 100 ? "bg-rose-500" : pct >= 80 ? "bg-amber-500" : "bg-violet-600";
  return (
    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-100">
      <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function Medidor({
  titulo, usados, tope, nota,
}: { titulo: string; usados: number; tope: number; nota: string }) {
  const quedan = Math.max(0, tope - usados);
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{titulo}</p>
      <p className="mt-1 text-2xl font-extrabold tracking-tight text-zinc-900">
        {usados.toLocaleString("es-PY")}
        <span className="ml-1 text-sm font-medium text-zinc-500">
          / {tope.toLocaleString("es-PY")}
        </span>
      </p>
      <Barra usados={usados} tope={tope} />
      <p className="mt-2 text-[11px] text-zinc-500">
        {quedan === 0 ? (
          <span className="text-rose-600">No queda nada este mes.</span>
        ) : (
          <>Quedan {quedan.toLocaleString("es-PY")}. {nota}</>
        )}
      </p>
    </div>
  );
}

export function PlanView({ companyId }: { companyId: number }) {
  const [consumo, setConsumo] = useState<Consumo | null>(null);
  const [catalogo, setCatalogo] = useState<PlanCatalogo[]>([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  const cargar = () =>
    planesApi.consumo(companyId).then(setConsumo).catch((e) => setError(motivoDe(e)));

  useEffect(() => {
    cargar();
    planesApi.catalogo().then(setCatalogo).catch(() => undefined);
  }, [companyId]);

  if (!consumo) {
    return (
      <p className="py-10 text-center text-sm text-zinc-500">
        {error || "Cargando…"}
      </p>
    );
  }

  const plan = consumo.plan;
  const ia = consumo.consumo_de_ia;
  const desde = new Date(consumo.desde + "T00:00:00").toLocaleDateString("es-PY", {
    day: "numeric", month: "long",
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-zinc-900">Tu plan</h1>
        <p className="mt-1 text-xs text-zinc-500">
          Lo que llevás usado desde el {desde}. Se reinicia el 1° de cada mes.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      <div className={`${card} p-5`}>
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Plan actual</p>
            <h2 className="text-lg font-bold text-zinc-900">{plan.nombre}</h2>
          </div>
          <p className="text-sm text-zinc-600">
            {plan.precio_gs > 0 ? `${formatGs(plan.precio_gs)} / mes` : "Sin costo"}
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Medidor
            titulo="Mensajes contestados"
            usados={consumo.mensajes.usados}
            tope={consumo.mensajes.tope}
            nota="Cada mensaje que responde el bot cuenta uno."
          />
          <Medidor
            titulo="Informes emitidos"
            usados={consumo.informes.usados}
            tope={consumo.informes.tope}
            nota="Cada informe privado del CFO cuenta uno."
          />
        </div>
      </div>

      <div className={`${card} p-5`}>
        <div className="mb-3 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-zinc-900">Consumo de inteligencia artificial</h3>
            <p className="mt-1 max-w-xl text-xs text-zinc-500">
              Lo que costó atender tus conversaciones este mes.{" "}
              {consumo.clave_en_uso === "plataforma"
                ? "Hoy lo paga MetaBot: está incluido en tu plan."
                : "Se lo factura OpenAI directamente a tu empresa."}
            </p>
          </div>
          <p className="shrink-0 text-right">
            <span className="block text-lg font-extrabold text-zinc-900">
              {formatGs(ia.costo_gs)}
            </span>
            <span className="text-[11px] text-zinc-500">
              {ia.tokens.toLocaleString("es-PY")} tokens
            </span>
          </p>
        </div>

        {ia.por_modelo.length === 0 ? (
          <p className="py-4 text-center text-xs text-zinc-500">
            Todavía no hubo conversaciones este mes.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="pb-2">Modelo</th>
                <th className="pb-2">Turnos</th>
                <th className="pb-2 text-right">Tokens</th>
                <th className="pb-2 text-right">Costo</th>
              </tr>
            </thead>
            <tbody>
              {ia.por_modelo.map((m) => (
                <tr key={m.modelo} className="border-t border-zinc-200">
                  <td className="py-2 font-mono text-[11px] text-zinc-700">{m.modelo}</td>
                  <td className="py-2 text-zinc-600">{m.turnos}</td>
                  <td className="py-2 text-right text-[11px] text-zinc-500">
                    {(m.tokens_entrada + m.tokens_salida).toLocaleString("es-PY")}
                  </td>
                  <td className="py-2 text-right text-zinc-700">
                    {m.gratuito ? (
                      <span className="text-[11px] text-zinc-500">sin cargo</span>
                    ) : (
                      formatGs(m.costo_gs)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className={`${card} p-5`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-xl">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
              <KeyRound size={14} className="text-zinc-500" />
              Con qué clave se te atiende
            </h3>
            <p className="mt-1 text-xs text-zinc-500">
              {consumo.clave_en_uso === "propia" ? (
                <>
                  Con la clave de OpenAI de tu empresa: el consumo te lo factura
                  OpenAI directamente, sin margen nuestro encima.
                </>
              ) : (
                <>
                  Con la de MetaBot, incluida en tu plan. Si tu volumen crece,
                  te conviene poner la tuya: pagás el consumo directo al
                  proveedor y la factura queda a nombre de tu empresa.
                </>
              )}
            </p>
            {aviso && (
              <p className="mt-2 flex items-start gap-1.5 text-[11px] text-emerald-700">
                <Check size={12} className="mt-0.5 shrink-0" /> {aviso}
              </p>
            )}
          </div>
          {consumo.clave_en_uso === "plataforma" && (
            <button
              onClick={async () => {
                try {
                  const r = await planesApi.solicitarClave(companyId);
                  setAviso(r.aviso || "Pedido registrado.");
                } catch (e) { setError(motivoDe(e)); }
              }}
              className="shrink-0 rounded-xl border border-zinc-200 px-3 py-2 text-xs font-semibold text-zinc-700 hover:border-violet-400 hover:text-violet-700"
            >
              Quiero usar mi propia clave
            </button>
          )}
        </div>
      </div>

      {catalogo.length > 0 && (
        <div className={`${card} p-5`}>
          <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold text-zinc-900">
            <TrendingUp size={14} className="text-zinc-500" /> Los planes
          </h3>
          <p className="mb-4 text-xs text-zinc-500">
            Para cambiar de plan, escribinos. No se cambia desde acá a propósito:
            lo confirma una persona de MetaBot con vos.
          </p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {catalogo.map((p) => {
              const actual = p.clave === plan.clave;
              return (
                <div
                  key={p.clave}
                  className={`rounded-xl border p-4 ${
                    actual
                      ? "border-violet-400 bg-violet-600/[0.06]"
                      : "border-zinc-200 bg-zinc-50"
                  }`}
                >
                  <div className="flex items-baseline justify-between">
                    <h4 className="text-sm font-bold text-zinc-900">{p.nombre}</h4>
                    {actual && (
                      <span className="rounded-lg bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-600">
                        el tuyo
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-base font-extrabold text-zinc-900">
                    {p.precio_gs > 0 ? formatGs(p.precio_gs) : "Sin costo"}
                    {p.precio_gs > 0 && (
                      <span className="text-[11px] font-medium text-zinc-500"> /mes</span>
                    )}
                  </p>
                  <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
                    {p.descripcion}
                  </p>
                  <ul className="mt-3 space-y-1 text-[11px] text-zinc-600">
                    <li>{p.mensajes_por_mes.toLocaleString("es-PY")} mensajes/mes</li>
                    <li>{p.informes_por_mes.toLocaleString("es-PY")} informes/mes</li>
                    <li>{p.identidades_cfo} números del CFO</li>
                    <li>{p.conectores} conectores de datos</li>
                    {p.clave_propia && (
                      <li className="text-amber-700">Con tu propia clave de OpenAI</li>
                    )}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
