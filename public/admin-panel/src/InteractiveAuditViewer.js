// src/InteractiveAuditViewer.js
/**
 * Autoauditoría Interactiva CSDDD
 * ─────────────────────────────────
 * Requisitos cubiertos:
 *  1. Flujo guiado pregunta a pregunta con skip logic automático
 *  2. Navegador de bloques (stepper) siempre visible — saber en qué fase estás
 *  3. Progreso detallado: respondidas / aplicables / pendientes / % completado
 *  4. Modo Asesor CSDDD disponible en cualquier momento durante la auditoría
 *  5. Botón "Ver informe actual" disponible desde el primer bloque completado
 *  6. Informe completo final con análisis de cumplimiento, brechas y exportación
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Box, Typography, Button, Paper, LinearProgress, Chip, Divider,
  TextField, CircularProgress, Drawer, IconButton, Tooltip,
  Alert, Stack, Snackbar, FormControl, InputLabel, Select,
  MenuItem, Radio, RadioGroup, FormControlLabel, FormLabel,
  Dialog, DialogTitle, DialogContent, Tabs, Tab, Table,
  TableBody, TableRow, TableCell, Stepper, Step, StepLabel,
  StepButton, Accordion, AccordionSummary, AccordionDetails,
  Badge,
} from '@mui/material';
import HelpOutlineIcon    from '@mui/icons-material/HelpOutline';
import CloseIcon          from '@mui/icons-material/Close';
import DownloadIcon       from '@mui/icons-material/Download';
import SendIcon           from '@mui/icons-material/Send';
import RestartAltIcon     from '@mui/icons-material/RestartAlt';
import AssessmentIcon     from '@mui/icons-material/Assessment';
import CheckCircleIcon    from '@mui/icons-material/CheckCircle';
import ErrorIcon          from '@mui/icons-material/Error';
import PendingIcon        from '@mui/icons-material/Pending';
import RemoveCircleIcon   from '@mui/icons-material/RemoveCircle';
import SkipNextIcon       from '@mui/icons-material/SkipNext';
import ExpandMoreIcon     from '@mui/icons-material/ExpandMore';
import PrintIcon          from '@mui/icons-material/Print';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import { getAuth } from 'firebase/auth';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8080';

// ── API helper ────────────────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const token = await getAuth().currentUser?.getIdToken();
  const resp  = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...options.headers },
  });
  const body = await resp.json();
  if (!resp.ok || body.ok === false)
    throw new Error(body?.error?.message || body?.error || `HTTP ${resp.status}`);
  return body.data ?? body;
}

// ── Exportación CSV ───────────────────────────────────────────────────────────
function exportToCSV(blocks, threadId) {
  const rows = [['ID', 'Bloque', 'Pregunta', 'Tipo', 'Respuesta', 'Cumplimiento']];
  blocks.forEach(b =>
    b.questions
      .filter(q => q.status === 'answered')
      .forEach(q => rows.push([
        q.id, b.label, q.text, q.type, q.answer ?? '',
        { compliant: 'Conforme', gap: 'Brecha', in_progress: 'En evaluación', informational: 'Informativo' }[q.compliance] ?? '',
      ]))
  );
  const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g,'""')}"`).join(',')).join('\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `auditoria_CSDDD_${threadId?.slice(0,8)}_${new Date().toISOString().slice(0,10)}.csv`;
  a.click(); URL.revokeObjectURL(a.href);
}

// ── Iconos y colores de cumplimiento ─────────────────────────────────────────
const COMPLIANCE = {
  compliant:      { label: 'Conforme',      color: 'success', icon: <CheckCircleIcon  fontSize="small" sx={{ color:'success.main' }} /> },
  gap:            { label: 'Brecha',         color: 'error',   icon: <ErrorIcon        fontSize="small" sx={{ color:'error.main'   }} /> },
  in_progress:    { label: 'En evaluación', color: 'warning', icon: <PendingIcon      fontSize="small" sx={{ color:'warning.main' }} /> },
  informational:  { label: 'Informativo',   color: 'info',    icon: null },
  not_applicable: { label: 'No aplica',     color: 'default', icon: <RemoveCircleIcon fontSize="small" sx={{ color:'grey.400'     }} /> },
};

const BLOCK_COMPLETION = {
  complete: { label: 'Completado', color: '#4caf50' },
  partial:  { label: 'En curso',   color: '#ff9800' },
  pending:  { label: 'Pendiente',  color: '#bdbdbd' },
};

// ── QuestionInput ─────────────────────────────────────────────────────────────
function QuestionInput({ question, value, onChange }) {
  const { type, options } = question;
  if (type === 'select' && Array.isArray(options))
    return (
      <FormControl fullWidth sx={{ mb: 2 }}>
        <InputLabel>Selecciona una opción</InputLabel>
        <Select value={value} label="Selecciona una opción" onChange={e => onChange(e.target.value)}>
          {options.map(o => <MenuItem key={o} value={o}>{o}</MenuItem>)}
        </Select>
      </FormControl>
    );
  if (type === 'si_no')
    return (
      <FormControl component="fieldset" sx={{ mb: 2, width:'100%' }}>
        <FormLabel sx={{ mb:1, fontSize:'0.875rem', color:'text.secondary' }}>Selecciona tu respuesta:</FormLabel>
        <RadioGroup row value={value} onChange={e => onChange(e.target.value)}>
          <FormControlLabel value="Sí"           control={<Radio color="success" />} label="Sí" />
          <FormControlLabel value="No"           control={<Radio color="error"   />} label="No" />
          <FormControlLabel value="En evaluación" control={<Radio color="warning" />} label="En evaluación" />
        </RadioGroup>
      </FormControl>
    );
  if (type === 'porcentaje')
    return (
      <TextField fullWidth type="number" label="Porcentaje (%)" inputProps={{ min:0, max:100, step:5 }}
        value={value} onChange={e => onChange(e.target.value)} helperText="Valor entre 0 y 100" sx={{ mb:2 }} />
    );
  return (
    <TextField fullWidth multiline minRows={3} maxRows={6} label="Tu respuesta"
      placeholder="Escribe tu respuesta..." value={value} onChange={e => onChange(e.target.value)} sx={{ mb:2 }} />
  );
}

// ── BlockStepper ──────────────────────────────────────────────────────────────
function BlockStepper({ blocks, currentBlockId }) {
  if (!blocks?.length) return null;
  const LABELS = blocks.map(b => b.label.replace(/^\d+\.\s*/, ''));
  const activeIdx = blocks.findIndex(b => b.id === currentBlockId);

  return (
    <Box sx={{ px:2, pt:1.5, pb:1, bgcolor:'background.paper', borderBottom:'1px solid', borderColor:'divider', overflowX:'auto' }}>
      <Stepper activeStep={activeIdx < 0 ? 0 : activeIdx} alternativeLabel nonLinear
        sx={{ minWidth: 700, '& .MuiStepLabel-label':{ fontSize:'0.7rem', mt:0.5 } }}>
        {blocks.map((block, idx) => {
          const compl = block.completion;
          const done  = compl === 'complete';
          const part  = compl === 'partial';
          return (
            <Step key={block.id} completed={done}>
              <StepLabel
                StepIconProps={{
                  sx: {
                    color: done ? 'success.main' : part ? 'warning.main' : undefined,
                    '&.Mui-active': { color: 'primary.main' },
                  },
                }}
                optional={
                  block.stats ? (
                    <Typography variant="caption" sx={{ color: BLOCK_COMPLETION[compl]?.color || '#bdbdbd' }}>
                      {block.stats.answered}/{block.stats.applicable} •{' '}
                      {block.stats.gaps > 0 ? `${block.stats.gaps} brecha${block.stats.gaps>1?'s':''}` : 'sin brechas'}
                    </Typography>
                  ) : null
                }
              >
                {LABELS[idx]}
              </StepLabel>
            </Step>
          );
        })}
      </Stepper>
    </Box>
  );
}

// ── AuditReportDialog ─────────────────────────────────────────────────────────
function AuditReportDialog({ open, onClose, reportData, loading, threadId, isCompleted }) {
  const [tab, setTab] = useState(0);

  const { summary, blocks, progress } = reportData || {};

  // Colores semáforo del nivel de cumplimiento
  const levelColor = { Alto:'success', Medio:'warning', Bajo:'error' }[summary?.compliance_level] || 'info';

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth
      PaperProps={{ sx:{ height:'90vh', display:'flex', flexDirection:'column' } }}>
      <DialogTitle sx={{ display:'flex', justifyContent:'space-between', alignItems:'center', pb:1 }}>
        <Box>
          <Typography variant="h6" fontWeight={700}>
            {isCompleted ? '📋 Informe Final de Auditoría CSDDD' : '📋 Informe Parcial de Auditoría CSDDD'}
          </Typography>
          {progress && (
            <Typography variant="caption" color="text.secondary">
              {progress.answered} respondidas • {progress.skipped || 0} no aplican • {progress.applicable - progress.answered} pendientes
            </Typography>
          )}
        </Box>
        <Stack direction="row" gap={1}>
          {blocks && (
            <Button startIcon={<DownloadIcon />} size="small" variant="outlined"
              onClick={() => exportToCSV(blocks, threadId)}>
              Exportar CSV
            </Button>
          )}
          <Button startIcon={<PrintIcon />} size="small" variant="outlined"
            onClick={() => window.print()}>
            Imprimir
          </Button>
          <IconButton onClick={onClose}><CloseIcon /></IconButton>
        </Stack>
      </DialogTitle>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ px:3, borderBottom:1, borderColor:'divider' }}>
        <Tab label="Resumen ejecutivo" />
        <Tab label="Detalle por bloques" />
      </Tabs>

      <DialogContent sx={{ flex:1, overflowY:'auto', p:0 }}>
        {loading ? (
          <Box sx={{ display:'flex', justifyContent:'center', pt:6 }}>
            <CircularProgress /><Typography sx={{ ml:2 }} color="text.secondary">Cargando informe...</Typography>
          </Box>
        ) : !reportData ? (
          <Box sx={{ p:3 }}><Alert severity="info">Responde al menos una pregunta para ver el informe.</Alert></Box>
        ) : (
          <>
            {/* ── TAB 0: Resumen ── */}
            {tab === 0 && (
              <Box sx={{ p:3 }}>
                {/* Tarjetas de métricas */}
                <Stack direction={{ xs:'column', sm:'row' }} spacing={2} sx={{ mb:3 }}>
                  {[
                    { label:'Respondidas',    value: summary?.total_answered ?? 0,       color:'primary.main' },
                    { label:'No aplican',     value: summary?.total_not_applicable ?? 0, color:'text.disabled' },
                    { label:'Brechas (No)',   value: summary?.total_gaps ?? 0,           color:'error.main'   },
                    { label:'Cumplimiento',   value: `${summary?.compliance_pct ?? 0}%`, color:
                        levelColor==='success'?'success.main':levelColor==='warning'?'warning.main':'error.main' },
                  ].map(m => (
                    <Paper key={m.label} variant="outlined" sx={{ flex:1, p:2, textAlign:'center' }}>
                      <Typography variant="h4" fontWeight={700} sx={{ color:m.color }}>{m.value}</Typography>
                      <Typography variant="caption" color="text.secondary">{m.label}</Typography>
                    </Paper>
                  ))}
                </Stack>

                {/* Nivel de cumplimiento */}
                <Alert severity={levelColor} sx={{ mb:3 }}>
                  <strong>Nivel de cumplimiento estimado: {summary?.compliance_level ?? '—'}</strong>
                  {summary?.compliance_level === 'Alto'   && ' — La empresa tiene un sistema de diligencia debida robusto con pocas brechas identificadas.'}
                  {summary?.compliance_level === 'Medio'  && ' — Existen brechas importantes que deben abordarse con un plan de acción específico.'}
                  {summary?.compliance_level === 'Bajo'   && ' — Se detectan brechas críticas. Se recomienda iniciar un programa de diligencia debida urgente.'}
                </Alert>

                {/* Progreso por bloques */}
                <Typography variant="subtitle1" fontWeight={700} sx={{ mb:1.5 }}>Estado por bloques</Typography>
                <Stack spacing={1} sx={{ mb:3 }}>
                  {blocks?.map(b => (
                    <Box key={b.id}>
                      <Box sx={{ display:'flex', justifyContent:'space-between', mb:0.5 }}>
                        <Typography variant="body2" fontWeight={500}>{b.label}</Typography>
                        <Stack direction="row" spacing={1} alignItems="center">
                          {b.stats.gaps > 0 && <Chip label={`${b.stats.gaps} brecha${b.stats.gaps>1?'s':''}`} size="small" color="error" />}
                          <Chip
                            label={`${b.stats.answered}/${b.stats.applicable} respondidas`}
                            size="small"
                            color={b.completion==='complete'?'success':b.completion==='partial'?'warning':'default'}
                          />
                        </Stack>
                      </Box>
                      <LinearProgress
                        variant="determinate"
                        value={b.stats.applicable > 0 ? (b.stats.answered / b.stats.applicable) * 100 : 0}
                        color={b.stats.gaps > 0 ? 'warning' : 'success'}
                        sx={{ height:6, borderRadius:3 }}
                      />
                    </Box>
                  ))}
                </Stack>

                {/* Brechas críticas */}
                {summary?.critical_gaps?.length > 0 && (
                  <>
                    <Typography variant="subtitle1" fontWeight={700} sx={{ mb:1 }} color="error">
                      🔴 Brechas detectadas ({summary.critical_gaps.length})
                    </Typography>
                    <Stack spacing={1}>
                      {summary.critical_gaps.map(g => (
                        <Alert key={g.question_id} severity="error" icon={<ErrorIcon />} sx={{ py:0.5 }}>
                          <Typography variant="caption" color="text.secondary">[{g.question_id}] {g.block}</Typography>
                          <Typography variant="body2">{g.text}</Typography>
                        </Alert>
                      ))}
                    </Stack>
                  </>
                )}

                {summary?.total_gaps === 0 && summary?.total_answered > 0 && (
                  <Alert severity="success" sx={{ mt:2 }}>
                    ✅ No se han detectado brechas en las preguntas respondidas hasta el momento.
                  </Alert>
                )}
              </Box>
            )}

            {/* ── TAB 1: Detalle por bloques ── */}
            {tab === 1 && (
              <Box sx={{ p:2 }}>
                {blocks?.map(b => (
                  <Accordion key={b.id} defaultExpanded={b.completion !== 'pending'} sx={{ mb:1 }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Box sx={{ display:'flex', alignItems:'center', gap:1.5, width:'100%' }}>
                        <Box sx={{
                          width:12, height:12, borderRadius:'50%', flexShrink:0,
                          bgcolor: BLOCK_COMPLETION[b.completion]?.color || '#bdbdbd',
                        }} />
                        <Typography fontWeight={600} sx={{ flex:1 }}>{b.label}</Typography>
                        <Stack direction="row" spacing={1}>
                          {b.stats.gaps > 0 && <Chip label={`${b.stats.gaps} brecha${b.stats.gaps>1?'s':''}`} size="small" color="error" />}
                          <Chip label={`${b.stats.answered}/${b.stats.applicable}`} size="small"
                            color={b.completion==='complete'?'success':b.completion==='partial'?'warning':'default'} />
                        </Stack>
                      </Box>
                    </AccordionSummary>
                    <AccordionDetails sx={{ p:0 }}>
                      <Table size="small">
                        <TableBody>
                          {b.questions.map(q => {
                            const c = COMPLIANCE[q.compliance] || {};
                            return (
                              <TableRow key={q.id} sx={{
                                opacity: q.status === 'not_applicable' ? 0.45 : 1,
                                bgcolor: q.compliance === 'gap' ? 'error.lighter' : undefined,
                              }}>
                                <TableCell sx={{ width:56, pl:2 }}>
                                  <Typography variant="caption" color="text.secondary" fontWeight={600}>{q.id}</Typography>
                                </TableCell>
                                <TableCell sx={{ verticalAlign:'top', py:1.5 }}>
                                  <Typography variant="body2" fontWeight={q.status==='answered'?500:400}>{q.text}</Typography>
                                </TableCell>
                                <TableCell sx={{ minWidth:160, verticalAlign:'top', py:1.5 }}>
                                  {q.status === 'answered' && (
                                    <Box sx={{ display:'flex', alignItems:'center', gap:0.75 }}>
                                      {c.icon}
                                      <Typography variant="body2" fontWeight={600}
                                        color={
                                          q.compliance==='gap'?'error.main':
                                          q.compliance==='compliant'?'success.main':
                                          q.compliance==='in_progress'?'warning.main':
                                          'text.primary'
                                        }>
                                        {q.answer}
                                      </Typography>
                                    </Box>
                                  )}
                                  {q.status === 'pending' && (
                                    <Chip label="Pendiente" size="small" variant="outlined" sx={{ fontSize:'0.7rem' }} />
                                  )}
                                  {q.status === 'not_applicable' && (
                                    <Chip label="No aplica" size="small" sx={{ fontSize:'0.7rem', bgcolor:'grey.200' }} />
                                  )}
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Box>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── Componente Principal ──────────────────────────────────────────────────────
export default function InteractiveAuditViewer() {
  // Estado de la sesión
  const [threadId,         setThreadId]         = useState(null);
  const [currentQuestion,  setCurrentQuestion]  = useState(null);
  const [progress,         setProgress]         = useState({ answered:0, applicable:0, total:0, skipped:0, percent:0 });
  const [phase,            setPhase]            = useState('idle'); // idle|loading|active|completed
  const [answer,           setAnswer]           = useState('');
  const [error,            setError]            = useState('');

  // Informe
  const [reportOpen,       setReportOpen]       = useState(false);
  const [reportData,       setReportData]       = useState(null);
  const [reportLoading,    setReportLoading]    = useState(false);
  // Bloques para el stepper (se actualiza al cargar el informe)
  const [blocks,           setBlocks]           = useState([]);

  // Modo Asesor
  const [advisorOpen,      setAdvisorOpen]      = useState(false);
  const [advisorMessages,  setAdvisorMessages]  = useState([]);
  const [advisorInput,     setAdvisorInput]     = useState('');
  const [advisorLoading,   setAdvisorLoading]   = useState(false);
  const advisorChatRef = useRef(null);

  // Notificación de saltos
  const [skipSnack, setSkipSnack] = useState({ open:false, count:0 });

  // ── Cargar informe (background) ─────────────────────────────────────────────
  const fetchReport = useCallback(async (tid, opts = {}) => {
    if (!tid) return;
    if (opts.showLoader) setReportLoading(true);
    try {
      const data = await apiFetch(`/api/audit/interactive/${tid}/export`);
      setReportData(data);
      if (data.blocks) setBlocks(data.blocks);
    } catch {
      /* no bloquear el flujo principal si falla */
    } finally {
      if (opts.showLoader) setReportLoading(false);
    }
  }, []);

  // ── Iniciar sesión ──────────────────────────────────────────────────────────
  const startSession = useCallback(async () => {
    setPhase('loading');
    setError('');
    setAdvisorMessages([]);
    setReportData(null);
    setBlocks([]);
    setSkipSnack({ open:false, count:0 });
    try {
      const data = await apiFetch('/api/audit/interactive/start', { method:'POST', body:'{}' });
      setThreadId(data.thread_id);
      setCurrentQuestion(data.current_question);
      setProgress(data.progress);
      setPhase('active');
      setAnswer('');
    } catch (e) {
      setError(`Error al iniciar: ${e.message}`);
      setPhase('idle');
    }
  }, []);

  // ── Enviar respuesta ────────────────────────────────────────────────────────
  const submitAnswer = async () => {
    if (!answer.trim() || !currentQuestion || !threadId) return;
    setPhase('loading');
    setError('');
    try {
      const data = await apiFetch(`/api/audit/interactive/${threadId}/submit`, {
        method: 'POST',
        body: JSON.stringify({ question_id: currentQuestion.id, answer }),
      });
      setProgress(data.progress);
      setAnswer('');
      // NO se borra el historial del asesor — se mantiene el hilo durante toda la auditoría
      // Si hay siguiente pregunta, inyectamos un separador visual en el chat
      if (data.next_question && advisorMessages.length > 0) {
        setAdvisorMessages(prev => [
          ...prev,
          {
            role: 'divider',
            text: `──── ${data.next_question.block_label || ''} · Pregunta ${data.next_question.id} ────`,
            questionText: data.next_question.text,
          },
        ]);
      }
      // Mantener el Drawer abierto si ya estaba abierto; si no, cerrarlo
      // (el usuario puede seguir consultando sin interrupciones)

      if (data.skipped_questions?.length > 0)
        setSkipSnack({ open:true, count: data.skipped_questions.length });

      if (data.status === 'completed') {
        setPhase('completed');
        setCurrentQuestion(null);
        setAdvisorOpen(false);
        fetchReport(threadId, { showLoader:false });
      } else {
        setCurrentQuestion(data.next_question);
        setPhase('active');
        fetchReport(threadId, { showLoader:false });
      }
    } catch (e) {
      setError(`Error al guardar respuesta: ${e.message}`);
      setPhase('active');
    }
  };

  // ── Abrir informe ───────────────────────────────────────────────────────────
  const openReport = () => {
    setReportOpen(true);
    if (!reportData) fetchReport(threadId, { showLoader:true });
  };

  // ── Modo Asesor ─────────────────────────────────────────────────────────────
  const openAdvisor = () => {
    setAdvisorOpen(true);
    // Mensaje de bienvenida solo si no hay historial (primera apertura)
    if (advisorMessages.length === 0 && currentQuestion) {
      setAdvisorMessages([{
        role: 'advisor',
        text: `Hola 👋 Soy tu auditor experto en CSDDD y diligencia debida.\n\nEstamos respondiendo la **Pregunta ${currentQuestion.id}** del bloque *${currentQuestion.block_label || ''}*:\n\n> ${currentQuestion.text}\n\nPuedo ayudarte a:\n- Entender qué información se espera\n- Saber qué evidencias necesitas revisar\n- Determinar si tu respuesta debe ser Sí, No o En evaluación\n- Resolver cualquier duda normativa (CSDDD, ESRS, OIT…)\n\n¿En qué tienes dudas?`,
      }]);
    }
  };

  const sendAdvisorMessage = async () => {
    if (!advisorInput.trim() || !currentQuestion || !threadId) return;
    const msg = advisorInput.trim();
    // Actualizamos el historial local (con el nuevo mensaje del usuario)
    const updatedHistory = [...advisorMessages, { role: 'user', text: msg }];
    setAdvisorMessages(updatedHistory);
    setAdvisorInput('');
    setAdvisorLoading(true);
    try {
      const data = await apiFetch(`/api/audit/interactive/${threadId}/consult-advisor`, {
        method: 'POST',
        body: JSON.stringify({
          question_id: currentQuestion.id,
          user_doubt:  msg,
          // Enviamos el historial completo (sin el mensaje actual) para el multi-turn
          history: updatedHistory.slice(0, -1), // el último ya es el user_doubt
        }),
      });
      setAdvisorMessages(p => [...p, { role: 'advisor', text: data.advisor_response }]);
    } catch (e) {
      setAdvisorMessages(p => [...p, { role: 'advisor', text: `⚠️ Error al consultar al asesor: ${e.message}` }]);
    } finally {
      setAdvisorLoading(false);
    }
  };

  useEffect(() => {
    if (advisorChatRef.current)
      advisorChatRef.current.scrollTop = advisorChatRef.current.scrollHeight;
  }, [advisorMessages]);

  // ── PANTALLA: idle ──────────────────────────────────────────────────────────
  if (phase === 'idle') return (
    <Box sx={{ p:4, maxWidth:680, mx:'auto', textAlign:'center' }}>
      <AssessmentIcon sx={{ fontSize:56, color:'primary.main', mb:2 }} />
      <Typography variant="h4" fontWeight={700} gutterBottom>Autoauditoría CSDDD</Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb:3 }}>
        Cuestionario guiado de diligencia debida en Sostenibilidad y Derechos Humanos.
        Las preguntas que no aplican a tu empresa se omiten automáticamente.
      </Typography>
      <Stack direction={{ xs:'column', sm:'row' }} spacing={2} justifyContent="center" sx={{ mb:3 }}>
        {[
          { icon:'📋', text:'48 preguntas CSDDD organizadas en 8 bloques' },
          { icon:'🔀', text:'Skip logic: solo respondes lo que aplica a ti' },
          { icon:'🤖', text:'Asesor IA disponible en cualquier pregunta' },
          { icon:'📊', text:'Informe de auditoría disponible en tiempo real' },
        ].map(f => (
          <Paper key={f.text} variant="outlined" sx={{ p:2, flex:1, textAlign:'left' }}>
            <Typography variant="h5" sx={{ mb:0.5 }}>{f.icon}</Typography>
            <Typography variant="caption" color="text.secondary">{f.text}</Typography>
          </Paper>
        ))}
      </Stack>
      <Button variant="contained" size="large" onClick={startSession} sx={{ px:6, py:1.5 }}>
        Iniciar nueva auditoría
      </Button>
      {error && <Alert severity="error" sx={{ mt:2 }}>{error}</Alert>}
    </Box>
  );

  // ── PANTALLA: loading ───────────────────────────────────────────────────────
  if (phase === 'loading') return (
    <Box sx={{ display:'flex', justifyContent:'center', alignItems:'center', height:'60vh' }}>
      <CircularProgress /><Typography sx={{ ml:2 }} color="text.secondary">Procesando...</Typography>
    </Box>
  );

  // ── PANTALLA: completed ─────────────────────────────────────────────────────
  if (phase === 'completed') return (
    <Box sx={{ p:4, maxWidth:700, mx:'auto' }}>
      <Box sx={{ textAlign:'center', mb:3 }}>
        <CheckCircleOutlineIcon sx={{ fontSize:64, color:'success.main', mb:1 }} />
        <Typography variant="h5" fontWeight={700}>¡Auditoría completada!</Typography>
        <Typography color="text.secondary">
          {progress.answered} preguntas respondidas · {progress.skipped||0} no aplicaban · {reportData?.summary?.total_gaps||0} brechas detectadas
        </Typography>
      </Box>

      {/* Mini resumen inline */}
      {reportData?.summary && (
        <Alert severity={{ Alto:'success', Medio:'warning', Bajo:'error' }[reportData.summary.compliance_level] || 'info'} sx={{ mb:3 }}>
          <strong>Nivel de cumplimiento: {reportData.summary.compliance_level}</strong>
          {' '}({reportData.summary.compliance_pct}% de respuestas conformes)
        </Alert>
      )}

      <Stack direction={{ xs:'column', sm:'row' }} spacing={2} justifyContent="center">
        <Button variant="contained" size="large" startIcon={<AssessmentIcon />} onClick={openReport}>
          Ver informe completo
        </Button>
        <Button variant="outlined" startIcon={<DownloadIcon />} disabled={!reportData?.blocks}
          onClick={() => exportToCSV(reportData.blocks, threadId)}>
          Exportar CSV
        </Button>
        <Button variant="text" startIcon={<RestartAltIcon />} onClick={startSession}>
          Nueva sesión
        </Button>
      </Stack>

      {/* Informe Dialog */}
      <AuditReportDialog open={reportOpen} onClose={() => setReportOpen(false)}
        reportData={reportData} loading={reportLoading} threadId={threadId} isCompleted />
    </Box>
  );

  // ── PANTALLA: active ────────────────────────────────────────────────────────
  const remaining = (progress.applicable || 0) - (progress.answered || 0);

  return (
    <Box sx={{ display:'flex', flexDirection:'column', height:'100%', overflow:'hidden' }}>

      {/* ── Block Stepper ── */}
      <BlockStepper blocks={blocks} currentBlockId={currentQuestion?.block_id} />

      {/* ── Barra de progreso global ── */}
      <Box sx={{ px:{xs:2, sm:3}, py:1.5, bgcolor:'background.paper', borderBottom:'1px solid', borderColor:'divider' }}>
        <Box sx={{ display:'flex', flexDirection:{xs:'column', md:'row'}, justifyContent:'space-between', alignItems:{xs:'flex-start', md:'center'}, gap:1, mb:1 }}>
          <Box sx={{ display:'flex', gap:1, alignItems:'center', flexWrap:'wrap' }}>
            <Typography variant="body2" fontWeight={600}>
              {progress.answered} / {progress.applicable} respondidas
            </Typography>
            {progress.skipped > 0 && (
              <Chip icon={<SkipNextIcon />} label={`${progress.skipped} no aplican`} size="small" sx={{ fontSize:'0.7rem', bgcolor:'grey.100' }} />
            )}
          </Box>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Typography variant="body2" color="text.secondary">
              Quedan <strong>{remaining}</strong>
            </Typography>
            <Chip label={`${progress.percent}%`} size="small" color="primary" />
            <Tooltip title="Ver informe de auditoría actual" arrow>
              <Button
                variant="outlined"
                size="small"
                startIcon={<AssessmentIcon />}
                onClick={openReport}
                disabled={progress.answered === 0}
              >
                Informe
              </Button>
            </Tooltip>
          </Stack>
        </Box>
        <LinearProgress variant="determinate" value={progress.percent} sx={{ height:6, borderRadius:3 }} />
      </Box>

      {/* ── Área principal ── */}
      <Box sx={{ flex:1, display:'flex', overflow:'hidden' }}>

        {/* Formulario de pregunta */}
        <Box sx={{ flex:1, p:3, overflowY:'auto', minWidth:0 }}>
          {currentQuestion && (
            <Paper elevation={0} variant="outlined" sx={{ p:3, borderRadius:2, maxWidth:700, mx:'auto' }}>

              {/* Bloque activo */}
              <Box sx={{ display:'flex', justifyContent:'space-between', alignItems:'center', mb:2 }}>
                <Chip
                  label={currentQuestion.block_label || `Bloque ${currentQuestion.block_id}`}
                  size="small" color="secondary" sx={{ fontWeight:600 }}
                />
                <Typography variant="caption" color="text.secondary">Pregunta {currentQuestion.id}</Typography>
              </Box>

              {/* Texto de la pregunta */}
              <Box sx={{ display:'flex', flexDirection:{ xs:'column', sm:'row' }, justifyContent:'space-between', alignItems:'flex-start', gap:1, mb:2 }}>
                <Typography variant="body1" fontWeight={600} sx={{ flex:1, lineHeight:1.6 }}>
                  {currentQuestion.text}
                </Typography>
                <Tooltip title="Consultar al Asesor CSDDD sobre esta pregunta" arrow>
                  <IconButton onClick={openAdvisor} color="info" size="small" sx={{ alignSelf:{xs:'flex-start', sm:'center'}, mt:{xs:0, sm:-0.5}, flexShrink:0 }}>
                    <HelpOutlineIcon />
                  </IconButton>
                </Tooltip>
              </Box>

              {/* Hint */}
              {currentQuestion.hint && (
                <Alert severity="info" icon={false} sx={{ mb:2.5, py:0.75, fontSize:'0.82rem', lineHeight:1.5 }}>
                  💡 {currentQuestion.hint}
                </Alert>
              )}

              {/* Input según tipo */}
              <QuestionInput question={currentQuestion} value={answer} onChange={setAnswer} />

              {error && <Alert severity="error" sx={{ mb:2 }}>{error}</Alert>}

              {/* Botones de acción */}
              <Box sx={{ display:'flex', flexDirection:{ xs:'column-reverse', sm:'row' }, justifyContent:'space-between', alignItems:{ xs:'stretch', sm:'center' }, gap:2, mt:1 }}>
                <Button
                  variant="text" size="small" color="info"
                  startIcon={<HelpOutlineIcon />} onClick={openAdvisor}
                >
                  Tengo dudas con esta pregunta
                </Button>
                <Button
                  variant="contained" size="large"
                  onClick={submitAnswer}
                  disabled={!answer.trim()}
                  endIcon={<SendIcon />}
                >
                  {remaining === 1 ? 'Finalizar auditoría' : 'Siguiente'}
                </Button>
              </Box>
            </Paper>
          )}
        </Box>

        {/* ── Drawer: Modo Asesor ── */}
        <Drawer
          anchor="right" open={advisorOpen} onClose={() => setAdvisorOpen(false)} variant="persistent"
          PaperProps={{ sx:{ width:{ xs:'100%', sm:380 }, position:'relative',
            boxShadow:'-4px 0 12px rgba(0,0,0,0.08)', display:'flex', flexDirection:'column' } }}
        >
          {/* Cabecera */}
          <Box sx={{ p:2, bgcolor:'secondary.main', color:'secondary.contrastText',
            display:'flex', justifyContent:'space-between', alignItems:'center', flexShrink:0 }}>
            <Box>
              <Typography variant="subtitle1" fontWeight={700}>🤖 Modo Asesor</Typography>
              <Typography variant="caption" sx={{ opacity:0.85 }}>Experto en CSDDD · ESRS · OIT · OCDE</Typography>
            </Box>
            <IconButton onClick={() => setAdvisorOpen(false)} size="small" sx={{ color:'inherit' }}>
              <CloseIcon />
            </IconButton>
          </Box>

          {/* Pregunta en contexto */}
          {currentQuestion && (
            <Box sx={{ px:2, py:1, bgcolor:'action.hover', borderBottom:'1px solid', borderColor:'divider', flexShrink:0 }}>
              <Typography variant="caption" color="text.secondary" fontWeight={600} display="block">
                PREGUNTA ACTIVA — {currentQuestion.id}
              </Typography>
              <Typography variant="body2" sx={{ mt:0.5, fontStyle:'italic' }}>
                {currentQuestion.text.length > 120 ? currentQuestion.text.slice(0,120)+'...' : currentQuestion.text}
              </Typography>
            </Box>
          )}

          {/* Historial del chat */}
          <Box ref={advisorChatRef}
            sx={{ flex:1, overflowY:'auto', p:2, display:'flex', flexDirection:'column', gap:1.5 }}>
            {advisorMessages.map((m, i) => (
              <Box key={i} sx={{
                maxWidth:'92%',
                alignSelf: m.role==='user' ? 'flex-end' : 'flex-start',
                bgcolor:   m.role==='user' ? 'primary.main' : 'grey.100',
                color:     m.role==='user' ? 'primary.contrastText' : 'text.primary',
                px:2, py:1.5, borderRadius:2,
              }}>
                <Typography variant="body2" sx={{ whiteSpace:'pre-wrap' }}>{m.text}</Typography>
              </Box>
            ))}
            {advisorLoading && (
              <Box sx={{ display:'flex', alignItems:'center', gap:1 }}>
                <CircularProgress size={16} />
                <Typography variant="caption" color="text.secondary">Consultando base de conocimiento...</Typography>
              </Box>
            )}
          </Box>

          {/* Input del asesor */}
          <Box sx={{ p:2, borderTop:'1px solid', borderColor:'divider', flexShrink:0 }}>
            <Box sx={{ display:'flex', gap:1 }}>
              <TextField fullWidth size="small" multiline maxRows={3}
                placeholder="Escribe tu duda aquí..." value={advisorInput}
                onChange={e => setAdvisorInput(e.target.value)}
                onKeyDown={e => { if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendAdvisorMessage(); } }}
                disabled={advisorLoading} />
              <IconButton onClick={sendAdvisorMessage} disabled={!advisorInput.trim()||advisorLoading} color="primary">
                <SendIcon />
              </IconButton>
            </Box>
            <Button fullWidth variant="outlined" size="small" sx={{ mt:1 }} onClick={() => setAdvisorOpen(false)}>
              Volver al cuestionario
            </Button>
          </Box>
        </Drawer>
      </Box>

      {/* ── Informe Dialog ── */}
      <AuditReportDialog
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        reportData={reportData}
        loading={reportLoading}
        threadId={threadId}
        isCompleted={phase === 'completed'}
      />

      {/* ── Snackbar: preguntas omitidas ── */}
      <Snackbar
        open={skipSnack.open} autoHideDuration={5000}
        onClose={() => setSkipSnack(p => ({ ...p, open:false }))}
        anchorOrigin={{ vertical:'bottom', horizontal:'center' }}
      >
        <Alert onClose={() => setSkipSnack(p => ({ ...p, open:false }))}
          severity="info" icon={<SkipNextIcon />} sx={{ maxWidth:480 }}>
          <strong>{skipSnack.count} pregunta{skipSnack.count!==1?'s':''} omitida{skipSnack.count!==1?'s':''} automáticamente</strong>
          {' '}por no aplicar a tu empresa según las respuestas anteriores.
        </Alert>
      </Snackbar>
    </Box>
  );
}
