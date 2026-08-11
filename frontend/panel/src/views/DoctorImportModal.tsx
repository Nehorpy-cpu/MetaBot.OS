import React from "react";
import { useEffect, useState } from "react";
import { BadgeCheck, FileSpreadsheet, Search, Upload, UserPlus } from "lucide-react";
import { api, type EspecialidadPadron, type ImportPreview, type ImportRow, type RegistryMatch } from "../api";
import { card, input, btnPrimary, Modal } from "../ui";

/**
 * Alta de profesionales sin tipearlos uno por uno.
 *
 * Dos caminos, porque las clínicas llegan de dos formas distintas:
 *   Padrón   → no tienen lista digital: buscan por especialidad o apellido y
 *              marcan a los suyos. Queda verificado con número de certificado.
 *   Planilla → ya tienen su Excel. Se lee como está y se cruza contra el
 *              padrón, pero NADA se guarda hasta que una persona lo confirma.
 */

const SIN_VERIFICAR = "El padrón del CPM es solo de médicos especialistas: "
  + "bioquímicas, odontólogos y veterinarios no figuran, y eso no es un error.";

// De las 4.773 certificaciones del padrón, 4.223 figuran vencidas. Decir
// "vencido" a secas haría dudar de profesionales que están habilitados: la
// fecha es la de NUESTRA copia del padrón, y la renovación puede no estar
// reflejada ahí.
const VENCIDO = "Vencida según la copia del padrón que tenemos. No significa "
  + "que no esté habilitado: puede haber renovado después de esta importación.";

function Certificacion({ m }: { m: RegistryMatch }) {
  const fecha = m.expires_at
    ? new Date(m.expires_at + "T00:00:00").toLocaleDateString("es-PY")
    : "sin fecha";
  return (
    <span
      title={m.vigente ? `Certificación vigente hasta ${fecha}` : `${VENCIDO} (${fecha})`}
      className={`text-[10px] px-2 py-0.5 rounded-full border font-bold whitespace-nowrap ${
        m.vigente
          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
          : "bg-white/[0.03] text-zinc-400 border-white/10"
      }`}>
      Reg. {m.cert_number}{m.vigente ? "" : " · vence " + fecha}
    </span>
  );
}

export function DoctorImportModal({ companyId, onClose, onSaved }: {
  companyId: number; onClose: () => void; onSaved: () => void;
}) {
  const [tab, setTab] = useState<"padron" | "planilla">("padron");
  return (
    <Modal title="Agregar profesionales" onClose={onClose}>
      <div className="flex gap-2 mb-5 border-b border-white/5 pb-3">
        {([["padron", "Buscar en el padrón", Search], ["planilla", "Subir planilla", FileSpreadsheet]] as const).map(
          ([k, label, Icon]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`text-xs font-bold px-3 py-2 rounded-lg flex items-center gap-2 ${
                tab === k ? "bg-cyan-500/10 text-cyan-300 border border-cyan-500/30" : "text-zinc-500 hover:text-zinc-300"
              }`}>
              <Icon size={14} /> {label}
            </button>
          )
        )}
      </div>
      {tab === "padron"
        ? <BuscarPadron companyId={companyId} onSaved={onSaved} />
        : <SubirPlanilla companyId={companyId} onSaved={onSaved} onClose={onClose} />}
    </Modal>
  );
}

// --- Camino 1: buscar en el padrón ---

function BuscarPadron({ companyId, onSaved }: { companyId: number; onSaved: () => void }) {
  const [q, setQ] = useState("");
  const [especialidad, setEspecialidad] = useState("");
  const [opciones, setOpciones] = useState<EspecialidadPadron[]>([]);
  const [resultados, setResultados] = useState<RegistryMatch[] | null>(null);
  const [total, setTotal] = useState(0);
  const [buscando, setBuscando] = useState(false);
  const [horarios, setHorarios] = useState<Record<number, string>>({});
  const [agregados, setAgregados] = useState<Record<number, string>>({});

  useEffect(() => {
    api.especialidadesPadron(companyId)
      .then((r) => setOpciones(r.especialidades))
      .catch(() => setOpciones([]));
  }, [companyId]);

  const buscar = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!q.trim() && !especialidad) return;
    setBuscando(true);
    try {
      const r = await api.buscarPadron(companyId, q, especialidad);
      setResultados(r.resultados);
      setTotal(r.total);
    } finally {
      setBuscando(false);
    }
  };

  const agregar = async (m: RegistryMatch) => {
    try {
      await api.altaDesdePadron(companyId, { registry_id: m.registry_id, schedule: horarios[m.registry_id] ?? "" });
      setAgregados({ ...agregados, [m.registry_id]: "ok" });
      onSaved();
    } catch (err) {
      setAgregados({ ...agregados, [m.registry_id]: err instanceof Error ? err.message : "Error" });
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-500 leading-relaxed">
        Marcá solo a los profesionales que <strong className="text-zinc-300">realmente atienden</strong> en tu
        institución. El padrón confirma la certificación; no dice dónde trabaja cada uno.
      </p>

      <form onSubmit={buscar} className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2">
        <input className={input} placeholder="Apellido o nombre" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className={input} value={especialidad} onChange={(e) => setEspecialidad(e.target.value)}>
          <option value="" className="bg-[#090b10]">Todas las especialidades</option>
          {opciones.map((e) => (
            <option key={e.clave} value={e.clave} className="bg-[#090b10]">
              {e.etiqueta} ({e.cantidad})
            </option>
          ))}
        </select>
        <button type="submit" disabled={buscando || (!q.trim() && !especialidad)} className={btnPrimary}>
          <Search size={14} /> Buscar
        </button>
      </form>

      {resultados !== null && !resultados.length && (
        <p className="text-xs text-zinc-500 py-6 text-center">
          No hay coincidencias. Si el profesional no es médico especialista, cargalo a mano: {SIN_VERIFICAR}
        </p>
      )}

      {resultados !== null && total > resultados.length && (
        <p className="text-xs text-amber-400/90">
          Mostrando {resultados.length} de {total}, los de certificación más vigente primero.
          Agregá el apellido para acotar la lista.
        </p>
      )}

      <div className="space-y-2 max-h-[45vh] overflow-y-auto">
        {(resultados ?? []).map((m) => (
          <div key={m.registry_id} className={`${card} p-3 flex flex-col md:flex-row md:items-center gap-3`}>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-zinc-100 truncate">{m.full_name}</p>
              <p className="text-[11px] text-cyan-300">{m.specialty}</p>
            </div>
            <Certificacion m={m} />
            <input className={`${input} md:w-48`} placeholder="Horario en tu clínica"
              value={horarios[m.registry_id] ?? ""}
              onChange={(e) => setHorarios({ ...horarios, [m.registry_id]: e.target.value })} />
            {agregados[m.registry_id] === "ok" ? (
              <span className="text-xs text-emerald-400 font-bold flex items-center gap-1 whitespace-nowrap">
                <BadgeCheck size={14} /> Agregado
              </span>
            ) : (
              <button onClick={() => agregar(m)}
                className="text-xs bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 px-3 py-2 rounded-lg flex items-center gap-1 whitespace-nowrap">
                <UserPlus size={13} /> Agregar
              </button>
            )}
            {agregados[m.registry_id] && agregados[m.registry_id] !== "ok" && (
              <span className="text-xs text-amber-400">{agregados[m.registry_id]}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Camino 2: subir la planilla que ya tienen ---

function SubirPlanilla({ companyId, onSaved, onClose }: {
  companyId: number; onSaved: () => void; onClose: () => void;
}) {
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set());
  const [filas, setFilas] = useState<ImportRow[]>([]);
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  const subir = async (archivo: File) => {
    setError(""); setCargando(true);
    try {
      const r = await api.previsualizarPlanilla(companyId, archivo);
      setPreview(r);
      setFilas(r.filas);
      // Se marcan por defecto las que se pueden cargar; las ya cargadas no.
      setMarcadas(new Set(r.filas.map((f, i) => (f.ya_cargado ? -1 : i)).filter((i) => i >= 0)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo leer el archivo");
    } finally {
      setCargando(false);
    }
  };

  const confirmar = async () => {
    const seleccion = filas.filter((_, i) => marcadas.has(i));
    if (!seleccion.length) return;
    setCargando(true);
    try {
      const r = await api.confirmarPlanilla(companyId, seleccion);
      onSaved();
      alert(
        `${r.creados.length} profesionales cargados.\n`
        + `${r.verificados} verificados en el padrón, ${r.no_figuran} sin coincidencia.\n`
        + (r.omitidos.length ? `${r.omitidos.length} omitidos (ya estaban).` : "")
      );
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setCargando(false);
    }
  };

  const editar = (i: number, campo: keyof ImportRow, valor: string) =>
    setFilas(filas.map((f, j) => (j === i ? { ...f, [campo]: valor } : f)));

  if (!preview) {
    return (
      <div className="space-y-4">
        <p className="text-xs text-zinc-500 leading-relaxed">
          Subí la lista como la tengas: Excel (.xlsx) o CSV. No hace falta renombrar columnas —
          se reconocen "Nombre", "Profesional", "Médico", "Especialidad", "Horario" y sus variantes.
        </p>
        <label className="block border-2 border-dashed border-white/10 hover:border-cyan-500/40 rounded-2xl p-10 text-center cursor-pointer transition-colors">
          <Upload size={28} className="mx-auto text-zinc-600 mb-3" />
          <span className="text-sm text-zinc-400">
            {cargando ? "Leyendo la planilla…" : "Elegí el archivo (.xlsx o .csv, hasta 5 MB)"}
          </span>
          <input type="file" accept=".csv,.xlsx,.xlsm,text/csv" className="hidden" disabled={cargando}
            onChange={(e) => e.target.files?.[0] && subir(e.target.files[0])} />
        </label>
        {error && <p className="text-red-400 text-xs">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4 text-xs text-zinc-400">
        <span><strong className="text-white">{preview.total}</strong> en el archivo</span>
        <span><strong className="text-emerald-400">{preview.en_padron}</strong> hallados en el padrón</span>
        {preview.ya_cargados > 0 && (
          <span><strong className="text-amber-400">{preview.ya_cargados}</strong> ya cargados</span>
        )}
        <span className="text-zinc-600">Todavía no se guardó nada.</span>
      </div>

      <div className="space-y-2 max-h-[45vh] overflow-y-auto">
        {filas.map((f, i) => (
          <div key={i} className={`${card} p-3 flex flex-col md:flex-row md:items-center gap-3 ${f.ya_cargado ? "opacity-50" : ""}`}>
            <input type="checkbox" checked={marcadas.has(i)} disabled={f.ya_cargado}
              onChange={(e) => {
                const s = new Set(marcadas);
                e.target.checked ? s.add(i) : s.delete(i);
                setMarcadas(s);
              }}
              className="accent-cyan-500 w-4 h-4 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-zinc-100 truncate">{f.name}</p>
              <p className="text-[11px] text-cyan-300">{f.specialty || "sin especialidad"}</p>
              {f.ya_cargado && <p className="text-[10px] text-amber-400">Ya está en tu lista</p>}
              {!f.ya_cargado && !f.padron && f.sugerencias.length > 0 && (
                <p className="text-[10px] text-zinc-500 mt-1">
                  ¿Será {f.sugerencias.map((s) => s.full_name).join(" o ")}? Revisá cómo está escrito.
                </p>
              )}
            </div>
            {f.padron
              ? <Certificacion m={f.padron} />
              : <span className="text-[10px] px-2 py-0.5 rounded-full border bg-white/[0.03] text-zinc-500 border-white/10" title={SIN_VERIFICAR}>
                  sin coincidencia
                </span>}
            <input className={`${input} md:w-48`} placeholder="Horario" value={f.schedule}
              onChange={(e) => editar(i, "schedule", e.target.value)} />
          </div>
        ))}
      </div>

      {error && <p className="text-red-400 text-xs">{error}</p>}
      <div className="flex justify-between items-center pt-3 border-t border-white/5">
        <button onClick={() => { setPreview(null); setFilas([]); setError(""); }}
          className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Elegir otro archivo</button>
        <button onClick={confirmar} disabled={cargando || !marcadas.size} className={btnPrimary}>
          <UserPlus size={14} /> Cargar {marcadas.size} profesionales
        </button>
      </div>
    </div>
  );
}
