'use strict';
const express = require('express');
const path = require('path');
const app = express();
app.use(express.static(path.join(__dirname, 'public')));
app.use('/node_modules/mqtt/dist', express.static(path.join(__dirname, 'node_modules/mqtt/dist')));
app.get('/', (_req, res) => res.redirect('/m1.html'));
const port = process.env.PORT || 3003;
app.listen(port, '127.0.0.1', () => console.log(`Dashboard M1 : http://localhost:${port}/m1.html`));
