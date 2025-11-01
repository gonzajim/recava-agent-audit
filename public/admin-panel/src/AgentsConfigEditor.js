import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import { auth } from './firebase';

const usingDefaultBaseUrl = !process.env.REACT_APP_ADVISOR_API_BASE_URL;
const API_BASE_URL = process.env.REACT_APP_ADVISOR_API_BASE_URL || 'http://localhost:8080';
const CONFIG_ENDPOINT = `${API_BASE_URL.replace(/\/$/, '')}/admin/agents-config`;

const textFieldSx = {
  '& .MuiInputBase-root': {
    fontFamily: 'monospace',
  },
};

function AgentsConfigEditor() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const [yamlText, setYamlText] = useState('');
  const [initialYaml, setInitialYaml] = useState('');

  const [instructions, setInstructions] = useState({});
  const [initialInstructions, setInitialInstructions] = useState({});
  const [selectedInstruction, setSelectedInstruction] = useState('');
  const [activeTab, setActiveTab] = useState('yaml');

  const instructionKeys = useMemo(() => Object.keys(instructions || {}), [instructions]);

  const isDirty = useMemo(() => {
    if (yamlText !== initialYaml) {
      return true;
    }
    return JSON.stringify(instructions) !== JSON.stringify(initialInstructions);
  }, [yamlText, initialYaml, instructions, initialInstructions]);

  const resetState = (yamlPayload, instructionsPayload) => {
    setYamlText(yamlPayload);
    setInitialYaml(yamlPayload);
    const normalized = JSON.parse(JSON.stringify(instructionsPayload || {}));
    setInstructions(normalized);
    setInitialInstructions(normalized);
    setSelectedInstruction(Object.keys(normalized || {})[0] || '');
  };

  const getAuthToken = async () => {
    if (!auth.currentUser) throw new Error('Usuario no autenticado.');
    return await auth.currentUser.getIdToken();
  };

  const fetchConfig = async () => {
    setLoading(true);
    setError('');
    setSuccessMessage('');
    try {
      const token = await getAuthToken();
      const response = await fetch(CONFIG_ENDPOINT, {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail?.detail || `Error al cargar configuración: ${response.status}`);
      }
      const payload = await response.json();
      resetState(payload.yaml || '', payload.instructions || {});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (auth.currentUser) {
      fetchConfig();
    }
  }, [auth.currentUser]);

  const handleInstructionChange = (path, value) => {
    setInstructions((prev) => ({
      ...prev,
      [path]: value,
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSuccessMessage('');
    try {
      const token = await getAuthToken();
      const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          yaml: yamlText,
          instructions,
        }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail?.detail || `Error al guardar configuración: ${response.status}`);
      }
      const payload = await response.json();
      resetState(payload.yaml || yamlText, payload.instructions || instructions);
      setSuccessMessage('Configuración guardada y agentes recargados correctamente.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => {
    resetState(initialYaml, initialInstructions);
    setSuccessMessage('');
    setError('');
  };

  if (loading) {
    return (
      <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" minHeight="60vh">
        <CircularProgress />
        <Typography sx={{ mt: 2 }}>Cargando configuración de agentes...</Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={3} sx={{ mt: 3 }}>
      {usingDefaultBaseUrl && (
        <Alert severity="warning">
          Usando la URL por defecto (http://localhost:8080). Configura la variable
          {' '}
          <code>REACT_APP_ADVISOR_API_BASE_URL</code>
          {' '}
          para entornos productivos.
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {successMessage && <Alert severity="success">{successMessage}</Alert>}

      <Paper variant="outlined">
        <Tabs
          value={activeTab}
          onChange={(_, value) => setActiveTab(value)}
          indicatorColor="primary"
          textColor="primary"
        >
          <Tab value="yaml" label="Config YAML" />
          <Tab value="instructions" label="Instrucciones" />
        </Tabs>

        <Divider />

        {activeTab === 'yaml' && (
          <Box p={3}>
            <Typography variant="subtitle1" sx={{ mb: 1 }}>
              Edita el archivo <code>config/agents.yaml</code>
            </Typography>
            <TextField
              fullWidth
              multiline
              minRows={16}
              value={yamlText}
              onChange={(event) => setYamlText(event.target.value)}
              sx={textFieldSx}
              disabled={saving}
            />
          </Box>
        )}

        {activeTab === 'instructions' && (
          <Box p={3} display="flex" gap={2} flexDirection={{ xs: 'column', md: 'row' }}>
            <Paper variant="outlined" sx={{ minWidth: 240, maxHeight: 400, overflowY: 'auto' }}>
              <List dense>
                {instructionKeys.length === 0 ? (
                  <ListItemText sx={{ p: 2 }} primary="Sin archivos de instrucciones configurados." />
                ) : (
                  instructionKeys.map((key) => (
                    <ListItemButton
                      key={key}
                      selected={selectedInstruction === key}
                      onClick={() => setSelectedInstruction(key)}
                    >
                      <ListItemText primary={key} />
                    </ListItemButton>
                  ))
                )}
              </List>
            </Paper>
            <Box flex={1}>
              {selectedInstruction ? (
                <>
                  <Typography variant="subtitle1" sx={{ mb: 1 }}>
                    Editando <code>{selectedInstruction}</code>
                  </Typography>
                  <TextField
                    fullWidth
                    multiline
                    minRows={14}
                    value={instructions[selectedInstruction] || ''}
                    onChange={(event) => handleInstructionChange(selectedInstruction, event.target.value)}
                    sx={textFieldSx}
                    disabled={saving}
                  />
                </>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Selecciona un archivo de instrucciones de la lista para editarlo.
                </Typography>
              )}
            </Box>
          </Box>
        )}
      </Paper>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="flex-end">
        <Button variant="outlined" onClick={handleDiscard} disabled={!isDirty || saving}>
          Descartar cambios
        </Button>
        <Button variant="contained" onClick={handleSave} disabled={!isDirty || saving}>
          {saving ? <CircularProgress size={24} /> : 'Guardar y recargar agentes'}
        </Button>
        <Button variant="text" onClick={fetchConfig} disabled={saving}>
          Volver a cargar desde servidor
        </Button>
      </Stack>
    </Stack>
  );
}

export default AgentsConfigEditor;
