import { useEffect, useState } from "react";
import { Check, Copy, KeyRound, ShieldCheck, UserPlus } from "lucide-react";
import { api, type AccesoProfesional, type Doctor } from "../api";
import { input, btnPrimary, Modal } from "../ui";

/**
 * Los accesos al Portal del Profesional: la clínica le da su login a cada
 * médico.
 *
 * Lo hace quien administra la empresa, nunca el profesional. La clave se
 * genera en el servidor y se muestra UNA vez: después solo queda su hash, así
 * que si se pierde hay que reiniciarla, no "buscarla".
 */
export function AccessModal({ companyId, doctors, onClose }: {
  companyId: number; doctors: Doctor[]; onClose: () => void;
}) {
  const [accesos, setAccesos] = useState<AccesoProfesional[]>([]);
  const [doctorId, setDoctorId] = useState(0);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [creando, setCreando] = useState(false);
  const [reciente, setReciente] = useState<{ doctor: string; email: string; clave: string } | null>(null);
  const [copiado, setCopiado] = useState(false);

  const cargar = () => {
    api.portalAccesos(companyId).then(setAccesos).catch(() => setAccesos([]));
  };
  useEffect(cargar, [companyId]);

  const conAcceso = new Set(accesos.map((a) => a.doctor_id));
  const disponibles = doctors.filter((d) => !conAcceso.has(d.id));

  useEffect(() => {
    if (!doctorId && disponibles.length) setDoctorId(disponibles[0].id);
  }, [disponibles, doctorId]);

  const crear = async () => {
    setError(""); setCreando(true); setReciente(null);
    try {
      const r = await api.crearAcceso(companyId, doctorId, email.trim());
      setReciente({ doctor: r.doctor, email: r.email, clave: r.clave_temporal });
      setEmail(""); setDoctorId(0);
      cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear el acceso");
    } finally {
      setCreando(false);
    }
  };

  const copiar = async () => {
    if (!reciente?.clave) return;
    try {
      await navigator.clipboard.writeText(reciente.clave);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      /* clipboard no disponible */
    }
  };

  return (
    <Modal title="Accesos al portal de los profesionales" onClose={onClose}>
      <div className="space-y-5">
        <p className="text-xs text-zinc-600 leading-relaxed">
          Cada profesional con acceso entra con su propio usuario y ve
          <strong className="text-zinc-800"> solo sus pacientes</strong>: el resumen del día y
          la ficha con lo que él recetó. No ve la agenda de la clínica ni los pacientes de
          sus colegas.
        </p>

        <section className="space-y-2">
          <h3 className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
            Con acceso ({accesos.length})
          </h3>
          {accesos.length === 0 && (
            <p className="text-xs text-zinc-500">Todavía no le diste acceso a nadie.</p>
          )}
          {accesos.map((a) => (
            <div key={a.doctor_id}
              className="flex items-center justify-between gap-3 bg-zinc-50 border border-zinc-200 rounded-xl px-3 py-2">
              <span className="text-sm text-zinc-800 flex items-center gap-2">
                <ShieldCheck size={13} className="text-emerald-700" /> {a.doctor}
              </span>
              <span className="text-[11px] text-zinc-500 font-mono">{a.email}</span>
            </div>
          ))}
        </section>

        {reciente && (
          <div className="bg-violet-600/5 border border-violet-300 rounded-xl p-4 space-y-2">
            <p className="text-xs text-cyan-200 font-bold flex items-center gap-1.5">
              <KeyRound size={13} /> Acceso creado para {reciente.doctor}
            </p>
            <p className="text-xs text-zinc-700">
              Usuario: <span className="font-mono">{reciente.email}</span>
            </p>
            {reciente.clave ? (
              <>
                <div className="flex items-center gap-2">
                  <code className="bg-zinc-900/20 px-3 py-1.5 rounded-lg text-sm text-zinc-900 font-mono select-all">
                    {reciente.clave}
                  </code>
                  <button onClick={copiar}
                    className="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1">
                    {copiado ? <><Check size={12} /> copiado</> : <><Copy size={12} /> copiar</>}
                  </button>
                </div>
                <p className="text-[11px] text-amber-700">
                  Esta clave se muestra una sola vez. Pasásela al profesional por un medio
                  privado y pedile que la cambie.
                </p>
              </>
            ) : (
              <p className="text-[11px] text-zinc-600">
                Ese email ya tenía usuario en el sistema: entra con la clave que ya usaba.
              </p>
            )}
          </div>
        )}

        <section className="space-y-3 pt-4 border-t border-zinc-200">
          <h3 className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
            Dar acceso a otro profesional
          </h3>
          {disponibles.length === 0 ? (
            <p className="text-xs text-zinc-500">
              Todos los profesionales cargados ya tienen acceso.
            </p>
          ) : (
            <>
              <select className={input} value={doctorId}
                onChange={(e) => setDoctorId(Number(e.target.value))}>
                {disponibles.map((d) => (
                  <option key={d.id} value={d.id} className="bg-white">{d.name}</option>
                ))}
              </select>
              <input className={input} type="email" placeholder="correo del profesional"
                value={email} onChange={(e) => setEmail(e.target.value)} />
              {error && <p className="text-red-600 text-xs">{error}</p>}
              <button onClick={crear} disabled={creando || !doctorId || !email.includes("@")}
                className={`${btnPrimary} w-full justify-center disabled:opacity-40`}>
                <UserPlus size={14} /> {creando ? "Creando…" : "Crear acceso"}
              </button>
            </>
          )}
        </section>
      </div>
    </Modal>
  );
}
