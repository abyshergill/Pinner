
import customtkinter as ctk
from tkinter import filedialog, messagebox

from pathmanager import PathManager
from pathlauncher import PathLauncher
from pathcard import PathCard


# Set appearance mode and color theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class PathManagerApp(ctk.CTk):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        self.title("Path Manager")
        self.geometry("900x700")
        self.minsize(600, 500) 
        # Initialize managers
        self.path_manager = PathManager()
        self.path_launcher = PathLauncher()
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # Create UI
        self._create_header()
        self._create_main_content()
        
        # Load initial data
        self.refresh_display()
    
    def _create_header(self):
        """Create header section"""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        header.grid_columnconfigure(0, weight=1)
        
        # Title
        title = ctk.CTkLabel(
            header,
            text="📁 Path Manager",
            font=ctk.CTkFont(size=28, weight="bold")
        )
        title.grid(row=0, column=0, sticky="w")
        
        # Buttons
        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")
        
        ctk.CTkButton(
            btn_frame,
            text="+ Add Folder",
            command=self.add_folder_dialog,
            width=120
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            btn_frame,
            text="+ Add File/App",
            command=self.add_file_dialog,
            width=120
        ).pack(side="left", padx=5)
    
    def _create_main_content(self):
        """Create main content area with tabs"""
        # Tabview
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        
        # Add tabs
        self.tabview.add("Folders")
        self.tabview.add("Files & Apps")
        
        # Configure tabs
        for tab_name in ["Folders", "Files & Apps"]:
            self.tabview.tab(tab_name).grid_columnconfigure(0, weight=1)
            self.tabview.tab(tab_name).grid_rowconfigure(0, weight=1)
        
        # Create scrollable frames (Using built-in CTkScrollableFrame)
        self.folders_scroll = ctk.CTkScrollableFrame(
            self.tabview.tab("Folders"),
            fg_color="transparent"
        )
        self.folders_scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.folders_scroll.grid_columnconfigure(0, weight=1)
        
        self.files_scroll = ctk.CTkScrollableFrame(
            self.tabview.tab("Files & Apps"),
            fg_color="transparent"
        )
        self.files_scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.files_scroll.grid_columnconfigure(0, weight=1)
    
    def add_folder_dialog(self):
        """Show dialog to add a folder"""
        folder_path = filedialog.askdirectory(title="Select Folder")
        if folder_path:
            # Create dialog for custom name
            dialog = ctk.CTkInputDialog(
                text=f"Enter display name for:\n{folder_path}",
                title="Add Folder"
            )
            name = dialog.get_input()
            
            if name:
                self.path_manager.add_folder(name, folder_path)
                self.refresh_display()
    
    def add_file_dialog(self):
        """Show dialog to add a file/application"""
        file_path = filedialog.askopenfilename(title="Select File or Application")
        if file_path:
            # Create dialog for custom name
            dialog = ctk.CTkInputDialog(
                text=f"Enter display name for:\n{file_path}",
                title="Add File/App"
            )
            name = dialog.get_input()
            
            if name:
                self.path_manager.add_file(name, file_path)
                self.refresh_display()
    
    def open_folder(self, path: str):
        """Open a folder"""
        try:
            self.path_launcher.open_folder(path)
        except FileNotFoundError:
            messagebox.showerror("Error", f"Folder not found:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{str(e)}")
    
    def launch_file(self, path: str):
        """Launch a file"""
        try:
            self.path_launcher.launch_file(path)
        except FileNotFoundError:
            messagebox.showerror("Error", f"File not found:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not launch file:\n{str(e)}")
    
    def delete_folder(self, index: int):
        """Delete a folder entry"""
        if messagebox.askyesno("Confirm Delete", "Are you sure you want to remove this folder?"):
            self.path_manager.remove_folder(index)
            self.refresh_display()
    
    def delete_file(self, index: int):
        """Delete a file entry"""
        if messagebox.askyesno("Confirm Delete", "Are you sure you want to remove this file?"):
            self.path_manager.remove_file(index)
            self.refresh_display()
    
    def refresh_display(self):
        """Refresh the display of all paths"""
        # Clear existing widgets
        for widget in self.folders_scroll.winfo_children():
            widget.destroy()
        for widget in self.files_scroll.winfo_children():
            widget.destroy()
        
        # Display folders
        folders = self.path_manager.get_folders()
        if not folders:
            no_folders_label = ctk.CTkLabel(
                self.folders_scroll,
                text="No folders added yet.\nClick '+ Add Folder' to get started.",
                font=ctk.CTkFont(size=14),
                text_color="gray60"
            )
            no_folders_label.pack(pady=50)
        else:
            for i, folder in enumerate(folders):
                card = PathCard(
                    self.folders_scroll,
                    name=folder["name"],
                    path=folder["path"],
                    on_open=lambda p=folder["path"]: self.open_folder(p),
                    on_delete=lambda idx=i: self.delete_folder(idx)
                )
                card.grid(row=i, column=0, sticky="ew", padx=5, pady=5)
        
        # Display files
        files = self.path_manager.get_files()
        if not files:
            no_files_label = ctk.CTkLabel(
                self.files_scroll,
                text="No files added yet.\nClick '+ Add File/App' to get started.",
                font=ctk.CTkFont(size=14),
                text_color="gray60"
            )
            no_files_label.pack(pady=50)
        else:
            for i, file in enumerate(files):
                card = PathCard(
                    self.files_scroll,
                    name=file["name"],
                    path=file["path"],
                    on_open=lambda p=file["path"]: self.launch_file(p),
                    on_delete=lambda idx=i: self.delete_file(idx)
                )
                card.grid(row=i, column=0, sticky="ew", padx=5, pady=5)