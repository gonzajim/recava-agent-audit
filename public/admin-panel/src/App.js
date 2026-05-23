// src/App.js
import React, { useState, useEffect } from 'react';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { auth } from './firebase';
import Login from './Login';
import EmpiricalAuditViewer from './EmpiricalAuditViewer';
import InteractiveAuditViewer from './InteractiveAuditViewer';

import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import theme from './theme';
import {
  AppBar, Toolbar, Typography, Button, Box, Paper, Tabs, Tab,
} from '@mui/material';
import AssessmentIcon from '@mui/icons-material/Assessment';
import QuizIcon from '@mui/icons-material/Quiz';

function TabPanel({ children, value, index }) {
  return (
    <Box
      role="tabpanel"
      hidden={value !== index}
      id={`tabpanel-${index}`}
      aria-labelledby={`tab-${index}`}
      sx={{ flex: 1, overflow: 'hidden', display: value === index ? 'flex' : 'none', flexDirection: 'column' }}
    >
      {value === index && children}
    </Box>
  );
}

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState(0);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setLoading(false);
    });
    return () => unsubscribe();
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Typography color="text.secondary">Cargando...</Typography>
      </Box>
    );
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        {/* ── Barra superior ── */}
        <AppBar position="static" elevation={1}>
          <Toolbar sx={{ flexWrap: 'wrap', minHeight: {xs: 64, sm: 64}, py: {xs:1, sm:0} }}>
            <Typography variant="h6" component="div" sx={{ flexGrow: 1, fontWeight: 700, fontSize: {xs:'1.1rem', sm:'1.25rem'} }}>
              ReCaVa Buscador
            </Typography>
            {user && (
              <Box sx={{ display: 'flex', gap: {xs:1, sm:2}, alignItems: 'center' }}>
                <Typography variant="body2" sx={{ opacity: 0.85, display: {xs:'none', sm:'block'} }}>
                  {user.email}
                </Typography>
                <Button color="inherit" size="small" onClick={() => signOut(auth)}>
                  Cerrar Sesión
                </Button>
              </Box>
            )}
          </Toolbar>
        </AppBar>

        {/* ── Contenido ── */}
        {user ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
            {/* Tabs de navegación */}
            <Box sx={{ borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
              <Tabs
                value={activeTab}
                onChange={(_, v) => setActiveTab(v)}
                aria-label="Módulos de auditoría"
                variant="scrollable"
                scrollButtons="auto"
              >
                <Tab
                  id="tab-0"
                  aria-controls="tabpanel-0"
                  icon={<AssessmentIcon />}
                  iconPosition="start"
                  label="Auditoría Empírica (NEIS S1)"
                />
                <Tab
                  id="tab-1"
                  aria-controls="tabpanel-1"
                  icon={<QuizIcon />}
                  iconPosition="start"
                  label="Autoauditoría Interactiva (CSDDD)"
                />
              </Tabs>
            </Box>

            {/* Contenido de cada tab */}
            <Box sx={{ flex: 1, overflow: 'auto' }}>
              <TabPanel value={activeTab} index={0}>
                <EmpiricalAuditViewer />
              </TabPanel>
              <TabPanel value={activeTab} index={1}>
                <InteractiveAuditViewer />
              </TabPanel>
            </Box>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '80vh' }}>
            <Paper elevation={3} sx={{ padding: 4, minWidth: 320 }}>
              <Login />
            </Paper>
          </Box>
        )}
      </Box>
    </ThemeProvider>
  );
}

export default App;