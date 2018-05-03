import tkinter as tk
from tkinter import ttk

from thonny.config_ui import ConfigurationPage
from thonny import get_workbench


class GeneralConfigurationPage(ConfigurationPage):
    
    def __init__(self, master):
        ConfigurationPage.__init__(self, master)
        
        self._single_instance_var = get_workbench().get_variable("general.single_instance")
        self._single_instance_checkbox = ttk.Checkbutton(self,
                                                         text="Allow only single Thonny instance", 
                                                      variable=self._single_instance_var)
        self._single_instance_checkbox.grid(row=1, column=0, sticky=tk.W, columnspan=2)
        
        self._expert_var = get_workbench().get_variable("general.expert_mode")
        self._expert_checkbox = ttk.Checkbutton(self, text="Expert mode", variable=self._expert_var)
        self._expert_checkbox.grid(row=2, column=0, sticky=tk.W, columnspan=2)
        
        self._debug_var = get_workbench().get_variable("general.debug_mode")
        self._debug_checkbox = ttk.Checkbutton(self, text="Debug mode", variable=self._debug_var)
        self._debug_checkbox.grid(row=3, column=0, sticky=tk.W, columnspan=2)
        
        self._scaling_var = get_workbench().get_variable("general.scaling")
        self._scaling_label = ttk.Label(self, text="UI scaling factor\n(at the moment seems to work\nonly in Windows)")
        self._scaling_label.grid(row=4, column=0, sticky=tk.W, padx=(0, 10))
        scalings = sorted({0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 
                           round(get_workbench()._default_scaling_factor, 2)})
        self._scaling_combo = ttk.Combobox(self, width=4,
                                        exportselection=False,
                                        textvariable=self._scaling_var,
                                        state='readonly',
                                        height=15,
                                        values=["auto"] + scalings)
        self._scaling_combo.grid(row=4, column=1, sticky=tk.W)

        
        reopen_label = ttk.Label(self, text="NB! Restart Thonny after changing these options"
                                 + "\nin order to see the full effect")
        reopen_label.grid(row=8, column=0, sticky=tk.W, pady=20, columnspan=2)
        
        
        self.columnconfigure(1, weight=1)
    

def load_plugin():
    get_workbench().add_configuration_page("General", GeneralConfigurationPage)
