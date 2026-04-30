const express = require('express');
const path = require('path');
const fs = require('fs');
const http = require('http');
const app = express();

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8001';
const backendParsed = new URL(BACKEND_URL);

// Reverse-proxy /api/* to the backend (avoids mixed-content when serving HTTPS)
app.use('/api', (req, res) => {
  const options = {
    hostname: backendParsed.hostname,
    port: backendParsed.port || 80,
    path: '/api' + req.url,
    method: req.method,
    headers: { ...req.headers, host: backendParsed.host },
  };
  const proxy = http.request(options, (backendRes) => {
    res.writeHead(backendRes.statusCode, backendRes.headers);
    backendRes.pipe(res, { end: true });
  });
  proxy.on('error', () => res.status(502).json({ error: 'Backend unavailable' }));
  req.pipe(proxy, { end: true });
});

app.use((req, res, next) => {
  if (req.path.endsWith('.html') || req.path === '/') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store, max-age=0');
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

app.get('/famille', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'famille.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('/admin/famille', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'admin_famille.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('/mobile/resident/:id', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'mobile_resident.html'), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
});

app.get('/album-activites', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'album_activites.html'), {
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
const HTTPS_PORT = process.env.HTTPS_PORT || 3443;

// HTTPS si les certificats mkcert sont présents dans ./certs/
try {
  const certPath = path.join(__dirname, 'certs');
  const files    = fs.existsSync(certPath) ? fs.readdirSync(certPath) : [];
  const certFile = files.find(f => f.endsWith('.pem') && !f.endsWith('-key.pem'));
  const keyFile  = files.find(f => f.endsWith('-key.pem'));
  if (certFile && keyFile) {
    const https = require('https');
    const options = {
      cert: fs.readFileSync(path.join(certPath, certFile)),
      key:  fs.readFileSync(path.join(certPath, keyFile)),
    };
    https.createServer(options, app).listen(HTTPS_PORT, '0.0.0.0', () =>
      console.log(`Dashboard HTTPS sur https://0.0.0.0:${HTTPS_PORT}`)
    );
  } else {
    console.log('Pas de certificats dans certs/ — HTTPS désactivé');
  }
} catch (e) {
  console.warn('HTTPS non démarré :', e.message);
}

// HTTP toujours actif (dashboard PC)
app.listen(PORT, '0.0.0.0', () => console.log(`Dashboard HTTP sur http://localhost:${PORT}`));
