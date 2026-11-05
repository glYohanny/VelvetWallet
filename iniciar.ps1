<#
.SYNOPSIS
  Levanta Velvet Wallet completo con un solo comando: los dos bancos simulados
  (Banco Simulado SFA en 8001 y Banco Austral en 8002), el backend (8000) y la
  app en el navegador (8081).

.DESCRIPTION
  Hace, en orden:
    1. Cierra lo que haya quedado corriendo en los puertos 8000, 8001, 8002 y 8081
       (un simulador o backend viejo de otra carpeta es la causa típica de
       errores raros, como un 404 en /panel).
    2. Prepara el entorno de Python en .venv (solo la primera vez, o si
       cambiaron los requirements) y las dependencias de la app (npm).
    3. Abre una ventana por servicio, espera a que respondan y avisa.

  Uso (desde la carpeta del proyecto):
      .\iniciar.cmd                 todo
      .\iniciar.cmd -SinApp         solo simulador y backend
      .\iniciar.cmd -Detener        cierra todo
      .\iniciar.cmd -Python C:\ruta\python.exe   usa ese Python

  Para la presentación, con la app en un celular (ver PRESENTACION.md):
      .\iniciar.cmd -Presentacion             todo, accesible desde la red, con la cuenta de prueba lista
      .\iniciar.cmd -Presentacion -BaseLocal  además, con las bases en Docker (sin depender de internet)
      .\iniciar.cmd -Presentacion -Ip 192.168.43.10   si la IP detectada no es la de la red del celular
      .\iniciar.cmd -AbrirFirewall            (como administrador, una vez) deja pasar los puertos
      .\iniciar.cmd -CerrarFirewall           (como administrador) quita esa regla después

  El backend necesita backend\.env (credenciales de Neon y Atlas). Git no lo
  sube: si falta, el script lo dice.
#>
[CmdletBinding()]
param(
    [switch]$SinApp,
    [switch]$Detener,
    [string]$Python = "",
    [switch]$Presentacion,
    [switch]$BaseLocal,
    [string]$Ip = "",
    [switch]$AbrirFirewall,
    [switch]$CerrarFirewall
)

$ErrorActionPreference = "Stop"
$Raiz = $PSScriptRoot
$Puertos = @{ 8001 = "simulador"; 8002 = "Banco Austral"; 8000 = "backend"; 8081 = "app" }

function Paso($texto)  { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Ok($texto)    { Write-Host "    $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    $texto" -ForegroundColor Yellow }
function Falla($texto) { Write-Host ""; Write-Host "ERROR: $texto" -ForegroundColor Red; exit 1 }

function Detener-Puertos {
    foreach ($puerto in $Puertos.Keys) {
        $conexiones = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue
        foreach ($pid_ in ($conexiones | Select-Object -ExpandProperty OwningProcess -Unique)) {
            if ($pid_ -and $pid_ -ne 0) {
                $proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
                if ($proc) {
                    Aviso ("Cerrando {0} en el puerto {1} ({2}, PID {3})" -f $Puertos[$puerto], $puerto, $proc.ProcessName, $pid_)
                    Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }
}

function Esperar-Servicio($nombre, $url, $segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { Ok "$nombre listo ($url)"; return $true }
        } catch { }
        Start-Sleep -Milliseconds 700
    }
    Aviso "$nombre no respondió en $segundos s. Revisa su ventana para ver el error."
    return $false
}

function Obtener-IpLocal {
    # La IP de la conexión que tiene salida (puerta de enlace): la del Wi-Fi o
    # del hotspot. Así no se elige la de un adaptador virtual (WSL, VirtualBox).
    $cfg = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1
    if ($cfg -and $cfg.IPv4Address) { return @($cfg.IPv4Address)[0].IPAddress }
    $otra = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1
    if ($otra) { return $otra.IPAddress }
    return $null
}

function Es-Administrador {
    $yo = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$yo).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Esperar-Postgres($usuario, $base, $segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        & docker exec velvet_postgres pg_isready -U $usuario -d $base *> $null
        if ($LASTEXITCODE -eq 0) { Ok "PostgreSQL listo"; return $true }
        Start-Sleep -Seconds 1
    }
    Aviso "PostgreSQL no respondió en $segundos s. Revisa: docker compose logs postgres (en BD)"
    return $false
}

function Abrir-Ventana($titulo, $carpeta, $comando) {
    $script = "`$Host.UI.RawUI.WindowTitle = '$titulo'; Set-Location '$carpeta'; $comando"
    Start-Process powershell -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $script) | Out-Null
}

# ── Firewall (solo con -AbrirFirewall / -CerrarFirewall) ─────────────────────
# Windows bloquea por defecto las conexiones que llegan desde otro equipo. La
# regla deja pasar solo los puertos de Velvet; se quita con -CerrarFirewall.
$ReglaFirewall = "Velvet Wallet (presentacion)"
if ($AbrirFirewall -or $CerrarFirewall) {
    Paso "Firewall de Windows"
    if (-not (Es-Administrador)) {
        Falla "Hay que abrir PowerShell como administrador (clic derecho > Ejecutar como administrador), ir a esta carpeta y correr de nuevo el comando."
    }
    if ($AbrirFirewall) {
        if (Get-NetFirewallRule -DisplayName $ReglaFirewall -ErrorAction SilentlyContinue) {
            Ok "La regla ya existía: los puertos 8000, 8001, 8002 y 8081 están abiertos."
        } else {
            New-NetFirewallRule -DisplayName $ReglaFirewall -Direction Inbound -Protocol TCP `
                -LocalPort 8000, 8001, 8002, 8081 -Action Allow -Profile Any | Out-Null
            Ok "Listo: el celular ya puede llegar a los puertos 8000, 8001, 8002 y 8081."
        }
    } else {
        Remove-NetFirewallRule -DisplayName $ReglaFirewall -ErrorAction SilentlyContinue
        Ok "Regla quitada: los puertos vuelven a estar cerrados para otros equipos."
    }
    exit 0
}

# ─────────────────────────────────────────────────────────────────────────────
Paso "Cerrando lo que estaba corriendo"
Detener-Puertos
if ($Detener) { Ok "Listo: todo cerrado."; exit 0 }

# ── Python ──────────────────────────────────────────────────────────────────
Paso "Entorno de Python"
$Venv = Join-Path $Raiz ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
if ($Python) {
    if (-not (Test-Path $Python)) { Falla "No existe $Python" }
    $Py = $Python
    Ok "Usando $Py"
} elseif (-not (Test-Path $Py)) {
    $base = $null
    foreach ($candidato in @("py", "python")) {
        if (Get-Command $candidato -ErrorAction SilentlyContinue) { $base = $candidato; break }
    }
    if (-not $base) { Falla "No encontré Python. Instálalo (3.12 o 3.13) o usa -Python C:\ruta\python.exe" }
    Aviso "Creando .venv (solo la primera vez)..."
    if ($base -eq "py") { & py -3 -m venv $Venv } else { & python -m venv $Venv }
    if (-not (Test-Path $Py)) { Falla "No se pudo crear .venv. Prueba con -Python apuntando a un python.exe que funcione." }
    Ok "Creado .venv"
} else {
    Ok "Usando .venv"
}

# Instala solo si cambiaron los requirements (se guarda su huella).
$Reqs = @((Join-Path $Raiz "backend\requirements.txt"), (Join-Path $Raiz "simulador\requirements.txt"))
$Huella = ($Reqs | ForEach-Object { (Get-FileHash $_ -Algorithm SHA256).Hash }) -join ""
$HuellaPy = (& $Py -c "import sys; print(sys.executable)")
$Huella = "$Huella|$HuellaPy"
$Marca = Join-Path $Raiz ".venv-requirements.txt"
$Previa = ""
if (Test-Path $Marca) { $Previa = [string](Get-Content $Marca -Raw) }
if ($Previa.Trim() -ne $Huella) {
    Aviso "Instalando dependencias de Python (tarda la primera vez)..."
    & $Py -m pip install --disable-pip-version-check -q -r $Reqs[0] -r $Reqs[1]
    if ($LASTEXITCODE -ne 0) { Falla "pip no pudo instalar las dependencias (mira el mensaje de arriba)." }
    Set-Content -Path $Marca -Value $Huella -Encoding ASCII
    Ok "Dependencias instaladas"
} else {
    Ok "Dependencias al día"
}

# ── .env del backend ────────────────────────────────────────────────────────
$Env_ = Join-Path $Raiz "backend\.env"
if (-not (Test-Path $Env_)) {
    $Vecino = Join-Path (Split-Path $Raiz -Parent) "VelvetWallet\backend\.env"
    if (Test-Path $Vecino) {
        Copy-Item $Vecino $Env_
        Ok "Copié backend\.env desde $Vecino"
    } elseif ($BaseLocal) {
        # Con las bases en Docker no hacen falta credenciales de la nube.
        Copy-Item (Join-Path $Raiz "backend\.env.example") $Env_
        Ok "Creé backend\.env desde el ejemplo (sirve para las bases en Docker)"
    } else {
        Falla "Falta backend\.env (credenciales de Neon y Atlas). Cópialo desde backend\.env.example y complétalo."
    }
}

# ── Bases de datos en Docker (solo con -BaseLocal) ───────────────────────────
# Para no depender de internet ni de la lista de IP permitidas de Atlas el día
# de la presentación. Las variables de aquí mandan sobre backend\.env.
if ($BaseLocal) {
    Paso "Bases de datos locales (Docker)"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Falla "No encontré Docker. Instala Docker Desktop y ábrelo, o corre sin -BaseLocal."
    }
    $EnvBd = Join-Path $Raiz "BD\.env"
    if (-not (Test-Path $EnvBd)) {
        Copy-Item (Join-Path $Raiz "BD\.env.example") $EnvBd
        Ok "Creé BD\.env desde el ejemplo"
    }
    $Bd = @{}
    foreach ($linea in Get-Content $EnvBd) {
        if ($linea -match '^\s*([A-Z_]+)\s*=\s*(.*?)\s*$') { $Bd[$Matches[1]] = $Matches[2] }
    }
    Push-Location (Join-Path $Raiz "BD")
    & docker compose up -d
    $codigo = $LASTEXITCODE
    Pop-Location
    if ($codigo -ne 0) { Falla "docker compose no pudo levantar las bases. ¿Está abierto Docker Desktop?" }
    $PuertoPg = if ($Bd["POSTGRES_PORT"]) { $Bd["POSTGRES_PORT"] } else { "5432" }
    $PuertoMongo = if ($Bd["MONGO_PORT"]) { $Bd["MONGO_PORT"] } else { "27017" }
    $env:DATABASE_URL = "postgresql://$($Bd["POSTGRES_USER"]):$($Bd["POSTGRES_PASSWORD"])@localhost:$PuertoPg/$($Bd["POSTGRES_DB"])"
    $env:MONGO_URL = "mongodb://$($Bd["MONGO_USER"]):$($Bd["MONGO_PASSWORD"])@localhost:$PuertoMongo/?authSource=admin"
    $env:MONGO_DB = $Bd["MONGO_DB"]
    $null = Esperar-Postgres $Bd["POSTGRES_USER"] $Bd["POSTGRES_DB"] 90
}

# ── Red (solo con -Presentacion) ─────────────────────────────────────────────
# El celular es otro equipo: todo tiene que escuchar en la red y no solo en
# este PC, y las direcciones que se abren EN EL CELULAR (la página del banco y
# la vuelta al backend) tienen que llevar la IP de este PC, no "localhost".
# Las ventanas heredan estas variables.
$HostServicios = "127.0.0.1"
if ($Presentacion) {
    Paso "Modo presentación: accesible desde la red"
    if (-not $Ip) { $Ip = Obtener-IpLocal }
    if (-not $Ip) { Falla "No encontré la IP de este PC. ¿Está conectado al Wi-Fi o al hotspot? También puedes pasarla: -Ip 192.168.43.10" }
    Ok "IP de este PC en la red: $Ip"
    $HostServicios = "0.0.0.0"
    $env:SFA_AUTORIZAR_URL = "http://$($Ip):8001/autorizar"
    $env:SFA_AUSTRAL_URL = "http://$($Ip):8002"
    $env:SFA_REDIRECT_URI = "http://$($Ip):8000/api/conexiones/retorno"
    $env:SFA_REDIRECT_URIS = "http://localhost:8000/api/conexiones/retorno,http://$($Ip):8000/api/conexiones/retorno"
    $env:VELVET_RETORNOS_PERMITIDOS = "http://localhost:8081,http://$($Ip):8081,velvetwallet://,exp://"
    $env:VELVET_RETORNO = "http://$($Ip):8081/"
    if (-not (Get-NetFirewallRule -DisplayName $ReglaFirewall -ErrorAction SilentlyContinue)) {
        Aviso "El firewall de Windows puede bloquear al celular. Una vez, como administrador: .\iniciar.cmd -AbrirFirewall"
    }
}

# ── Simulador y backend ─────────────────────────────────────────────────────
Paso "Levantando el simulador del banco (8001)"
Abrir-Ventana "Velvet - Simulador :8001" (Join-Path $Raiz "simulador") "& '$Py' -m uvicorn app.main:app --host $HostServicios --port 8001 --reload"
$okSim = Esperar-Servicio "Simulador" "http://localhost:8001/health" 40

# Un segundo banco, con otros clientes y movimientos: para probar que la app
# recibe más de un banco a la vez (RF-07). Si no levanta, lo demás sigue igual.
Paso "Levantando el segundo banco: Banco Austral (8002)"
Abrir-Ventana "Velvet - Banco Austral :8002" (Join-Path $Raiz "simulador") "`$env:SFA_BANCO = 'austral'; & '$Py' -m uvicorn app.main:app --host $HostServicios --port 8002 --reload"
$null = Esperar-Servicio "Banco Austral" "http://localhost:8002/health" 40

Paso "Levantando el backend (8000)"
Abrir-Ventana "Velvet - Backend :8000" (Join-Path $Raiz "backend") "& '$Py' -m uvicorn api.main:app --host $HostServicios --port 8000 --reload"
$okApi = Esperar-Servicio "Backend" "http://localhost:8000/health" 60

# La cuenta que muestra la pantalla de inicio de sesión, con los dos bancos
# vinculados: así en la presentación se entra y ya hay datos.
if ($Presentacion -and $okApi -and $okSim) {
    Paso "Cuenta de prueba (demo@velvetwallet.cl · velvet2026)"
    Push-Location (Join-Path $Raiz "backend")
    & $Py preparar_demo.py
    $codigo = $LASTEXITCODE
    Pop-Location
    if ($codigo -ne 0) { Aviso "No se pudo preparar la cuenta de prueba (mira el mensaje de arriba). Se puede crear una cuenta nueva desde la app." }
}

# ── App ─────────────────────────────────────────────────────────────────────
if (-not $SinApp) {
    Paso "App (8081)"
    $Movil = Join-Path $Raiz "movil"
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Aviso "No encontré npm (Node.js). Instálalo para abrir la app; simulador y backend ya están corriendo."
    } else {
        $Lock = Join-Path $Movil "package-lock.json"
        $Modulos = Join-Path $Movil "node_modules"
        $MarcaNpm = Join-Path $Modulos ".velvet-lock"
        $HuellaNpm = (Get-FileHash $Lock -Algorithm SHA256).Hash
        $PreviaNpm = ""
        if (Test-Path $MarcaNpm) { $PreviaNpm = ([string](Get-Content $MarcaNpm -Raw)).Trim() }
        if (-not (Test-Path $Modulos) -or $PreviaNpm -ne $HuellaNpm) {
            Aviso "Instalando dependencias de la app (npm install)..."
            Push-Location $Movil
            & npm install --no-audit --no-fund
            $codigo = $LASTEXITCODE
            Pop-Location
            if ($codigo -ne 0) { Falla "npm install falló (mira el mensaje de arriba)." }
            Set-Content -Path $MarcaNpm -Value $HuellaNpm -Encoding ASCII
        } else {
            Ok "Dependencias de la app al día"
        }
        $Lan = if ($Presentacion) { " --lan" } else { "" }
        Abrir-Ventana "Velvet - App :8081" $Movil "npx expo start --web --port 8081$Lan"
        $null = Esperar-Servicio "App" "http://localhost:8081" 120
    }
}

# ── Resumen ─────────────────────────────────────────────────────────────────
Paso "Todo arriba"
Write-Host "    App ........................ http://localhost:8081"
Write-Host "    Panel del simulador ........ http://localhost:8001/panel"
Write-Host "    Panel del Banco Austral .... http://localhost:8002/panel"
Write-Host "    API (documentación) ........ http://localhost:8000/docs"
Write-Host "    Clientes de prueba ......... http://localhost:8001/simulador/clientes"
if ($Presentacion) {
    Write-Host ""
    Write-Host "    En el celular (conectado a la misma red que este PC):" -ForegroundColor Cyan
    Write-Host "      App instalada (APK) ...... en 'Servidor > Cambiar' escribe: $Ip" -ForegroundColor Cyan
    Write-Host "      Navegador del celular .... http://$($Ip):8081" -ForegroundColor Cyan
    Write-Host "      Cuenta de prueba ......... demo@velvetwallet.cl · velvet2026" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "    Para cerrar todo: .\iniciar.cmd -Detener" -ForegroundColor DarkGray
if (-not ($okSim -and $okApi)) { exit 1 }
