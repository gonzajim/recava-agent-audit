# Especificación Funcional: Módulo de Auditoría Empírica (NEIS S1)

## 1. Objetivo
Desarrollar una nueva funcionalidad en la Home de Recava que permita realizar una auditoría automática y verificable sobre 37 indicadores específicos de la norma NEIS S1 (Personal Propio), enfocada en el análisis del IBEX 35.

## 2. Indicadores a Auditar (Total: 37)
| ID | Norma | Ref | Pregunta / Indicador |
|----|-------|-----|----------------------|
| 1 | S1-9 | 66. a) | ¿Divulga la distribución por género (en número y porcentaje) en la alta dirección? |
| 2 | S1-9 | 66. b) | ¿Divulga la distribución de los asalariados por grupos de edad? |
| 3 | S1-10 | 69. | ¿Divulga si todos sus asalariados perciben un salario adecuado de conformidad con lo índices de referencia aplicables? |
| 4 | S1-10 | 70. | Si no todos lo perciben, ¿divulga los países en que los asalariados ganan menos del índice de referencia de salario adecuado aplicable y el porcentaje de asalariados en esta situación en cada uno de los países? |
| 5 | S1-10 | 70. | Si no todos lo perciben, ¿divulga el porcentaje de asalariados en esta situación en cada uno de los países? |
| 6 | S1-10 | 71. | ¿Divulga la información especificada en este requisito con respecto a los trabajadores no asalariados de su personal propio? |
| 7 | S1-11 | 74. a) | ¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a enfermedad? |
| 8 | S1-11 | 74. b) | ¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a desempleo a partir del momento en que el trabajador propio trabaja para la empresa? |
| 9 | S1-11 | 74. c) | ¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a accidentes de trabajo y discapacidad adquirida? |
| 10 | S1-11 | 74. d) | ¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a permiso parental? |
| 11 | S1-11 | 74. e) | ¿Divulga si todos los asalariados están cubiertos por protección social contra la pérdida de ingresos debida a jubilación? |
| 12 | S1-11 | 75. [1] | Si no todos los asalariados están cubiertos por la protección social, ¿divulga los países en que los asalariados no dispongan de protección social?  |
| 13 | S1-11 | 75. [2] | Si no todos los asalariados están cubiertos por la protección social, ¿divulga por países los tipos de asalariados que no dispongan de protección social con respecto a cada acontecimiento vital importante? |
| 14 | S1-11 | 76. | ¿Divulga la información especificada en este requisito de divulgación con respecto a los trabajadores no asalariados de su personal propio? |
| 15 | S1-12 | 79. | ¿Divulga el porcentaje de personas con discapacidad entre sus asalariados? |
| 16 | S1-12 | 80.  | ¿Divulga el porcentaje de asalariados con discapacidad con desglose por género? |
| 17 | S1-14 | 88. a) [1] | Sobre el personal propio asalariado: ¿divulga el porcentaje de miembros de su personal propio cubiertos por el sistema de gestión de la salud y la seguridad de la empresa, sobre la base de requisitos legales o normas o directrices reconocidas? |
| 18 | S1-14 | 88. a) [2] | Sobre los trabajadores no asalariados: ¿divulga el porcentaje de miembros de su personal propio cubiertos por el sistema de gestión de la salud y la seguridad de la empresa, sobre la base de requisitos legales o normas o directrices reconocidas? |
| 19 | S1-14 | 88. b) [1] | Sobre el personal propio asalariado: ¿divulga el número de muertes como consecuencia de lesiones y problemas de salud relacionados con el trabajo? |
| 20 | S1-14 | 88. b) [2] | Sobre los trabajadores no asalariados: ¿divulga el número de muertes como consecuencia de lesiones y problemas de salud relacionados con el trabajo? |
| 21 | S1-14 | 88. b) [3] | Sobre otros trabajadores de la cadena de valor: ¿divulga el el número de muertes como consecuencia de lesiones y problemas de salud relacionados con el trabajo? |
| 22 | S1-14 | 88. b) [4] {AR 82} | ¿Divulga separadamente las muertes causadas por lesiones y las causadas por problemas de salud? |
| 23 | S1-14 | 88. c) [1] | Sobre el personal propio asalariado: ¿divulga el número y la tasa de accidentes de trabajo registrables? |
| 24 | S1-14 | 88. c) [2] | Sobre los trabajadores no asalariados: ¿divulga el número y la tasa de accidentes de trabajo registrables? |
| 25 | S1-14 | 88. d) | Sobre el personal propio asalariado: ¿divulga el número de casos de problemas de salud relacionados con el trabajo? |
| 26 | S1-14 | 88. d) [2] {89} | Sobre los trabajadores no asalariados: ¿divulga el número de casos de problemas de salud relacionados con el trabajo? |
| 27 | S1-14 | 88.e) | Sobre el personal propio asalariado: ¿divulga el número de días perdidos por lesiones y muertes relacionadas con el trabajo como consecuencia de accidentes laborales, problemas de salud relacionados con el trabajo y muertes por enfermedad? |
| 28 | S1-14 | 88. e) [2] {89} | Sobre los trabajadores no asalariados: ¿divulga el número de días perdidos por lesiones y muertes relacionadas con el trabajo como consecuencia de accidentes laborales, problemas de salud relacionados con el trabajo y muertes por enfermedad? |
| 29 | S1-14 | 90. | ¿Divulga el porcentaje de trabajadores propios cubiertos por un sistema de gestión de la salud y la seguridad basado en requisitos legales o en normas o directrices reconocidas y que ha sido auditado internamente o auditado o certificado por un tercero? |
| 30 | S1-14 | 90. {AR 81} | ¿Divulga la existencia o ausencia de esta auditoría, y en su caso las normas subyacentes en su realización? |
| 31 | S1-15 | 93. a) | ¿Divulga el porcentaje de asalariados que tienen derecho a acogerse a permisos por motivos familiares? |
| 32 | S1-15 | 93. b) | ¿Divulga el porcentaje de asalariados que gozan de este derecho y que se acogieron a permisos por motivos familiares, y su desglose por género? |
| 33 | S1-16 | 97. a) [1] | ¿Divulga la brecha salarial de género [del período de referencia actual {AR100}] expresada como porcentaje del nivel retributivo medio de los asalariados de género masculino? |
| 34 | S1-16 | 97. a) [2] {98} | ¿Divulga la brecha salarial de género por categoría de asalariado? |
| 35 | S1-16 | 97. a) [3] {98} | ¿Divulga la brecha salarial de género por país o segmento? |
| 36 | S1-16 | 97. b) [1] | ¿Divulga la relación entre la remuneración anual total de la persona con el mayor salario y la remuneración anual total media del conjunto de [todos: {AR 101.a)} asalariados (excluida la persona mejor pagada)? |
| 37 | S1-16 | 97. b). [2] {99} | ¿Divulga la relación entre la remuneración anual total de la persona con el mayor salario y la remuneración anual total media del conjunto de asalariados, ajustada para tener en cuenta las diferencias de poder adquisitivo entre países? |

## 3. Requisitos de Implementación (Arquitectura Recava)

### A. Backend (Cloud Run)
- **Procesamiento Asíncrono**: Crear un endpoint `/api/audit/empirical` que inicie un hilo (`threading.Thread`) para no bloquear la UI.
- **RAG de Precisión**: Por cada indicador, realizar una búsqueda en la Vector DB. La consulta debe devolver el texto y el metadato `page_number`.
- **Integración Gemini**: Usar Gemini 1.5 Pro con una temperatura de 0.0 para maximizar la consistencia.

### B. Almacenamiento (Firestore)
- **Colección `empirical_audits`**: Guardar el progreso y los resultados parciales.
- **Campos por resultado**: `cumple` (Sí/No/NA/FE), `evidencia_literal`, `pagina_real`, `razonamiento`.

### C. Frontend (React/Hosting)
- **Nueva Opción en Home**: Añadir una tarjeta/botón "Observatorio IBEX 35: Auditoría S1".
- **Panel de Validación**: Mostrar una tabla con los resultados donde el equipo de Alberto pueda marcar si la IA acertó (Feedback Loop).

## 4. Lógica de Respuesta (Mapeo)
- **SÍ**: Valor 1 + Evidencia + Página.
- **NO**: Valor 0.
- **No aparece (NA)**: Valor NA.
- **Referencia Externa (FE)**: Valor FE + Nombre del documento referido.
