// src/App.js
import React, { useState, useEffect } from 'react';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { auth } from './firebase';
import Login from './Login';
import ChatHistoryViewer from './ChatHistoryViewer';
import AgentsConfigEditor from './AgentsConfigEditor';

// --- NUEVAS IMPORTACIONES PARA EL TEMA ---
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import theme from './theme'; // Importamos nuestro tema personalizado
import { AppBar, Toolbar, Typography, Button, Box, Paper, Tabs, Tab } from '@mui/material';

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeView, setActiveView] = useState('history');

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setLoading(false);
    });
    return () => unsubscribe();
  }, []);

  useEffect(() => {
    if (!user) {
      setActiveView('history');
    }
  }, [user]);

  if (loading) {
    return <div>Cargando...</div>;
  }

  // Usamos el ThemeProvider para envolver toda la aplicación
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline /> {/* Normaliza los estilos del navegador */}
      <Box sx={{ flexGrow: 1 }}>
        {/* Cabecera superior con el estilo UCLM */}
        <AppBar position="static">
          <Toolbar>
            <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
              Panel de Experto ReCaVa
            </Typography>
            {user && (
              <Button color="inherit" onClick={() => signOut(auth)}>Cerrar Sesión</Button>
            )}
          </Toolbar>
        </AppBar>

        {/* Contenido Principal */}
        <main>
          {user ? (
            <Box sx={{ px: { xs: 1, sm: 2, md: 4 }, py: { xs: 2, md: 3 } }}>
              <Tabs
                value={activeView}
                onChange={(_, value) => setActiveView(value)}
                variant="scrollable"
                allowScrollButtonsMobile
              >
                <Tab value="history" label="Historial de chats" />
                <Tab value="config" label="Configuración de agentes" />
              </Tabs>
              <Box sx={{ mt: 3 }}>
                {activeView === 'history' && <ChatHistoryViewer />}
                {activeView === 'config' && <AgentsConfigEditor />}
              </Box>
            </Box>
          ) : (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '80vh' }}>
              <Paper elevation={3} sx={{ padding: 4 }}>
                <Login />
              </Paper>
            </Box>
          )}
        </main>
      </Box>
    </ThemeProvider>
  );
}

export default App;
