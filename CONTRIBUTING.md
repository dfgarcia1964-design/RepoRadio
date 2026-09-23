# Guía de Contribución - RepoRadio

¡Gracias por tu interés en contribuir a RepoRadio! Esta guía te ayudará a hacer contribuciones efectivas y significativas.

## 🚀 Primeros Pasos

### Requisitos
- Python 3.11+
- Git
- Un fork del repositorio

### Configuración Local

```bash
# 1. Clona tu fork
git clone https://github.com/TU_USUARIO/RepoRadio.git
cd RepoRadio

# 2. Crea rama de desarrollo
git checkout -b feature/tu-feature

# 3. Instala dependencias
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt

# 4. Ejecuta tests
python -m pytest tests/ -v
```

## 📋 Tipos de Contribuciones

### 🐛 Reportar Bugs

**Antes de reportar:**
1. Verifica que el bug aún existe en `main`
2. Busca en issues existentes
3. Prueba con la última versión de dependencias

**Al reportar, incluye:**
- Sistema operativo y versión Python
- Pasos exactos para reproducir
- Comportamiento esperado vs real
- Stack trace si es disponible

### ✨ Nuevas Funcionalidades

**Proceso:**
1. Abre una issue para discutir primero
2. Espera feedback del equipo
3. Implementa con tests
4. Envía PR con descripción clara

### 📖 Documentación

- Mejoras a README.md
- Comentarios en código complejo
- Docstrings para funciones públicas
- Guías de uso para nuevas features

## 💻 Estándares de Código

### Style Guide

```python
# ✅ Bueno
def render_audio_line(line_index, line_data, provider, lang="es"):
    """Renderizar una línea de audio.
    
    Args:
        line_index: Índice en el script
        line_data: Dict con 'speaker' y 'text'
        provider: Proveedor de TTS
        lang: Idioma (es o en-us)
    
    Returns:
        Tuple de (line_index, audio_segment)
    """
    if not isinstance(line_data, dict):
        voice_logger.warning(f"Línea {line_index}: tipo inválido")
        return (line_index, None)
    # ... implementación

# ❌ Evitar
def render(i, d, p, l="es"):  # Variables ambiguas
    # Renderizar audio
    if not isinstance(d, dict): return (i, None)  # Mucho en una línea
```

### Convenciones

- **Imports**: Organize en orden: stdlib, terceros, locales
- **Nombres**: `snake_case` para funciones/variables, `PascalCase` para clases
- **Docstrings**: Una línea para funciones simples, multilinea con Args/Returns para complejas
- **Type hints**: Recomendado para funciones públicas
- **Logging**: Usa loggers de `debug_logger.py`

### Limpieza de Recursos

**Siempre usa context managers:**
```python
# ✅ Bueno
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(task, x) for x in items]
    for future in as_completed(futures):
        result = future.result()

# ❌ Evitar
executor = ThreadPoolExecutor(max_workers=4)
futures = [executor.submit(task, x) for x in items]
# Posible fuga de recursos si ocurre excepción
```

## ✅ Pruebas

### Ejecutar Tests

```bash
# Todos los tests
python -m pytest tests/ -v

# Tests específicos
python -m pytest tests/test_voice.py::TestGetVoiceId -v

# Con coverage
python -m pytest tests/ --cov=src
```

### Escribir Tests

```python
import pytest
from audio_editor import format_clock

class TestFormatClock:
    def test_formats_ms_to_mmss(self):
        assert format_clock(65000) == "1:05"
    
    def test_handles_negative_values(self):
        assert format_clock(-1000) == "0:00"
    
    @pytest.fixture
    def sample_audio(self):
        return AudioSegment.silent(duration=5000)
    
    def test_with_fixture(self, sample_audio):
        assert len(sample_audio) == 5000
```

### Coverage Esperado
- Código crítico: 90%+
- Funcionalidad de usuario: 80%+
- Helpers/utils: 60%+

## 📝 Commit Messages

### Formato

```
tipo: descripción breve (máx 60 chars)

[Descripción más detallada si es necesario]

Fixes #123
```

### Tipos
- `feat`: Nueva funcionalidad
- `fix`: Corrección de bug
- `refactor`: Cambio de código sin cambio de comportamiento
- `test`: Agregar/actualizar tests
- `docs`: Documentación
- `perf`: Mejora de performance
- `chore`: Tareas de mantenimiento

### Ejemplos

```
✅ fix: Correct unchecked dict access in voice.py line 576

❌ fix bug in voice
```

## 🔄 Pull Request Process

### Antes de Enviar

```bash
# 1. Actualiza tu rama con main
git fetch origin
git rebase origin/main

# 2. Ejecuta tests localmente
python -m pytest tests/ -v

# 3. Verifica sintaxis
python -m py_compile src/*.py

# 4. Revisa tus cambios
git diff origin/main
```

### Descripción del PR

```markdown
## Descripción
Breve descripción de los cambios

## Tipo de Cambio
- [ ] Bug fix
- [ ] Nueva funcionalidad
- [ ] Breaking change
- [ ] Actualización de documentación

## ¿Cómo fue probado?
Describe los pasos para verificar los cambios

## Checklist
- [ ] Tests agregados/actualizados
- [ ] Documentación actualizada
- [ ] Sin warnings en linting
- [ ] Archivos relacionados revisados
```

## 🔍 Proceso de Revisión

### Qué Esperamos
- ✅ Tests que pasen
- ✅ Documentación clara
- ✅ Código limpio y mantenible
- ✅ Commits organizados

### Feedback Común
- **"Agregar test para..."**: Cubre casos edge
- **"Extractar a función..."**: Mejora reutilización
- **"Actualizar docstring..."**: Aclara comportamiento
- **"Agregar logging..."**: Ayuda con debugging

## 📚 Recursos

### Documentación
- [ARCHITECTURE.md](ARCHITECTURE.md) - Diseño del sistema
- [README.md](README.md) - Guía de usuario
- [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) - Configuración local

### Herramientas Útiles
- VSCode + Python extension
- Black (code formatter): `pip install black`
- Pylint (linter): `pip install pylint`

## 🤝 Código de Conducta

### Esperamos
- Respeto mutuo entre contribuidores
- Comunicación constructiva
- Crédito apropiado en comentarios
- Ayuda a otros aprendices

### No Toleramos
- Lenguaje ofensivo
- Acoso o discriminación
- Plagio de código
- Spam en issues/PRs

## ❓ Preguntas?

- **Dudas de setup**: Abre una issue con etiqueta `question`
- **Discusión de feature**: Comenta en el issue correspondiente
- **Problemas de test**: Incluye output completo en issue

¡Gracias por contribuir a RepoRadio! 🎙️
