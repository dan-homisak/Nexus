import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: {
      './vendor/react.js': 'react',
      './vendor/react-dom-client.js': 'react-dom/client',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./test/setup.js'],
    globals: true,
  },
});
