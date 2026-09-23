# Arquitectura de RepoRadio

## 🏗️ Visión General

RepoRadio es un sistema que convierte análisis de repositorios GitHub en podcasts de audio con IA. La arquitectura está diseñada para ser modular, escalable y fácil de mantener.

```
┌─────────────────────────────────────────────────────────────┐
│                     STREAMLIT UI (app.py)                  │
│  - Editor de guiones (Guion)                               │
│  - Editor de audio (Editar)                                │
│  - Reproductor de audio (Escuchar)                         │
│  - Herramientas de edición (Recortar)                      │
│  - Visualización de video (Video)                          │
└─────────────┬───────────────────────────────────────────────┘
              │
    ┌─────────┴──────────┬──────────────┬─────────────┐
    │                    │              │             │
    ▼                    ▼              ▼             ▼
┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐
│  BRAIN     │  │   VOICE    │  │   AUDIO    │  │ EPISODE  │
│  (IA)      │  │   (TTS)    │  │   (Mix)    │  │  STORE   │
│            │  │            │  │            │  │          │
│ - Scripts  │  │ - Kokoro   │  │ - Mixer    │  │ - JSON   │
│ - Guests   │  │ - ElevenLab│  │ - Crossfade│  │ - MP3    │
│ - Planning │  │ - Render   │  │ - Effects  │  │ - Cues   │
└────────────┘  └────────────┘  └────────────┘  └──────────┘
    ▲               ▲                  ▲             ▲
    │               │                  │             │
    └───────────────┴──────────────────┴─────────────┘
            │
    ┌───────┴──────────────────┐
    │                          │
    ▼                          ▼
┌────────────────┐        ┌──────────────┐
│    INGEST      │        │  DOCUMENT    │
│  (Repository)  │        │   HANDLER    │
│                │        │              │
│ - Git Clone    │        │ - Upload PDF │
│ - Analysis     │        │ - Parse Docs │
│ - Dependencies │        │ - Combine    │
└────────────────┘        └──────────────┘
```

## 📦 Módulos Principales

### 1. **app.py** - Interfaz de Usuario
- UI en Streamlit con 5 secciones principales
- Gestión de estado de sesión
- Integración de componentes React (line_follow, live_edit)
- Manejo de uploads y carga de archivos

### 2. **brain.py** - Motor de IA
- Generación de scripts de podcast
- Integración con LM Studio (local) u Ollama
- Carga de personajes (hosts)
- Planificación de análisis de código

### 3. **voice.py** - Síntesis de Voz (TTS)
- Renderizado paralelo de líneas de audio
- Soporte para Kokoro (local) y ElevenLabs (cloud)
- Manejo de errores con reintentos
- Limpieza de recursos

### 4. **audio/mixer.py** - Mezcla de Audio
- Overlay de música de fondo
- Crossfades entre segmentos
- Transiciones y jingles
- Generación de cues (marcas de tiempo)

### 5. **episode_store.py** - Almacenamiento
- Persistencia de guiones (JSON + TXT)
- Guardado de audio (MP3, WAV)
- Gestión de metadatos
- Recuperación de episodios previos

### 6. **ingest.py** - Análisis de Repositorios
- Clonado de repos en sandbox (Daytona)
- Extracción de git history
- Análisis de dependencias
- Identificación de archivos prioritarios

### 7. **playback.py** - Reproducción
- Cálculo de cues (sincronización de líneas)
- Seguimiento de línea durante reproducción
- Overlay de script en audio
- HTML para seguimiento interactivo

## 🔄 Flujos de Trabajo

### Flujo Principal: Crear Podcast

```
1. INGERIR (ingest.py)
   └─ User ingresa URL GitHub
      └─ Análisis de repo en sandbox
      └─ Extrae README, dependencias, git history

2. GENERAR GUION (brain.py)
   └─ IA genera script con múltiples hosts
   └─ Validación de formato JSON
   └─ Persistencia en JSON + TXT

3. EDITAR GUION (app.py)
   └─ User edita líneas de diálogo
   └─ Auto-guardado después cada cambio
   └─ Opción de mejorar claridad (IA)

4. GENERAR AUDIO (voice.py)
   └─ Renderizado paralelo de TTS
   └─ Reintentos automáticos para líneas fallidas
   └─ Inyección de pausas en puntos faltantes

5. MEZCLAR AUDIO (mixer.py)
   └─ Overlay de música de fondo
   └─ Crossfades entre hosts
   └─ Transiciones y jingles
   └─ Ducking automático de volumen

6. SINCRONIZAR TXT (playback.py)
   └─ Calcular cues (línea → timestamp)
   └─ Generar HTML para seguimiento
   └─ Guardar en cues.json

7. EDITAR AUDIO (audio_editor.py)
   └─ Trim, gain, drop ranges
   └─ Splice (reemplazar segmentos)
   └─ Shift cues cuando se reemplazan líneas

8. VIDEO (video_board.py)
   └─ Crear storyboard visual
   └─ Asignar media a líneas
   └─ Exportar para edición posterior

```

### Flujo Alternativo: Cargar Archivo

```
User carga archivo (JSON/TXT/MP3)
   │
   ├─ Si es MP3
   │  └─ Transcribir a guion (speech-to-text)
   │  └─ Populcar editor
   │
   ├─ Si es JSON/TXT
   │  └─ Parsear estructura
   │  └─ Validar formato
   │  └─ Cargar en editor
   │
   └─ Auto-guardar como episodio
```

## 🛡️ Manejo de Errores y Recursos

### Limpieza Garantizada
- **ThreadPoolExecutor**: Context manager asegura shutdown
- **Sandbox Daytona**: Try/finally asegura delete en fallos
- **Archivos MP3**: Limpieza en excepciones de exportación
- **Validación**: Checks antes de operaciones de archivo

### Validación de Entrada
- URLs: Patrón regex + sanitización
- Scripts: Verificación de estructura JSON
- Audio: Validación de duraciones
- Paths: Normalización de caracteres acentuados

## 📊 Flujos de Datos

### Script Object
```python
[
  {
    "speaker": "Alex",
    "text": "Welcome to RepoRadio!",
    "voice_id": "em_alex",  # opcional
  },
  ...
]
```

### Cues Object
```python
[
  {
    "index": 0,
    "speaker": "Alex",
    "text": "Welcome to RepoRadio!",
    "start_ms": 0,
    "end_ms": 2500,
  },
  ...
]
```

### Episode Metadata
```python
{
  "audio": "/path/to/episode.mp3",
  "duration_ms": 180000,
  "cues": [...],
  "title": "Mi Podcast",
  "created": "2025-09-23T10:30:00Z"
}
```

## 🔧 Configuración

### Variables de Entorno
- `OLLAMA_IP`: Host del servidor Ollama (default: local)
- `LM_STUDIO_URL`: URL de LM Studio (default: http://localhost:1234/v1)
- `ELEVENLABS_API_KEY`: Token de ElevenLabs (si usas cloud)
- `DAYTONA_API_KEY`: Token de Daytona (si usas sandbox remoto)

### Providers Soportados
- **Brain**: "Local (LM Studio)" o "Local (Ollama)"
- **Voice**: "Local (Kokoro)" o "Cloud (ElevenLabs)"

## 🚀 Escalabilidad

### Optimizaciones Actuales
- Renderizado paralelo de TTS (configurable: 1-8 workers)
- Caché de documentos procesados
- Limpieza automática de temporales
- Reintentos inteligentes en fallos de IA

### Puntos de Extensión
- Agregar nuevos providers de IA (OpenAI, Anthropic)
- Integrar otros TTS (Google Cloud, AWS Polly)
- Soportar más formatos de salida (EPUB, PDF)
- Agregar análisis de sentimiento o emoción
