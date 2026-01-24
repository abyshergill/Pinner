import customtkinter as ctk

# Set appearance mode and color theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class PathCard(ctk.CTkFrame):
    """Custom widget for displaying a path entry"""
    
    def __init__(self, master, name: str, path: str, on_open, on_delete, **kwargs):
        super().__init__(master, **kwargs)
        
        self.grid_columnconfigure(1, weight=1)
        # Name label
        name_label = ctk.CTkLabel(
            self, 
            text=name, 
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w"
        )
        name_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 2))
        
        # Path label (truncate if too long)
        display_path = path if len(path) < 70 else path[:67] + "..."
        path_label = ctk.CTkLabel(
            self, 
            text=display_path, 
            font=ctk.CTkFont(size=11),
            text_color="gray70",
            anchor="w"
        )
        path_label.grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))
        
        # Open button
        open_btn = ctk.CTkButton(
            self,
            text="Open",
            width=80,
            command=on_open,
            fg_color="green",
            hover_color="darkgreen"
        )
        open_btn.grid(row=0, column=3, rowspan=2, padx=(5, 5), pady=5)
        
        # Delete button
        delete_btn = ctk.CTkButton(
            self,
            text="✕",
            width=40,
            command=on_delete,
            fg_color="red",
            hover_color="darkred"
        )
        delete_btn.grid(row=0, column=4, rowspan=2, padx=(0, 10), pady=5)