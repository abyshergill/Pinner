
import os
import subprocess
import platform

class PathLauncher:
    """Handles opening folders and launching files"""
    
    @staticmethod
    def open_folder(path: str):
        """Open folder in file explorer"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Path does not exist: {path}")
        
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", path])
        else:  # Linux
            subprocess.run(["xdg-open", path])
    
    @staticmethod
    def launch_file(path: str):
        """Launch file or application"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"File does not exist: {path}")
        
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", path])
        else:  # Linux
            subprocess.run(["xdg-open", path])