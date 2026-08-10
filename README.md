# GREFA · Monitor de Licitaciones Públicas (PLACSP) y Ayudas/Premios (BDNS)

Aplicación web con **dos modos** al entrar:

1. **Licitaciones** — descarga el feed ATOM de la Plataforma de Contratación del
   Sector Público, puntúa con el **Índice de Relevancia GREFA** (0-100 %) y permite
   gestionar criterios desde Google Sheets.
2. **Ayudas y premios** — consulta la API de la **BDNS**
   ([infosubvenciones.es](https://www.infosubvenciones.es)): subvenciones, premios
   y ayudas públicas, con el mismo scoring por términos GREFA (sin CPV).

Puedes cambiar de modo en cualquier momento con **Cambiar de modo** en la barra lateral.

- **Pestaña «Oportunidades GREFA»**: relevancia media y alta, tarjetas, filtro y exportación.
- **Buscador general**: todas las descargadas en sesión.
- **Mis Licitaciones / Mis Convocatorias**: seguimiento del interés del equipo.
- **Criterios compartidos**: CPV (solo licitaciones) y palabras clave en Google Sheets.

---

## 1. Estructura

```
grefa-licitaciones/
├── .streamlit/
│   ├── config.toml            # Tema y configuración del servidor
│   └── secrets.toml.example   # Plantilla de credenciales (copiar a secrets.toml)
├── config/
│   └── default_criteria.py    # CPV y palabras clave iniciales + pesos del scoring
├── modules/
│   ├── ingestion.py           # Descarga y parseo del ATOM/CODICE de la PLACSP
│   ├── ingestion_bdns.py      # API BDNS (ayudas, premios, subvenciones)
│   ├── grefa_filter.py        # Índice de Relevancia GREFA, filtros y búsqueda
│   ├── ui_ayudas.py           # Interfaz del modo Ayudas y premios
│   ├── exporter.py            # Exportación a CSV y Excel
│   ├── sheets_store.py        # Criterios y oportunidades en Google Sheets
│   └── auth.py                # Login con Google restringido al equipo
├── app.py                     # Interfaz Streamlit (hub + modos)
├── Dockerfile                 # Imagen para Cloud Run
└── requirements.txt
```

---

## 2. Ejecución en local

```bash
cd grefa-licitaciones
pip install -r requirements.txt
streamlit run app.py
```

Se abre en `http://localhost:8501`. Sin configuración adicional funciona en modo
autónomo: acceso abierto y criterios guardados solo en la sesión del navegador.

La primera carga tarda 20-30 segundos porque descarga varias páginas del feed;
después queda cacheada 30 minutos.

### Sobre la fuente de datos

El feed principal configurado es el indicado en la especificación del proyecto,
`https://contrataciondelestado.es/sourcing/licitaciones/ATOM/licitaciones.atom`,
que **actualmente devuelve 404**. La aplicación lo intenta primero y, si falla,
recurre automáticamente a las sindicaciones oficiales alternativas; la que sirve
los datos hoy es `sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom`.
En la barra lateral se muestra siempre el origen realmente utilizado y puedes
cambiar la URL a mano.

Si la red bloquea el dominio, descarga el `.atom` manualmente y súbelo desde
«Cargar fichero ATOM local».

### Fuente BDNS (modo Ayudas y premios)

API REST: `https://www.infosubvenciones.es/bdnstrans/api`. La app busca por
términos GREFA y **entidades vigiladas**, enriquece con el detalle y puntúa sin CPV.
Además, la pestaña **Web por entidad** busca en internet (DuckDuckGo, o Google CSE
si configuras `[web_search]` en Secrets) y solo conserva resultados cuyo título o
snippet **contienen la cadena** del nombre de la entidad.
En Sheets: `OportunidadesAyudas`, `MisConvocatorias` y `EntidadesAyudas`.

---

## 3. Google Sheets como almacén compartido

1. Crea una hoja de cálculo en Drive (por ejemplo, «GREFA · Licitaciones»).
2. En Google Cloud, crea una **cuenta de servicio** y descarga su clave JSON.
   Habilita las APIs `sheets.googleapis.com` y `drive.googleapis.com`.
3. **Comparte la hoja como Editor** con el `client_email` de la cuenta de servicio.
4. Copia el ID de la hoja (el tramo entre `/d/` y `/edit` de su URL) y configúralo:
   - en local: bloque `[sheets]` de `.streamlit/secrets.toml`;
   - en Cloud Run: variable de entorno `GREFA_SPREADSHEET_ID`.

La aplicación crea sola las tres pestañas la primera vez:

| Pestaña | Columnas | Uso |
| --- | --- | --- |
| `CPV` | `codigo`, `descripcion`, `activo` | Códigos vigilados. Pon `no` en `activo` para desactivar uno sin borrarlo. |
| `PalabrasClave` | `termino`, `categoria`, `activo` | Términos buscados en título y descripción. |
| `Oportunidades` | 15 columnas, incluidas `seguimiento` y `notas` | Volcado de licitaciones relevantes, sin duplicados. Las dos últimas columnas son para el equipo. |

Los cambios hechos desde la aplicación se guardan solos en la hoja, y los hechos
a mano en la hoja se recogen con el botón «⬇️ Cargar» o al recargar la página.

---

## 4. Acceso restringido a las cuentas @grefa.org

El equipo usa Google Workspace, así que el acceso se controla con la cuenta
corporativa y hay **dos barreras independientes**:

1. **Pantalla de consentimiento en modo Interno**: solo las cuentas del
   Workspace de GREFA pueden completar el login. Es la barrera real y además
   evita el proceso de verificación de Google que exigen las apps públicas.
2. **Comprobación del dominio en el servidor**: la aplicación vuelve a validar
   que el correo termine en `@grefa.org` antes de mostrar nada. Si nadie
   configura restricciones, se aplica igualmente `grefa.org` por defecto, de
   modo que un despliegue mal configurado nunca queda abierto.

### Pasos en Google Cloud

1. Crea el proyecto **dentro de la organización grefa.org** (importante: si el
   proyecto es personal, no podrás usar el modo Interno).
2. *API y servicios* → *Pantalla de consentimiento de OAuth* → tipo de usuario
   **Interno**.
3. *Credenciales* → **Crear credenciales** → *ID de cliente de OAuth 2.0* → tipo
   *Aplicación web*.
4. En **URI de redirección autorizados** añade:
   - `https://licitaciones.grefa.org/oauth2callback` (producción)
   - `http://localhost:8501/oauth2callback` (solo si vas a probarlo en local)
5. Copia `client_id` y `client_secret` al bloque `[auth]` de `secrets.toml`, y
   genera el `cookie_secret`:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

### Excepciones puntuales

Si algún colaborador externo necesita entrar sin cuenta corporativa, añádelo en
`[access] allowed_emails` (o en la variable `GREFA_ALLOWED_EMAILS`, separando
por comas). Ten en cuenta que con la pantalla de consentimiento en modo Interno
esas cuentas externas no podrán autenticarse: para admitirlas habría que pasarla
a modo Externo y confiar solo en la comprobación del servidor.

El login es opcional a efectos de desarrollo: sin bloque `[auth]` en los
secretos, la app arranca abierta y no necesitas configurar nada en local.

---

## 5. Despliegue en Google Cloud Run

> **Firebase Hosting no sirve para esta aplicación.** Streamlit necesita una
> conexión WebSocket permanente y Firebase Hosting es una CDN que bufferiza las
> respuestas: no soporta WebSockets ni streaming en sus reglas de `rewrite`, y
> corta las peticiones a los 60 segundos. Cloud Run sí los soporta de forma
> nativa. La web actual puede seguir en Firebase Hosting y enlazar al subdominio.

```bash
gcloud config set project MI_PROYECTO
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    sheets.googleapis.com drive.googleapis.com secretmanager.googleapis.com

# Secretos de Streamlit (auth + cuenta de servicio) como fichero en Secret Manager
gcloud secrets create grefa-streamlit-secrets --data-file=.streamlit/secrets.toml

gcloud run deploy grefa-licitaciones \
    --source . \
    --region europe-southwest1 \
    --allow-unauthenticated \
    --port 8080 \
    --cpu 1 --memory 1Gi \
    --timeout 3600 \
    --session-affinity \
    --min-instances 0 --max-instances 3 \
    --set-env-vars GREFA_SPREADSHEET_ID=EL_ID_DE_LA_HOJA \
    --set-secrets /home/grefa/.streamlit/secrets.toml=grefa-streamlit-secrets:latest
```

Parámetros que **no** son opcionales y conviene entender:

- `--timeout 3600`: en Cloud Run el WebSocket es una petición larga; con el
  timeout por defecto (5 min) la interfaz se desconectaría constantemente.
- `--session-affinity`: mantiene al usuario en la misma instancia, que es donde
  vive su sesión de Streamlit.
- `--max-instances 3`: cada instancia tiene su propia caché del feed; conviene
  mantener el número bajo.
- `--min-instances 0` deja el coste prácticamente en cero a cambio de unos 20
  segundos de arranque en frío. Con `1` la app está siempre despierta por unos
  5-8 € al mes.

### Dominio propio

```bash
gcloud beta run domain-mappings create --service grefa-licitaciones \
    --domain licitaciones.grefa.org --region europe-southwest1
```

Añade en el DNS de `grefa.org` los registros que devuelva el comando. El
certificado HTTPS se emite automáticamente. Recuerda que el dominio debe apuntar
**directamente a Cloud Run**, no a través de Firebase Hosting.

### Prueba local del contenedor

```bash
docker build -t grefa-licitaciones .
docker run --rm -p 8080:8080 -e GREFA_SPREADSHEET_ID=EL_ID_DE_LA_HOJA grefa-licitaciones
```

---

## 6. Cómo se calcula el Índice de Relevancia GREFA

| Bloque | Puntos | Detalle |
| --- | --- | --- |
| CPV | 50 | Coincidencia jerárquica: `77200000-2` captura también `77211500` o `77231900`. |
| Palabras clave | 50 | Reparto proporcional: un acierto en el título pesa 1,0 y en la descripción 0,6; con 3 puntos ponderados se llega al máximo. |

Categorías resultantes: **Alta** (≥ 70 %, «Oportunidad GREFA»), **Media**
(40-69 %, «Revisar») y **Baja** (< 40 %). Una licitación que solo coincide en CPV
se queda en 50 %, es decir, en «Revisar»: para llegar a Alta necesita además
palabras clave. Los umbrales y pesos se ajustan en `config/default_criteria.py`.

El índice es una estimación automática de apoyo: revisa siempre el pliego original.
