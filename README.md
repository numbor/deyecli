# deyecli
Bash CLI per le API REST di [Deye Cloud](https://developer.deyecloud.com/api), pensato per controllare e monitorare inverter fotovoltaici Deye direttamente da terminale.

## Requisiti

| Tool | Note |
|------|------|
| `bash` ≥ 4.0 | disponibile su qualsiasi Linux moderno |
| `curl` | per le chiamate HTTP |
| `jq` | parsing/formattazione JSON — opzionale ma raccomandato |
| `sha256sum` | hashing della password — incluso in `coreutils` |

## Installazione

```bash
git clone <repo-url> deyecli
cd deyecli
chmod +x deyecli.sh
```

Opzionalmente, aggiungere un symlink al `PATH`:

```bash
ln -s "$PWD/deyecli.sh" ~/.local/bin/deyecli
```

---

## Configurazione

Lo script legge i parametri da più sorgenti, in ordine di precedenza decrescente:

```
flag CLI  >  variabile d'ambiente  >  file di config
```

### File di config

Posizione predefinita: `~/.config/deyecli/config`  
Sovrascrivibile con la variabile `DEYE_CONFIG=/altro/percorso`.

```bash
mkdir -p ~/.config/deyecli
cp config.example ~/.config/deyecli/config
$EDITOR ~/.config/deyecli/config
```

Esempio di file compilato:

```ini
# URL base — cambiare prefisso di regione se necessario
DEYE_BASE_URL=https://eu1-developer.deyecloud.com

# Credenziali applicazione (obbligatorie per ogni chiamata)
# Ottenibili da https://developer.deyecloud.com
DEYE_APP_ID=<il-tuo-app-id>
DEYE_APP_SECRET=<il-tuo-app-secret>

# Credenziali di login — fornire UNO tra username, email o mobile
DEYE_EMAIL=utente@esempio.com

# Password in chiaro — lo script la converte in SHA-256 prima dell'invio
DEYE_PASSWORD=latuapassword

# ID azienda per token business (lasciare vuoto per account personale)
DEYE_COMPANY_ID=

# Token di accesso — aggiornato automaticamente dal comando 'token'
DEYE_TOKEN=

# Seriale del dispositivo predefinito usato dai comandi config
DEYE_DEVICE_SN=
```

> **Sicurezza:** il file viene letto con un parser riga per riga, senza `eval` né `source`.
> È sicuro inserire valori con caratteri speciali (token JWT, password con `%`, ecc.).

### Variabili d'ambiente

Tutte le chiavi del file di config si possono passare come variabili d'ambiente:

```bash
DEYE_APP_ID=xxx DEYE_APP_SECRET=yyy DEYE_EMAIL=me@example.com \
  DEYE_PASSWORD=mypassword ./deyecli.sh token
```

---

## Comandi

### `token` — Ottieni un token di accesso

`POST /v1.0/account/token`

Esegue il login e ottiene un `accessToken`. Se la chiamata ha successo **il token viene salvato automaticamente** in `DEYE_TOKEN` nel file di config (tramite `jq`).

```bash
./deyecli.sh token
```

**Parametri obbligatori:**

| Variabile | Flag | Descrizione |
|-----------|------|-------------|
| `DEYE_APP_ID` | `--app-id` | ID applicazione Deye |
| `DEYE_APP_SECRET` | `--app-secret` | Secret applicazione Deye |
| `DEYE_PASSWORD` | `--password` | Password in chiaro (hashata SHA-256) |
| `DEYE_EMAIL` *oppure* `DEYE_USERNAME` *oppure* `DEYE_MOBILE` | `--email` / `--username` / `--mobile` | Identificatore di login |

**Parametri opzionali:**

| Variabile | Flag | Descrizione |
|-----------|------|-------------|
| `DEYE_COUNTRY_CODE` | `--country-code` | Obbligatorio se si usa `DEYE_MOBILE` |
| `DEYE_COMPANY_ID` | `--company-id` | Per ottenere un token business |

**Esempio:**

```bash
./deyecli.sh token
# → POST https://eu1-developer.deyecloud.com/v1.0/account/token?appId=...
# ✔  DEYE_TOKEN saved to /home/utente/.config/deyecli/config
```

**Risposta (estratto):**

```json
{
  "code": "1000000",
  "success": true,
  "accessToken": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expiresIn": "5183999",
  "tokenType": "bearer"
}
```

> **Nota:** Deye restituisce il token con prefisso `"Bearer "`. Lo script lo rimuove prima di salvarlo e prima di ogni chiamata successiva, evitando il doppio prefisso `Bearer Bearer ...`.

---

### `config-battery` — Parametri configurazione batteria

`POST /v1.0/config/battery`

Legge i parametri di configurazione della batteria per un inverter ibrido con storage.

Il seriale del dispositivo può essere fornito in tre modi equivalenti:

```bash
# 1. Argomento posizionale
./deyecli.sh config-battery 2401110313

# 2. Flag esplicito
./deyecli.sh config-battery --device-sn 2401110313

# 3. Dal config file (DEYE_DEVICE_SN)
./deyecli.sh config-battery
```

**Parametri obbligatori:**

| Variabile | Flag | Descrizione |
|-----------|------|-------------|
| `DEYE_TOKEN` | `--token` | Token di accesso |
| `DEYE_DEVICE_SN` | `--device-sn` o arg posizionale | Seriale dell'inverter ibrido |

**Esempio di risposta:**

```json
{
  "code": "1000000",
  "success": true,
  "battCapacity": 100,
  "battLowCapacity": 20,
  "battShutDownCapacity": 10,
  "maxChargeCurrent": 50,
  "maxDischargeCurrent": 50
}
```

> **Attenzione:** il `deviceSn` deve essere quello di un **inverter ibrido** (con batteria), non del collector/logger. Per trovare il seriale corretto usare l'app Deye o l'API `/v1.0/device/list`.

---

## Flusso tipico

```bash
# 1. Prima configurazione
cp config.example ~/.config/deyecli/config
$EDITOR ~/.config/deyecli/config   # inserire APP_ID, APP_SECRET, EMAIL, PASSWORD

# 2. Login — il token viene salvato automaticamente nel config
./deyecli.sh token

# 3. Inserire il seriale del proprio inverter nel config
#    (DEYE_DEVICE_SN=<seriale>)

# 4. Leggere la configurazione della batteria
./deyecli.sh config-battery
```

---

## Opzioni globali

Tutte le opzioni possono comparire prima o dopo il nome del comando:

| Flag | Variabile | Descrizione |
|------|-----------|-------------|
| `--base-url <url>` | `DEYE_BASE_URL` | URL base API |
| `--app-id <id>` | `DEYE_APP_ID` | ID applicazione |
| `--app-secret <secret>` | `DEYE_APP_SECRET` | Secret applicazione |
| `--username <name>` | `DEYE_USERNAME` | Username di login |
| `--email <email>` | `DEYE_EMAIL` | Email di login |
| `--mobile <number>` | `DEYE_MOBILE` | Numero di cellulare |
| `--country-code <code>` | `DEYE_COUNTRY_CODE` | Prefisso internazionale (richiesto con `--mobile`) |
| `--password <pass>` | `DEYE_PASSWORD` | Password in chiaro (hashata SHA-256 prima dell'invio) |
| `--company-id <id>` | `DEYE_COMPANY_ID` | ID azienda per token business |
| `--token <bearer>` | `DEYE_TOKEN` | Token di accesso |
| `--device-sn <sn>` | `DEYE_DEVICE_SN` | Seriale dispositivo |
| `-h, --help` | | Mostra l'aiuto |

---

## Regioni supportate

| Regione | Base URL |
|---------|----------|
| EU1 (default) | `https://eu1-developer.deyecloud.com` |

Per altre regioni aggiornare `DEYE_BASE_URL` nel config o passare `--base-url`.

---

## Riferimenti

- [Deye Cloud Developer Portal](https://developer.deyecloud.com)
- [Deye OpenAPI Swagger (EU1)](https://eu1-developer.deyecloud.com/v2/api-docs)
- [Sample code ufficiale (GitHub)](https://github.com/DeyeCloudDevelopers/deye-openapi-client-sample-code)