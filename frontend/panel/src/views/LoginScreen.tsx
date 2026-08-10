import { useState } from "react";
import { Zap } from "lucide-react";
import { auth } from "../api";
import { btnPrimary, card, input } from "../ui";

export function LoginScreen({ onAuthed }: { onAuthed: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setChecking(true);
    setError("");
    try {
      await auth.login(email.trim().toLowerCase(), password);
      onAuthed();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión.");
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
        <p className="text-sm text-zinc-400">Ingresá con tu correo y contraseña.</p>
        <div className="space-y-3">
          <input type="email" autoComplete="username" className={input} placeholder="tu@correo.com"
            value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          <input type="password" autoComplete="current-password" className={input} placeholder="Contraseña"
            value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <button type="submit" disabled={checking || !email.trim() || !password}
          className={`${btnPrimary} w-full justify-center`}>
          {checking ? "Verificando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}
