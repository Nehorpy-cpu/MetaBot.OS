export interface Company {
  id: number;
  name: string;
  vertical: string;
  niche: string;
  industry: string;
  address: string;
  wa_mode: "none" | "meta" | "qr";
  // null = sin configurar. No es cadena vacía: el número es único entre
  // empresas, y varias sin configurar no pueden chocar entre sí.
  wa_phone_number_id: string | null;
  supervision: "off" | "shadow" | "inline";
  supervision_pct: number;
  // Módulos habilitados por los Business Packs. El panel decide qué vistas
  // mostrar con ESTO y no con `vertical`: un sanatorio, una odontológica y una
  // veterinaria son verticales distintas con la misma agenda.
  modules: string[];
  // Los bloques contratados, tal como están guardados ("core,booking").
  // `modules` es la consecuencia; esto es la causa, y es lo que se necesita
  // para saber qué ofrecerle al cliente que todavía no lo compró.
  packs: string;
}

/** Un bloque del catálogo comercial. */
export interface Bloque {
  key: string;
  name: string;
  description: string;
  modules: string[];
  requires: string[];
  /** El núcleo viene con cualquier contratación: no se vende aparte. */
  incluido: boolean;
  incluye: string[];
}

export interface Insurer {
  id: number;
  name: string;
  plan: string;
  coverage_pct: number;
  copay_gs: number;
  active: boolean;
  notes: string;
  coberturas_especificas: number;
}

export interface PrescriptionItemIn {
  medication: string;
  dose: string;
  route: string;
  frequency: string;
  // 0 = pauta a demanda: no se programan recordatorios.
  every_hours: number;
  duration_days: number;
  instructions: string;
}

export interface PrescriptionItem extends PrescriptionItemIn {
  id: number;
  a_demanda: boolean;
}

export interface Prescription {
  id: number;
  doctor: string;
  doctor_id: number;
  patient_name: string;
  patient_phone: string;
  diagnosis: string;
  indications: string;
  status: string;
  reminders_enabled: boolean;
  version: number;
  issued_at: string;
  items: PrescriptionItem[];
}

export interface RecordatoriosResult {
  programadas: number;
  motivo: string;
  a_demanda_omitidas?: number;
}

export interface SupervisionEvent {
  id: number;
  conversation_id: number;
  trigger: string;
  agente: string;
  modo: string;
  brazo: string;
  accion: string;
  motivo: string;
  degradado: string;
  latencia_ms: number;
  creado: string;
}

export interface SupervisionReport {
  supervision: "off" | "shadow" | "inline";
  supervision_pct: number;
  total: number;
  supervisadas: number;
  control: number;
  por_disparador: Record<string, number>;
  por_accion: Record<string, number>;
  latencia_media_ms: number;
  recientes: SupervisionEvent[];
}

export interface PromptSuggestion {
  id: number;
  agent_id: number;
  agent_name: string;
  old_prompt: string;
  suggested_prompt: string;
  rationale: string;
  status: string;
  created_at: string;
}

export interface WaStatus {
  mode: string;
  status: string;
  qr?: string | null;
  phone?: string | null;
  channel_name?: string;
  official?: boolean;
  warning?: string;
  capabilities?: string[];
}

export const CAPABILITY_ES: Record<string, string> = {
  can_reply: "Responder mensajes",
  can_send_media: "Enviar fotos y archivos",
  can_send_catalog: "Enviar catálogo",
  can_send_template: "Plantillas aprobadas",
  can_send_proactive: "Escribir primero (recordatorios y campañas)",
  can_receive_voice: "Recibir audios",
  can_receive_images: "Recibir imágenes",
  can_receive_location: "Recibir ubicación",
};

export const ALL_CAPABILITIES = Object.keys(CAPABILITY_ES);

export interface AgentSummary {
  id: number;
  slug: string;
  name: string;
  role: string;
  model: string;
  temperature: number;
  active: boolean;
}

export interface AgentDetail extends AgentSummary {
  company_id: number;
  system_prompt: string;
}

export interface Doctor {
  id: number;
  name: string;
  specialty: string;
  schedule: string;
  phone: string;
  email: string;
  // Resultado del cruce contra el padrón del CPM. `not_found` no es un error:
  // el padrón es solo de médicos especialistas, así que una bioquímica o un
  // veterinario nunca van a figurar.
  verification?: "unverified" | "verified" | "expired" | "not_found";
  cert_number?: string;
  cert_specialty?: string;
  cert_expires_at?: string | null;
  // "libre" = todavía no cargó su horario: sus turnos se toman como pedido y
  // el bot no puede rechazar un domingo a las 23:00.
  agenda_mode?: "libre" | "estructurado";
  /** Qué parte de lo facturado le queda al profesional (0-100). */
  honorario_pct?: number;
}

export interface Franja {
  id?: number;
  // 0 = lunes … 6 = domingo, igual que en el servidor.
  weekday: number;
  desde: string; // "HH:MM"
  hasta: string;
  // Vacío = la franja vale para todo. Con servicio, vale SOLO para ese: así se
  // carga al profesional que atiende consulta toda la semana pero hace
  // ecografías los martes a la tarde.
  service_id?: number | null;
  lugar?: string;
}

export interface HorarioDoctor {
  // "libre" = todavía no cargó su horario. Se le siguen tomando turnos, pero
  // como PEDIDO: el bot avisa que recepción confirma en vez de prometer.
  agenda_mode: "libre" | "estructurado";
  // El horario como lo escribió la clínica, para transcribirlo al lado. El
  // servidor NO lo interpreta.
  texto_libre: string;
  franjas: Franja[];
  nota: string;
}

export interface CitaFueraDeHorario {
  id: number;
  paciente: string;
  telefono: string;
  cuando: string;
  motivo: string;
}

export interface ResultadoHorario {
  agenda_mode: string;
  franjas: number;
  // Personas que ya tenían turno y ahora quedan fuera del horario nuevo. No se
  // cancelan: hay que llamarlas.
  citas_fuera_de_horario: CitaFueraDeHorario[];
}

export interface FichaPaciente {
  hora: string;
  paciente: string;
  /** Para abrir la ficha desde el post-it. No va en el texto de WhatsApp. */
  telefono: string;
  motivo: string;
  servicio: string;
  duracion_min: number;
  // Lo más importante del resumen: no se atiende igual a alguien que viene
  // por primera vez que a alguien que ya vino seis veces.
  primera_vez: boolean;
  visitas_previas: number;
  // Turnos a los que el paciente NO se presentó. Se cuentan aparte: antes
  // figuraban como visitas y el doctor creía que hubo una consulta.
  faltas_previas: number;
  // Hay registros con el mismo número a nombre de otra persona (la madre que
  // agenda con su celular para el hijo). No se muestran: se avisa que existen.
  numero_compartido: boolean;
  ultima_visita: string;
  sin_confirmar: boolean;
  turno_sin_verificar: boolean;
  preparacion_requerida?: string;
  ultima_receta?: {
    fecha: string;
    por: string;
    diagnostico: string;
    medicacion: string[];
    vigente: boolean;
  };
}

/** ─── Portal del Profesional (bloque 4) ─────────────────────────────── */

export interface PortalMe {
  doctor_id: number;
  nombre: string;
  especialidad: string;
  empresa: string;
}

export interface PortalPaciente {
  nombre: string;
  telefono: string;
  ultima_visita: string;
  visitas: number;
}

export interface RecetaDelPortal {
  id: number;
  fecha: string;
  diagnostico: string;
  indicaciones: string;
  estado: string;
  medicacion: {
    nombre: string; dosis: string; via: string; frecuencia: string;
    cada_horas: number; dias: number; indicaciones: string;
  }[];
}

export interface FichaCompleta {
  paciente: string;
  telefono: string;
  /** Con este número hay registros a nombre de otra persona. */
  numero_compartido: boolean;
  visitas: { fecha: string; estado: string; motivo: string }[];
  recetas: RecetaDelPortal[];
}

/** Lo que un convenio cubre para UNA práctica. */
export interface CoberturaDePractica {
  service_id: number;
  servicio: string;
  precio_lista_gs: number;
  coverage_pct: number;
  copay_gs: number;
  excluded: boolean;
  /** Monto fijo del nomenclador. 0 = no configurado, se usa el porcentaje. */
  arancel_gs: number;
}

export interface ItemHonorario {
  fecha: string;
  paciente: string;
  servicio: string;
  precio_lista_gs: number;
  /** Lo que se le factura a la aseguradora (o al particular). */
  facturado_gs: number;
  honorario_gs: number;
  origen_arancel: string;
  /** Solo en los renglones ya guardados: identifica el renglón a ajustar. */
  id?: number;
  /** Alguien corrigió este monto a mano antes de firmar. */
  ajustado_a_mano?: boolean;
  facturado_calculado_gs?: number;
  ajuste_motivo?: string;
  /** Solo en el preview: lo que pone el paciente de su bolsillo. */
  paga_el_paciente_gs?: number;
  /** Sin servicio cargado no hay precio, y sin precio no hay honorario. */
  sin_arancel?: boolean;
}

export interface GrupoHonorario {
  insurer_id: number | null;
  aseguradora: string;
  items: ItemHonorario[];
  total_facturado_gs: number;
  total_honorario_gs: number;
}

export interface PreviewHonorarios {
  doctor: string;
  doctor_id: number;
  honorario_pct: number;
  desde: string;
  hasta: string;
  grupos: GrupoHonorario[];
  total_facturado_gs: number;
  total_honorario_gs: number;
  atenciones: number;
  /** Turnos del período que nadie cerró: si no se avisan, se cobra de menos. */
  sin_marcar_como_atendido: number;
  ya_liquidadas: number;
  sin_arancel: number;
}

export type EstadoPlanilla = "borrador" | "firmada" | "entregada" | "cobrada";

export interface Planilla {
  id: number;
  aseguradora: string;
  insurer_id: number | null;
  desde: string;
  hasta: string;
  estado: EstadoPlanilla;
  atenciones: number | null;
  total_facturado_gs: number;
  total_honorario_gs: number;
  honorario_pct: number;
  firmada_at: string | null;
  entregada_at: string | null;
  cobrada_at: string | null;
  notas: string;
  /** Cuántos renglones se corrigieron a mano. */
  ajustados?: number;
  items?: ItemHonorario[];
  /** La hoja lista para imprimir y firmar de puño. */
  texto?: string;
  /** Solo en la vista de administración. */
  doctor?: string;
  doctor_id?: number;
}

export interface AccesoProfesional {
  doctor_id: number;
  doctor: string;
  email: string;
  activo: boolean;
}

export interface Previsita {
  doctor: string;
  doctor_id: number;
  fecha: string;
  dia_de_la_semana: string;
  total: number;
  primera_vez: number;
  sin_confirmar: number;
  pacientes: FichaPaciente[];
  // Armado en el servidor con los datos cargados, sin pasar por ningún
  // modelo: un resumen "redactado" puede afirmar algo que el doctor nunca
  // escribió.
  texto: string;
}

export interface Ausencia {
  id: number;
  doctor_id: number | null; // null = cierra la institución entera
  desde: string;
  hasta: string;
  motivo: string;
}

export interface EspecialidadPadron {
  // El padrón escribe la misma especialidad de varias formas. `clave` es la
  // forma normalizada con la que se busca; `etiqueta` es la más usada, que es
  // la que se le muestra a la gente.
  clave: string;
  etiqueta: string;
  cantidad: number;
}

export interface RegistryMatch {
  registry_id: number;
  full_name: string;
  specialty: string;
  cert_number: string;
  expires_at: string | null;
  vigente: boolean;
}

export interface ImportRow {
  name: string;
  specialty: string;
  schedule: string;
  phone: string;
  email: string;
  ya_cargado: boolean;
  // El mismo nombre en el padrón. `sugerencias` son parecidos, por si la
  // planilla trae el nombre incompleto o mal escrito.
  padron: RegistryMatch | null;
  sugerencias: RegistryMatch[];
}

export interface ImportPreview {
  archivo: string;
  total: number;
  en_padron: number;
  ya_cargados: number;
  filas: ImportRow[];
}

export interface ImportResult {
  creados: { id: number; name: string; verification: string; cert_number: string }[];
  omitidos: { name: string; motivo: string }[];
  verificados: number;
  no_figuran: number;
}

export interface Appointment {
  id: number;
  doctor_id: number;
  patient_name: string;
  patient_phone: string;
  scheduled_at: string;
  status: string;
  /** Por qué convenio viene. null = particular. Define en qué planilla de
   *  honorarios cae la atención, así que un dato que falta acá es plata que
   *  el profesional no puede cobrar. */
  insurer_id: number | null;
  notes: string;
}

export interface DashboardData {
  company: Company;
  agents_active: number;
  agents_total: number;
  doctors: number;
  appointments_today: number;
  conversations: number;
  products?: number;
  services?: number;
}

export interface DashboardSeries {
  activity: { date: string; count: number }[];
  appointments_by_status: Record<string, number>;
  has_booking: boolean;
}

export interface DailySummary {
  doctor: string;
  date: string;
  count: number;
  text: string;
}

// La sesión vive en una cookie HttpOnly puesta por el backend: el token
// nunca es accesible desde JavaScript (un XSS ya no se lo lleva).
let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

export interface BloqueoInfo {
  modulo: string; bloque: string; bloque_nombre: string; motivo: string;
}

let onBlocked: ((info: BloqueoInfo) => void) | null = null;

/**
 * Qué hacer cuando la API contesta "esa función es de un bloque que no
 * contrataste" (402). Se avisa en UN solo lugar, igual que el 401: si cada
 * pantalla tuviera que acordarse, la que se olvide muestra un error crudo.
 */
export const setBlockedHandler = (fn: (info: BloqueoInfo) => void) => {
  onBlocked = fn;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (resp.status === 401) {
    onUnauthorized?.();
    throw new Error("Sesión expirada. Ingresá de nuevo.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const error = new ApiError(resp.status, body.detail);
    const bloqueado = esModuloNoContratado(error);
    if (bloqueado) onBlocked?.(bloqueado);
    throw error;
  }
  return resp.status === 204 ? (undefined as T) : resp.json();
}

/**
 * Error de la API con el detalle ESTRUCTURADO, no solo el texto.
 *
 * FastAPI puede devolver `detail` como objeto —por ejemplo el 409 al agendar
 * fuera de horario, que trae el motivo, los horarios libres y si se puede
 * forzar—. Con `new Error(detail)` eso quedaba en "[object Object]" y la
 * pantalla no podía ofrecer nada.
 */
export class ApiError extends Error {
  status: number;
  detail: any;

  constructor(status: number, detail: any) {
    super(
      typeof detail === "string" ? detail
        : detail?.motivo ?? `Error ${status}`
    );
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Si el error vino de la API, sin usar `instanceof`.
 *
 * `instanceof` falla cuando el módulo se cargó dos veces —pasa con el
 * hot-reload en desarrollo— y el error queda sin manejar sin que nada avise.
 * Mirar la forma del objeto es a prueba de eso.
 */
export function esErrorApi(err: unknown): err is ApiError {
  return typeof err === "object" && err !== null && "status" in err && "detail" in err;
}

/**
 * El error es "esta empresa no contrató ese bloque" (402).
 *
 * Se mira el `codigo`, NUNCA el texto: el mensaje está para el humano y va a
 * cambiar. Ya se desarmó una guardia sola porque alguien mejoró la redacción
 * del mensaje que esa guardia comparaba.
 */
export function esModuloNoContratado(err: unknown): false | BloqueoInfo {
  if (!esErrorApi(err) || err.status !== 402) return false;
  const d = err.detail;
  if (typeof d !== "object" || d === null || d.codigo !== "modulo_no_contratado") return false;
  return d;
}

async function upload<T>(path: string, archivo: File): Promise<T> {
  const cuerpo = new FormData();
  cuerpo.append("archivo", archivo);
  // Sin `Content-Type`: el navegador tiene que ponerlo con su propio boundary.
  const resp = await fetch(`/api${path}`, {
    method: "POST", credentials: "same-origin", body: cuerpo,
  });
  if (resp.status === 401) {
    onUnauthorized?.();
    throw new Error("Sesión expirada. Ingresá de nuevo.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `Error ${resp.status}`);
  }
  return resp.json();
}

export interface Me {
  user: { id: number | null; email: string; full_name: string };
  is_platform_admin: boolean;
  memberships: { company_id: number; name: string; role: string }[];
}

export const auth = {
  login: (email: string, password: string) =>
    request<Me>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  /** Cambia la propia clave y cierra las demás sesiones. */
  cambiarClave: (actual: string, nueva: string) =>
    request<{ ok: boolean; sesiones_cerradas: number }>("/auth/password", {
      method: "POST", body: JSON.stringify({ actual, nueva }),
    }),
  me: () => request<Me>("/auth/me"),
};


export const api = {
  listCompanies: () => request<Company[]>("/companies"),
  /** El catálogo de bloques. No es por empresa: es lo que vendemos. */
  bloques: () => request<Bloque[]>("/packs"),
  /** Contrata bloques. Solo el operador de la plataforma (403 si no). */
  setPacks: (companyId: number, packs: string[]) =>
    request<Company>(`/companies/${companyId}/packs`, {
      method: "PUT",
      body: JSON.stringify({ packs }),
    }),
  createCompany: (name: string, vertical: string) =>
    request<Company>("/companies", { method: "POST", body: JSON.stringify({ name, vertical }) }),
  createCompanySmart: (name: string, description: string, website: string) =>
    request<Company>("/companies/smart", {
      method: "POST",
      body: JSON.stringify({ name, description, website }),
    }),
  dashboard: (companyId: number) => request<DashboardData>(`/companies/${companyId}/dashboard`),
  dashboardSeries: (companyId: number) =>
    request<DashboardSeries>(`/companies/${companyId}/dashboard/series`),
  listAgents: (companyId: number) => request<AgentSummary[]>(`/companies/${companyId}/agents`),
  supervisionReport: (companyId: number) =>
    request<SupervisionReport>(`/companies/${companyId}/supervision`),
  getAgent: (agentId: number) => request<AgentDetail>(`/agents/${agentId}`),
  updateAgent: (agentId: number, data: Partial<AgentDetail>) =>
    request<AgentDetail>(`/agents/${agentId}`, { method: "PATCH", body: JSON.stringify(data) }),
  listDoctors: (companyId: number) => request<Doctor[]>(`/companies/${companyId}/doctors`),
  createDoctor: (companyId: number, data: Omit<Doctor, "id">) =>
    request<Doctor>(`/companies/${companyId}/doctors`, { method: "POST", body: JSON.stringify(data) }),
  buscarPadron: (companyId: number, q: string, specialty: string) =>
    request<{ resultados: RegistryMatch[]; total: number; mostrados: number; hay_mas: boolean; nota: string }>(
      `/companies/${companyId}/registry/search?q=${encodeURIComponent(q)}&specialty=${encodeURIComponent(specialty)}`
    ),
  especialidadesPadron: (companyId: number) =>
    request<{ especialidades: EspecialidadPadron[] }>(`/companies/${companyId}/registry/specialties`),
  portalMe: (companyId: number) =>
    request<PortalMe>(`/companies/${companyId}/portal/me`),
  portalAgenda: (companyId: number, dia?: string) =>
    request<Previsita>(`/companies/${companyId}/portal/agenda${dia ? `?dia=${dia}` : ""}`),
  portalPacientes: (companyId: number, q = "") =>
    request<PortalPaciente[]>(
      `/companies/${companyId}/portal/pacientes${q ? `?q=${encodeURIComponent(q)}` : ""}`
    ),
  portalFicha: (companyId: number, telefono: string, nombre: string) =>
    request<FichaCompleta>(
      `/companies/${companyId}/portal/pacientes/ficha?telefono=${encodeURIComponent(telefono)}` +
      `&nombre=${encodeURIComponent(nombre)}`
    ),
  previewHonorarios: (companyId: number, desde: string, hasta: string) =>
    request<PreviewHonorarios>(
      `/companies/${companyId}/portal/honorarios/preview?desde=${desde}&hasta=${hasta}`
    ),
  armarHonorarios: (companyId: number, desde: string, hasta: string) =>
    request<Planilla[]>(
      `/companies/${companyId}/portal/honorarios?desde=${desde}&hasta=${hasta}`,
      { method: "POST" }
    ),
  listarHonorarios: (companyId: number) =>
    request<Planilla[]>(`/companies/${companyId}/portal/honorarios`),
  verHonorarios: (companyId: number, id: number) =>
    request<Planilla>(`/companies/${companyId}/portal/honorarios/${id}`),
  borrarHonorarios: (companyId: number, id: number) =>
    request<void>(`/companies/${companyId}/portal/honorarios/${id}`, { method: "DELETE" }),
  avanzarPlanilla: (companyId: number, id: number, paso: "firmar" | "entregar" | "pagar") =>
    request<Planilla>(`/companies/${companyId}/portal/honorarios/${id}/${paso}`, {
      method: "POST", body: JSON.stringify({}),
    }),
  /** Corrige el monto de un renglón del borrador. */
  ajustarRenglon: (companyId: number, batchId: number, itemId: number, facturado_gs: number, motivo: string) =>
    request<Planilla>(`/companies/${companyId}/portal/honorarios/${batchId}/items/${itemId}`, {
      method: "PATCH", body: JSON.stringify({ facturado_gs, motivo }),
    }),
  honorariosAPagar: (companyId: number) =>
    request<Planilla[]>(`/companies/${companyId}/portal/honorarios-a-pagar`),
  portalAccesos: (companyId: number) =>
    request<AccesoProfesional[]>(`/companies/${companyId}/portal/accesos`),
  crearAcceso: (companyId: number, doctorId: number, email: string) =>
    request<{ email: string; doctor: string; clave_temporal: string; aviso: string }>(
      `/companies/${companyId}/portal/accesos`,
      { method: "POST", body: JSON.stringify({ doctor_id: doctorId, email }) }
    ),
  previsita: (companyId: number, doctorId: number, onDate?: string) =>
    request<Previsita>(
      `/companies/${companyId}/doctors/${doctorId}/pre-visit${onDate ? `?on_date=${onDate}` : ""}`
    ),
  enviarPrevisita: (companyId: number, doctorId: number, onDate?: string) =>
    request<{ enviado: boolean; motivo: string; pacientes: number }>(
      `/companies/${companyId}/doctors/${doctorId}/pre-visit/send`,
      { method: "POST", body: JSON.stringify({ on_date: onDate ?? null }) }
    ),
  verHorario: (companyId: number, doctorId: number) =>
    request<HorarioDoctor>(`/companies/${companyId}/doctors/${doctorId}/schedule`),
  guardarHorario: (companyId: number, doctorId: number, franjas: Franja[]) =>
    request<ResultadoHorario>(`/companies/${companyId}/doctors/${doctorId}/schedule`, {
      method: "PUT", body: JSON.stringify({ franjas }),
    }),
  verHorarioClinica: (companyId: number) =>
    request<{ franjas: Franja[]; nota: string }>(`/companies/${companyId}/clinic-schedule`),
  guardarHorarioClinica: (companyId: number, franjas: Franja[]) =>
    request<{ franjas: number }>(`/companies/${companyId}/clinic-schedule`, {
      method: "PUT", body: JSON.stringify({ franjas }),
    }),
  listarAusencias: (companyId: number) =>
    request<Ausencia[]>(`/companies/${companyId}/absences`),
  crearAusencia: (companyId: number, data: Omit<Ausencia, "id">) =>
    request<{ id: number; citas_afectadas: CitaFueraDeHorario[] }>(
      `/companies/${companyId}/absences`, { method: "POST", body: JSON.stringify(data) }
    ),
  borrarAusencia: (companyId: number, id: number) =>
    request<void>(`/companies/${companyId}/absences/${id}`, { method: "DELETE" }),
  reverificarDoctores: (companyId: number) =>
    request<{ total: number; por_estado: Record<string, number> }>(
      `/companies/${companyId}/doctors/verify-all`, { method: "POST" }
    ),
  altaDesdePadron: (companyId: number, data: { registry_id: number; schedule?: string; phone?: string; email?: string }) =>
    request<{ id: number; name: string; verification: string; cert_number: string }>(
      `/companies/${companyId}/doctors/from-registry`, { method: "POST", body: JSON.stringify(data) }
    ),
  previsualizarPlanilla: (companyId: number, archivo: File) =>
    upload<ImportPreview>(`/companies/${companyId}/doctors/import/preview`, archivo),
  confirmarPlanilla: (companyId: number, profesionales: Partial<Doctor>[]) =>
    request<ImportResult>(`/companies/${companyId}/doctors/import/confirm`, {
      method: "POST", body: JSON.stringify({ profesionales }),
    }),
  listAppointments: (companyId: number, doctorId?: number) =>
    request<Appointment[]>(
      `/companies/${companyId}/appointments${doctorId ? `?doctor_id=${doctorId}` : ""}`
    ),
  createAppointment: (
    companyId: number,
    data: Omit<Appointment, "id" | "status">,
    // Sobreturno o caso especial: salta la validación de horario. Va por query
    // porque el servidor arma la fila con el cuerpo entero.
    forzar = false,
  ) =>
    request<Appointment>(
      `/companies/${companyId}/appointments${forzar ? "?forzar=true" : ""}`,
      { method: "POST", body: JSON.stringify(data) },
    ),
  updateAppointmentStatus: (companyId: number, apptId: number, status: string) =>
    request<Appointment>(`/companies/${companyId}/appointments/${apptId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  dailySummary: (companyId: number, doctorId: number, onDate?: string) =>
    request<DailySummary>(
      `/companies/${companyId}/doctors/${doctorId}/daily-summary${onDate ? `?on_date=${onDate}` : ""}`
    ),
};

export interface Conversation {
  id: number;
  channel: string;
  contact_phone: string;
  contact_name: string;
  status: string;
}

export interface ChatMessage {
  id: number;
  direction: "in" | "out";
  body: string;
  created_at: string;
}

export interface ChatResponse {
  conversation_id: number;
  reply: string | null;
  status: string;
  actions?: { tool: string; args: Record<string, unknown>; result: Record<string, unknown> }[];
  error?: string;
}

export interface PasoDeCanal {
  paso: string;
  // null = no se puede verificar desde el servidor (ej. el webhook en Meta).
  ok: boolean | null;
  detalle: string;
  donde: string;
}

export interface DiagnosticoCanal {
  mode: string;
  canal: string;
  oficial: boolean;
  advertencia: string;
  listo: boolean;
  pasos: PasoDeCanal[];
  // Lo que el canal permite DE VERDAD. WhatsApp Web no manda campañas ni
  // plantillas: prometerlo termina con el número del cliente restringido.
  puede_enviar_proactivo: boolean;
  puede_plantillas: boolean;
}

export const waApi = {
  updateCompany: (companyId: number, data: { wa_mode?: string; wa_phone_number_id?: string; address?: string; supervision?: string; supervision_pct?: number }) =>
    request<Company>(`/companies/${companyId}`, { method: "PATCH", body: JSON.stringify(data) }),
  status: (companyId: number) => request<WaStatus>(`/companies/${companyId}/wa/status`),
  start: (companyId: number) => request<WaStatus>(`/companies/${companyId}/wa/start`, { method: "POST" }),
  logout: (companyId: number) => request<WaStatus>(`/companies/${companyId}/wa/logout`, { method: "POST" }),
  diagnostico: (companyId: number) =>
    request<DiagnosticoCanal>(`/companies/${companyId}/wa/diagnostico`),
};

export const clinicalApi = {
  listInsurers: (companyId: number) => request<Insurer[]>(`/companies/${companyId}/insurers`),
  /** Qué tiene cargado un convenio, práctica por práctica. */
  coberturas: (companyId: number, insurerId: number) =>
    request<CoberturaDePractica[]>(`/companies/${companyId}/insurers/${insurerId}/coverage`),
  /** Carga o corrige el arancel de una práctica en ese convenio. */
  setCobertura: (
    companyId: number, insurerId: number,
    data: { service_id: number; coverage_pct: number; copay_gs: number; excluded: boolean; arancel_gs: number },
  ) =>
    request<{ ok: boolean }>(`/companies/${companyId}/insurers/${insurerId}/coverage`, {
      method: "PUT", body: JSON.stringify(data),
    }),
  createInsurer: (companyId: number, data: { name: string; plan: string; coverage_pct: number; copay_gs: number }) =>
    request<{ id: number }>(`/companies/${companyId}/insurers`, { method: "POST", body: JSON.stringify(data) }),
  listPrescriptions: (companyId: number) =>
    request<Prescription[]>(`/companies/${companyId}/prescriptions`),
  createPrescription: (companyId: number, data: Record<string, unknown>) =>
    request<Prescription & { recordatorios: RecordatoriosResult }>(
      `/companies/${companyId}/prescriptions`, { method: "POST", body: JSON.stringify(data) }),
  cancelPrescription: (companyId: number, id: number) =>
    request<{ ok: boolean }>(`/companies/${companyId}/prescriptions/${id}/cancel`, { method: "POST" }),
  verifyDoctors: (companyId: number) =>
    request<{ total: number; por_estado: Record<string, number>; nota: string }>(
      `/companies/${companyId}/doctors/verify`, { method: "POST" }),
};

export interface Report {
  id: number;
  kind: string;
  title: string;
  content: string;
  created_at: string;
}

export interface Finding {
  id: number;
  conversation_id: number;
  severity: string;
  note: string;
  created_at: string;
}

export interface Competitor {
  id: number;
  url: string;
  label: string;
}

export const intelApi = {
  listReports: (companyId: number) => request<Report[]>(`/companies/${companyId}/reports`),
  generateWeekly: (companyId: number) =>
    request<Report>(`/companies/${companyId}/reports/weekly`, { method: "POST" }),
  generateCompetitive: (companyId: number) =>
    request<Report>(`/companies/${companyId}/reports/competitive`, { method: "POST" }),
  runAudit: (companyId: number) =>
    request<{ new_findings: number }>(`/companies/${companyId}/audits/run`, { method: "POST" }),
  listAudits: (companyId: number) => request<Finding[]>(`/companies/${companyId}/audits`),
  listCompetitors: (companyId: number) => request<Competitor[]>(`/companies/${companyId}/competitors`),
  researchSegments: (companyId: number, website: string) =>
    request<Report>(`/companies/${companyId}/segments/research`, {
      method: "POST",
      body: JSON.stringify({ website }),
    }),
  runOptimizer: (companyId: number) =>
    request<{ new_suggestions: number }>(`/companies/${companyId}/prompt-suggestions/run`, { method: "POST" }),
  listSuggestions: (companyId: number) =>
    request<PromptSuggestion[]>(`/companies/${companyId}/prompt-suggestions`),
  applySuggestion: (companyId: number, id: number) =>
    request<{ applied: boolean }>(`/companies/${companyId}/prompt-suggestions/${id}/apply`, { method: "POST" }),
  rejectSuggestion: (companyId: number, id: number) =>
    request<{ rejected: boolean }>(`/companies/${companyId}/prompt-suggestions/${id}/reject`, { method: "POST" }),
  addCompetitor: (companyId: number, url: string, label: string) =>
    request<Competitor>(`/companies/${companyId}/competitors`, {
      method: "POST",
      body: JSON.stringify({ url, label }),
    }),
  deleteCompetitor: (companyId: number, id: number) =>
    request<void>(`/companies/${companyId}/competitors/${id}`, { method: "DELETE" }),
};

export interface Creative {
  id: number;
  brief: string;
  copy_text: string;
  image_prompt: string;
  image_path: string;
  provider: string;
  created_at: string;
}

export const creativeApi = {
  list: (companyId: number) => request<Creative[]>(`/companies/${companyId}/creatives`),
  create: (companyId: number, brief: string) =>
    request<Creative>(`/companies/${companyId}/creatives`, {
      method: "POST",
      body: JSON.stringify({ brief }),
    }),
  remove: (companyId: number, id: number) =>
    request<void>(`/companies/${companyId}/creatives/${id}`, { method: "DELETE" }),
};

export interface CampaignCard {
  position: number;
  headline: string;
  copy: string;
  visual: string;
  image_path: string;
}

export interface Campaign {
  id: number;
  title: string;
  brief: string;
  format: string;
  strategy: { title?: string; angle?: string; audience?: string };
  cards: CampaignCard[];
  audit_severity: string;
  audit_note: string;
  status: string;
  created_at: string;
}

export const campaignApi = {
  list: (companyId: number) => request<Campaign[]>(`/companies/${companyId}/campaigns`),
  create: (companyId: number, brief: string, format: string, n_cards: number) =>
    request<Campaign>(`/companies/${companyId}/campaigns`, {
      method: "POST",
      body: JSON.stringify({ brief, format, n_cards }),
    }),
  remove: (companyId: number, id: number) =>
    request<void>(`/companies/${companyId}/campaigns/${id}`, { method: "DELETE" }),
};

export interface Service {
  id: number;
  name: string;
  category: string;
  description: string;
  price_gs: number;
  duration_min: number;
  active: boolean;
  doctors: { id: number; name: string }[];
}

export interface Product {
  id: number;
  name: string;
  brand: string;
  category: string;
  gender: string;
  price_gs: number;
  in_stock: boolean;
  image_path: string;
  active: boolean;
}

export interface ServiceSuggestion {
  name: string;
  category: string;
  typical_price_gs: number;
  duration_min: number;
  used_by: number;
}

export const catalogApi = {
  importFrom: (companyId: number, website: string) =>
    request<{ method: string; imported: number; updated: number; with_image: number }>(
      `/companies/${companyId}/catalog/import`,
      { method: "POST", body: JSON.stringify({ website }) }
    ),
  listProducts: (companyId: number) => request<Product[]>(`/companies/${companyId}/products`),
};

export const serviceApi = {
  suggestions: (companyId: number) =>
    request<ServiceSuggestion[]>(`/companies/${companyId}/services/suggestions`),
  list: (companyId: number) => request<Service[]>(`/companies/${companyId}/services`),
  create: (companyId: number, data: { name: string; category: string; price_gs: number; duration_min: number; doctor_ids: number[] }) =>
    request<Service>(`/companies/${companyId}/services`, { method: "POST", body: JSON.stringify(data) }),
  update: (companyId: number, id: number, data: Partial<{ price_gs: number; active: boolean; doctor_ids: number[] }>) =>
    request<Service>(`/companies/${companyId}/services/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  remove: (companyId: number, id: number) =>
    request<void>(`/companies/${companyId}/services/${id}`, { method: "DELETE" }),
};

export const chatApi = {
  send: (companyId: number, contactPhone: string, contactName: string, text: string) =>
    request<ChatResponse>(`/companies/${companyId}/chat`, {
      method: "POST",
      body: JSON.stringify({ contact_phone: contactPhone, contact_name: contactName, text }),
    }),
  listConversations: (companyId: number) =>
    request<Conversation[]>(`/companies/${companyId}/conversations`),
  listMessages: (companyId: number, convId: number) =>
    request<ChatMessage[]>(`/companies/${companyId}/conversations/${convId}/messages`),
};

export const STATUS_ES: Record<string, string> = {
  pending: "Pendiente",
  confirmed: "Confirmado",
  cancelled: "Cancelado",
  attended: "Atendido",
  no_show: "No asistió",
};

export const formatGs = (n: number) => `₲ ${n.toLocaleString("es-PY")}`;

// ─── CFO de Finanzas ─────────────────────────────────────────────────────

export interface CfoIdentidad {
  id: number;
  phone: string;
  nombre: string;
  sensibilidad_max: "baja" | "media" | "alta";
  /** Si TIENE PIN, no cuál es: el valor nunca sale del servidor. */
  tiene_pin: boolean;
  pin_bloqueado: boolean;
  activo: boolean;
  ultimo_uso_at: string | null;
}

export interface CfoMetrica {
  clave: string;
  nombre: string;
  formula: string;
  version: number;
  estado: string;
  fuentes: string[];
  /** Qué fuentes le faltan para poder calcularse. Vacío = se puede. */
  faltan: string[];
  excluye?: string;
  notas_contables?: string;
  aprobada_por?: string | null;
  vigente_desde?: string | null;
}

export interface CfoConector {
  id: number;
  fuente: string;
  tipo: string;
  nombre: string;
  activo: boolean;
  ultima_sync: string | null;
  ultima_sync_ok: boolean;
  ultimo_error: string;
  filas_ultima_sync: number;
  filas_totales: number;
  /** Conectado NO es disponible: cuenta cuando trajo filas alguna vez. */
  habilita_la_fuente: boolean;
}

export interface CfoFuente {
  fuente: string;
  disponible: boolean;
  corte: string | null;
  interna: boolean;
}

export interface CfoInforme {
  id: number;
  titulo: string;
  desde: string;
  hasta: string;
  creado: string;
  enlaces_vigentes: number;
  aperturas: number;
  ultima_apertura: string | null;
}

export interface CfoInformeCreado {
  id: number;
  titulo: string;
  /** Se muestra UNA sola vez. Después queda el hash y hay que emitir otro. */
  enlace: string;
  vence_en_horas: number;
  un_solo_uso: boolean;
  aviso: string;
}

export interface CfoMemoria {
  id: number;
  tipo: string;
  clave: string;
  valor: string;
  phone: string;
  fuente: string;
  vence: string | null;
  actualizada: string | null;
}

export const cfoApi = {
  identidades: (c: number) => request<CfoIdentidad[]>(`/companies/${c}/cfo/identidades`),
  crearIdentidad: (c: number, data: { phone: string; nombre: string; sensibilidad_max: string }) =>
    request<CfoIdentidad>(`/companies/${c}/cfo/identidades`, {
      method: "POST", body: JSON.stringify(data),
    }),
  editarIdentidad: (c: number, id: number, data: Partial<CfoIdentidad>) =>
    request<CfoIdentidad>(`/companies/${c}/cfo/identidades/${id}`, {
      method: "PATCH", body: JSON.stringify(data),
    }),
  ponerPin: (c: number, id: number, pin: string) =>
    request<{ ok: boolean }>(`/companies/${c}/cfo/identidades/${id}/pin`, {
      method: "PUT", body: JSON.stringify({ pin }),
    }),
  quitarIdentidad: (c: number, id: number) =>
    request<void>(`/companies/${c}/cfo/identidades/${id}`, { method: "DELETE" }),

  metricas: (c: number) => request<CfoMetrica[]>(`/companies/${c}/cfo/metricas`),
  aprobar: (c: number, clave: string, version: number) =>
    request<CfoMetrica>(`/companies/${c}/cfo/metricas/${clave}/aprobar`, {
      method: "POST", body: JSON.stringify({ version }),
    }),
  deprecar: (c: number, clave: string) =>
    request<CfoMetrica>(`/companies/${c}/cfo/metricas/${clave}/deprecar`, { method: "POST" }),

  conectores: (c: number) => request<CfoConector[]>(`/companies/${c}/cfo/conectores`),
  crearConector: (c: number, data: { fuente: string; tipo: string; nombre: string }) =>
    request<CfoConector>(`/companies/${c}/cfo/conectores`, {
      method: "POST", body: JSON.stringify(data),
    }),
  editarConector: (c: number, id: number, data: { activo?: boolean }) =>
    request<CfoConector>(`/companies/${c}/cfo/conectores/${id}`, {
      method: "PATCH", body: JSON.stringify(data),
    }),
  borrarConector: (c: number, id: number) =>
    request<void>(`/companies/${c}/cfo/conectores/${id}`, { method: "DELETE" }),
  /** La planilla va como multipart, así que no pasa por `request`. */
  cargarPlanilla: async (c: number, id: number, archivo: File) => {
    const fd = new FormData();
    fd.append("archivo", archivo);
    const resp = await fetch(`/api/companies/${c}/cfo/conectores/${id}/cargar`, {
      method: "POST", credentials: "same-origin", body: fd,
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new ApiError(resp.status, body.detail);
    return body as { nuevas: number; actualizadas: number; leidas: number };
  },
  fuentes: (c: number) => request<CfoFuente[]>(`/companies/${c}/cfo/fuentes`),

  informes: (c: number) => request<CfoInforme[]>(`/companies/${c}/cfo/informes`),
  crearInforme: (c: number, data: {
    metricas: string[]; desde: string; hasta: string; titulo: string;
    un_solo_uso: boolean; horas_de_vigencia: number;
  }) =>
    request<CfoInformeCreado>(`/companies/${c}/cfo/informes`, {
      method: "POST", body: JSON.stringify(data),
    }),
  revocarInforme: (c: number, id: number) =>
    request<{ revocados: number }>(`/companies/${c}/cfo/informes/${id}/revocar`, {
      method: "POST",
    }),

  memoria: (c: number) => request<CfoMemoria[]>(`/companies/${c}/cfo/memoria`),
  borrarMemoria: (c: number, id: number) =>
    request<void>(`/companies/${c}/cfo/memoria/${id}`, { method: "DELETE" }),
  borrarTodaLaMemoria: (c: number) =>
    request<{ borradas: number }>(`/companies/${c}/cfo/memoria`, { method: "DELETE" }),
};

/** Nombres de fuente en castellano, para no mostrar `caja_y_bancos`. */
export const FUENTES_ES: Record<string, string> = {
  ventas: "Ventas / facturación",
  cobranzas: "Cobranzas",
  compras: "Compras",
  gastos: "Gastos",
  inventario: "Inventario",
  caja_y_bancos: "Caja y bancos",
  impuestos: "Impuestos",
  metas: "Metas",
  nomina: "Nómina",
  interna: "Del propio sistema",
};

export const RIESGO_ES: Record<string, string> = {
  baja: "Básico",
  media: "Sensible",
  alta: "Crítico",
};

// ─── Planes y consumo ────────────────────────────────────────────────────

export interface PlanCatalogo {
  clave: string;
  nombre: string;
  descripcion: string;
  mensajes_por_mes: number;
  informes_por_mes: number;
  identidades_cfo: number;
  conectores: number;
  precio_gs: number;
  /** A partir de este volumen conviene que el cliente ponga su propia clave. */
  clave_propia: boolean;
}

export interface ConsumoPorModelo {
  modelo: string;
  turnos: number;
  tokens_entrada: number;
  tokens_salida: number;
  costo_gs: number;
  /** No es que operarlo sea gratis: es que no se factura por token. */
  gratuito: boolean;
}

export interface Consumo {
  plan: { clave: string; nombre: string; precio_gs: number; clave_propia: boolean };
  desde: string;
  mensajes: { usados: number; tope: number; restantes: number };
  informes: { usados: number; tope: number; restantes: number };
  consumo_de_ia: { por_modelo: ConsumoPorModelo[]; tokens: number; costo_gs: number };
  /** "plataforma" = lo paga MetaBot. "propia" = lo paga el cliente. */
  clave_en_uso: "plataforma" | "propia";
}

export const planesApi = {
  catalogo: () => request<PlanCatalogo[]>("/planes"),
  consumo: (c: number) => request<Consumo>(`/companies/${c}/consumo`),
  cambiarPlan: (c: number, plan: string) =>
    request<Consumo>(`/companies/${c}/plan`, {
      method: "PUT", body: JSON.stringify({ plan }),
    }),
  solicitarClave: (c: number) =>
    request<{ ya_tiene: boolean; aviso?: string }>(
      `/companies/${c}/clave-openai/solicitar`, { method: "POST" }),
};
