import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// SPA estatica; base "/" sirve igual en Amplify y en S3 website.
export default defineConfig({
  plugins: [react()],
});
