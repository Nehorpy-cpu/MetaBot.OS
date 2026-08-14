import { useEffect, useState } from "react";
import {
  Activity, Bot, Boxes, Building2, Calendar, ChevronDown, LayoutDashboard, Link2,
  Lock, MessageSquare, Pill, Plus, Sliders, Video, Zap,
} from "lucide-react";
import { api, auth, setBlockedHandler, setUnauthorizedHandler, type Company, type Me } from "./api";
import { btnPrimary } from "./ui";
import { NewCompanyModal } from "./views/NewCompanyModal";
import { DashboardView } from "./views/DashboardView";
import { AgentsView } from "./views/AgentsView";
import { MedicalAgendaView } from "./views/MedicalAgendaView";
import { ServicesView } from "./views/ServicesView";
import { StudioView } from "./views/StudioView";
import { IntelligenceView } from "./views/IntelligenceView";
import { ConnectionsView } from "./views/ConnectionsView";
import { ChatView } from "./views/ChatView";
import { ClinicalView } from "./views/ClinicalView";
import { BlocksView } from "./views/BlocksView";
import { PortalView } from "./views/PortalView";
import { LoginScreen } from "./views/LoginScreen";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null); // null = verificando
  const [companies, setCompanies] = useState<Company[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [view, setView] = useState<"dashboard" | "agents" | "medical" | "chat" | "connections" | "intelligence" | "studio" | "services" | "clinical" | "blocks">("dashboard");
  // Qué bloque mostrar destacado al entrar a la vista de bloques (el que el
  // usuario acaba de intentar usar sin tenerlo contratado).
  const [bloqueResaltado, setBloqueResaltado] = useState("");
  const [esPlataforma, setEsPlataforma] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [showNewCompany, setShowNewCompany] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false));
    // Si algo pide una función de un bloque que la empresa no contrató, en
    // vez de un error crudo se lo lleva a ver qué incluye ese bloque.
    setBlockedHandler((info) => { setBloqueResaltado(info.bloque); setView("blocks"); });
    // La sesión vive en cookie HttpOnly: se le pregunta al backend si sigue viva.
    auth.me()
      .then((quien) => {
        setAuthed(true);
        setMe(quien);
        setEsPlataforma(quien.is_platform_admin);
      })
      .catch(() => setAuthed(false));
  }, []);

  useEffect(() => {
    if (!authed) return;
    api.listCompanies()
      .then((list) => {
        setCompanies(list);
        if (list.length && activeId === null) setActiveId(list[0].id);
      })
      .catch(() => setLoadError("No se pudo conectar con el backend (¿está corriendo uvicorn?)"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed]);

  if (authed === null) {
    return <div className="min-h-screen bg-[#040609] flex items-center justify-center text-zinc-500 text-sm">Cargando…</div>;
  }
  if (!authed) return <LoginScreen onAuthed={() => setAuthed(true)} />;

  const active = companies.find((c) => c.id === activeId) ?? null;

  // Un profesional no usa el panel de la clínica: usa su portal, que es otra
  // aplicación. El backend además lo encierra en /portal, así que si acá se
  // le mostrara el panel vería una pantalla de errores.
  const rolAca = me?.memberships.find((m) => m.company_id === activeId)?.role ?? "";
  if (activeId && rolAca === "professional") {
    return <PortalView companyId={activeId} onSalir={() => setAuthed(false)} />;
  }

  const navBtn = (id: typeof view, label: string, Icon: typeof LayoutDashboard) => (
    <button onClick={() => setView(id)}
      className={`w-full flex items-center px-3 py-2.5 rounded-xl text-xs font-semibold transition-all ${view === id ? "text-white bg-white/5 border border-white/10" : "text-zinc-400 hover:bg-white/[0.02] hover:text-zinc-200"}`}>
      <Icon size={16} className={`mr-3 ${view === id ? "text-cyan-400" : "text-zinc-500"}`} /> {label}
    </button>
  );

  /**
   * Un módulo del panel: el botón normal si está contratado, y si no un
   * candado que lleva a la oferta.
   *
   * Esconderlo del todo era peor de las dos maneras: el cliente no se entera
   * de que existe algo más para comprar, y el que sí lo compró y no lo ve
   * cree que se rompió. El candado dice las dos cosas.
   */
  const navModulo = (
    id: typeof view, label: string, Icon: typeof LayoutDashboard,
    modulo: string, bloque: string,
  ) => {
    if (active?.modules?.includes(modulo)) return navBtn(id, label, Icon);
    return (
      <button
        onClick={() => { setBloqueResaltado(bloque); setView("blocks"); }}
        title="Esta función es de otro bloque. Tocá para ver qué incluye."
        className="w-full flex items-center px-3 py-2.5 rounded-xl text-xs font-semibold text-zinc-600 hover:text-zinc-400 hover:bg-white/[0.02] transition-all">
        <Icon size={16} className="mr-3 text-zinc-700" /> {label}
        <Lock size={11} className="ml-auto text-zinc-700" />
      </button>
    );
  };

  return (
    <div className="min-h-screen bg-[#040609] font-sans text-zinc-300 flex">
      <aside className="w-72 bg-[#06080d] border-r border-white/5 flex-col z-20 hidden md:flex shrink-0">
        <div className="p-6 border-b border-white/5">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-500 flex items-center justify-center">
              <Zap size={18} className="text-white fill-current" />
            </div>
            <div>
              <span className="font-extrabold text-base tracking-tight text-white">MetaBot<span className="text-cyan-400">.OS</span></span>
              <p className="text-[9px] text-zinc-500 uppercase tracking-widest font-mono">Py • Enterprise & Medical</p>
            </div>
          </div>
          <div className="space-y-2">
            <div className="relative">
              <select value={activeId ?? ""} onChange={(e) => setActiveId(Number(e.target.value))}
                className="w-full bg-white/[0.03] border border-white/10 rounded-xl py-2.5 px-3 text-xs text-zinc-200 font-semibold focus:outline-none focus:border-cyan-500 appearance-none cursor-pointer">
                {companies.map((c) => (
                  <option key={c.id} value={c.id} className="bg-[#06080d]">
                    {c.name} ({c.vertical === "medical" ? "Médico" : c.industry || c.vertical})
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-3.5 text-zinc-500 pointer-events-none" />
            </div>
            <button onClick={() => setShowNewCompany(true)}
              className="w-full py-2 bg-gradient-to-r from-cyan-500/10 to-indigo-500/10 border border-cyan-500/30 hover:border-cyan-500 text-cyan-300 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5">
              <Plus size={14} /> Agregar empresa
            </button>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          <div className="text-[9px] font-bold text-zinc-500 uppercase tracking-widest px-3 py-2">Módulos</div>
          {navBtn("dashboard", "Dashboard", LayoutDashboard)}
          {navModulo("medical", "Agenda de Doctores", Calendar, "agenda", "booking")}
          {navModulo("clinical", "Recetas y Convenios", Pill, "prescriptions", "healthcare")}
          {navBtn("services", "Servicios & Estudios", Sliders)}
          {navBtn("chat", "CX Bot (Simulador)", MessageSquare)}
          {navBtn("connections", "Conexiones (WhatsApp)", Link2)}
          {navBtn("intelligence", "Inteligencia (Informes)", Activity)}
          {navBtn("studio", "Estudio Visual", Video)}
          {navBtn("agents", "Enjambre de Agentes", Bot)}
          <div className="pt-3 mt-2 border-t border-white/5">
            {navBtn("blocks", "Bloques del sistema", Boxes)}
          </div>
        </nav>
        <div className="p-4 border-t border-white/5">
          <button onClick={() => { auth.logout().finally(() => setAuthed(false)); }}
            className="w-full text-xs text-zinc-500 hover:text-zinc-300 py-2">Cerrar sesión</button>
        </div>
      </aside>

      <main className="flex-1 h-screen overflow-y-auto">
        <div className="p-8 md:p-12 max-w-6xl mx-auto w-full pb-24">
          {loadError && (
            <div className="mb-6 bg-red-500/10 border border-red-500/30 text-red-300 text-sm rounded-xl p-4 flex items-center gap-2">
              <Building2 size={16} /> {loadError}
            </div>
          )}
          {!active && !loadError && (
            <div className="text-center py-24 space-y-4">
              <Building2 size={48} className="mx-auto text-zinc-600" />
              <h2 className="text-xl font-bold text-white">Sin empresas todavía</h2>
              <button onClick={() => setShowNewCompany(true)} className={`${btnPrimary} mx-auto`}>
                <Plus size={15} /> Crear la primera empresa
              </button>
            </div>
          )}
          {active && view === "dashboard" && <DashboardView companyId={active.id} />}
          {active && view === "agents" && (
            <AgentsView
              company={active}
              onCompanyUpdated={() => api.listCompanies().then(setCompanies).catch(() => {})}
            />
          )}
          {active && view === "medical" && active.modules?.includes("agenda") && <MedicalAgendaView companyId={active.id} modules={active.modules} />}
          {/* El render se gatea igual que el botón. Si solo se escondiera el
              botón, la vista seguiría montándose cuando el bloque se apaga con
              esa pantalla abierta, y dispararía llamadas que dan 402. */}
          {active && view === "clinical" && active.modules?.includes("prescriptions") && <ClinicalView company={active} />}
          {active && view === "blocks" && (
            <BlocksView
              company={active}
              esPlataforma={esPlataforma}
              resaltar={bloqueResaltado}
              onCambio={(c) => setCompanies((prev) => prev.map((x) => (x.id === c.id ? c : x)))}
            />
          )}
          {active && view === "chat" && <ChatView companyId={active.id} />}
          {active && view === "intelligence" && <IntelligenceView companyId={active.id} />}
          {active && view === "studio" && <StudioView companyId={active.id} />}
          {active && view === "services" && <ServicesView company={active} />}
          {active && view === "connections" && (
            <ConnectionsView
              company={active}
              onCompanyUpdated={(c) => setCompanies((prev) => prev.map((x) => (x.id === c.id ? c : x)))}
            />
          )}
        </div>
      </main>

      {showNewCompany && (
        <NewCompanyModal
          onClose={() => setShowNewCompany(false)}
          onCreated={(c) => {
            setCompanies((prev) => [...prev, c]);
            setActiveId(c.id);
            setView("dashboard");
          }}
        />
      )}
    </div>
  );
}
