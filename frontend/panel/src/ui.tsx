import React from "react";
import { BarChart3, Command, MessageSquare, PenTool, ShieldCheck, Video, X } from "lucide-react";

export const AGENT_ICONS: Record<string, typeof Command> = {
  ceo: Command, quant: BarChart3, guard: ShieldCheck,
  creative: PenTool, visual: Video, cx: MessageSquare,
};

/**
 * Los tokens del tema. Viven acá y no repartidos por las vistas: cambiar el
 * color de marca tiene que ser una línea, no una cacería por 22 archivos.
 */
export const card =
  "bg-white border border-zinc-200 rounded-2xl shadow-sm";
export const input =
  "w-full bg-white border border-zinc-300 rounded-xl p-2.5 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-100 transition-colors";
export const btnPrimary =
  "bg-gradient-to-r from-violet-600 to-pink-500 hover:from-violet-500 hover:to-pink-400 text-white font-semibold rounded-xl text-sm px-5 py-2.5 flex items-center gap-2 shadow-lg shadow-violet-500/25 transition-all disabled:opacity-50";
/** El de acción secundaria: mismo peso visual, sin gritar. */
export const btnSuave =
  "border border-zinc-300 bg-white hover:bg-zinc-50 hover:border-zinc-400 text-zinc-700 font-semibold rounded-xl text-sm px-4 py-2.5 flex items-center gap-2 transition-all disabled:opacity-50";

/**
 * El color de cada módulo. Se repite en el menú, en el ícono y en la tarjeta:
 * el color deja de ser decoración y pasa a ser una pista de dónde estás.
 *
 * `pastilla` es el fondo del ícono; `texto` el del ícono y los acentos.
 */
export const COLOR_MODULO: Record<string, { pastilla: string; texto: string; barra: string }> = {
  dashboard: { pastilla: "bg-violet-100", texto: "text-violet-600", barra: "bg-violet-500" },
  medical: { pastilla: "bg-emerald-100", texto: "text-emerald-600", barra: "bg-emerald-500" },
  clinical: { pastilla: "bg-pink-100", texto: "text-pink-600", barra: "bg-pink-500" },
  honorarios: { pastilla: "bg-purple-100", texto: "text-purple-600", barra: "bg-purple-500" },
  cfo: { pastilla: "bg-amber-100", texto: "text-amber-600", barra: "bg-amber-500" },
  plan: { pastilla: "bg-orange-100", texto: "text-orange-600", barra: "bg-orange-500" },
  services: { pastilla: "bg-teal-100", texto: "text-teal-600", barra: "bg-teal-500" },
  chat: { pastilla: "bg-blue-100", texto: "text-blue-600", barra: "bg-blue-500" },
  connections: { pastilla: "bg-lime-100", texto: "text-lime-600", barra: "bg-lime-500" },
  intelligence: { pastilla: "bg-cyan-100", texto: "text-cyan-600", barra: "bg-cyan-500" },
  studio: { pastilla: "bg-fuchsia-100", texto: "text-fuchsia-600", barra: "bg-fuchsia-500" },
  agents: { pastilla: "bg-red-100", texto: "text-red-600", barra: "bg-red-500" },
  blocks: { pastilla: "bg-purple-100", texto: "text-purple-600", barra: "bg-purple-500" },
};

/**
 * La paleta de los post-it, en orden fijo.
 *
 * Fijo y no aleatorio a propósito: el color de una nota tiene que ser el
 * mismo cada vez que el dueño entra, o deja de servirle para encontrarla de
 * un vistazo. Se asigna por posición y se repite recién en la novena.
 */
export const PAPELES = [
  { fondo: "bg-emerald-100", texto: "text-emerald-950", icono: "bg-emerald-200/70" },
  { fondo: "bg-sky-100", texto: "text-sky-950", icono: "bg-sky-200/70" },
  { fondo: "bg-amber-100", texto: "text-amber-950", icono: "bg-amber-200/70" },
  { fondo: "bg-pink-100", texto: "text-pink-950", icono: "bg-pink-200/70" },
  { fondo: "bg-violet-100", texto: "text-violet-950", icono: "bg-violet-200/70" },
  { fondo: "bg-orange-100", texto: "text-orange-950", icono: "bg-orange-200/70" },
  { fondo: "bg-teal-100", texto: "text-teal-950", icono: "bg-teal-200/70" },
  { fondo: "bg-rose-100", texto: "text-rose-950", icono: "bg-rose-200/70" },
];

export const papelDe = (i: number) => PAPELES[i % PAPELES.length];

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-zinc-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-200 rounded-2xl w-full max-w-2xl shadow-2xl p-6 max-h-[90vh] overflow-y-auto aparece">
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-lg font-bold text-zinc-900">{title}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-900 p-1 rounded-lg hover:bg-zinc-100 transition-colors"><X size={20} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

/**
 * Interruptor de encendido/apagado. Existe como componente y no como markup
 * suelto porque aparece en cada post-it: repetido a mano, uno queda de otro
 * color y nadie se entera hasta que lo ve un cliente.
 */
export function Interruptor({ activo, onToggle, titulo }: {
  activo: boolean; onToggle?: () => void; titulo?: string;
}) {
  return (
    <button
      type="button"
      title={titulo ?? (activo ? "Activo" : "En pausa")}
      onClick={(e) => { e.stopPropagation(); onToggle?.(); }}
      className={`relative h-[18px] w-[34px] shrink-0 rounded-full transition-colors ${
        activo ? "bg-emerald-500" : "bg-zinc-300"
      }`}
    >
      <span
        className={`absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white shadow transition-all ${
          activo ? "left-[18px]" : "left-[2px]"
        }`}
      />
    </button>
  );
}
