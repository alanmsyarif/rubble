# Start Blender 5.2 with Rubble registered from this checkout (extra arguments go to Blender).
$blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
Set-Location (Split-Path $PSScriptRoot)
& $blender --python tools\dev_register.py @args
