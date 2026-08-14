import { useEffect, useState } from "react";
import { Check, Lock, Loader2, ShoppingCart } from "lucide-react";
import { api, type Bloque, type Company } from "./../api";

/**
 * Los bloques del sistema: qué tiene contratado la empresa y qué le falta.
 *
 * El catálogo lo manda el servidor (`GET /api/packs`). Si el panel tuviera su
 * propia lista, el día que se agregue un bloque habría que acordarse de tocar
 * dos lados y lo que se ofrece dejaría de coincidir con lo que se habilita.
 *
 * Activar un bloque es del operador de la plataforma, no del cliente: el
 * backend responde 403 si lo intenta el dueño de la empresa, y acá ni se
 * muestra el botón. Que el candado se vea igual es a propósito — el cliente
 * tiene que saber qué más hay para comprar.
 */
export function BlocksView({
  company, esPlataforma, resaltar, onCambio,
}: {
  company: Company;
  esPlataforma: boolean;
  /** Clave del bloque que el usuario acaba de intentar usar sin tenerlo. */
  resaltar?: string;
  onCambio: (c: Company) => void;
}) {
  const [bloques, setBloques] = useState<Bloque[]>([]);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState("");

  useEffect(() => {
    api.bloques().then(setBloques)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, []);

  const contratados = new Set(company.packs.split(",").filter(Boolean));

  const alternar = async (clave: string, prender: boolean) => {
    setGuardando(clave); setError("");
    // Se manda la lista COMPLETA, no un delta: el servidor resuelve las
    // dependencias (salud arrastra agenda) y devuelve el resultado real.
    // Apagar un bloque no apaga a mano lo que dependía de él —eso lo decide
    // `active_packs`—, así que acá solo se saca la clave pedida.
    const nuevas = prender
      ? [...contratados, clave]
      : [...contratados].filter((k) => k !== clave);
    try {
      onCambio(await api.setPacks(company.id, nuevas.filter((k) => k !== "core")));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando("");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold text-white tracking-tight">Bloques del sistema</h1>
        <p className="text-sm text-zinc-400 mt-1">
          MetaBot.OS se vende por partes. {company.name} tiene contratado lo que aparece
          en verde; lo del candado se puede agregar cuando quiera.
        </p>
      </div>

      {error && <p className="text-red-400 text-xs">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {bloques.map((b) => {
          const tiene = b.incluido || contratados.has(b.key);
          const destacado = resaltar === b.key;
          return (
            <div key={b.key}
              className={`rounded-2xl border p-5 space-y-3 transition-all ${
                destacado ? "border-cyan-500/60 bg-cyan-500/[0.04]"
                  : tiene ? "border-emerald-500/25 bg-emerald-500/[0.02]"
                  : "border-white/5 bg-white/[0.01]"
              }`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-sm font-bold text-white flex items-center gap-2">
                    {tiene ? <Check size={14} className="text-emerald-400" />
                      : <Lock size={13} className="text-zinc-500" />}
                    {b.name}
                  </h2>
                  <p className="text-[11px] text-zinc-500 mt-1 leading-relaxed">{b.description}</p>
                </div>
                {b.incluido ? (
                  <span className="text-[10px] text-zinc-500 border border-white/10 px-2 py-1 rounded-full shrink-0">
                    incluido
                  </span>
                ) : tiene ? (
                  <span className="text-[10px] text-emerald-400 border border-emerald-500/30 px-2 py-1 rounded-full shrink-0">
                    activo
                  </span>
                ) : (
                  <span className="text-[10px] text-zinc-500 border border-white/10 px-2 py-1 rounded-full shrink-0">
                    no contratado
                  </span>
                )}
              </div>

              <ul className="space-y-1.5">
                {b.incluye.map((linea, i) => (
                  <li key={i} className={`text-[11px] flex items-start gap-2 ${tiene ? "text-zinc-300" : "text-zinc-500"}`}>
                    <span className={`mt-1.5 w-1 h-1 rounded-full shrink-0 ${tiene ? "bg-emerald-400" : "bg-zinc-600"}`} />
                    {linea}
                  </li>
                ))}
              </ul>

              {b.requires.length > 0 && !tiene && (
                <p className="text-[10px] text-zinc-600">
                  Necesita: {b.requires.map((r) => bloques.find((x) => x.key === r)?.name ?? r).join(", ")}
                </p>
              )}

              {!b.incluido && (
                esPlataforma ? (
                  <button
                    onClick={() => alternar(b.key, !tiene)}
                    disabled={guardando === b.key}
                    className={`w-full py-2 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 transition-all disabled:opacity-50 ${
                      tiene
                        ? "text-zinc-400 border border-white/10 hover:border-red-500/40 hover:text-red-300"
                        : "text-cyan-300 border border-cyan-500/30 hover:border-cyan-500 bg-cyan-500/5"
                    }`}>
                    {guardando === b.key ? <Loader2 size={13} className="animate-spin" />
                      : tiene ? "Desactivar" : <><ShoppingCart size={13} /> Activar bloque</>}
                  </button>
                ) : !tiene && (
                  <p className="text-[11px] text-cyan-300/80 border-t border-white/5 pt-3">
                    Para activarlo, escribinos por WhatsApp.
                  </p>
                )
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
