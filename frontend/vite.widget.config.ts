import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: 'src/widget/embed.ts',
      name: 'PowabaseWidget',
      formats: ['iife'],
      fileName: () => 'widget.js',
    },
    outDir: 'dist-widget',
    emptyOutDir: true,
  },
});
