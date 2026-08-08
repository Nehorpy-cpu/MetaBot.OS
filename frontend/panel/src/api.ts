export interface Company {
  id: number;
  name: string;
  vertical: "medical" | "ecommerce";
  niche: string;
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

export const STATUS_ES: Record<string, string> = {
  pending: "Pendiente",
  confirmed: "Confirmado",
  cancelled: "Cancelado",
  attended: "Atendido",
  no_show: "No asistió",
};

export const formatGs = (n: number) => `₲ ${n.toLocaleString("es-PY")}`;
