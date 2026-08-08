export interface Company {
  id: number;
  name: string;
  vertical: string;
  niche: string;
  industry: string;
  wa_mode: "none" | "meta" | "qr";
  wa_phone_number_id: string;
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
}

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
}

export interface Appointment {
  id: number;
  doctor_id: number;
  patient_name: string;
  patient_phone: string;
  scheduled_at: string;
  status: string;
  notes: string;
}

export interface DashboardData {
  company: Company;
  agents_active: number;
  agents_total: number;
  doctors: number;
  appointments_today: number;
  conversations: number;
}

export interface DailySummary {
  doctor: string;
  date: string;
  count: number;
  text: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `Error ${resp.status}`);
  }
  return resp.status === 204 ? (undefined as T) : resp.json();
}

export const api = {
  listCompanies: () => request<Company[]>("/companies"),
  createCompany: (name: string, vertical: string) =>
    request<Company>("/companies", { method: "POST", body: JSON.stringify({ name, vertical }) }),
  createCompanySmart: (name: string, description: string, website: string) =>
    request<Company>("/companies/smart", {
      method: "POST",
      body: JSON.stringify({ name, description, website }),
    }),
  dashboard: (companyId: number) => request<DashboardData>(`/companies/${companyId}/dashboard`),
  listAgents: (companyId: number) => request<AgentSummary[]>(`/companies/${companyId}/agents`),
  getAgent: (agentId: number) => request<AgentDetail>(`/agents/${agentId}`),
  updateAgent: (agentId: number, data: Partial<AgentDetail>) =>
    request<AgentDetail>(`/agents/${agentId}`, { method: "PATCH", body: JSON.stringify(data) }),
  listDoctors: (companyId: number) => request<Doctor[]>(`/companies/${companyId}/doctors`),
  createDoctor: (companyId: number, data: Omit<Doctor, "id">) =>
    request<Doctor>(`/companies/${companyId}/doctors`, { method: "POST", body: JSON.stringify(data) }),
  listAppointments: (companyId: number, doctorId?: number) =>
    request<Appointment[]>(
      `/companies/${companyId}/appointments${doctorId ? `?doctor_id=${doctorId}` : ""}`
    ),
  createAppointment: (companyId: number, data: Omit<Appointment, "id" | "status">) =>
    request<Appointment>(`/companies/${companyId}/appointments`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
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

export const waApi = {
  updateCompany: (companyId: number, data: { wa_mode?: string; wa_phone_number_id?: string }) =>
    request<Company>(`/companies/${companyId}`, { method: "PATCH", body: JSON.stringify(data) }),
  status: (companyId: number) => request<WaStatus>(`/companies/${companyId}/wa/status`),
  start: (companyId: number) => request<WaStatus>(`/companies/${companyId}/wa/start`, { method: "POST" }),
  logout: (companyId: number) => request<WaStatus>(`/companies/${companyId}/wa/logout`, { method: "POST" }),
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

export const serviceApi = {
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
