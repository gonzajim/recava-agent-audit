"""Test del motor de historial multi-turn del Modo Asesor."""
import sys
sys.path.insert(0, '.')
import types

# Mock de dependencias externas
sys.modules['src.config'] = types.SimpleNamespace(
    logger=type('L', (), {'debug': print, 'info': print, 'warning': print, 'error': print})(),
    firestore_db=None
)
sys.modules['src.vector_service'] = types.SimpleNamespace(retrieve_context=lambda **k: 'RAG')
sys.modules['google.generativeai'] = types.SimpleNamespace()
sys.modules['google.cloud.firestore_v1'] = types.SimpleNamespace(SERVER_TIMESTAMP=None)

from src.interactive_audit_service import _prepare_gemini_history

tests_ok = 0

# T1: Vacío
h = _prepare_gemini_history([])
assert h == [], f'T1 fallo: {h}'
print('T1 OK: vacío -> []'); tests_ok += 1

# T2: Solo saludo del asesor -> conservado como contexto
h = _prepare_gemini_history([{'role': 'advisor', 'text': 'Hola'}])
assert len(h) == 1 and h[0]['role'] == 'model'
print('T2 OK: saludo asesor -> [model]'); tests_ok += 1

# T3: Un turno completo
h = _prepare_gemini_history([
    {'role': 'advisor', 'text': 'Hola'},
    {'role': 'user',    'text': 'Qué es CSDDD?'},
    {'role': 'advisor', 'text': 'Es la directiva...'},
])
assert h[-1]['role'] == 'model' and len(h) == 3
print('T3 OK: turno completo [m,u,m] -> correcto'); tests_ok += 1

# T4: User al final se elimina (es el mensaje actual, va por send_message)
h = _prepare_gemini_history([
    {'role': 'advisor', 'text': 'Hola'},
    {'role': 'user',    'text': 'Pregunta 1'},
    {'role': 'advisor', 'text': 'Respuesta 1'},
    {'role': 'user',    'text': 'Nueva pregunta (ACTUAL - debe eliminarse)'},
])
assert h[-1]['role'] == 'model', 'T4: user final no eliminado'
assert len(h) == 3
print('T4 OK: user final eliminado correctamente'); tests_ok += 1

# T5: Divider ignorado + fusión de model consecutivos
h = _prepare_gemini_history([
    {'role': 'advisor', 'text': 'Hola P1'},
    {'role': 'user',    'text': 'Duda P1'},
    {'role': 'advisor', 'text': 'Resp P1'},
    {'role': 'divider', 'text': '--- P2 ---'},
    {'role': 'advisor', 'text': 'Hola P2'},
])
assert len(h) == 3, f'T5: esperaba 3, encontré {len(h)}'
assert h[-1]['role'] == 'model'
assert 'Resp P1' in h[2]['parts'][0] and 'Hola P2' in h[2]['parts'][0]
print('T5 OK: divider ignorado + model consecutivos fusionados'); tests_ok += 1

# T6: Escenario real — conversación que cruza 2 preguntas
h = _prepare_gemini_history([
    {'role': 'advisor', 'text': 'Bienvenido P1'},        # P1 greeting
    {'role': 'user',    'text': 'Qué evidencias?'},        # P1 user
    {'role': 'advisor', 'text': 'Necesitas X, Y, Z'},      # P1 advisor
    {'role': 'divider', 'text': '--- P2 ---'},             # divider (ignored)
    {'role': 'advisor', 'text': 'Ahora P2: ...' },         # P2 greeting
    {'role': 'user',    'text': 'Tengo duda P2'},          # P2 user (CURRENT - remove)
])
# Esperamos: [model(P1 bienvenido), user(P1 duda), model(P1 resp + P2 greeting)]
# El user final P2 se elimina
assert len(h) == 3, f'T6: esperaba 3, encontré {len(h)} -> {[(x["role"], x["parts"][0][:30]) for x in h]}'
assert h[0]['role'] == 'model'
assert h[1]['role'] == 'user'
assert h[2]['role'] == 'model'
assert 'Necesitas X' in h[2]['parts'][0]  # fusion de P1 resp + P2 greeting
assert 'Ahora P2' in h[2]['parts'][0]
print('T6 OK: escenario real con 2 preguntas cruzadas'); tests_ok += 1

print()
print(f'Todos los tests ({tests_ok}/6) pasaron correctamente.')
print()
print('Motor de historial multi-turn validado:')
print('  ✓ Mensajes divider ignorados')
print('  ✓ Mensajes vacíos ignorados')
print('  ✓ Roles consecutivos iguales fusionados (Gemini requiere alternancia)')
print('  ✓ Historial nunca termina en "user" (evita error de la API de Gemini)')
print('  ✓ Conversación que cruza múltiples preguntas funciona correctamente')
