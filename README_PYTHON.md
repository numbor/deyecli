# Deye CLI - Python Implementation

## Overview

`deye_cli.py` è una traduzione completa da bash a Python del progetto deyecli che integra anche le funzionalità del server API HTTP.

### Caratteristiche principali

✅ **Traduzione completa da Bash a Python**
- Tutti i comandi dello script bash `deyecli.sh` sono disponibili
- Stessi parametri e opzioni
- Compatibilità con il file di configurazione

✅ **Server API HTTP integrato**
- Endpoints REST per tutti i comandi
- Supporto autenticazione Bearer token
- CORS enabled
- Configurazione porta e indirizzo

✅ **Gestione configurazione avanzata**
- File di configurazione XDG-compliant
- Variabili d'ambiente
- Argomenti CLI (con precedenza)
- Auto-rilevamento e save token

✅ **Funzionalità complete**
- Hash SHA256 password
- Retry logic con backoff esponenziale
- Timeout configurabili
- Debug mode
- Forecast solare con Open-Meteo

## Installazione

```bash
# Rendere eseguibile
chmod +x deye_cli.py

# Installare dipendenze opzionali (consigliato)
pip install requests
```

## Uso

### Comandi CLI

#### 1. Ottenere token di accesso

```bash
./deye_cli.py token \
  --app-id YOUR_APP_ID \
  --app-secret YOUR_APP_SECRET \
  --email your@email.com \
  --password yourpassword
```

Token viene salvato automaticamente in: `~/.config/deyecli/config`

#### 2. Leggere configurazione batteria

```bash
./deye_cli.py config-battery DEVICE_SN
```

#### 3. Leggere configurazione sistema

```bash
./deye_cli.py config-system DEVICE_SN
```

#### 4. Aggiornare parametri batteria

```bash
./deye_cli.py battery-parameter-update \
  --param-type MAX_CHARGE_CURRENT \
  --value 20 \
  --device-sn DEVICE_SN
```

Parametri supportati:
- `MAX_CHARGE_CURRENT`: 0-200 (A)
- `MAX_DISCHARGE_CURRENT`: 0-200 (A)
- `GRID_CHARGE_AMPERE`: 0-100 (A)
- `BATT_LOW`: 0-100 (%)

#### 5. Listare stazioni

```bash
./deye_cli.py station-list
```

#### 6. Ottenere dati recenti stazione

```bash
./deye_cli.py station-latest STATION_ID
```

#### 7. Ottenere dati recenti dispositivo

```bash
./deye_cli.py device-latest DEVICE_SN
```

#### 8. Generare cron per carica solare

```bash
./deye_cli.py solar-charge-cron \
  --lat 44.0637 \
  --lon 12.4525 \
  --hours 12 \
  --min-radiation 200 \
  --low-charge-current 20 \
  --dry-run
```

Opzioni:
- `--lat`, `--lon`: Coordinate GPS (obbligatorio)
- `--hours`: Ore di forecast (default: 12)
- `--min-radiation`: Radiazione minima W/m² (default: 200)
- `--low-charge-current`: Corrente ridotta quando soleggiato (default: 20 A)
- `--restore-default-charge-current`: Ripristinare valore originale dopo slot soleggiati
- `--print-slots`: Mostrare tabella slot orari
- `--dry-run`: Mostrare content senza scrivere file
- `--show-config`: Mostrare configurazione in uso

#### 9. Mostrare configurazione

```bash
./deye_cli.py show-config
```

#### 10. Avviare server API HTTP

```bash
./deye_cli.py api --host 0.0.0.0 --port 8000
```

### Opzioni globali

```bash
./deye_cli.py [OPZIONI_GLOBALI] <comando> [OPZIONI_COMANDO]
```

Opzioni globali disponibili:
- `--base-url`: URL base API (default: https://eu1-developer.deyecloud.com)
- `--app-id`: Application ID
- `--app-secret`: Application secret
- `--username`: Username
- `--email`: Email
- `--mobile`: Numero mobile
- `--country-code`: Country code
- `--password`: Password (hashing automatico)
- `--company-id`: Company ID
- `--token`: Bearer token
- `--device-sn`: Device serial number
- `--station-id`: Station ID
- `--print-query`: Debug mode (mostra curl commands)

## Configurazione

### File configurazione

Il programma carica la configurazione da: `~/.config/deyecli/config`

Formato:
```ini
DEYE_APP_ID="your-app-id"
DEYE_APP_SECRET="your-app-secret"
DEYE_EMAIL="your@email.com"
DEYE_TOKEN="bearer-token-xxx"
DEYE_WEATHER_LAT="44.0637"
DEYE_WEATHER_LON="12.4525"
DEYE_SOLAR_MIN_RADIATION="250"
DEYE_SOLAR_LOW_CHARGE_CURRENT="25"
```

### Variabili d'ambiente

Tutte le impostazioni supportano variabili d'ambiente prefixate con `DEYE_`:

```bash
export DEYE_APP_ID="xxx"
export DEYE_TOKEN="yyy"
./deye_cli.py station-list
```

### Precedenza configurazione

1. **Argomenti CLI** (massima priorità)
2. **File di configurazione** (`~/.config/deyecli/config`)
3. **Variabili d'ambiente** (`DEYE_*`)
4. **Valori di default**

## Server API HTTP

### Avviare il server

```bash
./deye_cli.py api --host 0.0.0.0 --port 8000
```

### Endpoint disponibili

#### POST /api/token
Ottieni token di accesso
```bash
curl -X POST http://localhost:8000/api/token \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "xxx",
    "app_secret": "yyy",
    "email": "me@example.com",
    "password": "pass"
  }'
```

#### GET /api/station/list
Lista stazioni
```bash
curl -X GET http://localhost:8000/api/station/list \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/station/latest
Dati recenti stazione
```bash
curl -X GET 'http://localhost:8000/api/station/latest?station_id=123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/device/latest
Dati recenti dispositivo
```bash
curl -X GET 'http://localhost:8000/api/device/latest?device_sn=ABC123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/config/battery
Configurazione batteria
```bash
curl -X GET 'http://localhost:8000/api/config/battery?device_sn=ABC123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/config/system
Configurazione sistema
```bash
curl -X GET 'http://localhost:8000/api/config/system?device_sn=ABC123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### POST /api/battery/parameter/update
Aggiorna parametro batteria
```bash
curl -X POST http://localhost:8000/api/battery/parameter/update \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "device_sn": "ABC123",
    "param_type": "MAX_CHARGE_CURRENT",
    "value": 20
  }'
```

#### POST /api/solar-charge-cron
Genera cron solare
```bash
curl -X POST http://localhost:8000/api/solar-charge-cron \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lat": "44.0637",
    "lon": "12.4525",
    "hours": "12",
    "min_radiation": "200",
    "low_charge_current": "20",
    "device_sn": "ABC123"
  }'
```

## Esempi pratici

### 1. Setup completo

```bash
# 1. Creare file di configurazione
mkdir -p ~/.config/deyecli
cat > ~/.config/deyecli/config << EOF
DEYE_BASE_URL="https://eu1-developer.deyecloud.com"
DEYE_APP_ID="your-app-id"
DEYE_APP_SECRET="your-app-secret"
DEYE_EMAIL="your@email.com"
DEYE_DEVICE_SN="your-device-sn"
DEYE_STATION_ID="123"
DEYE_WEATHER_LAT="44.0637"
DEYE_WEATHER_LON="12.4525"
EOF

# 2. Ottenere token
./deye_cli.py token --password yourpassword

# 3. Testare
./deye_cli.py station-list
```

### 2. Generare cron giornaliero

```bash
./deye_cli.py solar-charge-cron \
  --lat 44.0637 \
  --lon 12.4525 \
  --restore-default-charge-current \
  --low-charge-current 15 \
  --print-slots

# Installare crontab
crontab ~/.config/deyecli/solar-charge.cron
```

### 3. Usare con Home Assistant

```bash
# Avviare server API
./deye_cli.py api --host 0.0.0.0 --port 8000 &

# Configurare Home Assistant con URL:
# http://your-ip:8000/api/station/latest?station_id=123
```

## Dipendenze

### Richieste
- Python 3.6+

### Opzionali
- `requests`: Per richieste HTTP (fallback a `curl` se non installato)

Installare:
```bash
pip install requests
```

## Differenze da bash

1. **Nessun `jq` richiesto**: JSON parsing nativo Python
2. **Nessun `curl` richiesto**: Usa `requests` (o fallback a `curl`)
3. **Password non deve essere salvata**: Automaticamente hashata
4. **Server API integrato**: No bisogno di `api_server.py` separato

## Troubleshooting

### "API request failed"
- Verificare token: `./deye_cli.py show-config | grep TOKEN`
- Verificare parametri: `echo $DEYE_*`
- Usare debug: `./deye_cli.py --print-query <comando>`

### "Weather API error"
- Verificare coordinate: `--lat` e `--lon`
- Controllare connessione internet
- Provare: `curl https://api.open-meteo.com/v1/forecast?latitude=44&longitude=12&hourly=direct_radiation`

### "requests library not found"
- Installare: `pip install requests`
- O usare curl fallback (automatico)

## Licenza

Stesso progetto originale `deyecli`.

## Supporto

Per problemi o suggerimenti, consultare la documentazione originale:
- https://developer.deyecloud.com/api
- Repository: deyecli
