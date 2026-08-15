/**
 * El panel del CFO de Finanzas.
 *
 * Es donde una persona hace las cuatro cosas que el bot NO puede hacer solo,
 * y no las puede hacer por diseño:
 *
 *  - autorizar un número (dar acceso es exactamente lo que un atacante querría
 *    conseguir por chat);
 *  - aprobar una métrica (aprobar es un acto administrativo con nombre y
 *    fecha, no una frase en una conversación);
 *  - conectar una fuente de datos;
 *  - mirar y borrar lo que el sistema recuerda.
 *
 * Todo lo que se muestra acá sale de la API. La pantalla no calcula ni un
 * monto: si mostrara un total sumado en el navegador, ese número no tendría
 * definición, ni versión, ni fecha de corte, que es justo lo que el módulo
 * entero existe para garantizar.
 */
import { useEffect, useState } from "react";
import {
  AlertTriangle, Check, Copy, Database, FileText, KeyRound, Link2,
  Plus, Shield, Trash2, Upload, X,
} from "lucide-react";

import {
  ApiError, cfoApi, CfoConector, CfoFuente, CfoIdentidad, CfoInforme,
  CfoInformeCreado, CfoMemoria, CfoMetrica, FUENTES_ES, RIESGO_ES,
} from "../api";
import { btnPrimary, card, input, Modal } from "../ui";

type Solapa = "accesos" | "metricas" | "datos" | "informes" | "memoria";

const SOLAPAS: { id: Solapa; label: string; Icon: typeof Shield }[] = [
  { id: "accesos", label: "Quién pregunta", Icon: Shield },
  { id: "metricas", label: "Métricas", Icon: FileText },
  { id: "datos", label: "Datos", Icon: Database },
  { id: "informes", label: "Informes", Icon: Link2 },
  { id: "memoria", label: "Memoria", Icon: KeyRound },
];

/** El motivo, sea texto plano o el objeto estructurado del backend. */
function motivoDe(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { motivo?: string; renglones?: string[] } | string;
    if (typeof d === "string") return d;
    if (d?.motivo) {
      return d.renglones?.length
        ? `${d.motivo}\n\n${d.renglones.join("\n")}`
        : d.motivo;
    }
  }
  return e instanceof Error ? e.message : "Algo salió mal.";
}

const fecha = (s: string | null) =>
  s ? new Date(s).toLocaleString("es-PY", { dateStyle: "short", timeStyle: "short" }) : "—";

function Aviso({ texto, onCerrar }: { texto: string; onCerrar: () => void }) {
  return (
    <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <pre className="flex-1 whitespace-pre-wrap font-sans">{texto}</pre>
      <button onClick={onCerrar} className="text-amber-700 hover:text-amber-800">
        <X size={14} />
      </button>
    </div>
  );
}

export function CfoView({ companyId }: { companyId: number }) {
  const [solapa, setSolapa] = useState<Solapa>("accesos");
  const [error, setError] = useState("");

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-xl font-bold text-zinc-900">CFO de Finanzas</h1>
        <p className="mt-1 text-xs text-zinc-500">
          El dueño pregunta por WhatsApp; los números salen calculados del
          servidor, con su definición y la fecha de sus datos.
        </p>
      </div>

      <div className="mb-5 flex flex-wrap gap-2">
        {SOLAPAS.map(({ id, label, Icon }) => (
          <button
            key={id}
            onClick={() => { setSolapa(id); setError(""); }}
            className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold transition-all ${
              solapa === id
                ? "border border-zinc-200 bg-zinc-50 text-zinc-900"
                : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800"
            }`}
          >
            <Icon size={14} className={solapa === id ? "text-violet-600" : ""} />
            {label}
          </button>
        ))}
      </div>

      {error && <Aviso texto={error} onCerrar={() => setError("")} />}

      {solapa === "accesos" && <Accesos companyId={companyId} onError={setError} />}
      {solapa === "metricas" && <Metricas companyId={companyId} onError={setError} />}
      {solapa === "datos" && <Datos companyId={companyId} onError={setError} />}
      {solapa === "informes" && <Informes companyId={companyId} onError={setError} />}
      {solapa === "memoria" && <Memoria companyId={companyId} onError={setError} />}
    </div>
  );
}

type Props = { companyId: number; onError: (s: string) => void };

// ─── Quién pregunta ──────────────────────────────────────────────────────

function Accesos({ companyId, onError }: Props) {
  const [filas, setFilas] = useState<CfoIdentidad[]>([]);
  const [alta, setAlta] = useState(false);
  const [pinDe, setPinDe] = useState<CfoIdentidad | null>(null);
  const [form, setForm] = useState({ phone: "", nombre: "", sensibilidad_max: "baja" });
  const [pin, setPin] = useState("");

  const cargar = () =>
    cfoApi.identidades(companyId).then(setFilas).catch((e) => onError(motivoDe(e)));
  useEffect(() => { cargar(); }, [companyId]);

  const crear = async () => {
    try {
      await cfoApi.crearIdentidad(companyId, form);
      setAlta(false);
      setForm({ phone: "", nombre: "", sensibilidad_max: "baja" });
      cargar();
    } catch (e) { onError(motivoDe(e)); }
  };

  const guardarPin = async () => {
    if (!pinDe) return;
    try {
      await cfoApi.ponerPin(companyId, pinDe.id, pin);
      setPinDe(null);
      setPin("");
      cargar();
    } catch (e) { onError(motivoDe(e)); }
  };

  return (
    <div className={`${card} p-5`}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <p className="max-w-2xl text-xs text-zinc-500">
          Un WhatsApp no es una identidad: se clona, se hereda con un chip
          reciclado y se pierde en un taxi. Por eso lo sensible pide además un
          PIN, y el permiso es <strong className="text-zinc-700">por
          empresa</strong>, no por número.
        </p>
        <button onClick={() => setAlta(true)} className={btnPrimary}>
          <Plus size={15} /> Autorizar número
        </button>
      </div>

      {filas.length === 0 ? (
        <p className="py-8 text-center text-sm text-zinc-500">
          Nadie autorizado todavía. Sin esto, el CFO no le contesta a nadie.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="pb-2">Teléfono</th>
              <th className="pb-2">Nombre</th>
              <th className="pb-2">Hasta dónde ve</th>
              <th className="pb-2">PIN</th>
              <th className="pb-2">Último uso</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => (
              <tr key={f.id} className="border-t border-zinc-200">
                <td className="py-2.5 font-mono text-xs text-zinc-700">{f.phone}</td>
                <td className="py-2.5 text-zinc-600">{f.nombre || "—"}</td>
                <td className="py-2.5">
                  <span className="rounded-lg bg-zinc-50 px-2 py-0.5 text-[11px] text-zinc-700">
                    {RIESGO_ES[f.sensibilidad_max]}
                  </span>
                </td>
                <td className="py-2.5">
                  {f.tiene_pin ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700">
                      <Check size={12} /> configurado
                    </span>
                  ) : (
                    <span className="text-[11px] text-amber-700">sin PIN</span>
                  )}
                  {f.pin_bloqueado && (
                    <span className="ml-2 text-[11px] text-rose-600">bloqueado</span>
                  )}
                </td>
                <td className="py-2.5 text-[11px] text-zinc-500">{fecha(f.ultimo_uso_at)}</td>
                <td className="py-2.5 text-right">
                  <button
                    onClick={() => { setPinDe(f); setPin(""); }}
                    className="mr-3 text-[11px] text-violet-600 hover:text-violet-700"
                  >
                    {f.tiene_pin ? "Cambiar PIN" : "Poner PIN"}
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        await cfoApi.editarIdentidad(companyId, f.id, { activo: !f.activo });
                        cargar();
                      } catch (e) { onError(motivoDe(e)); }
                    }}
                    className="text-[11px] text-zinc-500 hover:text-zinc-800"
                  >
                    {f.activo ? "Desactivar" : "Activar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {alta && (
        <Modal title="Autorizar un número" onClose={() => setAlta(false)}>
          <div className="space-y-3">
            <input
              className={input}
              placeholder="Teléfono con código de país (595981…)"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
            <input
              className={input}
              placeholder="Nombre de la persona"
              value={form.nombre}
              onChange={(e) => setForm({ ...form, nombre: e.target.value })}
            />
            <select
              className={input}
              value={form.sensibilidad_max}
              onChange={(e) => setForm({ ...form, sensibilidad_max: e.target.value })}
            >
              <option value="baja">Básico — ventas y metas</option>
              <option value="media">Sensible — márgenes, gastos, cobranzas</option>
              <option value="alta">Crítico — caja, bancos, utilidad</option>
            </select>
            <p className="text-[11px] text-zinc-500">
              Nace <strong className="text-zinc-700">sin PIN</strong>, así que
              todavía no ve nada sensible aunque le pongas un nivel alto. El PIN
              se configura después, desde acá.
            </p>
            <button onClick={crear} className={btnPrimary}>Autorizar</button>
          </div>
        </Modal>
      )}

      {pinDe && (
        <Modal title={`PIN de ${pinDe.nombre || pinDe.phone}`} onClose={() => setPinDe(null)}>
          <div className="space-y-3">
            <input
              className={input}
              type="password"
              inputMode="numeric"
              placeholder="4 a 12 dígitos"
              value={pin}
              onChange={(e) => setPin(e.target.value)}
            />
            <p className="text-[11px] text-zinc-500">
              Se guarda hasheado y no vuelve a salir de la base: el panel te dice
              si tiene PIN, nunca cuál es. Decíselo por un canal distinto del
              WhatsApp que estás protegiendo.
            </p>
            <button onClick={guardarPin} className={btnPrimary}>Guardar</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ─── Métricas ────────────────────────────────────────────────────────────

function Metricas({ companyId, onError }: Props) {
  const [filas, setFilas] = useState<CfoMetrica[]>([]);
  const [detalle, setDetalle] = useState<CfoMetrica | null>(null);

  const cargar = () =>
    cfoApi.metricas(companyId).then(setFilas).catch((e) => onError(motivoDe(e)));
  useEffect(() => { cargar(); }, [companyId]);

  return (
    <div className={`${card} p-5`}>
      <p className="mb-4 max-w-2xl text-xs text-zinc-500">
        "Ventas" no quiere decir lo mismo para vos, para tu contador y para la
        aseguradora. Acá se aprueba <strong className="text-zinc-700">qué
        significa cada número</strong> — con tu nombre y la fecha —, y recién
        entonces el CFO puede contestarlo.
      </p>

      <div className="grid gap-3 md:grid-cols-2">
        {filas.map((m) => {
          const activa = m.estado === "activa";
          return (
            <div key={m.clave} className="rounded-xl border border-zinc-200 bg-zinc-50 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-zinc-900">{m.nombre}</h3>
                  <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{m.formula}</p>
                </div>
                <span
                  className={`shrink-0 rounded-lg px-2 py-0.5 text-[10px] font-semibold ${
                    activa
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-zinc-50 text-zinc-500"
                  }`}
                >
                  {activa ? `activa v${m.version}` : m.estado}
                </span>
              </div>

              {m.faltan.length > 0 && (
                <p className="mt-3 rounded-lg border-l-2 border-amber-500 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-700">
                  Falta conectar: {m.faltan.map((f) => FUENTES_ES[f] || f).join(", ")}
                </p>
              )}

              <div className="mt-3 flex items-center gap-3">
                <button
                  onClick={() => setDetalle(m)}
                  className="text-[11px] text-zinc-500 hover:text-zinc-800"
                >
                  Ver definición
                </button>
                {activa ? (
                  <button
                    onClick={async () => {
                      try { await cfoApi.deprecar(companyId, m.clave); cargar(); }
                      catch (e) { onError(motivoDe(e)); }
                    }}
                    className="text-[11px] text-zinc-500 hover:text-rose-600"
                  >
                    Dar de baja
                  </button>
                ) : (
                  <button
                    onClick={async () => {
                      try { await cfoApi.aprobar(companyId, m.clave, m.version); cargar(); }
                      catch (e) { onError(motivoDe(e)); }
                    }}
                    className="text-[11px] font-semibold text-violet-600 hover:text-violet-700"
                  >
                    Aprobar v{m.version}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {detalle && (
        <Modal title={detalle.nombre} onClose={() => setDetalle(null)}>
          <dl className="space-y-4 text-sm">
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-500">Cómo se calcula</dt>
              <dd className="mt-1 text-zinc-700">{detalle.formula}</dd>
            </div>
            {detalle.excluye && (
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-zinc-500">Qué NO entra</dt>
                <dd className="mt-1 text-zinc-700">{detalle.excluye}</dd>
              </div>
            )}
            {detalle.notas_contables && (
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-zinc-500">Para tener en cuenta</dt>
                <dd className="mt-1 text-amber-700">{detalle.notas_contables}</dd>
              </div>
            )}
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-500">De dónde sale</dt>
              <dd className="mt-1 text-zinc-700">
                {detalle.fuentes.map((f) => FUENTES_ES[f] || f).join(", ")}
              </dd>
            </div>
            {detalle.vigente_desde && (
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-zinc-500">Rige desde</dt>
                <dd className="mt-1 text-zinc-700">{detalle.vigente_desde}</dd>
              </div>
            )}
          </dl>
        </Modal>
      )}
    </div>
  );
}

// ─── Datos ───────────────────────────────────────────────────────────────

function Datos({ companyId, onError }: Props) {
  const [conectores, setConectores] = useState<CfoConector[]>([]);
  const [fuentes, setFuentes] = useState<CfoFuente[]>([]);
  const [alta, setAlta] = useState(false);
  const [form, setForm] = useState({ fuente: "ventas", tipo: "csv", nombre: "" });
  const [subiendo, setSubiendo] = useState(0);
  const [ok, setOk] = useState("");

  const cargar = () => {
    cfoApi.conectores(companyId).then(setConectores).catch((e) => onError(motivoDe(e)));
    cfoApi.fuentes(companyId).then(setFuentes).catch(() => undefined);
  };
  useEffect(() => { cargar(); }, [companyId]);

  const subir = async (id: number, archivo: File) => {
    setSubiendo(id);
    setOk("");
    try {
      const r = await cfoApi.cargarPlanilla(companyId, id, archivo);
      setOk(`Se leyeron ${r.leidas} filas: ${r.nuevas} nuevas, ${r.actualizadas} actualizadas.`);
      cargar();
    } catch (e) { onError(motivoDe(e)); }
    finally { setSubiendo(0); }
  };

  return (
    <div className="space-y-4">
      <div className={`${card} p-5`}>
        <h3 className="mb-1 text-sm font-semibold text-zinc-900">Qué puede contestar hoy</h3>
        <p className="mb-4 text-xs text-zinc-500">
          Una fuente cuenta cuando <strong className="text-zinc-700">trajo datos
          al menos una vez</strong>. Un conector recién creado y vacío haría que
          el CFO conteste ₲ 0 con cara de certeza.
        </p>
        <div className="flex flex-wrap gap-2">
          {fuentes.map((f) => (
            <span
              key={f.fuente}
              title={f.corte ? `Datos hasta ${fecha(f.corte)}` : "Sin datos cargados"}
              className={`rounded-lg px-2.5 py-1 text-[11px] ${
                f.disponible
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-zinc-50 text-zinc-500"
              }`}
            >
              {FUENTES_ES[f.fuente] || f.fuente}
              {f.interna && " (ya incluida)"}
            </span>
          ))}
        </div>
      </div>

      <div className={`${card} p-5`}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <p className="max-w-2xl text-xs text-zinc-500">
            Exportá de tu sistema de facturación y subí el archivo. Acepta el
            CSV que sale de Excel en castellano: separador <code>;</code>,
            montos <code>1.234.567</code> y fechas <code>dd/mm/aaaa</code>.
          </p>
          <button onClick={() => setAlta(true)} className={btnPrimary}>
            <Plus size={15} /> Conectar fuente
          </button>
        </div>

        {ok && (
          <p className="mb-3 rounded-xl border border-emerald-300 bg-emerald-50 p-2.5 text-xs text-emerald-700">
            {ok}
          </p>
        )}

        {conectores.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-500">
            Sin fuentes conectadas. El CFO solo puede usar lo que ya está en el
            sistema: atenciones, prestaciones y convenios.
          </p>
        ) : (
          <div className="space-y-2">
            {conectores.map((c) => (
              <div
                key={c.id}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3"
              >
                <div className="min-w-48 flex-1">
                  <p className="text-sm font-medium text-zinc-900">{c.nombre}</p>
                  <p className="text-[11px] text-zinc-500">
                    {FUENTES_ES[c.fuente] || c.fuente} · {c.filas_totales} filas ·
                    {c.ultima_sync ? ` datos al ${fecha(c.ultima_sync)}` : " nunca cargado"}
                  </p>
                  {c.ultimo_error && (
                    <p className="mt-1 text-[11px] text-rose-600">{c.ultimo_error}</p>
                  )}
                </div>

                <span
                  className={`rounded-lg px-2 py-0.5 text-[10px] font-semibold ${
                    c.habilita_la_fuente
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {c.habilita_la_fuente ? "en uso" : "sin datos"}
                </span>

                <label className="cursor-pointer text-[11px] text-violet-600 hover:text-violet-700">
                  {subiendo === c.id ? "Subiendo…" : (
                    <span className="inline-flex items-center gap-1">
                      <Upload size={12} /> Subir planilla
                    </span>
                  )}
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) subir(c.id, f);
                      e.target.value = "";
                    }}
                  />
                </label>

                <button
                  onClick={async () => {
                    try {
                      await cfoApi.editarConector(companyId, c.id, { activo: !c.activo });
                      cargar();
                    } catch (e) { onError(motivoDe(e)); }
                  }}
                  className="text-[11px] text-zinc-500 hover:text-zinc-800"
                >
                  {c.activo ? "Apagar" : "Encender"}
                </button>

                <button
                  onClick={async () => {
                    if (!confirm(`¿Borrar "${c.nombre}" y todos sus datos?`)) return;
                    try { await cfoApi.borrarConector(companyId, c.id); cargar(); }
                    catch (e) { onError(motivoDe(e)); }
                  }}
                  className="text-zinc-500 hover:text-rose-600"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {alta && (
        <Modal title="Conectar una fuente de datos" onClose={() => setAlta(false)}>
          <div className="space-y-3">
            <select
              className={input}
              value={form.fuente}
              onChange={(e) => setForm({ ...form, fuente: e.target.value })}
            >
              {Object.entries(FUENTES_ES)
                .filter(([k]) => k !== "interna")
                .map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input
              className={input}
              placeholder="Nombre (ej: Sistema de facturación, Sucursal centro)"
              value={form.nombre}
              onChange={(e) => setForm({ ...form, nombre: e.target.value })}
            />
            <p className="text-[11px] text-zinc-500">
              Por ahora solo planilla (CSV). Las columnas son:{" "}
              <code className="text-zinc-600">fecha, monto, categoria, referencia</code>.
              Si una fila no se entiende <strong className="text-zinc-700">no se
              carga ninguna</strong> y te decimos cuál: cargar 98 de 100 da un
              total que se ve bien y cierra mal.
            </p>
            <button
              onClick={async () => {
                try {
                  await cfoApi.crearConector(companyId, form);
                  setAlta(false);
                  setForm({ fuente: "ventas", tipo: "csv", nombre: "" });
                  cargar();
                } catch (e) { onError(motivoDe(e)); }
              }}
              className={btnPrimary}
            >
              Crear
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ─── Informes ────────────────────────────────────────────────────────────

function Informes({ companyId, onError }: Props) {
  const [filas, setFilas] = useState<CfoInforme[]>([]);
  const [metricas, setMetricas] = useState<CfoMetrica[]>([]);
  const [alta, setAlta] = useState(false);
  const [recien, setRecien] = useState<CfoInformeCreado | null>(null);
  const [copiado, setCopiado] = useState(false);

  const hoy = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    titulo: "", desde: hoy.slice(0, 8) + "01", hasta: hoy,
    metricas: [] as string[], un_solo_uso: false, horas_de_vigencia: 24,
  });

  const cargar = () =>
    cfoApi.informes(companyId).then(setFilas).catch((e) => onError(motivoDe(e)));
  useEffect(() => {
    cargar();
    cfoApi.metricas(companyId)
      .then((m) => setMetricas(m.filter((x) => x.estado === "activa")))
      .catch(() => undefined);
  }, [companyId]);

  return (
    <div className={`${card} p-5`}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <p className="max-w-2xl text-xs text-zinc-500">
          El informe queda <strong className="text-zinc-700">congelado</strong>:
          si lo reenviás a tu contador tres días después, los dos ven el mismo
          número. El enlace vence, se puede revocar y se muestra una sola vez.
        </p>
        <button onClick={() => setAlta(true)} className={btnPrimary}>
          <Plus size={15} /> Nuevo informe
        </button>
      </div>

      {filas.length === 0 ? (
        <p className="py-8 text-center text-sm text-zinc-500">Todavía no emitiste ninguno.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="pb-2">Informe</th>
              <th className="pb-2">Período</th>
              <th className="pb-2">Enlaces vivos</th>
              <th className="pb-2">Aperturas</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => (
              <tr key={f.id} className="border-t border-zinc-200">
                <td className="py-2.5 text-zinc-700">{f.titulo || `Informe ${f.id}`}</td>
                <td className="py-2.5 text-[11px] text-zinc-500">{f.desde} al {f.hasta}</td>
                <td className="py-2.5">
                  <span className={f.enlaces_vigentes ? "text-emerald-700" : "text-zinc-500"}>
                    {f.enlaces_vigentes}
                  </span>
                </td>
                <td className="py-2.5 text-[11px] text-zinc-500">
                  {f.aperturas} {f.ultima_apertura && `· ${fecha(f.ultima_apertura)}`}
                </td>
                <td className="py-2.5 text-right">
                  {f.enlaces_vigentes > 0 && (
                    <button
                      onClick={async () => {
                        if (!confirm("¿Revocar los enlaces de este informe?")) return;
                        try { await cfoApi.revocarInforme(companyId, f.id); cargar(); }
                        catch (e) { onError(motivoDe(e)); }
                      }}
                      className="text-[11px] text-zinc-500 hover:text-rose-600"
                    >
                      Revocar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {alta && (
        <Modal title="Nuevo informe" onClose={() => setAlta(false)}>
          <div className="space-y-3">
            <input
              className={input}
              placeholder="Título (ej: Agosto a la fecha)"
              value={form.titulo}
              onChange={(e) => setForm({ ...form, titulo: e.target.value })}
            />
            <div className="grid grid-cols-2 gap-3">
              <input type="date" className={input} value={form.desde}
                onChange={(e) => setForm({ ...form, desde: e.target.value })} />
              <input type="date" className={input} value={form.hasta}
                onChange={(e) => setForm({ ...form, hasta: e.target.value })} />
            </div>

            <div>
              <p className="mb-2 text-[10px] uppercase tracking-wider text-zinc-500">
                Qué incluir
              </p>
              {metricas.length === 0 ? (
                <p className="text-xs text-amber-700">
                  No hay métricas aprobadas todavía. Aprobá alguna en la solapa
                  Métricas.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {metricas.map((m) => (
                    <label key={m.clave} className="flex items-center gap-2 text-xs text-zinc-700">
                      <input
                        type="checkbox"
                        checked={form.metricas.includes(m.clave)}
                        onChange={(e) =>
                          setForm({
                            ...form,
                            metricas: e.target.checked
                              ? [...form.metricas, m.clave]
                              : form.metricas.filter((k) => k !== m.clave),
                          })
                        }
                      />
                      {m.nombre}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <label className="flex items-center gap-2 text-xs text-zinc-700">
              <input
                type="checkbox"
                checked={form.un_solo_uso}
                onChange={(e) => setForm({ ...form, un_solo_uso: e.target.checked })}
              />
              Que se pueda abrir una sola vez
            </label>
            <p className="text-[11px] text-zinc-500">
              Para lo más sensible: si el enlace se reenvía por un grupo, ya no
              abre.
            </p>

            <button
              disabled={form.metricas.length === 0}
              onClick={async () => {
                try {
                  const r = await cfoApi.crearInforme(companyId, form);
                  setAlta(false);
                  setRecien(r);
                  setCopiado(false);
                  cargar();
                } catch (e) { onError(motivoDe(e)); }
              }}
              className={btnPrimary}
            >
              Emitir
            </button>
          </div>
        </Modal>
      )}

      {recien && (
        <Modal title="El enlace del informe" onClose={() => setRecien(null)}>
          <div className="space-y-3">
            <p className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
              {recien.aviso} Copialo ahora: no se puede volver a ver, hay que
              emitir uno nuevo.
            </p>
            <div className="flex gap-2">
              <input className={input} readOnly value={recien.enlace} />
              <button
                onClick={() => {
                  navigator.clipboard?.writeText(recien.enlace);
                  setCopiado(true);
                }}
                className={btnPrimary}
              >
                {copiado ? <Check size={15} /> : <Copy size={15} />}
                {copiado ? "Copiado" : "Copiar"}
              </button>
            </div>
            <p className="text-[11px] text-zinc-500">
              Vence en {recien.vence_en_horas} h
              {recien.un_solo_uso && " y sirve una sola vez"}.
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ─── Memoria ─────────────────────────────────────────────────────────────

function Memoria({ companyId, onError }: Props) {
  const [filas, setFilas] = useState<CfoMemoria[]>([]);

  const cargar = () =>
    cfoApi.memoria(companyId).then(setFilas).catch((e) => onError(motivoDe(e)));
  useEffect(() => { cargar(); }, [companyId]);

  return (
    <div className={`${card} p-5`}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <p className="max-w-2xl text-xs text-zinc-500">
          Lo que el CFO fue aprendiendo de tu negocio para no volver a
          preguntártelo. Nunca guarda montos ni permisos: los accesos se dan
          acá, en "Quién pregunta".
        </p>
        {filas.length > 0 && (
          <button
            onClick={async () => {
              if (!confirm("¿Borrar TODO lo que el sistema recuerda de esta empresa?")) return;
              try { await cfoApi.borrarTodaLaMemoria(companyId); cargar(); }
              catch (e) { onError(motivoDe(e)); }
            }}
            className="shrink-0 rounded-xl border border-zinc-200 px-3 py-2 text-xs font-semibold text-zinc-600 hover:border-rose-400 hover:text-rose-600"
          >
            Borrar todo
          </button>
        )}
      </div>

      {filas.length === 0 ? (
        <p className="py-8 text-center text-sm text-zinc-500">
          Todavía no recuerda nada. Se va llenando solo cuando le contás cosas
          de tu negocio por WhatsApp.
        </p>
      ) : (
        <div className="space-y-2">
          {filas.map((m) => (
            <div
              key={m.id}
              className="flex items-start gap-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3"
            >
              <div className="flex-1">
                <p className="text-sm text-zinc-800">{m.valor}</p>
                <p className="mt-1 text-[11px] text-zinc-500">
                  {m.clave} · {m.tipo} · lo cargó {m.fuente === "panel" ? "el panel" : "una persona por chat"}
                  {m.phone && ` · solo para ${m.phone}`}
                  {m.vence && ` · vence ${fecha(m.vence)}`}
                </p>
              </div>
              <button
                onClick={async () => {
                  try { await cfoApi.borrarMemoria(companyId, m.id); cargar(); }
                  catch (e) { onError(motivoDe(e)); }
                }}
                className="text-zinc-500 hover:text-rose-600"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
