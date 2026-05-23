# Alfred AI - Bot de recordatorios (Telegram)


# 1. Estado actual del bot

## Resumen funcional
El bot permite crear recordatorios en lenguaje natural por Telegram. Interpreta el mensaje con OpenAI para extraer tarea y fecha, guarda el recordatorio en SQLite y programa una notificacion con APScheduler. Incluye flujo de registro por invitacion y comandos de administracion.

## Capacidades actuales
- Registro de usuarios con codigo de invitacion.
- Deteccion de ciudad y zona horaria del usuario durante el registro.
- Creacion de recordatorios con texto libre (con fecha/hora).
- Aviso anticipado: "recuérdame 2 horas antes que tengo médico a las 8" programa el aviso a las 6 y guarda la hora real del evento por separado.
- Detalle rico en la tarea: conserva lugar, persona, dirección, teléfono, enlace u otros datos útiles que mencione el usuario.
- Notas sin fecha: si no se especifica hora, pregunta si quiere recordatorio. Si dice no, guarda como nota.
- Validacion de fechas (solo futuras); si la hora ya pasó hoy, avisa y pide de nuevo.
- Edicion de hora de un recordatorio con `/edit <id>` o detectando intención en lenguaje natural ("cambia el recordatorio X a las 5").
- Listado de recordatorios programados y notas sin fecha en secciones separadas. Si hay aviso anticipado, muestra hora de aviso y hora del evento.
- Eliminacion de recordatorio (`/delete <id>`) o nota (`/delete N-<id>`).
- Eliminacion de todos los recordatorios y notas propios.
- Consulta de notas por lenguaje natural ("qué tengo pendiente", "de qué me tengo que acordar"...).
- Notificaciones automaticas cuando llega la hora.
- Mensajes de notificacion generados por OpenAI.
- Administracion: generar invitaciones, listar usuarios, revocar acceso.

## Flujo de usuario (registro)
1) Usuario escribe `/start`.
2) Si es admin, se le muestran comandos y finaliza el flujo.
3) Si no está registrado, se solicita código de invitación.
4) Se pide ciudad para inferir zona horaria.
5) Se solicita un nombre/apodo.
6) Se registra el usuario y queda activo.

## Flujo de usuario (recordatorios)
1) Usuario envia un mensaje con la tarea y la fecha.
2) Se genera contexto temporal (fecha/hora actual + zona horaria del usuario).
3) OpenAI devuelve JSON con tarea, fecha ISO y confirmacion.
4) Si hay fecha: se valida que sea futura y se programa en APScheduler. Si la hora ya pasó hoy, avisa y pide de nuevo.
5) Si no hay fecha: pregunta si quiere que se lo recuerde a alguna hora.
   - Si sí: pide la hora → crea recordatorio programado.
   - Si no: guarda como nota sin fecha (aparece en `/list` y se puede consultar por lenguaje natural).
6) Al llegar la hora, el scheduler dispara la notificacion.

## Flujo de usuario (notas sin fecha)
- Crear: enviar mensaje sin hora → responder "no" cuando pregunta si quiere hora.
- Ver: `/list` (sección "Cosas pendientes") o preguntar "qué tengo pendiente".
- Borrar: `/delete N-<id>`.

## Comandos disponibles
- `/help`: ayuda general y ejemplos.
- `/list`: lista recordatorios programados y notas sin fecha (en secciones separadas).
- `/edit <id>`: cambia la hora de un recordatorio existente (también detectable por lenguaje natural).
- `/delete <id>`: elimina un recordatorio propio.
- `/delete N-<id>`: elimina una nota sin fecha propia.
- `/delete_all`: elimina todos los recordatorios y notas pendientes.
- `/start`: inicia flujo de registro (ConversationHandler).

Comandos admin (solo el user_id que esté guardado como admin):
- `/admin_invite`: genera codigo de invitacion.
- `/admin_users`: lista usuarios registrados.
- `/admin_revoke <user_id>`: desactiva usuario.



# 2. Infraestructura técnica

## Parte 1: Explicacion general del proyecto

### Requisitos
- Python 3.11+ (probado con 3.13 en el entorno actual)
- Token de bot de Telegram (BotFather)
- API key de OpenAI

### Estructura del proyecto (resumen)
- `main.py`: punto de entrada, inicializacion de servicios y arranque del bot.
- `bot/handlers.py`: comandos y mensajes de usuarios.
- `bot/registration.py`: flujo de registro por invitacion.
- `services/openai_service.py`: parseo de recordatorios + mensajes de notificacion con OpenAI.
- `services/time_service.py`: parseo/formatos de tiempo y zonas horarias.
- `services/city_service.py`: mapeo ciudad -> zona horaria via OpenAI.
- `database/db.py`: persistencia en SQLite (recordatorios, usuarios, invitaciones).
- `scheduler/reminder_scheduler.py`: programacion y ejecucion de recordatorios.
- `data/reminders.db`: base de datos (se crea/usa automaticamente).

### Flujo de uso
- Usuarios normales: deben registrarse con `/start` y un codigo de invitacion.
- Admin: con `/admin_invite` genera codigos. `/admin_users` lista usuarios. `/admin_revoke` desactiva.
- Uso normal: escribir un mensaje tipo "Recu�rdame ..." crea recordatorio.

### Base de datos
SQLite en `data/reminders.db`. Se crea automaticamente al iniciar. Tablas: `reminders`, `notes`, `users`, `invitation_codes`.

### Troubleshooting
- Error de configuracion: revisa `.env` y que `ADMIN_USER_ID` sea numerico.
- OpenAI: valida la API key y el modelo configurado en `config.py`.
- Zonas horarias: el sistema usa IANA (ej: `Europe/Madrid`).

## Parte 2: Replicacion y despliegue

### Configuracion
1) Copia `.env.example` a `.env` y completa los valores:

```
TELEGRAM_TOKEN=...   # token del bot (BotFather)
OPENAI_API_KEY=...   # api key de OpenAI
DFT_TIMEZONE=Europe/Madrid
ADMIN_USER_ID=...    # tu user_id de Telegram
```

Notas:
- `ADMIN_USER_ID` es obligatorio. El admin puede generar codigos de invitacion.
- `DFT_TIMEZONE` se usa como fallback cuando un usuario no tiene zona horaria.

### Instalacion local (Windows / Linux / macOS)
Desde el directorio `alfred-ai/`:

```
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

### Ejecucion local
```
python main.py
```

El bot iniciara en modo polling y quedara a la espera de mensajes.

### Docker (recomendado para despliegue simple)
1) Copia `.env.example` a `.env` y completa valores.
2) Construye la imagen:

```
docker build -t alfred-bot .
```

3) Ejecuta el contenedor (persistiendo la base de datos):

```
docker run --env-file .env -v ${PWD}/data:/app/data --name alfred-bot --restart unless-stopped alfred-bot
```

### Docker Compose
1) Copia `.env.example` a `.env` y completa valores.
2) Levanta el servicio:

```
docker compose up -d --build
```

3) Verifica logs:

```
docker compose logs -f
```

### Replicar el proceso en otra maquina (pasos claros)
1) Clona el repo en la nueva maquina.
2) Instala Python 3.11+.
3) Crea y activa un virtualenv.
4) Instala dependencias con `pip install -r requirements.txt`.
5) Copia `.env.example` a `.env` y completa valores.
6) Ejecuta `python main.py` para validar que inicia correctamente.

### Despliegue (produccion)
El bot funciona como proceso en primer plano. Para produccion se recomienda gestionarlo como servicio.

#### Opcion A: Linux (systemd)
Crea un servicio como `alfred-bot.service`:

```
[Unit]
Description=Alfred AI Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/ruta/al/proyecto/app
EnvironmentFile=/ruta/al/proyecto/app/.env
ExecStart=/ruta/al/proyecto/app/.venv/bin/python /ruta/al/proyecto/app/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Luego:
```
sudo systemctl daemon-reload
sudo systemctl enable alfred-bot
sudo systemctl start alfred-bot
sudo systemctl status alfred-bot
```

#### Opcion B: Windows (Task Scheduler o NSSM)
- **Task Scheduler**: crea una tarea que ejecute `python main.py` al iniciar sesion o al arrancar el sistema.
- **NSSM**: registra el script como servicio apuntando a `python.exe` y `main.py`.

### Logs
- El logging va a stdout. En servicios, redirige a archivo o usa el sistema de logs del SO.


# 3. Tests

## Ejecutar los tests
Instala las dependencias de desarrollo:
```
pip install -r requirements-dev.txt
```

Ejecuta los tests:
```
pytest
```

O con salida detallada:
```
pytest -v --tb=short
```

## Herramientas de calidad de código
```
# Linter
ruff check .

# Auditoría de seguridad de dependencias
pip-audit -r requirements.txt
```

## Cobertura actual
Los tests cubren los módulos principales con mocks de servicios externos:
- `tests/test_config.py`: validación de configuración y variables de entorno.
- `tests/test_database.py`: operaciones CRUD sobre SQLite (reminders, usuarios, invitaciones).
- `tests/test_openai_service.py`: parseo de recordatorios y generación de notificaciones con OpenAI mockeado.
- `tests/test_time_service.py`: parseo de fechas ISO, zonas horarias y formateo.

Los tests son asincrónicos y usan `pytest-asyncio` en modo `auto` (configurado en `pytest.ini`).


# 4. CI/CD (GitHub Actions)

El repositorio incluye cuatro workflows:

## `ci.yml` — Integración continua
Se ejecuta en cada push y pull request sobre cualquier rama.
- **Lint (Ruff)**: verifica estilo y calidad del código.
- **Tests**: ejecuta `pytest` con Python 3.11.
- **Validate .env.example**: comprueba que no haya tokens reales y que estén declaradas las variables requeridas.

## `docker.yml` — Build & Push Docker
Se ejecuta solo en push a `main` (o manual con `workflow_dispatch`).
- Construye la imagen Docker y la publica en GitHub Container Registry (`ghcr.io`).
- Etiquetas generadas: `sha-<commit>` y `latest`.

## `deploy.yml` — Deploy a servidor
Se ejecuta automáticamente cuando `docker.yml` termina con éxito en `main`.
- Conecta al servidor via SSH y ejecuta `docker compose pull && docker compose up -d`.

### GitHub Secrets necesarios para el deploy
| Secret | Descripción |
|---|---|
| `SSH_HOST` | IP o hostname del servidor de producción |
| `SSH_USER` | Usuario SSH |
| `SSH_KEY` | Clave SSH privada (en formato PEM) |
| `SSH_PORT` | Puerto SSH (por defecto 22) |
| `DEPLOY_PATH` | Ruta absoluta al directorio del proyecto en el servidor |

## `security.yml` — Auditoría de seguridad
- Se ejecuta cada lunes a las 8:00 UTC y en cada push a `main` que modifique `requirements.txt`.
- Usa `pip-audit` para detectar vulnerabilidades conocidas en las dependencias.
- El informe se guarda como artefacto en GitHub Actions durante 30 días.
