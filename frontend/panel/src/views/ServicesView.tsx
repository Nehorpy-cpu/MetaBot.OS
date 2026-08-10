import React from "react";
import { useCallback, useEffect, useState } from "react";
import { Globe2, RefreshCw, X } from "lucide-react";
import { api, catalogApi, serviceApi, type Company, type Doctor, type Product, type Service, type ServiceSuggestion } from "../api";
import { card, input, btnPrimary } from "../ui";

export function ServicesView({ company }: { company: Company }) {
  const [services, setServices] = useState<Service[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [suggestions, setSuggestions] = useState<ServiceSuggestion[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [catalogUrl, setCatalogUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState("");
  const [form, setForm] = useState({ name: "", category: "", price_gs: 0, duration_min: 30 });
  const [selDoctors, setSelDoctors] = useState<number[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    serviceApi.list(company.id).then(setServices).catch(() => setServices([]));
    api.listDoctors(company.id).then(setDoctors).catch(() => setDoctors([]));
    serviceApi.suggestions(company.id).then(setSuggestions).catch(() => setSuggestions([]));
    catalogApi.listProducts(company.id).then(setProducts).catch(() => setProducts([]));
  }, [company.id]);
  useEffect(load, [load]);

  const acceptSuggestion = async (s: ServiceSuggestion) => {
    try {
      await serviceApi.create(company.id, {
        name: s.name, category: s.category, price_gs: s.typical_price_gs,
        duration_min: s.duration_min, doctor_ids: [],
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  };

  const importCatalog = async () => {
    setImporting(true);
    setImportMsg("");
    try {
      const r = await catalogApi.importFrom(company.id, catalogUrl.trim());
      setImportMsg(`Importados ${r.imported} nuevos, ${r.updated} actualizados, ${r.with_image} con foto real (${r.method}).`);
      load();
    } catch (err) {
      setImportMsg(err instanceof Error ? err.message : "Error");
    } finally {
      setImporting(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await serviceApi.create(company.id, { ...form, doctor_ids: selDoctors });
      setForm({ name: "", category: "", price_gs: 0, duration_min: 30 });
      setSelDoctors([]);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight">Servicios & Estudios</h2>
        <p className="text-zinc-400 text-sm mt-1">
          El CX Bot usa esta base para responder precios exactos y derivar al profesional correcto. Precio 0 = "consultar".
        </p>
      </div>

      {suggestions.length > 0 && (
        <div className={`${card} p-4 space-y-2`}>
          <p className="text-xs font-bold text-zinc-400 uppercase tracking-widest">
            Sugeridos para tu rubro (cargados por empresas similares — tocá para agregar)
          </p>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button key={s.name} onClick={() => acceptSuggestion(s)}
                className="text-xs bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 px-3 py-1.5 rounded-lg">
                + {s.name}{s.typical_price_gs ? ` (₲ ${s.typical_price_gs.toLocaleString("es-PY")} típico)` : ""}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={submit} className={`${card} p-5 grid grid-cols-1 md:grid-cols-5 gap-3 items-end`}>
        <div className="md:col-span-2">
          <label className="text-xs font-bold text-zinc-400 uppercase block mb-1">Nombre *</label>
          <input className={input} required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Ej. Ecografía abdominal" />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase block mb-1">Categoría</label>
          <input className={input} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
            placeholder="Estudios" />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase block mb-1">Precio (₲)</label>
          <input type="number" min={0} className={input} value={form.price_gs}
            onChange={(e) => setForm({ ...form, price_gs: Number(e.target.value) })} />
        </div>
        <div>
          <label className="text-xs font-bold text-zinc-400 uppercase block mb-1">Minutos</label>
          <input type="number" min={5} max={480} className={input} value={form.duration_min}
            onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })} />
        </div>
        {doctors.length > 0 && (
          <div className="md:col-span-4">
            <label className="text-xs font-bold text-zinc-400 uppercase block mb-1">Atendido por</label>
            <div className="flex flex-wrap gap-2">
              {doctors.map((d) => (
                <label key={d.id} className={`text-xs px-3 py-1.5 rounded-lg border cursor-pointer ${selDoctors.includes(d.id) ? "bg-cyan-500/10 border-cyan-500/50 text-cyan-300" : "bg-white/[0.02] border-white/5 text-zinc-400"}`}>
                  <input type="checkbox" className="hidden" checked={selDoctors.includes(d.id)}
                    onChange={() => setSelDoctors((prev) => prev.includes(d.id) ? prev.filter((x) => x !== d.id) : [...prev, d.id])} />
                  {d.name}
                </label>
              ))}
            </div>
          </div>
        )}
        <button type="submit" className={btnPrimary}>+ Agregar</button>
        {error && <p className="text-red-400 text-xs md:col-span-5">{error}</p>}
      </form>

      <div className={`${card} p-5 overflow-x-auto`}>
        <table className="w-full text-left text-sm text-zinc-300">
          <thead className="text-[10px] uppercase text-zinc-500 border-b border-white/5">
            <tr><th className="pb-2">Servicio</th><th className="pb-2">Categoría</th><th className="pb-2">Precio</th><th className="pb-2">Duración</th><th className="pb-2">Atiende</th><th className="pb-2 text-right">Acciones</th></tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {services.map((s) => (
              <tr key={s.id} className={s.active ? "" : "opacity-40"}>
                <td className="py-2.5 text-white font-medium">{s.name}</td>
                <td className="py-2.5 text-xs">{s.category}</td>
                <td className="py-2.5 font-mono text-cyan-300">{s.price_gs ? `₲ ${s.price_gs.toLocaleString("es-PY")}` : "consultar"}</td>
                <td className="py-2.5 text-xs">{s.duration_min} min</td>
                <td className="py-2.5 text-xs">{s.doctors.map((d) => d.name).join(", ") || "—"}</td>
                <td className="py-2.5 text-right space-x-2">
                  <button onClick={() => serviceApi.update(company.id, s.id, { active: !s.active }).then(load)}
                    className="text-xs bg-white/5 border border-white/10 px-2.5 py-1 rounded-lg text-zinc-300">
                    {s.active ? "Pausar" : "Activar"}
                  </button>
                  <button onClick={() => serviceApi.remove(company.id, s.id).then(load)}
                    className="text-zinc-500 hover:text-red-400"><X size={14} /></button>
                </td>
              </tr>
            ))}
            {!services.length && <tr><td colSpan={6} className="py-8 text-center text-zinc-600 text-xs">Sin servicios cargados.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className={`${card} p-5 space-y-4`}>
        <div>
          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest">Catálogo real ({products.length} productos)</h3>
          <p className="text-xs text-zinc-500 mt-1">
            Importado de la web del negocio con FOTOS REALES. El bot las envía por WhatsApp y las campañas las usan en vez de generar imágenes.
          </p>
        </div>
        <div className="flex gap-2">
          <input className={input} placeholder="https://tu-tienda.com (vacío = web del perfil)" value={catalogUrl}
            onChange={(e) => setCatalogUrl(e.target.value)} />
          <button onClick={importCatalog} disabled={importing} className={btnPrimary}>
            {importing ? <RefreshCw className="animate-spin" size={15} /> : <Globe2 size={15} />} Importar catálogo
          </button>
        </div>
        {importMsg && <p className="text-xs text-cyan-300">{importMsg}</p>}
        {products.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {products.slice(0, 18).map((p) => (
              <div key={p.id} className="bg-white/[0.02] border border-white/5 rounded-xl overflow-hidden">
                {p.image_path ? (
                  <img src={p.image_path} alt={p.name} className="w-full aspect-square object-cover" />
                ) : (
                  <div className="w-full aspect-square flex items-center justify-center text-zinc-700 text-[10px]">sin foto</div>
                )}
                <div className="p-2">
                  <p className="text-[11px] font-bold text-zinc-200 truncate">{p.name}</p>
                  <p className="text-[10px] text-zinc-500">{p.brand} · {p.price_gs ? `₲ ${p.price_gs.toLocaleString("es-PY")}` : "consultar"}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
