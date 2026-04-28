const express = require('express');
const path = require('path');
const app = express();
const DIST = path.join(__dirname, 'dist');

app.use((req, res, next) => {
  if (req.path.endsWith('.html') || req.path === '/') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
  }
  next();
});

// Serve built React/Vite app
app.use(express.static(DIST));

// SPA fallback — React Router handles all client-side routes
app.get('*', (_req, res) => {
  res.sendFile(path.join(DIST, 'index.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Dashboard sur http://localhost:${PORT}`));
