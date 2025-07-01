// src/theme.js
import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    primary: {
      main: '#8C1B3A', // El rojo corporativo de la UCLM
      dark: '#6D142C',  // Una versión más oscura para el efecto hover
    },
    secondary: {
      main: '#4A4A4A', // Un gris oscuro para texto secundario
    },
    background: {
      default: '#f4f6f8', // Un gris muy claro para el fondo de la página
      paper: '#ffffff',   // Blanco para los "papeles" o tarjetas
    },
  },
  typography: {
    fontFamily: [
      'Inter', // Una fuente moderna y limpia similar a la de la web
      'Roboto',
      '"Helvetica Neue"',
      'Arial',
      'sans-serif'
    ].join(','),
    h6: {
      fontWeight: 600, // Títulos un poco más pesados
    }
  },
  components: {
    // Sobrescribir estilos de componentes específicos
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none', // Para que los botones no estén en mayúsculas
          borderRadius: '8px',   // Bordes ligeramente redondeados
        },
      },
    },
    MuiPaper: {
        styleOverrides: {
            root: {
                borderRadius: '8px', // Bordes redondeados para las "tarjetas"
            }
        }
    }
  },
});

export default theme;