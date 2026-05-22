// src/EmpiricalAuditViewer.js
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box, Typography, Button, Paper, Table,
  TableBody, TableCell, TableContainer, TableHead, TableRow,
  CircularProgress, Switch, FormControlLabel, Chip, Tooltip,
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import { getAuth } from 'firebase/auth';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8080';
const POLL_INTERVAL_MS = 3000;

// Mapa de indicadores (igual que en el backend)
const INDICATORS_MAP = {
  "1":  { ref: "S1-9 66. a)",           question: "¿Divulga la distribución por género (en número y porcentaje) en la alta dirección?" },
  "2":  { ref: "S1-9 66. b)",           question: "¿Divulga la distribución de los asalariados por grupos de edad?" },
  "3":  { ref: "S1-10 69.",             question: "¿Divulga si todos sus asalariados perciben un salario adecuado de conformidad con los índices de referencia aplicables?" },
  "4":  { ref: "S1-10 70.",             question: "Si no todos lo perciben, ¿divulga los países en que los asalariados ganan menos del índice de referencia?" },
  "5":  { ref: "S1-10 70.",             question: "Si no todos lo perciben, ¿divulga el porcentaje de asalariados en esa situación por países?" },
  "6":  { ref: "S1-10 71.",             question: "¿Divulga la información del requisito con respecto a los trabajadores no asalariados?" },
  "7":  { ref: "S1-11 74. a)",          question: "¿Divulga si todos los asalariados están cubiertos por protección social contra pérdida de ingresos por enfermedad?" },
  "8":  { ref: "S1-11 74. b)",          question: "¿Divulga si todos los asalariados están cubiertos por protección social contra pérdida de ingresos por desempleo?" },
  "9":  { ref: "S1-11 74. c)",          question: "¿Divulga si todos los asalariados están cubiertos por protección social contra pérdida por accidentes y discapacidad?" },
  "10": { ref: "S1-11 74. d)",          question: "¿Divulga si todos los asalariados están cubiertos por protección social contra pérdida por permiso parental?" },
  "11": { ref: "S1-11 74. e)",          question: "¿Divulga si todos los asalariados están cubiertos por protección social contra pérdida por jubilación?" },
  "12": { ref: "S1-11 75. [1]",         question: "Si no todos están cubiertos, ¿divulga los países sin protección social?" },
  "13": { ref: "S1-11 75. [2]",         question: "Si no todos están cubiertos, ¿divulga por países los tipos de asalariados sin protección por cada acontecimiento vital?" },
  "14": { ref: "S1-11 76.",             question: "¿Divulga la información con respecto a los trabajadores no asalariados de su personal propio?" },
  "15": { ref: "S1-12 79.",             question: "¿Divulga el porcentaje de personas con discapacidad entre sus asalariados?" },
  "16": { ref: "S1-12 80.",             question: "¿Divulga el porcentaje de asalariados con discapacidad con desglose por género?" },
  "17": { ref: "S1-14 88. a) [1]",      question: "Personal asalariado: ¿divulga el % cubierto por el sistema de gestión de salud y seguridad?" },
  "18": { ref: "S1-14 88. a) [2]",      question: "Trabajadores no asalariados: ¿divulga el % cubierto por el sistema de gestión de salud y seguridad?" },
  "19": { ref: "S1-14 88. b) [1]",      question: "Personal asalariado: ¿divulga el número de muertes por lesiones/enfermedades laborales?" },
  "20": { ref: "S1-14 88. b) [2]",      question: "Trabajadores no asalariados: ¿divulga el número de muertes por lesiones/enfermedades laborales?" },
  "21": { ref: "S1-14 88. b) [3]",      question: "Otros trabajadores de la cadena de valor: ¿divulga el número de muertes laborales?" },
  "22": { ref: "S1-14 88. b) [4]",      question: "¿Divulga separadamente las muertes por lesiones y las causadas por problemas de salud?" },
  "23": { ref: "S1-14 88. c) [1]",      question: "Personal asalariado: ¿divulga el número y tasa de accidentes de trabajo registrables?" },
  "24": { ref: "S1-14 88. c) [2]",      question: "Trabajadores no asalariados: ¿divulga el número y tasa de accidentes registrables?" },
  "25": { ref: "S1-14 88. d)",          question: "Personal asalariado: ¿divulga el número de casos de problemas de salud relacionados con el trabajo?" },
  "26": { ref: "S1-14 88. d) [2]",      question: "Trabajadores no asalariados: ¿divulga el número de casos de problemas de salud laborales?" },
  "27": { ref: "S1-14 88.e)",           question: "Personal asalariado: ¿divulga el número de días perdidos por lesiones/muertes laborales?" },
  "28": { ref: "S1-14 88. e) [2]",      question: "Trabajadores no asalariados: ¿divulga el número de días perdidos por lesiones/muertes laborales?" },
  "29": { ref: "S1-14 90.",             question: "¿Divulga el % de trabajadores propios cubiertos por un sistema de SST auditado o certificado?" },
  "30": { ref: "S1-14 90. {AR 81}",     question: "¿Divulga la existencia/ausencia de auditoría SST y las normas subyacentes?" },
  "31": { ref: "S1-15 93. a)",          question: "¿Divulga el % de asalariados con derecho a acogerse a permisos familiares?" },
  "32": { ref: "S1-15 93. b)",          question: "¿Divulga el % de asalariados que se acogieron a permisos familiares, con desglose por género?" },
  "33": { ref: "S1-16 97. a) [1]",      question: "¿Divulga la brecha salarial de género expresada como % del nivel retributivo medio masculino?" },
  "34": { ref: "S1-16 97. a) [2]",      question: "¿Divulga la brecha salarial de género por categoría de asalariado?" },
  "35": { ref: "S1-16 97. a) [3]",      question: "¿Divulga la brecha salarial de género por país o segmento?" },
  "36": { ref: "S1-16 97. b) [1]",      question: "¿Divulga la relación entre la remuneración del mejor pagado y la media del resto?" },
  "37": { ref: "S1-16 97. b). [2]",     question: "¿Divulga esa relación ajustada por poder adquisitivo entre países?" },
};

// ── Export to CSV ────────────────────────────────────────────────────────────
function exportToCSV(results, filename) {
  const headers = ['ID', 'Referencia ESRS', 'Indicador', 'Cumple', 'Página', 'Evidencia Literal', 'Razonamiento', '¿IA Acertó?'];
  const rows = Object.values(results)
    .sort((a, b) => Number(a.indicator_id) - Number(b.indicator_id))
    .map((row) => {
      const ind = INDICATORS_MAP[row.indicator_id] || {};
      return [
        row.indicator_id,
        ind.ref || '',
        ind.question || '',
        row.cumple || '',
        row.pagina_real || '',
        (row.evidencia_literal || '').replace(/\n/g, ' '),
        (row.razonamiento || '').replace(/\n/g, ' '),
        row.human_validation === true ? 'Sí' : row.human_validation === false ? 'No' : 'Sin validar',
      ].map((cell) => `"${String(cell).replace(/"/g, '""')}"`);
    });

  const csvContent = [headers.map((h) => `"${h}"`), ...rows].map((r) => r.join(',')).join('\n');
  const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// ── Chip de color para "cumple" ──────────────────────────────────────────────
function CumpleChip({ value }) {
  const normalized = (value || '').toUpperCase().replace('Í', 'I');
  const map = {
    'SÍ': { label: 'SÍ', color: 'success' },
    'SI': { label: 'SÍ', color: 'success' },
    'NO': { label: 'NO', color: 'error' },
    'NA': { label: 'N/A', color: 'default' },
    'FE': { label: 'FE',  color: 'warning' },
    'ERROR': { label: 'ERROR', color: 'error' },
  };
  const cfg = map[normalized] || { label: value, color: 'default' };
  return <Chip label={cfg.label} color={cfg.color} size="small" />;
}

// ── Componente principal ─────────────────────────────────────────────────────
export default function EmpiricalAuditViewer() {
  const [file, setFile] = useState(null);
  const [threadId, setThreadId] = useState('');
  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef(null);

  const fetchAuditStatus = useCallback(async (id) => {
    try {
      const resp = await fetch(`${API_URL}/api/audit/empirical/${id}`);
      if (!resp.ok) return;
      const body = await resp.json();
      if (body.ok && body.data) {
        setAuditData(body.data);
        if (body.data.status === 'completed' || body.data.status === 'error') {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }
    } catch (err) {
      console.error('Error en polling:', err);
    }
  }, []);

  useEffect(() => {
    if (!threadId) return;
    fetchAuditStatus(threadId);
    pollRef.current = setInterval(() => fetchAuditStatus(threadId), POLL_INTERVAL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [threadId, fetchAuditStatus]);

  const handleLaunchAudit = async () => {
    if (!file) { setError('Por favor, selecciona un archivo PDF.'); return; }
    setError(''); setLoading(true); setAuditData(null); setThreadId('');
    try {
      const auth = getAuth();
      if (!auth.currentUser) throw new Error('Usuario no autenticado.');
      const token = await auth.currentUser.getIdToken();
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(`${API_URL}/api/audit/empirical`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!response.ok) throw new Error('Error al iniciar la auditoría');
      const data = await response.json();
      setThreadId(data.thread_id);
    } catch (err) {
      console.error(err); setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedbackToggle = async (indicatorId, currentValue) => {
    if (!threadId || !auditData) return;
    setAuditData((prev) => ({
      ...prev,
      results: { ...prev.results, [indicatorId]: { ...prev.results[indicatorId], human_validation: !currentValue } },
    }));
    try {
      const auth = getAuth();
      const token = await auth.currentUser?.getIdToken();
      await fetch(`${API_URL}/api/audit/empirical/${threadId}/feedback`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ indicator_id: indicatorId, human_validation: !currentValue }),
      });
    } catch (err) { console.error('Error al guardar feedback:', err); }
  };

  const results = auditData?.results || {};
  const isCompleted = auditData?.status === 'completed';
  const isProcessing = auditData?.status === 'processing' || (threadId && !auditData);
  const completedCount = Object.keys(results).length;
  const exportFilename = `auditoria_NEIS_S1_${auditData?.filename?.replace('.pdf','') || 'informe'}_${new Date().toISOString().slice(0,10)}.csv`;

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        Observatorio IBEX 35 – Auditoría NEIS S1
      </Typography>

      {/* ── Panel de lanzamiento ── */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>Lanzar Nueva Auditoría Empírica</Typography>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          <Button variant="outlined" component="label" sx={{ height: 56, flexGrow: 1 }}>
            {file ? file.name : 'Seleccionar Archivo PDF'}
            <input type="file" hidden accept="application/pdf" onChange={(e) => setFile(e.target.files[0])} />
          </Button>
          <Button variant="contained" onClick={handleLaunchAudit} disabled={loading || !file} sx={{ height: 56, whiteSpace: 'nowrap' }}>
            {loading ? <CircularProgress size={24} /> : 'Lanzar Auditoría'}
          </Button>
        </Box>
        {error && <Typography color="error" sx={{ mt: 2 }}>{error}</Typography>}
      </Paper>

      {/* ── Tabla de resultados ── */}
      {threadId && (
        <Paper sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 1 }}>
            <Typography variant="h6">
              Resultados de la Auditoría ({completedCount} / 37)
              {auditData?.filename && <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>— {auditData.filename}</Typography>}
            </Typography>
            <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
              {isProcessing && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <CircularProgress size={18} />
                  <Typography color="text.secondary" variant="body2">Analizando… ({POLL_INTERVAL_MS / 1000}s)</Typography>
                </Box>
              )}
              {isCompleted && <Chip label="✓ Completado" color="success" />}
              {auditData?.status === 'error' && <Chip label="✗ Error" color="error" />}
              {isCompleted && (
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<DownloadIcon />}
                  onClick={() => exportToCSV(results, exportFilename)}
                >
                  Exportar CSV
                </Button>
              )}
            </Box>
          </Box>

          <TableContainer sx={{ maxHeight: 600 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell width={50}><strong>ID</strong></TableCell>
                  <TableCell width={130}><strong>Referencia ESRS</strong></TableCell>
                  <TableCell><strong>Indicador</strong></TableCell>
                  <TableCell width={90}><strong>Cumple</strong></TableCell>
                  <TableCell width={70}><strong>Página</strong></TableCell>
                  <TableCell><strong>Evidencia Literal</strong></TableCell>
                  <TableCell><strong>Razonamiento</strong></TableCell>
                  <TableCell width={110}><strong>¿IA Acertó?</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {completedCount === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} align="center">
                      {isProcessing ? 'Esperando primeros resultados...' : 'Sin resultados'}
                    </TableCell>
                  </TableRow>
                ) : (
                  Object.values(results)
                    .sort((a, b) => Number(a.indicator_id) - Number(b.indicator_id))
                    .map((row) => {
                      const ind = INDICATORS_MAP[row.indicator_id] || {};
                      return (
                        <TableRow key={row.indicator_id} hover>
                          <TableCell><strong>{row.indicator_id}</strong></TableCell>
                          <TableCell>
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                              {ind.ref || '—'}
                            </Typography>
                          </TableCell>
                          <TableCell sx={{ maxWidth: 220, whiteSpace: 'normal', fontSize: '0.82rem' }}>
                            <Tooltip title={ind.question || ''} placement="top" arrow>
                              <span>{ind.question || '—'}</span>
                            </Tooltip>
                          </TableCell>
                          <TableCell><CumpleChip value={row.cumple} /></TableCell>
                          <TableCell align="center">{row.pagina_real}</TableCell>
                          <TableCell sx={{ maxWidth: 260, whiteSpace: 'normal', fontSize: '0.82rem', color: 'text.secondary' }}>
                            {row.evidencia_literal}
                          </TableCell>
                          <TableCell sx={{ maxWidth: 280, whiteSpace: 'normal', fontSize: '0.82rem' }}>
                            {row.razonamiento}
                          </TableCell>
                          <TableCell>
                            <FormControlLabel
                              control={
                                <Switch
                                  size="small"
                                  checked={row.human_validation === true}
                                  onChange={() => handleFeedbackToggle(row.indicator_id, row.human_validation)}
                                  color="primary"
                                />
                              }
                              label={<Typography variant="caption">{row.human_validation ? 'Sí' : 'No'}</Typography>}
                            />
                          </TableCell>
                        </TableRow>
                      );
                    })
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}
    </Box>
  );
}
