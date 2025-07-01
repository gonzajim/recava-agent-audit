// frontend/src/ChatHistoryViewer.js
import React, { useState, useEffect } from 'react';
import { auth } from './firebase';
import ReactQuill from 'react-quill';
import 'react-quill/dist/quill.snow.css'; // Estilos para el editor
import DOMPurify from 'dompurify'; // Librería de seguridad

// Importaciones de Material-UI
import {
  Box, Button, Modal, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, TextField, Typography, CircularProgress,
  InputAdornment
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search'; // Icono de búsqueda

// URLs de nuestras funciones HTTP
const GET_HISTORY_URL = "https://europe-west1-recava-auditor-dev.cloudfunctions.net/getChatHistory";
const UPDATE_RESPONSE_URL = "https://europe-west1-recava-auditor-dev.cloudfunctions.net/updateExpertResponse";

// Estilo para la ventana Modal de MUI
const modalStyle = {
  position: 'absolute',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  width: '90%',
  maxWidth: 700,
  bgcolor: 'background.paper',
  border: '1px solid #ddd',
  borderRadius: '8px',
  boxShadow: 24,
  p: 4,
};

function ChatHistoryViewer() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingItem, setEditingItem] = useState(null);
  const [expertResponse, setExpertResponse] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  const getAuthToken = async () => {
    if (!auth.currentUser) throw new Error("Usuario no autenticado.");
    return await auth.currentUser.getIdToken();
  };

  const fetchHistory = async (currentSearchTerm = '') => {
    setLoading(true);
    setError('');
    try {
      const token = await getAuthToken();
      const response = await fetch(GET_HISTORY_URL, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: { searchTerm: currentSearchTerm } })
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: `Error del servidor: ${response.status}` }));
        throw new Error(errorData.error || `Error del servidor: ${response.status}`);
      }
      const result = await response.json();
      setHistory(result.history);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (auth.currentUser) {
      fetchHistory(); // Carga inicial sin filtro
    }
  }, [auth.currentUser]);

  const handleSearch = () => {
    fetchHistory(searchTerm);
  };
  
  const handleEditClick = (item) => {
    setEditingItem(item);
    setExpertResponse(item.expert_response || '');
  };

  const handleSave = async () => {
    if (!editingItem) return;
    setLoading(true);
    try {
      const token = await getAuthToken();
      await fetch(UPDATE_RESPONSE_URL, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: { id: editingItem.id, expertResponse: expertResponse } })
      });
      setHistory(history.map(item =>
        item.id === editingItem.id ? { ...item, expert_response: expertResponse } : item
      ));
      setEditingItem(null);
    } catch (err) {
      alert(`Error al guardar: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  if (error) return <Typography p={4} color="error">Error: {error}</Typography>;

  return (
    <Box sx={{ padding: { xs: 1, sm: 2, md: 3 } }}>
      <Modal open={!!editingItem} onClose={() => setEditingItem(null)}>
        <Box sx={modalStyle}>
          <Typography variant="h6" component="h2">
            Revisando Conversación
          </Typography>
          <Paper variant="outlined" sx={{ p: 2, mt: 2, maxHeight: 200, overflowY: 'auto', bgcolor: '#f9f9f9' }}>
            <Typography variant="body2"><strong>Usuario:</strong> {editingItem?.user_message}</Typography>
            <Typography variant="body2" sx={{ mt: 1, color: 'text.secondary' }}><strong>Bot:</strong> {editingItem?.assistant_response}</Typography>
          </Paper>
          <Typography variant="subtitle1" sx={{ mt: 2, mb: 1, fontWeight: 'bold' }}>
            Análisis del Experto
          </Typography>
          <Box sx={{ mt: 1, border: '1px solid #ccc', borderRadius: '4px' }}>
            <ReactQuill
              theme="snow"
              value={expertResponse}
              onChange={setExpertResponse}
            />
          </Box>
          <Box sx={{ mt: 3, display: 'flex', justifyContent: 'flex-end', gap: 2 }}>
            <Button variant="outlined" onClick={() => setEditingItem(null)} disabled={loading}>
              Cancelar
            </Button>
            <Button variant="contained" onClick={handleSave} disabled={loading}>
              {loading ? <CircularProgress size={24} /> : 'Guardar'}
            </Button>
          </Box>
        </Box>
      </Modal>

      <Paper sx={{ p: 2, mb: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
        <TextField
          fullWidth
          label="Buscar en preguntas y respuestas..."
          variant="outlined"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon />
              </InputAdornment>
            ),
          }}
        />
        <Button variant="contained" onClick={handleSearch} disabled={loading} sx={{ height: '56px' }}>
          Buscar
        </Button>
      </Paper>
      
      {loading ? (
        <Box display="flex" justifyContent="center" p={8}><CircularProgress /></Box>
      ) : (
        <TableContainer component={Paper}>
          <Table sx={{ minWidth: 650 }}>
            <TableHead>
              <TableRow sx={{ '& th': { fontWeight: 'bold', backgroundColor: '#fafafa' } }}>
                <TableCell>Fecha</TableCell>
                <TableCell>Pregunta Usuario</TableCell>
                <TableCell>Respuesta Experto</TableCell>
                <TableCell align="right">Acciones</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {history.map((item) => (
                <TableRow key={item.id} hover sx={{ '&:last-child td, &:last-child th': { border: 0 } }}>
                  <TableCell>{new Date(item.timestamp.value).toLocaleString()}</TableCell>
                  <TableCell sx={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.user_message}
                  </TableCell>
                  <TableCell>
                    <Box dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(item.expert_response) }} sx={{ 
                      maxHeight: 60, 
                      overflow: 'hidden', 
                      '& *': { margin: 0, padding: 0 } 
                    }} />
                  </TableCell>
                  <TableCell align="right">
                    <Button variant="text" size="small" onClick={() => handleEditClick(item)}>Editar</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
}

export default ChatHistoryViewer;