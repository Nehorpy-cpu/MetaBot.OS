import React from "react";
import { BarChart3, Command, MessageSquare, PenTool, ShieldCheck, Video, X } from "lucide-react";

export const AGENT_ICONS: Record<string, typeof Command> = {
  ceo: Command, quant: BarChart3, guard: ShieldCheck,
  creative: PenTool, visual: Video, cx: MessageSquare,
};

export const card = "bg-[#07090e] border border-white/10 rounded-2xl shadow-md";
export const input =
  "w-full bg-white/[0.03] border border-white/10 rounded-xl p-2.5 text-sm text-zinc-100 focus:outline-none focus:border-cyan-500 transition-colors";
export const btnPrimary =
  "bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white font-semibold rounded-xl text-sm px-5 py-2.5 flex items-center gap-2 shadow-lg transition-all disabled:opacity-50";

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="bg-[#090b10] border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-lg font-bold text-white">{title}</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white p-1"><X size={20} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}
