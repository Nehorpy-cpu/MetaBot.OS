import { useEffect, useState } from "react";
import {
  Activity, Bot, Boxes, Building2, Calendar, ChevronDown, LayoutDashboard, Link2,
  Gauge, Lock, MessageSquare, Pill, Plus, Receipt, Sliders, Video, Wallet, Zap,
} from "lucide-react";
import { api, auth, setBlockedHandler, setUnauthorizedHandler, type Company, type Me } from "./api";
import { COLOR_MODULO } from "./ui";
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
import { HonorariosAPagarView } from "./views/HonorariosAPagarView";
import { CfoView } from "./views/CfoView";
import { PlanView } from "./views/PlanView";
import { LoginScreen } from "./views/LoginScreen";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null); // null = verificando
  const [companies, setCompanies] = useState<Company[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [view, setView] = useState<"dashboard" | "agents" | "medical" | "chat" | "connections" | "intelligence" | "studio" | "services" | "clinical" | "blocks" | "honorarios" | "cfo" | "plan">("dashboard");
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
    return <div className="min-h-screen bg-[#f6f4ff] flex items-center justify-center text-zinc-500 text-sm">Cargando…</div>;
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

  /**
   * Un ítem del menú. Cada módulo tiene su color, y ese color se repite en su
   * pantalla: deja de ser decoración y pasa a ser una pista de dónde estás
   * parado. El ícono va en una pastilla del color, no suelto, para que el
   * menú se lea de un vistazo y no como una lista de texto gris.
   */
  const navBtn = (id: typeof view, label: string, Icon: typeof LayoutDashboard) => {
    const c = COLOR_MODULO[id] ?? COLOR_MODULO.dashboard;
    const activo = view === id;
    return (
      <button onClick={() => setView(id)}
        className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl text-[13px] font-semibold transition-all ${
          activo
            ? "bg-violet-50 text-violet-900 shadow-sm"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
        }`}>
        <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg ${c.pastilla} ${c.texto} transition-transform ${activo ? "scale-105" : ""}`}>
          <Icon size={15} />
        </span>
        <span className="truncate text-left">{label}</span>
        {activo && <span className={`ml-auto h-5 w-1 shrink-0 rounded-full ${c.barra}`} />}
      </button>
    );
  };

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
        className="group w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl text-[13px] font-semibold text-zinc-400 hover:bg-amber-50 hover:text-amber-700 transition-all">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-zinc-100 text-zinc-400 group-hover:bg-amber-100 group-hover:text-amber-600">
          <Icon size={15} />
        </span>
        <span className="truncate text-left">{label}</span>
        <Lock size={11} className="ml-auto shrink-0 text-zinc-300 group-hover:text-amber-500" />
      </button>
    );
  };

  return (
    <div className="min-h-screen bg-[#f6f4ff] font-sans text-zinc-700 flex">
      <aside className="w-72 bg-white border-r border-zinc-200 flex-col z-20 hidden md:flex shrink-0">
        <div className="p-6 border-b border-zinc-200">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-violet-600 to-pink-500 flex items-center justify-center">
              <Zap size={18} className="text-white fill-current" />
            </div>
            <div>
              <span className="font-extrabold text-base tracking-tight text-zinc-900">MetaBot<span className="text-violet-600">.OS</span></span>
              <p className="text-[9px] text-zinc-500 uppercase tracking-widest font-mono">Py • Enterprise & Medical</p>
            </div>
          </div>
          <div className="space-y-2">
            <div className="relative">
              <select value={activeId ?? ""} onChange={(e) => setActiveId(Number(e.target.value))}
                className="w-full bg-zinc-50 border border-zinc-200 rounded-xl py-2.5 px-3 text-xs text-zinc-800 font-semibold focus:outline-none focus:border-violet-500 appearance-none cursor-pointer">
                {companies.map((c) => (
                  <option key={c.id} value={c.id} className="bg-white">
                    {c.name} ({c.vertical === "medical" ? "Médico" : c.industry || c.vertical})
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-3.5 text-zinc-500 pointer-events-none" />
            </div>
            <button onClick={() => setShowNewCompany(true)}
              className="w-full py-2 bg-gradient-to-r from-violet-500/10 to-pink-500/10 border border-violet-300 hover:border-violet-500 text-violet-600 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5">
              <Plus size={14} /> Agregar empresa
            </button>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          <div className="text-[9px] font-bold text-zinc-500 uppercase tracking-widest px-3 py-2">Módulos</div>
          {navBtn("dashboard", "Dashboard", LayoutDashboard)}
          {navModulo("medical", "Agenda de Doctores", Calendar, "agenda", "booking")}
          {navModulo("clinical", "Recetas y Convenios", Pill, "prescriptions", "healthcare")}
          {navModulo("honorarios", "Honorarios a pagar", Receipt, "portal", "practitioner")}
          {navModulo("cfo", "CFO de Finanzas", Wallet, "cfo", "finance")}
          {navBtn("plan", "Tu plan y consumo", Gauge)}
          {navBtn("services", "Servicios & Estudios", Sliders)}
          {navBtn("chat", "CX Bot (Simulador)", MessageSquare)}
          {navBtn("connections", "Conexiones (WhatsApp)", Link2)}
          {navBtn("intelligence", "Inteligencia (Informes)", Activity)}
          {navBtn("studio", "Estudio Visual", Video)}
          {navBtn("agents", "Enjambre de Agentes", Bot)}
          <div className="pt-3 mt-2 border-t border-zinc-200">
            {navBtn("blocks", "Bloques del sistema", Boxes)}
          </div>
        </nav>
        <div className="p-4 border-t border-zinc-200">
          <button onClick={() => { auth.logout().finally(() => setAuthed(false)); }}
            className="w-full text-xs text-zinc-500 hover:text-zinc-800 py-2">Cerrar sesión</button>
        </div>
      </aside>

      <main className="flex-1 h-screen overflow-y-auto">
        <div className="p-8 md:p-12 max-w-6xl mx-auto w-full pb-24">
          {loadError && (
            <div className="mb-6 bg-red-500/10 border border-red-500/30 text-red-600 text-sm rounded-xl p-4 flex items-center gap-2">
              <Building2 size={16} /> {loadError}
            </div>
          )}
          {!active && !loadError && (
            <div className="text-center py-24 space-y-4">
              <Building2 size={48} className="mx-auto text-zinc-500" />
              <h2 className="text-xl font-bold text-zinc-900">Sin empresas todavía</h2>
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
          {active && view === "cfo" && active.modules?.includes("cfo") && (
            <CfoView companyId={active.id} />
          )}
          {active && view === "plan" && <PlanView companyId={active.id} />}
          {active && view === "honorarios" && active.modules?.includes("portal") && (
            <HonorariosAPagarView companyId={active.id} />
          )}
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
