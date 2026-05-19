import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Base path pro GitHub Pages: https://omnimedia.github.io/datovy-brief/
// Pokud změníš název repa, uprav tady.
export default defineConfig({
  plugins: [react()],
  base: '/datovy-brief/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
});
