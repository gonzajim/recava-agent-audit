# Vector Store Utilities

Scripts auxiliares para gestionar OpenAI Vector Stores que sustituyen a cualquier base de datos vectorial local.

## Requisitos

- Python 3.11+
- `openai` (se instala automáticamente en el entorno del backend)
- Variable `OPENAI_API_KEY` exportada en el terminal

## Crear un vector store y subir ficheros

```bash
python ops/vectorstore/create_store.py --name recava-advisor --upload docs/\*.pdf
```

Salida de ejemplo:

```
Created vector store: vs_z1abc123
Uploaded 5 files to vs_z1abc123
[
  {
    "id": "file_123",
    "filename": "manual.pdf",
    "status": "completed",
    ...
  }
]
```

Guarda el `vector_store_id` (`vs_*`) y configúralo en tu agente de la Responses API o en la llamada específica al workflow usando la herramienta `file_search`.

## Solo listar archivos existentes

```bash
python ops/vectorstore/create_store.py --store-id vs_z1abc123
```

## Notas

- Este flujo mantiene todo el retrieval en OpenAI Platform, eliminando la necesidad de bases vectoriales on-prem.
- La ingesta es eventual-consistente; espera a `status == "completed"` antes de usar el store en producción.
