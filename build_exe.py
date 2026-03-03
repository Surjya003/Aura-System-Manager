import os
import subprocess
import customtkinter

# Get the directory where customtkinter is installed
customtkinter_path = os.path.dirname(customtkinter.__file__)

# Define PyInstaller arguments
# - --noconfirm: to overwrite if exists
# - --onedir: creates a directory with the exe and dependencies (better for complex apps than onefile)
# - --windowed: no console window (since it's a GUI app, though we might need it for UAC prompt? Actually, for UAC prompt we might want console or the app itself requests elevation. The app already requests elevation if run without it). Wait, if we use windowed and it prints to console it might crash. Let's use --windowed as it's a GUI.
# - --add-data: carefully add customtkinter's assets

# Note: on Windows, the separator for --add-data is ';'
add_data_arg = f"{customtkinter_path};customtkinter/"

cmd = [
    "pyinstaller",
    "--noconfirm",
    "--windowed",
    "--onedir",
    "--name", "SystemOptimizer",
    "--add-data", add_data_arg,
    "main.py"
]

print("Running PyInstaller command:", " ".join(cmd))
subprocess.run(cmd, check=True)
print("Build finished successfully!")
