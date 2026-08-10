import React from "react";
import { useState } from "react";
import { Zap } from "lucide-react";
import { auth, validateToken } from "../api";
import { card, input, btnPrimary } from "../ui";

export function LoginScreen({ onAuthed }: { onAuthed: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setChecking(true);
    setError("");
    try {
      if (await validateToken(token.trim())) {
        auth.set(token.trim());
        onAuthed();
      } else {
        setError("Token incorrecto.");
      }
    } catch {
      setError("No se pudo conectar con el servidor.");
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#040609] flex items-center justify-center p-4 font-sans">
      <form onSubmit={submit} className={`${card} p-8 w-full max-w-sm space-y-5`}>
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-500 flex items-center justify-center">
            <Zap size={18} className="text-white fill-current" />
          </div>
          <span className="font-extrabold text-lg text-white">MetaBot<span className="text-cyan-400">.OS</span></span>
        </div>
        <p className="text-sm text-zinc-400">Ingresá el token de acceso al panel.</p>
        <input type="password" className={input} placeholder="Token de acceso" value={token}
          onChange={(e) => setToken(e.target.value)} autoFocus />
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <button type="submit" disabled={checking || !token.trim()} className={`${btnPrimary} w-full justify-center`}>
          {checking ? "Verificando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}
