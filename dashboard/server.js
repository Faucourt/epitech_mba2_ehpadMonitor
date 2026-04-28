const express = require('express');
const path = require('path');
const app = express();

app.use((req, res, next) => {
  if (req.path.endsWith('.html') || req.path === '/') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
  }
  next();
});

app.use(express.static(path.join(__dirname, 'public')));
app.use('/node_modules', express.static(path.join(__dirname, 'node_modules')));

app.get('/soignant', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'soignant.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('/soignant/:id', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'soignant.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('/resident/:id', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'resident.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('/mobile/resident/:id', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'mobile_resident.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('/simulateur/config', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'simulateur_config.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Dashboard sur http://localhost:${PORT}`));
