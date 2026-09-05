const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("paixStage", {
  getConfig: () => ipcRenderer.invoke("stage:get-config"),
  selectModel: () => ipcRenderer.invoke("stage:select-model"),
  selectCore: () => ipcRenderer.invoke("stage:select-core"),
  close: () => ipcRenderer.invoke("stage:close"),
});
