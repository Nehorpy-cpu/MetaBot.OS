import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Search } from "lucide-react";
import {
  clinicalApi, serviceApi, type CoberturaDePractica, type Insurer,
} from "../api";
import { input, Modal } from "../ui";

/**
 * Los aranceles de un convenio: cuánto paga esa aseguradora por cada práctica.
 *
 * Es como funciona de verdad — cada convenio tiene su nomenclador con un
 * monto fijo por práctica, que rara vez es un porcentaje redondo del precio
 * de lista de la clínica. Se carga acá una vez y el sistema lo toma tal cual:
 * el bot, para decirle al paciente cuánto le sale, y la planilla de
 * honorarios, para decirle al profesional cuánto le tienen que pagar.
 *
 * Vacío o 0 = no configurado, y ahí se sigue usando el porcentaje general del
 * convenio. No es lo mismo que cargar 0: eso sería decir que no paga nada.
 */

const gs = (n: number) => (n ?? 0).toLocaleString("es-PY").replace(/,/g, ".");

type Fila = {
  service_id: number;
  servicio: string;
  precio_lista_gs: number;
  arancel_gs: number;
  excluded: boolean;
  coverage_pct: number;
  copay_gs: number;
};

export function ArancelesModal({ companyId, insurer, onClose }: {
  companyId: number; insurer: Insurer; onClose: () => void;
}) {
  const [filas, setFilas] = useState<Fila[]>([]);
  const [busqueda, setBusqueda] = useState("");
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(0);
  const [guardado, setGuardado] = useState(0);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vivo = true;
    Promise.all([
      serviceApi.list(companyId),
      clinicalApi.coberturas(companyId, insurer.id),
    ])
      .then(([servicios, cargadas]) => {
        if (!vivo) return;
        const porServicio = new Map<number, CoberturaDePractica>(
          cargadas.map((c) => [c.service_id, c])
        );
        // Se listan TODAS las prácticas, no solo las que ya tienen algo
        // cargado: si solo aparecieran las configuradas, no habría desde
        // dónde configurar la primera.
        setFilas(
          servicios.map((s) => {
            const c = porServicio.get(s.id);
            return {
              service_id: s.id,
              servicio: s.name,
              precio_lista_gs: s.price_gs,
              arancel_gs: c?.arancel_gs ?? 0,
              excluded: c?.excluded ?? false,
              coverage_pct: c?.coverage_pct ?? 0,
              copay_gs: c?.copay_gs ?? 0,
            };
          })
        );
      })
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"))
      .finally(() => vivo && setCargando(false));
    return () => { vivo = false; };
  }, [companyId, insurer.id]);

  const guardar = async (f: Fila) => {
    setGuardando(f.service_id); setError("");
    try {
      await clinicalApi.setCobertura(companyId, insurer.id, {
        service_id: f.service_id,
        coverage_pct: f.coverage_pct,
        copay_gs: f.copay_gs,
        excluded: f.excluded,
        arancel_gs: f.arancel_gs,
      });
      setGuardado(f.service_id);
      setTimeout(() => setGuardado(0), 1800);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(0);
    }
  };

  const cambiar = (id: number, cambio: Partial<Fila>) =>
    setFilas((prev) => prev.map((f) => (f.service_id === id ? { ...f, ...cambio } : f)));

  const visibles = busqueda.trim()
    ? filas.filter((f) => f.servicio.toLowerCase().includes(busqueda.trim().toLowerCase()))
    : filas;
  const configuradas = filas.filter((f) => f.arancel_gs > 0 || f.excluded).length;

  return (
    <Modal title={`Aranceles · ${insurer.name} ${insurer.plan}`.trim()} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-xs text-zinc-600 leading-relaxed">
          Cuánto paga <strong className="text-zinc-800">{insurer.name}</strong> por cada
          práctica, según su nomenclador. Lo que cargues acá se usa tal cual: el bot le
          dice al paciente cuánto le sale, y la planilla del profesional lo toma para
          liquidar. Vacío = se usa el {insurer.coverage_pct}% general del convenio.
        </p>

        <div className="flex items-center justify-between gap-3">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <input className={`${input} pl-9`} placeholder="Buscar práctica…"
              value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
          </div>
          <span className="text-[11px] text-zinc-500 shrink-0">
            {configuradas} de {filas.length} con arancel
          </span>
        </div>

        {error && <p className="text-red-600 text-xs">{error}</p>}
        {cargando && <p className="text-sm text-zinc-500 py-6 text-center">Cargando…</p>}
        {!cargando && filas.length === 0 && (
          <p className="text-xs text-amber-700 flex items-start gap-2">
            <AlertTriangle size={13} className="shrink-0 mt-0.5" />
            Esta empresa no tiene prácticas cargadas todavía. Cargalas en Servicios &amp;
            Estudios y después volvé acá a ponerles el arancel.
          </p>
        )}

        <div className="space-y-1.5 max-h-[50vh] overflow-y-auto pr-1">
          {visibles.map((f) => (
            <div key={f.service_id}
              className="flex flex-wrap items-center gap-2 bg-zinc-50 border border-zinc-200
                         rounded-lg px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-zinc-800 truncate">{f.servicio}</p>
                <p className="text-[10px] text-zinc-500">
                  lista ₲ {gs(f.precio_lista_gs)}
                  {f.arancel_gs > 0 && f.precio_lista_gs > f.arancel_gs && (
                    <> · al paciente ₲ {gs(f.precio_lista_gs - f.arancel_gs)}</>
                  )}
                </p>
              </div>
              <label className="flex items-center gap-1.5 text-[10px] text-zinc-500 shrink-0">
                <input type="checkbox" checked={f.excluded}
                  onChange={(e) => cambiar(f.service_id, { excluded: e.target.checked })} />
                no cubre
              </label>
              <input
                className={`${input} w-32 text-right tabular-nums`}
                type="number" min={0} step={1000} placeholder="arancel ₲"
                disabled={f.excluded}
                value={f.arancel_gs || ""}
                onChange={(e) => cambiar(f.service_id, { arancel_gs: Number(e.target.value) || 0 })}
                onBlur={() => guardar(f)}
              />
              <span className="w-5 shrink-0 text-center">
                {guardando === f.service_id && <Loader2 size={13} className="animate-spin text-zinc-500" />}
                {guardado === f.service_id && <Check size={14} className="text-emerald-700" />}
              </span>
            </div>
          ))}
        </div>

        <p className="text-[10px] text-zinc-500">
          Se guarda al salir de cada casilla. &quot;No cubre&quot; significa que el paciente lo
          abona particular: esa atención va a la planilla de particulares, no a la de
          {" "}{insurer.name}.
        </p>
      </div>
    </Modal>
  );
}
