// =============================================================================
//  webpage.h — HTML for the ESP32-hosted pages, stored in flash (PROGMEM).
//
//  STATUS_PAGE_HTML : live status dashboard. It fetches STATE_JSON_PATH
//                     (/state.json) every couple of seconds and renders it.
//  CONFIG_PAGE_HTML : Wi-Fi / server config form shown in AP (captive) mode.
//
//  Kept as self-contained pages (inline CSS/JS, no external requests) so they
//  work with no internet access.
// =============================================================================
#pragma once
#include <Arduino.h>

static const char STATUS_PAGE_HTML[] PROGMEM = R"HTML(
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 SDR Monitor</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, Arial, sans-serif; background:#0e1116; color:#e6edf3; }
  header { padding:16px 20px; background:#161b22; border-bottom:1px solid #30363d; }
  h1 { margin:0; font-size:18px; }
  .sub { color:#8b949e; font-size:12px; margin-top:4px; }
  .wrap { padding:16px; display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:14px 16px; }
  .k { color:#8b949e; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .v { font-size:22px; margin-top:6px; font-variant-numeric:tabular-nums; }
  .v.small { font-size:16px; }
  .pill { display:inline-block; padding:2px 10px; border-radius:999px; font-size:13px; font-weight:600; }
  .on  { background:#12351f; color:#3fb950; }
  .off { background:#3a1113; color:#f85149; }
  .warn{ background:#3a2d10; color:#d29922; }
  footer { padding:12px 20px; color:#6e7681; font-size:11px; }
  a { color:#58a6ff; }
</style>
</head>
<body>
<header>
  <h1>RTL-SDR Channel Monitor <span id="mode" class="pill warn">...</span></h1>
  <div class="sub">ESP32-WROOM-32 status mirror &mdash; the ESP32 does not receive RF. Updated <span id="age">--</span></div>
</header>
<div class="wrap">
  <div class="card"><div class="k">SDR</div><div class="v"><span id="sdr" class="pill warn">...</span></div></div>
  <div class="card"><div class="k">Server</div><div class="v small" id="server">--</div></div>
  <div class="card"><div class="k">Scan range</div><div class="v small" id="range">--</div></div>
  <div class="card"><div class="k">Strongest candidate</div><div class="v" id="strongest">--</div><div class="k" id="strongestdet" style="margin-top:6px">&nbsp;</div></div>
  <div class="card"><div class="k">Active candidates</div><div class="v" id="active">--</div></div>
  <div class="card"><div class="k">Last detection</div><div class="v small" id="lastdet">--</div></div>
</div>
<footer>ESP32 IP <span id="ip">--</span> &middot; auto-refresh 2s &middot; <a href="/state.json">raw json</a></footer>

<script>
function mhz(hz){ if(!hz||hz<=0) return "--"; return (hz/1e6).toFixed(3)+" MHz"; }
function pill(el,on,txt){ el.textContent=txt; el.className="pill "+(on?"on":"off"); }
async function tick(){
  try{
    const r = await fetch('/state.json',{cache:'no-store'});
    const s = await r.json();
    pill(document.getElementById('mode'), s.serverReachable||s.mock, s.mock?"MOCK":(s.serverReachable?"LIVE":"NO SERVER"));
    pill(document.getElementById('sdr'), s.sdrOnline, s.sdrOnline?("ONLINE"+(s.simulation?" (sim)":"")):"OFFLINE");
    document.getElementById('server').textContent =
      (s.serverReachable?("v"+s.serverVersion+"  up "+Math.round(s.uptimeS)+"s"):"unreachable");
    document.getElementById('range').textContent = mhz(s.scanStartHz)+"  ..  "+mhz(s.scanEndHz);
    document.getElementById('strongest').textContent = mhz(s.strongestHz);
    document.getElementById('strongestdet').textContent =
      (s.strongestPowerDb>-900 ? (s.strongestPowerDb.toFixed(1)+" dB, SNR "+s.strongestSnrDb.toFixed(1)+" dB") : " ");
    document.getElementById('active').textContent = s.activeChannels+" / "+s.totalChannels;
    document.getElementById('lastdet').textContent = s.lastDetectionIso||"--";
    document.getElementById('ip').textContent = s.ip;
    document.getElementById('age').textContent = (s.ageMs/1000).toFixed(1)+"s ago";
  }catch(e){
    document.getElementById('age').textContent = "connection error";
  }
}
tick(); setInterval(tick, 2000);
</script>
</body>
</html>
)HTML";

static const char CONFIG_PAGE_HTML[] PROGMEM = R"HTML(
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 SDR Monitor &mdash; Setup</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font-family:system-ui,Arial,sans-serif; background:#0e1116; color:#e6edf3; }
  .box { max-width:420px; margin:6vh auto; background:#161b22; border:1px solid #30363d; border-radius:12px; padding:22px; }
  h1 { font-size:18px; margin:0 0 4px; }
  p.sub { color:#8b949e; font-size:13px; margin:0 0 18px; }
  label { display:block; font-size:12px; color:#8b949e; margin:12px 0 4px; text-transform:uppercase; letter-spacing:.04em; }
  input { width:100%; padding:10px; border-radius:8px; border:1px solid #30363d; background:#0e1116; color:#e6edf3; font-size:15px; }
  button { margin-top:20px; width:100%; padding:12px; border:0; border-radius:8px; background:#238636; color:#fff; font-size:15px; font-weight:600; cursor:pointer; }
</style>
</head>
<body>
<div class="box">
  <h1>ESP32 SDR Monitor &mdash; Setup</h1>
  <p class="sub">Enter your Wi-Fi and the rtl-sdr-channel-detector server. Saved to flash; the device reboots and connects.</p>
  <form method="POST" action="/save">
    <label>Wi-Fi SSID</label>
    <input name="ssid" required maxlength="63" autocomplete="off">
    <label>Wi-Fi password</label>
    <input name="pass" type="password" maxlength="63" autocomplete="off">
    <label>Server host / IP</label>
    <input name="host" placeholder="192.168.1.50" maxlength="63">
    <label>Server port</label>
    <input name="port" type="number" value="8080" min="1" max="65535">
    <button type="submit">Save &amp; reboot</button>
  </form>
</div>
</body>
</html>
)HTML";
