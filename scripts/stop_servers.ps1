# Para el backend (uvicorn) y el panel (Next.js) que esten escuchando en
# 8000/3000, para que Actualizar_Fantasy.bat pueda levantarlos con red.
#
# Por que hace falta: un uvicorn arrancado antes del salto del air-gap nacio
# sellado. Su boton Actualizar puede abrir la puerta desde dentro, pero
# «Conectar cuenta» (login de Google con Chrome) no: el proceso no puede
# relanzarse a si mismo en produccion. Matandolo aqui, el [3/3] lo levanta
# con LALIGA_ENV=production ya puesto en la consola.
#
# No toca nada mas: si los puertos estan libres, no hace nada.

[CmdletBinding()]
param(
    [int[]] $Ports = @(8000, 3000)
)

$ErrorActionPreference = 'SilentlyContinue'

$stopped = @()
foreach ($port in $Ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen
    foreach ($owner in ($connections | Select-Object -ExpandProperty OwningProcess -Unique)) {
        if (-not $owner -or $stopped -contains $owner) { continue }
        $process = Get-Process -Id $owner
        if (-not $process) { continue }
        # Solo lo nuestro: uvicorn/.venv python para 8000 y node/next para 3000.
        # Cualquier otro dueño del puerto se respeta y se avisa.
        $isPython = $process.ProcessName -match '^python'
        $isNode = $process.ProcessName -match '^(node|next)'
        if (($port -eq 8000 -and $isPython) -or ($port -eq 3000 -and $isNode)) {
            Stop-Process -Id $owner -Force
            $stopped += $owner
            Write-Output "Parado $($process.ProcessName) (PID $owner) en el puerto $port"
        }
        else {
            Write-Warning "El puerto $port lo tiene $($process.ProcessName) (PID $owner); no lo toco."
        }
    }
}

# Next.js deja a veces el hijo del compilador vivo aunque el padre muera.
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -match 'FANTASY\\frontend' -and $_.CommandLine -match 'next' } |
    ForEach-Object {
        if ($stopped -notcontains $_.ProcessId) {
            Stop-Process -Id $_.ProcessId -Force
            $stopped += $_.ProcessId
            Write-Output "Parado next dev (PID $($_.ProcessId))"
        }
    }

if ($stopped.Count -eq 0) {
    Write-Output 'No habia backend ni panel corriendo.'
}
