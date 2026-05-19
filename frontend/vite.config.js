import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Base path pro GitHub Pages musí odpovídat jménu repa.
// Repo: OmnimediaPR/OZP_data_mining → URL: https://omnimediapr.github.io/OZP_data_mining/
// Pokud někdy repo přejmenuješ, uprav tady.
export default defineConfig({
  plugins: [react()],
  base: '/OZP_data_mining/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
});
