import React from "react";
import { useCallback, useEffect, useState } from "react";
import { MessageSquare, Send } from "lucide-react";
import { chatApi, type ChatMessage, type Conversation } from "../api";
import { card, input, btnPrimary } from "../ui";

export function ChatView({ companyId }: { companyId: number }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newName, setNewName] = useState("");

  const loadConversations = useCallback(() => {
    chatApi.listConversations(companyId).then(setConversations).catch(() => setConversations([]));
  }, [companyId]);
  useEffect(loadConversations, [loadConversations]);

  const loadMessages = useCallback((conv: Conversation) => {
    chatApi.listMessages(companyId, conv.id).then(setMessages).catch(() => setMessages([]));
  }, [companyId]);

  useEffect(() => {
    if (selected) loadMessages(selected);
    else setMessages([]);
  }, [selected, loadMessages]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const phone = selected?.contact_phone ?? newPhone.trim();
    if (!phone || !draft.trim() || sending) return;
    const text = draft.trim();
    setDraft("");
    setSending(true);
    setError("");
    setMessages((prev) => [
      ...prev,
      { id: -1, direction: "in", body: text, created_at: new Date().toISOString() },
    ]);
    try {
      const resp = await chatApi.send(companyId, phone, selected?.contact_name ?? newName, text);
      if (resp.error) setError(resp.error);
      loadConversations();
      const conv = selected ?? {
        id: resp.conversation_id, channel: "whatsapp", contact_phone: phone,
        contact_name: newName, status: resp.status,
      };
      if (!selected) setSelected(conv);
      chatApi.listMessages(companyId, resp.conversation_id).then(setMessages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
          <MessageSquare className="text-cyan-400" size={26} /> CX Bot — Simulador de WhatsApp
        </h2>
        <p className="text-zinc-400 text-sm mt-1">
          Probá el bot con IA real. Puede consultar la agenda, agendar citas de verdad y escalar a humano.
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={`${card} p-4 space-y-3`}>
          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest">Conversaciones</h3>
          <div className="space-y-2 border-b border-white/5 pb-3">
            <input className={input} placeholder="Teléfono (ej. +595 981 000000)" value={newPhone}
              onChange={(e) => setNewPhone(e.target.value)} />
            <input className={input} placeholder="Nombre del contacto" value={newName}
              onChange={(e) => setNewName(e.target.value)} />
            <button onClick={() => setSelected(null)}
              className="w-full py-2 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 rounded-xl text-xs font-bold">
              + Nueva conversación con estos datos
            </button>
          </div>
          {conversations.map((c) => (
            <div key={c.id} onClick={() => setSelected(c)}
              className={`p-3 rounded-xl border cursor-pointer ${selected?.id === c.id ? "bg-cyan-500/10 border-cyan-500/50" : "bg-white/[0.02] border-white/5 hover:bg-white/[0.04]"}`}>
              <div className="flex justify-between items-center">
                <p className="font-bold text-sm text-zinc-100">{c.contact_name || c.contact_phone}</p>
                {c.status === "needs_human" && (
                  <span className="text-[9px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold uppercase">Humano</span>
                )}
              </div>
              <p className="text-[10px] text-zinc-500">{c.contact_phone}</p>
            </div>
          ))}
        </div>

        <div className={`lg:col-span-2 ${card} flex flex-col h-[560px]`}>
          <div className="flex-1 overflow-y-auto p-4 space-y-2">
            {messages.map((m, i) => (
              <div key={`${m.id}-${i}`} className={`flex ${m.direction === "in" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[75%] px-3.5 py-2 rounded-2xl text-sm whitespace-pre-wrap ${m.direction === "in" ? "bg-cyan-600/30 text-cyan-50 rounded-br-sm" : "bg-white/[0.06] text-zinc-200 rounded-bl-sm"}`}>
                  {m.body}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-white/[0.06] text-zinc-500 px-3.5 py-2 rounded-2xl text-sm italic">escribiendo…</div>
              </div>
            )}
            {!messages.length && !sending && (
              <p className="text-center text-zinc-600 text-xs pt-24">
                {selected ? "Sin mensajes." : "Cargá teléfono y nombre a la izquierda y escribí el primer mensaje como si fueras el cliente."}
              </p>
            )}
          </div>
          {error && <p className="text-red-400 text-xs px-4 pb-1">{error}</p>}
          <form onSubmit={send} className="p-3 border-t border-white/5 flex gap-2">
            <input className={input} placeholder="Escribí como el cliente…" value={draft}
              onChange={(e) => setDraft(e.target.value)} />
            <button type="submit" disabled={sending || !draft.trim()} className={btnPrimary}>
              <Send size={15} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
