import psutil
import subprocess
import os

print("--- psutil sensors ---")
try:
    if hasattr(psutil, "sensors_temperatures"):
        temps = psutil.sensors_temperatures()
        print("temps:", temps)
    else:
        print("psutil doesnt have sensors_temperatures here")
        
    if hasattr(psutil, "sensors_fans"):
        fans = psutil.sensors_fans()
        print("fans:", fans)
except Exception as e:
    print("psutil error:", e)

print("\n--- WMI Thermal Zone ---")
try:
    out = subprocess.check_output("wmic /namespace:\\\\root\\wmi PATH MSAcpi_ThermalZoneTemperature get CurrentTemperature", shell=True)
    print(out.decode('utf-8'))
except Exception as e:
    print("wmic error thermal zone:", e)

print("\n--- WMI Fan ---")
try:
    out = subprocess.check_output("wmic path Win32_Fan get DesiredSpeed, Name", shell=True)
    print(out.decode('utf-8'))
except Exception as e:
    print("wmic error fan:", e)
