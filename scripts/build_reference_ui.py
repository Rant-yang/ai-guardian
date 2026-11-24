"""Extract the user's v6 visual reference, keeping backend data as the authority."""
from pathlib import Path
import re
import sys

if '--reset-reference' not in sys.argv:
    raise SystemExit('This legacy importer replaces customized UI files. Use --reset-reference only to intentionally restore the original reference.')

root = Path(__file__).resolve().parent.parent
source = (root/'design/mockups/dashboard-v6.html').read_text(encoding='utf-8')
css = source.split('<style>')[1].split('</style>')[0]
(root/'web/style.css').write_text(css + '''
[hidden]{display:none!important}
button,input,select{font:inherit}button,select{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}
select,input{color:var(--txt);background:#1b1b20;border:1px solid #34343d;border-radius:7px;padding:8px 10px;font-size:11px}
button:disabled{opacity:.4;cursor:default}.app{padding:22px 24px;gap:16px}.topbar{min-height:48px}.brand h1{font-size:17px}.brand .tag{font-size:11px;margin-top:5px}
.grid{grid-template-columns:230px minmax(340px,1fr) 310px;gap:14px}.col-head{padding:17px 16px;font-size:11px}.scope{gap:12px;padding:0 14px 16px}.appitem{padding:13px 12px}.appitem .nm{font-size:13px}.appitem .sub{font-size:10px;margin-top:6px}.chip{font-size:9px;padding:3px 6px}.chips{margin-top:10px}.note{font-size:11px;line-height:1.8}.note strong{color:var(--txt);font-weight:500}.section-title{font-size:10px;color:var(--dim2);letter-spacing:.15em;margin:8px 0 0}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex:none;padding:0 16px 12px}.segments{display:flex;background:#09090b;border:1px solid var(--line);border-radius:7px;padding:3px;gap:3px}.segments button{border:0;background:transparent;color:var(--dim);padding:6px 12px;border-radius:4px;font-size:11px}.segments button.active{color:var(--cyan);background:#c8ff4d13}.filter{max-width:145px}.stream{overflow:auto;gap:8px;padding-bottom:14px;min-height:150px}.evt{text-align:left;color:var(--txt);cursor:pointer;width:100%;grid-template-columns:52px 20px minmax(0,1fr) auto;font:inherit;font-size:12px;padding:12px 10px;gap:8px}.evt.selected{outline:1px solid #c8ff4d80;outline-offset:-1px}.evt .meta{font-size:10px;margin-top:5px;overflow-wrap:anywhere}.evt .ttl{line-height:1.5}.evt .verd{font-size:10px}.coreband{flex:0 0 43%;height:auto;min-height:260px;max-height:420px;background:radial-gradient(ellipse at center,#c8ff4d05,transparent 70%)}.corehead{padding:15px 16px 0}.corehead select{padding:4px 6px;font-size:10px}.core-label{transform:translateY(88px)}.core-label .num{font-size:24px}.core-label .cap{font-size:9px;margin-top:4px}.core-label .sub2{font-size:10px}.detail{padding:0 16px 16px;gap:15px}.verdict{padding:16px}.verdict.neutral{border-color:#c8ff4d35;background:linear-gradient(160deg,#c8ff4d0d,transparent)}.verdict.neutral .big{color:var(--cyan)}.verdict.warning{border-color:#ffa53d60;background:#ffa53d09}.verdict.warning .big{color:var(--amber)}.verdict .task{font-size:12px;line-height:1.8}.kv .line{font-size:11px}.kv .v{font-size:11px}.evi{padding:11px;font-size:11px}.evi .src{font-size:10px;margin-bottom:6px}.evi .body{color:var(--dim);line-height:1.8}.sect-label{font-size:10px}.btn{padding:11px 12px;font-size:12px}.btn.primary{background:var(--cyan);color:#172000}.actions{gap:9px}.footer{display:flex;justify-content:space-between;align-items:center;font-size:10px;color:var(--dim2);gap:12px}.footer b{color:var(--dim);font-weight:400}.empty{margin:auto;padding:30px 15px;text-align:center;color:var(--dim);font-size:12px;line-height:2}.empty .symbol{display:block;color:var(--cyan);font-size:30px;margin-bottom:12px}.auth{display:flex;align-items:center;gap:10px;border:1px solid #c8ff4d30;background:#c8ff4d06;border-radius:10px;padding:12px 16px;font-size:12px}.auth input{flex:1;min-width:120px}.auth small{color:var(--dim);font-size:10px}.auth button{white-space:nowrap}.scope .local-engine{margin-top:10px}.status.offline .pill{color:var(--amber);border-color:#ffa53d50;background:#ffa53d08}.status.offline .dot{background:var(--amber);box-shadow:none;animation:none}.detail pre{font-size:10px;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--dim);line-height:1.6;margin-top:10px}.detail summary{font-size:11px;color:var(--dim);cursor:pointer}#result{line-height:1.7;font-size:11px;color:var(--dim)}.demo-label{color:var(--amber)}
@media(min-width:1500px){.grid{grid-template-columns:260px minmax(400px,1fr) 350px}.evt{padding:14px 12px}.detail{gap:18px}}
@media(max-width:1050px){.app{padding:14px;gap:12px}.grid{grid-template-columns:190px minmax(300px,1fr) 270px;gap:10px}.stat{display:none}.evt{grid-template-columns:20px 1fr auto}.evt .t{display:none}.auth small{display:none}.scope{padding:0 10px 12px}.coreband{min-height:250px}}
@media(max-width:820px){body{overflow:auto}.app{height:auto;min-height:100vh}.grid{grid-template-columns:1fr}.scope{display:grid;grid-template-columns:1fr 1fr}.scope .note,.scope .divider,.scope .section-title{grid-column:1/-1}.center{height:700px}.detail{min-height:300px}.status{font-size:10px}.footer{flex-wrap:wrap}.auth{flex-wrap:wrap}.auth label{width:100%}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
''', encoding='utf-8')
script = source.split('<script>')[1].split('  /* ================= 事件流 ================= */')[0]
script = script.replace('let evtCount = 1284, blkCount = 3;', 'let evtCount = 0, blkCount = 0;')
script = script.replace("name:'Ollama'", "name:'Demo'").replace("name:'MCP 网关'", "name:'MCP · 未接入'").replace("name:'Cursor'", "name:'Codex · 未接入'")
script = script.replace("curve:-1, bypass:false}", "curve:-1, bypass:true}")
script = script.replace("name:'Demo',      curve:-1, bypass:true", "name:'Demo',      curve:-1, bypass:false")
script = script.replace("name:'Demo'", "name:'OpenCode'").replace("name:'MCP · 未接入'", "name:'Gemini CLI'").replace("name:'Codex · 未接入'", "name:'Demo / MCP'")
script = script.replace("name:'Demo / MCP',      curve: 1, bypass:true}", "name:'Demo / MCP',      curve: 1, bypass:true},\n    {fx:0.50, fy:0.08, name:'Ollama', curve:1, bypass:false}")
script = script.replace('function spawnFrom(i){', 'function spawnFrom(i, col){').replace('    const col = pickColor();','')
script = re.sub(r'      blkCount\+\+;\s*setText\(\$blkCount, blkCount\);\s*setText\(\$coreBlk, blkCount\);', '', script)
script = script.replace("          if(b.kind !== 'bad') evtCount++;", '')
start = script.index('      // 生成')
end = script.index('      // 粒子', start)
script = script[:start] + '''      // Event bursts are driven only by backend records.
      while(pending.length && particles.length < 120){
        const e = pending.shift();
        const index = Number.isInteger(e.sourceIndex) ? Math.max(0,Math.min(srcPts.length-1,e.sourceIndex)) : (e.demo?3:0);
        for(let j=0;j<8;j++) spawnFrom(index, {c:e.color,kind:e.kind});
      }
''' + script[end:]
script = script.replace("      setText($coreNum, evtCount.toLocaleString());\n      setText($evtCount, evtCount.toLocaleString());", '')
script = script.replace('const d  = (p[2] + 1) / 2;', 'const d = Math.max(0, Math.min(1, (p[2]/oR + 1)/2));')
script = script.replace('cx = W/2; cy = H/2;', 'cx = W/2; cy = H*.43;')
script = script.replace('R = Math.min(W*0.062, H*0.20);', 'R = Math.min(W*0.073, H*0.18);')
script = script.replace('  function frame(now){', '''  const pending = [];
  let lastDraw = 0;
  window.guardianVizPush = function(e){
    if(pending.length<40) pending.push(e);
  };
  window.guardianVizClear = function(){ pending.length=0; particles.length=0; bursts.length=0; ripples.length=0; };
  function frame(now){''')
script = script.replace('    frames++;', '''    if(document.hidden) {last=now;return;}
    const reduced = document.getElementById('motion').value==='off' || matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(now-lastDraw < (reduced ? 250 : 33)) return;
    lastDraw=now;
    if(reduced){pending.length=0;particles.length=0;bursts.length=0;ripples.length=0;}
    frames++;''')
script = script.replace('drawCore3D(now);', 'drawCore3D(reduced ? 0 : now);')
script = script.replace("setDbg(Math.round(W)+'×'+Math.round(H)+' · 点云'+SPH.length+\n               ' · 粒子'+particles.length+' · 帧'+frames, false);", "setDbg(reduced ? '静态视图' : '点云待机 · 事件触发流量', false);")
script = re.sub(r'  function pickColor\(\)\{.*?\n  \}', '', script, flags=re.S)
script = script.replace('  let evtCount = 0, blkCount = 0;', '')
script += '\n  requestAnimationFrame(frame);\n})();\n'
script=script.replace('(function(){', "(function(){\n  if(typeof location!=='undefined' && location.pathname==='/monitor')return;",1)
script=script.replace('R = Math.min(W*0.073, H*0.18);', "R = typeof location!=='undefined' && ['/orb','/overlay'].includes(location.pathname) ? Math.min(W*.16,H*.25) : Math.min(W*0.073, H*0.18);")
(root/'web/viz.js').write_text(script, encoding='utf-8')
