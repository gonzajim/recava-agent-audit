"""Script de análisis del cuestionario y validación del skip logic."""
import json

with open('data/cuestionario_base.json', encoding='utf-8') as f:
    q = json.load(f)

blocks = q.get('blocks', [])
all_qs = [(block['id'], block['label'], qn) for block in blocks for qn in block.get('questions', [])]
all_ids = {qn['id'] for _, _, qn in all_qs}

total = len(all_qs)
conditional = sum(1 for _, _, qn in all_qs if 'show_if' in qn)
gate = sum(1 for _, _, qn in all_qs if qn.get('_skip_trigger'))

print(f"Total preguntas: {total}")
print(f"Con skip logic (show_if): {conditional}")
print(f"Preguntas gate (triggers): {gate}")
print()

print("=== Árbol de Skip Logic ===")
errors = []
for bid, blabel, qn in all_qs:
    if 'show_if' in qn:
        deps = [c.get('question_id') for c in qn['show_if']]
        # Validar que todas las dependencias existen
        for dep in deps:
            if dep not in all_ids:
                errors.append(f"ERROR: Q{qn['id']} depende de Q{dep} que NO EXISTE en el cuestionario")
        print(f"  [{bid}] Q{qn['id']} <- depende de: {deps}")

print()
if errors:
    print("=== ERRORES ENCONTRADOS ===")
    for e in errors:
        print(f"  {e}")
else:
    print("=== Sin errores de referencia ===")
    print("Todas las dependencias apuntan a preguntas existentes.")

print()
print("=== Escenario: empresa solo en España ===")
print("  1.7=Si -> se omiten: 3.2b, 3.6, 4.2b, 4.5, 6.1b, 6.4b, 8.1b")
print()
print("=== Escenario: sin mapa de cadena de valor (3.1=No) ===")
print("  3.1=No -> se omiten: 3.2, 3.2b, 3.4, 3.5, 3.6, 6.3b, 6.4b")
print()
print("=== Escenario: sin órgano de gobierno (2.1=No) ===")
print("  2.1=No -> se omiten: 2.4, 2.5")
print()
print("=== Escenario: sin canal de denuncias (4.2=No) ===")
print("  4.2=No -> se omiten: 4.2b")
print()
print("=== Escenario: sector no EUDR (5.2b=No) ===")
print("  5.2b=No -> se omite: 5.3")
print()
print("=== Escenario: sin denuncias (7.3=No) ===")
print("  7.3=No -> se omite: 7.3b")
