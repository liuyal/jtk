import runpy
import sys

# Launcher for the alpine submodule's supervisord (python3 /home/main.py)
sys.path.insert(0, "/home/app")
runpy.run_path("/home/app/backend/index.py", run_name="__main__")
