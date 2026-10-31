import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "API_PROXY_");
  const proxy = {
    "/api": {
      target: env.API_PROXY_TARGET || "http://127.0.0.1:8000",
      changeOrigin: true,
    },
  };

  const allowedHosts = [
    "autodispatch.system-agam.my.id",
  ];

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy,
      allowedHosts,
    },
    preview: {
      port: 3000,
      proxy,
      allowedHosts,
    },
  };
});
