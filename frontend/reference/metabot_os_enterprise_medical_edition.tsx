import React, { useState, useEffect } from 'react';
import { 
  Command, BarChart3, ShieldCheck, PenTool, Video, MessageSquare, 
  Settings, Network, Server, Sliders, X, Plus, ChevronDown, 
  Activity, Zap, LayoutDashboard, Globe, Users, CheckCircle, RefreshCw,
  Terminal, Send, Bot, MessageCircle, Instagram, CreditCard, AlertTriangle, Headset,
  CreditCard as BillingIcon, PieChart, Cpu, Smartphone, Sparkles,
  Facebook, Link2, Shield, Key, Palette, Image as ImageIcon, UploadCloud, Wand2, CheckCircle2, Play, Fingerprint, Type,
  Mic, BookOpen, Calendar, Clock, UserCheck, Stethoscope, Building2, Check, ExternalLink, Download, MessageSquareText
} from 'lucide-react';

const getTemplateConfig = (vertical) => {
  if (vertical === 'medical') {
    return {
      nicheName: 'Clínica Médica / Consultorio Odontológico',
      agents: [
        { agentId: 1, name: 'CEO (Orquestador Clínico)', role: 'Gestión de Citas, Triaje & Leads', status: 'active', model: 'Nemotron-4-340B', iconName: 'Command', tasks: 'Orquestando agenda de médicos, odontólogos y pacientes en Paraguay', prompt: 'Sos el CEO Autónomo del centro médico u odontológico en Paraguay. Usá voseo y Jopara sutil (ej. "¡Hola, todo bien? Agendamos tu consulta..."). Tu prioridad es llenar la agenda de los doctores, responder consultas con empatía, validar especialidades y coordinar turnos vía WhatsApp.', temperature: 0.2, tools: [{ name: 'Medical RAG MCP', type: 'MCP', active: true, desc: 'Base de conocimiento de especialidades.', cost: 'Free' }, { name: 'WhatsApp Web-JS (QR)', type: 'API', active: true, desc: 'Atención a pacientes sin Meta Verified.', cost: 'Free' }] },
        { agentId: 2, name: 'Analista Quant Clínico', role: 'Métricas de Asistencia & ROI', status: 'active', model: 'Llama-3-70B', iconName: 'BarChart3', tasks: 'Analizando tasa de no-asistencia y picos de demanda', prompt: 'Analizá estadísticas de pacientes, cancelaciones y especialidades más solicitadas. Generá reportes semanales en Guaraníes (₲).', temperature: 0.3, tools: [{ name: 'Clinic Database MCP', type: 'MCP', active: true, desc: 'Historial de turnos.', cost: 'Free' }] },
        { agentId: 3, name: 'Auditor de Calidad Médica', role: 'Cumplimiento & Normativa Sanitaria', status: 'active', model: 'Nemotron-Guard-8B', iconName: 'ShieldCheck', tasks: 'Validando protocolos de atención y veracidad de síntomas', prompt: 'Auditoría de conversaciones médicas. Verificá que no se den diagnósticos definitivos por chat, derivando siempre a turnos presenciales.', temperature: 0.1, tools: [{ name: 'Medical Ethics RAG', type: 'MCP', active: true, desc: 'Protocolos de triaje.', cost: 'Free' }] },
        { agentId: 4, name: 'Director Creativo (Campañas Salud)', role: 'Estrategia de Anuncios de Salud', status: 'active', model: 'Mistral-Large-2', iconName: 'PenTool', tasks: 'Diseñando campañas de prevención y odontología', prompt: 'Redactá copys persuasivos para Meta Ads enfocados en prevención, estética dental o chequeos anuales. Usá voseo paraguayo.', temperature: 0.5, tools: [{ name: 'Meta Ads Manager API', type: 'API', active: true, desc: 'Lanzamiento de campañas.', cost: 'Free' }] },
        { agentId: 5, name: 'Estudio Visual & Avatares', role: 'Generación de Creativos Médicos', status: 'active', model: 'NVIDIA Edify / Picasso', iconName: 'Video', tasks: 'Creando imágenes limpias de consultorios y flyers', prompt: 'Generá prompts para NVIDIA Edify con estética clínica profesional, colores limpios y confianza.', temperature: 0.4, tools: [{ name: 'NVIDIA Edify API', type: 'API', active: true, desc: 'Generación de imágenes.', cost: 'Compute' }] },
        { agentId: 6, name: 'CX Bot (Triaje & WhatsApp)', role: 'Atención 24/7 de Pacientes', status: 'active', model: 'Llama-3-8B-Instruct', iconName: 'MessageSquare', tasks: 'Coordinando turnos y respondiendo dudas en Jopara', prompt: 'Atendé pacientes en WhatsApp. Si preguntan horarios o precios de consultas, respondé de inmediato en voseo y Jopara.', temperature: 0.3, tools: [{ name: 'WhatsApp Business API', type: 'API', active: true, desc: 'Mensajería automatizada.', cost: 'Free' }] }
      ],
      doctors: [
        { id: 'doc1', name: 'Dr. Juan Carlos Benítez', specialty: 'Cardiología & Medicina Interna', schedule: '08:00 - 12:00', phone: '+595 981 123456', email: 'jbenitez@medica.py' },
        { id: 'doc2', name: 'Dra. María Estigarribia', specialty: 'Pediatría & Vacunación', schedule: '14:00 - 18:00', phone: '+595 972 987654', email: 'mestigarribia@medica.py' },
        { id: 'doc3', name: 'Dr. Roberto Gamarra', specialty: 'Odontología General & Implantes', schedule: '09:00 - 17:00', phone: '+595 991 555444', email: 'rgamarra@medica.py' }
      ]
    };
  } else {
    return {
      nicheName: 'E-Commerce / B2B Retail',
      agents: [
        { agentId: 1, name: 'CEO (Orquestador)', role: 'Estrategia, Presupuesto & Routing', status: 'active', model: 'Nemotron-4-340B', iconName: 'Command', tasks: 'Optimizando ROAS de Meta Ads en Paraguay', prompt: 'Sos el CEO Autónomo. Maximizás el ROAS en Paraguay. Manejás presupuesto global en Guaraníes (₲).', temperature: 0.4, tools: [{ name: 'Meta Business Admin', type: 'API', active: true, desc: 'Control de campañas.', cost: 'Free' }] },
        { agentId: 2, name: 'Analista Quant', role: 'Atribución de Ventas & CPA', status: 'active', model: 'Llama-3-70B', iconName: 'BarChart3', tasks: 'Monitoreando conversiones y costo por adquisición', prompt: 'Analizá el retorno publicitario de las campañas de Meta.', temperature: 0.3, tools: [{ name: 'Meta Graph API', type: 'API', active: true, desc: 'Métricas de anuncios.', cost: 'Free' }] },
        { agentId: 3, name: 'Auditor de Calidad', role: 'Compliance de Anuncios Meta', status: 'active', model: 'Nemotron-Guard-8B', iconName: 'ShieldCheck', tasks: 'Revisando políticas de Facebook Ads', prompt: 'Auditoría estricta para evitar bloqueos de cuentas publicitarias en Meta.', temperature: 0.1, tools: [{ name: 'Meta Policy RAG', type: 'MCP', active: true, desc: 'Reglas de anuncios.', cost: 'Free' }] },
        { agentId: 4, name: 'Director Creativo', role: 'Copywriting & Psicología de Venta', status: 'active', model: 'Mistral-Large-2', iconName: 'PenTool', tasks: 'Escribiendo copys con voseo paraguayo', prompt: 'Redactá copys publicitarios de alta conversión con voseo y Jopara.', temperature: 0.6, tools: [{ name: 'Meta Ad Library Scraper', type: 'MCP', active: true, desc: 'Tendencias de copys.', cost: 'Free' }] },
        { agentId: 5, name: 'Estudio Visual', role: 'Generación de Creativos & Videos', status: 'active', model: 'NVIDIA Edify / Picasso', iconName: 'Video', tasks: 'Generando imágenes de productos y banners', prompt: 'Creación de imágenes hiperrealistas para e-commerce.', temperature: 0.4, tools: [{ name: 'NVIDIA Edify API', type: 'API', active: true, desc: 'Generador visual.', cost: 'Compute' }] },
        { agentId: 6, name: 'CX & Sales Bot', role: 'Omnicanalidad & Cierre de Ventas', status: 'active', model: 'Llama-3-8B-Instruct', iconName: 'MessageSquare', tasks: 'Cierre de ventas vía WhatsApp y Bancar vPOS', prompt: 'Atención al cliente y ventas. Pasá link de cobro Bancar vPOS.', temperature: 0.3, tools: [{ name: 'Bancar vPOS / SIPAP', type: 'API', active: true, desc: 'Enlaces de pago locales.', cost: 'Tx Fee' }] }
      ],
      doctors: []
    };
  }
};

const getIcon = (name) => {
  const icons = { Command, BarChart3, ShieldCheck, PenTool, Video, MessageSquare, LayoutDashboard, Globe, Users, Settings, Calendar, Mic };
  return icons[name] || Activity;
};

const NewCompanyModal = ({ onClose, onSave }) => {
  const [name, setName] = useState('');
  const [vertical, setVertical] = useState('medical');
  const [isCreating, setIsCreating] = useState(false);

  const handleCreate = (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsCreating(true);
    setTimeout(() => {
      const template = getTemplateConfig(vertical);
      onSave({
        id: Date.now().toString(),
        name,
        vertical,
        niche: template.nicheName,
        agents: template.agents,
        doctors: template.doctors,
        appointments: vertical === 'medical' ? [
          { id: 1, patient: 'Ramón Duarte', doctor: 'Dr. Juan Carlos Benítez', time: '09:00', date: '2026-06-07', status: 'Confirmado', phone: '+595 982 111222', notes: 'Control de presión arterial' },
          { id: 2, patient: 'Fátima Acosta', doctor: 'Dra. María Estigarribia', time: '14:30', date: '2026-06-07', status: 'Pendiente', phone: '+595 971 333444', notes: 'Vacuración niño 2 años' }
        ] : []
      });
      setIsCreating(false);
      onClose();
    }, 1200);
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4 animate-in fade-in">
      <div className="bg-[#090b10] border border-white/10 rounded-2xl w-full max-w-xl shadow-2xl p-6 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-48 h-48 bg-cyan-500/10 blur-3xl rounded-full"></div>
        <div className="flex justify-between items-center mb-6 relative z-10">
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Building2 className="text-cyan-400" size={22}/> Nueva Empresa / Consultorio con IA Autónoma
          </h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white p-1 rounded-lg"><X size={20}/></button>
        </div>

        <form onSubmit={handleCreate} className="space-y-5 relative z-10">
          <div>
            <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-2">Nombre de la Empresa o Clínica</label>
            <input 
              type="text" 
              placeholder="Ej. Centro Médico San Roque o Odontología Asunción"
              value={name} 
              onChange={e => setName(e.target.value)}
              className="w-full bg-white/[0.03] border border-white/10 rounded-xl p-3 text-sm text-zinc-100 focus:outline-none focus:border-cyan-500 transition-colors"
              required
            />
          </div>

          <div>
            <label className="text-xs font-bold text-zinc-400 uppercase tracking-widest block mb-2">Tipo de Vertical (Define el Enjambre de Bots)</label>
            <div className="grid grid-cols-2 gap-4">
              <button 
                type="button"
                onClick={() => setVertical('medical')}
                className={`p-4 rounded-xl border text-left transition-all ${vertical === 'medical' ? 'bg-cyan-500/10 border-cyan-500/50 text-white shadow-lg' : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/[0.04]'}`}
              >
                <Stethoscope className="text-cyan-400 mb-2" size={24}/>
                <p className="font-bold text-sm">Consultorio / Sanatorio</p>
                <p className="text-[10px] text-zinc-500 mt-1">Agenda de médicos, triaje, WhatsApp y resúmenes diarios.</p>
              </button>
              <button 
                type="button"
                onClick={() => setVertical('ecommerce')}
                className={`p-4 rounded-xl border text-left transition-all ${vertical === 'ecommerce' ? 'bg-indigo-500/10 border-indigo-500/50 text-white shadow-lg' : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/[0.04]'}`}
              >
                <BarChart3 className="text-indigo-400 mb-2" size={24}/>
                <p className="font-bold text-sm">E-Commerce / Retail</p>
                <p className="text-[10px] text-zinc-500 mt-1">Campañas Meta Ads, IA de ventas y pasarela Bancar vPOS.</p>
              </button>
            </div>
          </div>

          <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-xl p-3 text-xs text-cyan-300 flex items-start gap-2">
            <Sparkles size={16} className="shrink-0 mt-0.5 text-cyan-400"/>
            <p>El CEO Autónomo configurará los 6 agentes especializados (CEO, Analista, Auditor, Creativo, Visual y CX Bot) adaptados al nicho seleccionado en Paraguay.</p>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-white/5">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button>
            <button 
              type="submit" 
              disabled={isCreating}
              className="px-6 py-2.5 bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white font-semibold rounded-xl text-sm flex items-center shadow-lg transition-all"
            >
              {isCreating ? <><RefreshCw className="mr-2 animate-spin" size={16}/> Inicializando...</> : 'Crear Enjambre y Empresa'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

const DashboardView = ({ company }) => {
  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="flex justify-between items-end">
        <div>
          <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest bg-cyan-500/10 px-2.5 py-1 rounded-full border border-cyan-500/20">{company?.niche}</span>
          <h2 className="text-3xl font-bold text-white tracking-tight mt-2">{company?.name}</h2>
          <p className="text-zinc-400 text-sm mt-1">Panel de control operativo e inteligencia de enjambre en tiempo real.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          { label: company?.vertical === 'medical' ? 'Pacientes Agendados (Hoy)' : 'Gasto Meta Ads (7d)', value: company?.vertical === 'medical' ? '12 Turnos' : '₲ 8.540.000', trend: 'Activo', color: 'text-white' },
          { label: company?.vertical === 'medical' ? 'Doctores Activos' : 'ROAS Global', value: company?.vertical === 'medical' ? `${company?.doctors?.length || 0} Médicos` : '3.42x', trend: 'Línea Verde', color: 'text-cyan-400' },
          { label: 'Conversaciones IA', value: '432 Atendidas', trend: '100% Automático', color: 'text-emerald-400' },
          { label: 'Estado del Sistema', value: 'Sincronizado', trend: 'NVIDIA NIM OK', color: 'text-indigo-400' },
        ].map((kpi, idx) => (
          <div key={idx} className="bg-[#07090e] border border-white/10 rounded-2xl p-5 hover:border-white/20 transition-all shadow-md">
            <h4 className="text-zinc-500 text-[10px] font-bold tracking-widest uppercase mb-2">{kpi.label}</h4>
            <div className="flex items-end justify-between">
              <span className={`text-2xl font-bold tracking-tight ${kpi.color}`}>{kpi.value}</span>
              <span className="text-[9px] px-2 py-0.5 rounded border border-white/10 bg-white/5 text-zinc-300 font-bold uppercase">{kpi.trend}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const MedicalAgendaView = ({ company }) => {
  const [selectedDoctor, setSelectedDoctor] = useState('all');
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [copied, setCopied] = useState(false);

  if (company?.vertical !== 'medical') {
    return (
      <div className="p-12 text-center space-y-4">
        <Stethoscope size={48} className="mx-auto text-zinc-600"/>
        <h3 className="text-xl font-bold text-white">Módulo No Habilitado para este Nicho</h3>
        <p className="text-zinc-400 text-sm max-w-md mx-auto">Esta empresa está configurada como E-Commerce. Para usar la agenda de consultorios, creá un nuevo perfil seleccionando la vertical de salud.</p>
      </div>
    );
  }

  const generateDailyTemplate = (doc) => {
    const docAppointments = (company.appointments || []).filter(a => selectedDoctor === 'all' || a.doctor === doc.name);
    let text = `📋 *AGENDA MÉDICA DIARIA - ${doc.name.toUpperCase()}*\n`;
    text += `📅 Fecha: ${new Date().toLocaleDateString('es-PY')}\n`;
    text += `━━━━━━━━━━━━━━━━━━━━━━━\n`;
    docAppointments.forEach((app, index) => {
      text += `${index + 1}. *Hora:* ${app.time} | *Paciente:* ${app.patient}\n   📞 Tel: ${app.phone} | *Motivo:* ${app.notes}\n\n`;
    });
    text += `_Enviado automáticamente por MetaBot OS - Asistente IA_`;
    return text;
  };

  const handleCopyTemplate = (doc) => {
    const templateText = generateDailyTemplate(doc);
    navigator.clipboard.writeText(templateText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <Calendar className="text-cyan-400" size={28}/> Gestión de Citas & Consultorios
          </h2>
          <p className="text-zinc-400 text-sm mt-1">Agenda centralizada, horarios de médicos y plantillas automáticas de fin de día.</p>
        </div>
        <button 
          onClick={() => setShowTemplateModal(true)}
          className="bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 text-white px-5 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 shadow-lg transition-all"
        >
          <Send size={16}/> Enviar Resumen Diario a Doctores (WhatsApp)
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-[#07090e] border border-white/10 rounded-2xl p-5 space-y-4 shadow-xl">
          <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest flex items-center gap-2">
            <Users size={16} className="text-indigo-400"/> Plantel Médicos / Odontólogos ({company.doctors?.length || 0})
          </h3>
          <div className="space-y-3">
            <div 
              onClick={() => setSelectedDoctor('all')}
              className={`p-3 rounded-xl border cursor-pointer transition-all ${selectedDoctor === 'all' ? 'bg-cyan-500/10 border-cyan-500/50 text-white' : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/[0.04]'}`}
            >
              <p className="font-bold text-sm">Todos los Consultorios</p>
              <p className="text-[10px] text-zinc-500">Vista general de citas</p>
            </div>
            {(company.doctors || []).map(doc => (
              <div 
                key={doc.id}
                onClick={() => setSelectedDoctor(doc.name)}
                className={`p-3 rounded-xl border cursor-pointer transition-all ${selectedDoctor === doc.name ? 'bg-cyan-500/10 border-cyan-500/50 text-white' : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/[0.04]'}`}
              >
                <div className="flex justify-between items-start">
                  <p className="font-bold text-sm text-zinc-100">{doc.name}</p>
                  <span className="text-[10px] bg-cyan-500/10 text-cyan-300 px-2 py-0.5 rounded font-mono">{doc.specialty}</span>
                </div>
                <p className="text-xs text-zinc-400 mt-2 flex items-center gap-1"><Clock size={12}/> Horario: {doc.schedule}</p>
                <p className="text-xs text-zinc-500 flex items-center gap-1 mt-1"><Smartphone size={12}/> {doc.phone}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-2 bg-[#07090e] border border-white/10 rounded-2xl p-5 space-y-4 shadow-xl flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-widest flex items-center gap-2">
                <Clock size={16} className="text-cyan-400"/> Turnos Programados
              </h3>
              <span className="text-xs font-mono text-zinc-500">Fecha: Hoy</span>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-zinc-300">
                <thead className="text-[10px] uppercase text-zinc-500 border-b border-white/5">
                  <tr>
                    <th className="pb-3">Hora</th>
                    <th className="pb-3">Paciente</th>
                    <th className="pb-3">Especialista Asignado</th>
                    <th className="pb-3">Estado</th>
                    <th className="pb-3 text-right">Acción</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {(company.appointments || [])
                    .filter(app => selectedDoctor === 'all' || app.doctor === selectedDoctor)
                    .map(app => (
                    <tr key={app.id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 font-mono font-bold text-cyan-400">{app.time}</td>
                      <td className="py-3 font-medium text-white">
                        {app.patient}
                        <span className="block text-[10px] text-zinc-500">{app.phone}</span>
                      </td>
                      <td className="py-3 text-xs text-zinc-300">{app.doctor}</td>
                      <td className="py-3">
                        <span className={`text-[10px] px-2.5 py-1 rounded-full border font-bold uppercase ${app.status === 'Confirmado' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border-amber-500/20'}`}>
                          {app.status}
                        </span>
                      </td>
                      <td className="py-3 text-right">
                        <button className="text-xs bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-lg border border-white/5 text-zinc-300">Detalle</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      {showTemplateModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4 animate-in fade-in">
          <div className="bg-[#090b10] border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl p-6 relative overflow-hidden">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Send className="text-cyan-400" size={18}/> Plantilla de Resumen Diario para Especialistas
              </h3>
              <button onClick={() => setShowTemplateModal(false)} className="text-zinc-500 hover:text-white"><X size={20}/></button>
            </div>
            
            <p className="text-xs text-zinc-400 mb-4">Esta plantilla es generada automáticamente por el CEO IA para enviársela al doctor por WhatsApp o permitirle agregarlo a su agenda privada.</p>

            <div className="space-y-4">
              {(company.doctors || []).map(doc => (
                <div key={doc.id} className="bg-white/[0.02] border border-white/5 rounded-xl p-4 space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="font-bold text-sm text-white">{doc.name} <span className="text-xs text-zinc-500 font-normal">({doc.phone})</span></span>
                    <button 
                      onClick={() => handleCopyTemplate(doc)}
                      className="text-xs bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors"
                    >
                      <Download size={14}/> {copied ? '¡Copiado!' : 'Copiar Agenda / Google Calendar'}
                    </button>
                  </div>
                  <pre className="bg-[#040609] p-3 rounded-lg text-xs font-mono text-zinc-300 whitespace-pre-wrap border border-white/5">
                    {generateDailyTemplate(doc)}
                  </pre>
                </div>
              ))}
            </div>

            <div className="flex justify-end pt-4 mt-4 border-t border-white/5">
              <button onClick={() => setShowTemplateModal(false)} className="px-5 py-2 bg-white/5 hover:bg-white/10 text-white text-sm rounded-xl">Cerrar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const App = () => {
  const [companies, setCompanies] = useState([
    { 
      id: '1', 
      name: 'Centro Médico & Odontológico Asunción', 
      vertical: 'medical', 
      niche: 'Clínica Médica / Consultorio Odontológico',
      agents: getTemplateConfig('medical').agents,
      doctors: getTemplateConfig('medical').doctors,
      appointments: [
        { id: 1, patient: 'Ramón Duarte', doctor: 'Dr. Juan Carlos Benítez', time: '09:00', date: '2026-06-07', status: 'Confirmado', phone: '+595 982 111222', notes: 'Control cardiológico' },
        { id: 2, patient: 'Fátima Acosta', doctor: 'Dra. María Estigarribia', time: '14:30', date: '2026-06-07', status: 'Confirmado', phone: '+595 971 333444', notes: 'Pediatría general' }
      ]
    }
  ]);
  const [activeCompanyId, setActiveCompanyId] = useState('1');
  const [currentView, setCurrentView] = useState('dashboard');
  const [showNewCompanyModal, setShowNewCompanyModal] = useState(false);

  const activeCompany = companies.find(c => c.id === activeCompanyId) || companies[0];

  const handleAddNewCompany = (newComp) => {
    setCompanies([...companies, newComp]);
    setActiveCompanyId(newComp.id);
    setCurrentView('dashboard');
  };

  return (
    <div className="min-h-screen bg-[#040609] font-sans text-zinc-300 flex overflow-hidden selection:bg-cyan-500/30">
      <div className="w-72 bg-[#06080d] border-r border-white/5 flex flex-col z-20 hidden md:flex shadow-2xl">
        <div className="p-6 border-b border-white/5">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-500 flex items-center justify-center shadow-[0_0_20px_rgba(34,211,238,0.3)]">
              <Zap size={18} className="text-white fill-current" />
            </div>
            <div>
              <span className="font-extrabold text-base tracking-tight text-white">MetaBot<span className="text-cyan-400">.OS</span></span>
              <p className="text-[9px] text-zinc-500 uppercase tracking-widest font-mono">Py • Enterprise & Medical</p>
            </div>
          </div>
          
          <div className="space-y-2">
            <div className="relative">
              <select 
                value={activeCompanyId}
                onChange={e => setActiveCompanyId(e.target.value)}
                className="w-full bg-white/[0.03] border border-white/10 rounded-xl py-2.5 px-3 text-xs text-zinc-200 font-semibold focus:outline-none focus:border-cyan-500 appearance-none cursor-pointer"
              >
                {companies.map(c => (
                  <option key={c.id} value={c.id} className="bg-[#06080d] text-white">🏢 {c.name} ({c.vertical === 'medical' ? 'Médico' : 'E-Comm'})</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-3.5 text-zinc-500 pointer-events-none"/>
            </div>
            
            <button 
              onClick={() => setShowNewCompanyModal(true)}
              className="w-full py-2 bg-gradient-to-r from-cyan-500/10 to-indigo-500/10 border border-cyan-500/30 hover:border-cyan-500 text-cyan-300 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 transition-all"
            >
              <Plus size={14}/> Agregar Empresa / Consultorio
            </button>
          </div>
        </div>

        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          <div className="text-[9px] font-bold text-zinc-500 uppercase tracking-widest px-3 py-2">Módulos del Sistema</div>
          
          <button 
            onClick={() => setCurrentView('dashboard')}
            className={`w-full flex items-center px-3 py-2.5 rounded-xl text-xs font-semibold transition-all ${currentView === 'dashboard' ? 'text-white bg-white/5 border border-white/10 shadow-sm' : 'text-zinc-400 hover:bg-white/[0.02] hover:text-zinc-200'}`}
          >
            <LayoutDashboard size={16} className={`mr-3 ${currentView === 'dashboard' ? 'text-cyan-400' : 'text-zinc-500'}`} /> Dashboard General
          </button>

          {activeCompany?.vertical === 'medical' && (
            <button 
              onClick={() => setCurrentView('medical-agenda')}
              className={`w-full flex items-center px-3 py-2.5 rounded-xl text-xs font-semibold transition-all ${currentView === 'medical-agenda' ? 'text-white bg-white/5 border border-white/10 shadow-sm' : 'text-zinc-400 hover:bg-white/[0.02] hover:text-zinc-200'}`}
            >
              <Calendar size={16} className={`mr-3 ${currentView === 'medical-agenda' ? 'text-cyan-400' : 'text-zinc-500'}`} /> Agenda de Doctores & Citas
            </button>
          )}

          <button 
            onClick={() => setCurrentView('agents')}
            className={`w-full flex items-center px-3 py-2.5 rounded-xl text-xs font-semibold transition-all ${currentView === 'agents' ? 'text-white bg-white/5 border border-white/10 shadow-sm' : 'text-zinc-400 hover:bg-white/[0.02] hover:text-zinc-200'}`}
          >
            <Users size={16} className={`mr-3 ${currentView === 'agents' ? 'text-cyan-400' : 'text-zinc-500'}`} /> Enjambre de 6 Agentes IA
          </button>
        </nav>
      </div>

      <main className="flex-1 flex flex-col h-screen overflow-y-auto bg-[#040609] relative">
        <div className="p-8 md:p-12 max-w-6xl mx-auto w-full pb-24">
          {currentView === 'dashboard' && <DashboardView company={activeCompany} />}
          {currentView === 'medical-agenda' && <MedicalAgendaView company={activeCompany} />}
          {currentView === 'agents' && (
            <div className="space-y-6 animate-in fade-in duration-300">
              <div className="flex justify-between items-center">
                <div>
                  <h2 className="text-3xl font-bold text-white tracking-tight">Flota de 6 Agentes IA ({activeCompany.name})</h2>
                  <p className="text-zinc-400 text-sm mt-1">Cada agente cuenta con su modelo NVIDIA NIM, herramientas MCP y prompt autónomo.</p>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {(activeCompany.agents || []).map(agent => {
                  const Icon = getIcon(agent.iconName);
                  return (
                    <div key={agent.agentId} className="bg-[#07090e] border border-white/10 rounded-2xl p-5 shadow-lg space-y-4 hover:border-cyan-500/40 transition-all">
                      <div className="flex items-center gap-3">
                        <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20"><Icon size={20}/></div>
                        <div>
                          <h3 className="font-bold text-white text-sm">{agent.name}</h3>
                          <p className="text-[10px] text-zinc-500 uppercase">{agent.role}</p>
                        </div>
                      </div>
                      <p className="text-xs text-zinc-400 bg-white/[0.02] p-3 rounded-xl border border-white/5">{agent.prompt}</p>
                      <div className="flex justify-between items-center pt-2 border-t border-white/5 text-[10px] font-mono text-zinc-400">
                        <span>Modelo: {agent.model}</span>
                        <span className="text-emerald-400 uppercase font-bold">{agent.status}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </main>

      {showNewCompanyModal && (
        <NewCompanyModal onClose={() => setShowNewCompanyModal(false)} onSave={handleAddNewCompany} />
      )}
    </div>
  );
};

export default App;