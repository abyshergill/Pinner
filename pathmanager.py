import os
import json
from typing import Dict, List

class PathManager:
    """Handles storage and retrieval of paths"""
    
    def __init__(self, storage_file: str = "path_manager_data.json"):
        self.storage_file = storage_file
        self.data = self._load_data()
    
    def _load_data(self) -> Dict:
        """Load data from JSON file"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {"folders": [], "files": []}
        return {"folders": [], "files": []}
    
    def _save_data(self):
        """Save data to JSON file"""
        with open(self.storage_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def add_folder(self, name: str, path: str):
        """Add a folder path"""
        self.data["folders"].append({"name": name, "path": path})
        self._save_data()
    
    def add_file(self, name: str, path: str):
        """Add a file/application path"""
        self.data["files"].append({"name": name, "path": path})
        self._save_data()
    
    def remove_folder(self, index: int):
        """Remove a folder by index"""
        if 0 <= index < len(self.data["folders"]):
            self.data["folders"].pop(index)
            self._save_data()
    
    def remove_file(self, index: int):
        """Remove a file by index"""
        if 0 <= index < len(self.data["files"]):
            self.data["files"].pop(index)
            self._save_data()
    
    def get_folders(self) -> List[Dict]:
        """Get all folders"""
        return self.data["folders"]
    
    def get_files(self) -> List[Dict]:
        """Get all files"""
        return self.data["files"]