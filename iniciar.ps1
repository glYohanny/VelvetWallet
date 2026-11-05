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

  El backend necesita backend\.env (credenciales de Neon y Atlas). Git no lo
  sube: si falta, el script lo dice.
#>
[CmdletBinding()]
param(
    [switch]$SinApp,
    [switch]$Detener,
    [string]$Python = ""
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

function Abrir-Ventana($titulo, $carpeta, $comando) {
    $script = "`$Host.UI.RawUI.WindowTitle = '$titulo'; Set-Location '$carpeta'; $comando"
    Start-Process powershell -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $script) | Out-Null
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
    } else {
        Falla "Falta backend\.env (credenciales de Neon y Atlas). Cópialo desde backend\.env.example y complétalo."
    }
}

# ── Simulador y backend ─────────────────────────────────────────────────────
Paso "Levantando el simulador del banco (8001)"
Abrir-Ventana "Velvet - Simulador :8001" (Join-Path $Raiz "simulador") "& '$Py' -m uvicorn app.main:app --port 8001 --reload"
$okSim = Esperar-Servicio "Simulador" "http://localhost:8001/health" 40

# Un segundo banco, con otros clientes y movimientos: para probar que la app
# recibe más de un banco a la vez (RF-07). Si no levanta, lo demás sigue igual.
Paso "Levantando el segundo banco: Banco Austral (8002)"
Abrir-Ventana "Velvet - Banco Austral :8002" (Join-Path $Raiz "simulador") "`$env:SFA_BANCO = 'austral'; & '$Py' -m uvicorn app.main:app --port 8002 --reload"
$null = Esperar-Servicio "Banco Austral" "http://localhost:8002/health" 40

Paso "Levantando el backend (8000)"
Abrir-Ventana "Velvet - Backend :8000" (Join-Path $Raiz "backend") "& '$Py' -m uvicorn api.main:app --port 8000 --reload"
$okApi = Esperar-Servicio "Backend" "http://localhost:8000/health" 60

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
        Abrir-Ventana "Velvet - App :8081" $Movil "npx expo start --web --port 8081"
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
Write-Host ""
Write-Host "    Para cerrar todo: .\iniciar.cmd -Detener" -ForegroundColor DarkGray
if (-not ($okSim -and $okApi)) { exit 1 }
