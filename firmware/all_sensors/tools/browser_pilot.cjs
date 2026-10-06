// Real Wokwi browser simulations. Browser fallback covers three residents + entrance.
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const BASE = path.resolve(__dirname, '..');
const ROOT = path.resolve(BASE, '../..');
const OUT = path.join(ROOT, 'build/browser-pilot');
const ENTITIES = ['R001', 'R002', 'R003', 'entree'];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
fs.mkdirSync(OUT, {recursive: true});
let stopping = false, browser, server, relay, controls=Promise.resolve();
const states = {};
const save = () => fs.writeFileSync(path.join(OUT, 'status.json'), JSON.stringify({
  pid:process.pid, updated_at:new Date().toISOString(),
  scope:'Three residents and entrance; other environmental zones not running', states
}, null, 2));
async function start(entity) {
  const publication = JSON.parse(fs.readFileSync(path.join(ROOT, 'output/wokwi-transfert/pages-corrigees.json')));
  const published = publication.projects.find(project => project.entity === entity && project.status === 'verified');
  if (!published || !/^https:\/\/wokwi\.com\/projects\/[0-9]+$/.test(published.page_corrigee)) {
    throw new Error('No verified published Wokwi project for ' + entity);
  }
  const evidence = {url: published.page_corrigee};
  const wiring = JSON.parse(fs.readFileSync(path.join(BASE, 'collective', entity, 'wiring.json')));
  const allowed = new Set(wiring.devices.map(d => d.id));
  const page = await browser.newPage({viewport:{width:1400,height:900}});
  page.setDefaultTimeout(30000);
  const state = states[entity] = {state:'loading',url:evidence.url,received:0}; save();
  const openedAt=Date.now();
  try {
  await page.goto(evidence.url, {waitUntil:'domcontentloaded',timeout:60000});
  await page.getByRole('button',{name:'sketch.ino',exact:true}).click();
  await page.getByRole('textbox',{name:/Editor content/}).focus();
  await page.keyboard.press('F1');
  await page.getByRole('combobox').fill('>firmware');
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('option',{name:/Upload Firmware and Start Simulation/}).click();
  await (await chooser).setFiles(path.join(ROOT,'build','collective-'+entity+'.bin'));
  await page.getByRole('button',{name:'Stop the simulation',exact:true}).waitFor();
  state.state='running'; save();
  const seen = new Map();
  let controlsStarted=false;
  let lastProgress = Date.now();
  while (!stopping) {
    // Recreate the page periodically to release the simulator and serial UI heap.
    if(Date.now()-openedAt>30*60*1000) {state.state='renewing';save();return;}
    const text = await page.locator('body').innerText();
    for (const match of text.matchAll(/SAMPLE (\{[^\r\n]+\})/g)) {
      let row; try {row=JSON.parse(match[1]);} catch {continue;}
      if(row.entity_id!==entity || !allowed.has(row.device_id) || row.source!=='wokwi' || !row.boot) continue;
      const key=row.device_id+':'+row.boot;
      if(row.seq <= (seen.get(key) ?? -1)) continue;
      seen.set(key,row.seq);
      if(seen.size>allowed.size*4) {state.state='restart-required';throw Error(entity+': too many boots');}
      if(!relay.stdin.write(match[1]+'\n')) await new Promise(resolve=>relay.stdin.once('drain',resolve));
      state.received++; state.boot=row.boot; state.last_serial_at=new Date().toISOString();
      state.uptime_ms=row.uptime_ms;
      lastProgress=Date.now();
    }
    if(Date.now()-lastProgress>20000) {
      state.restarts=(state.restarts||0)+1;
      if(state.restarts>3) {state.state='stalled';save();throw Error(entity+': UART repeatedly stopped; measures will expire');}
      await page.getByRole('button',{name:'Restart the simulation',exact:true}).click();
      controlsStarted=false;state.uptime_ms=0;lastProgress=Date.now();
    }
    if(!controlsStarted && state.uptime_ms>12000) {
      controlsStarted=true;
      // Operate the simulated controls, without inventing measurements.
      controls=controls.then(async()=>{
        const pressure=wiring.devices.find(d=>d.kind==='nibp');
        if(pressure) {
          await page.bringToFront();
          await page.locator('#'+pressure.part.replace('_sensor','_start')).hover();
          await page.mouse.down();try{await delay(4000);}finally{await page.mouse.up();}
          state.pressure_start_pressed=true;
        }
        for(const device of wiring.devices.filter(d=>d.kind==='rfid')) {
          await page.bringToFront();await page.locator('#'+device.part).click();
          await page.getByRole('checkbox',{name:/hold/i}).check();
          await page.locator('div[class*="selectedPartInfo"] button[class*="closeButton"]').click();
        }
      }).catch(error=>{state.control_error=error.message;save();});
    }
    save(); await delay(1000);
  }
  } finally { await page.close().catch(()=>{}); }
}
async function supervise(entity) {
  let failures=0;
  while(!stopping) {
    try { await start(entity); failures=0; }
    catch(error) {
      failures++;
      states[entity]={...states[entity],state:'restarting',error:error.message,consecutive_failures:failures};
      save();console.error(entity+': '+error.message);
      if(failures>=3) {states[entity].state='failed';save();return;}
    }
    if(!stopping) await delay(Math.min(30000,2000*2**failures));
  }
}
async function main() {
  cp.execFileSync('python',[path.join(__dirname,'run_collective.py'),'--pilot','--check'],{stdio:'inherit'});
  for(const entity of ENTITIES) {
    const firmware=fs.readFileSync(path.join(BASE,'collective',entity,'build/sketch.ino.bin'));
    const merged=fs.readFileSync(path.join(ROOT,'build','collective-'+entity+'.bin'));
    if(!merged.subarray(0x10000,0x10000+firmware.length).equals(firmware))
      throw Error(entity+': merged firmware is stale; rebuild it before starting');
  }
  relay=cp.spawn('python',['-u',path.join(__dirname,'browser_gateway.py')],{stdio:['pipe','inherit','inherit'],windowsHide:true});
  relay.on('exit',()=>{if(!stopping){stopping=true;console.error('MQTT gateway stopped');}});
  server=await chromium.launchServer({headless:false});
  fs.writeFileSync(path.join(OUT,'browser-endpoint.txt'),server.wsEndpoint());
  browser=await chromium.connect(server.wsEndpoint());
  const jobs=[];
  for(const entity of ENTITIES) {
    const job=supervise(entity);
    jobs.push(job);
    // Limit startup pressure; each board continues while the next starts.
    await delay(8000);
  }
  const dashboard=await browser.newPage();
  await dashboard.goto('http://localhost:3005/?source=wokwi');
  await dashboard.bringToFront();
  await Promise.all(jobs);
  if(Object.values(states).some(state=>state.state==='failed')) throw Error('Browser simulations stopped; inspect status.json');
}
async function cleanup() {stopping=true;if(relay)relay.stdin.end();if(browser)await browser.close();if(server)await server.close();}
process.on('SIGINT',()=>cleanup().then(()=>process.exit()));
process.on('SIGTERM',()=>cleanup().then(()=>process.exit()));
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(cleanup);
