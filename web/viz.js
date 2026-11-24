
(function(){
  if(typeof location!=='undefined' && location.pathname==='/monitor')return;
  /* ---------- 自检 ---------- */
  const dbgEl = document.getElementById('dbg');
  let errMsg = '';
  function setDbg(t, bad){ if(dbgEl){ dbgEl.textContent = t; dbgEl.classList.toggle('bad', !!bad); } }

  const $coreNum  = document.getElementById('coreNum');
  const $coreBlk  = document.getElementById('coreBlk');
  const $evtCount = document.getElementById('evtCount');
  const $blkCount = document.getElementById('blkCount');
  function setText(el, v){ if(el) el.textContent = v; }

  const canvas = document.getElementById('viz');
  const ctx = canvas.getContext('2d');
  if(!ctx){ setDbg('无法获取 2d 上下文', true); return; }

  /* ---------- 调色板 A ---------- */
  const CHANNELS=['#40dfff','#b67bff','#ff69c7','#ffcc58','#53ffb4'];
  let absorbedColor=CHANNELS[0];
  const ACC  = '#c8ff4d';   // 安全/主色
  const ACC2 = '#6ee7a8';   // 次色（内部探针）
  const WARN = '#ffa53d';
  const BAD  = '#ff5470';

  function hexA(hex, a){
    const h = hex.replace('#',''), n = parseInt(h,16);
    return 'rgba(' + ((n>>16)&255) + ',' + ((n>>8)&255) + ',' + (n&255) + ',' + a + ')';
  }

  let W=0, H=0, cx=0, cy=0, R=54, canvasDpr=0;


  /* ================= 三维 ================= */
  const FOV = 460, CAMD = 460;      // 焦距 / 相机距离
  function proj(x, y, z){
    const s = FOV / Math.max(z + CAMD, 1);
    return { x: cx + x*s, y: cy + y*s, s: s };
  }

  /* ================= 粒子流 ================= */
  let SOURCES = [
    {fx:0.02, fy:0.26, color:CHANNELS[0], name:'Claude Code', curve: 1, bypass:false},
    {fx:0.02, fy:0.78, color:CHANNELS[1], name:'OpenCode',      curve:-1, bypass:false},
    {fx:0.98, fy:0.20, color:CHANNELS[2], name:'Gemini CLI',     curve:-1, bypass:true},
    {fx:0.98, fy:0.82, color:CHANNELS[3], name:'Codex / MCP',      curve: 1, bypass:true},
    {fx:0.50, fy:0.08, color:CHANNELS[4], name:'Ollama', curve:1, bypass:false}
  ];
  ['claude-hook','opencode-plugin','gemini-hook','codex-hook','ollama-local'].forEach((id,i)=>SOURCES[i].id=id);
  const sourceColors=new Map(SOURCES.map(s=>[s.id,s.color]));
  sourceColors.set('qoder-hook','#ff8b62');sourceColors.set('codex-mcp','#8eabff');
  let sourceSignature='';
  let srcPts = [];

  const particles = [], bursts = [], ripples = [];
  let coreFlash = 0, absorbPulse = 0;



  function bezierPt(p0,p1,p2,t){
    const u = 1-t;
    return { x: u*u*p0.x + 2*u*t*p1.x + t*t*p2.x,
             y: u*u*p0.y + 2*u*t*p1.y + t*t*p2.y };
  }
  function makeCtrl(s, tx, ty){
    const mx=(s.x+tx)/2, my=(s.y+ty)/2;
    const dx=tx-s.x, dy=ty-s.y, len=Math.hypot(dx,dy)||1;
    const k = 0.26 * s.curve * len * 0.5;
    return { x: mx - dy/len*k, y: my + dx/len*k };
  }

  function spawnFrom(i, col){
    const s = srcPts[i]; if(!s) return;

    const ang = Math.atan2(s.y-cy, s.x-cx);
    const p2 = { x: cx + Math.cos(ang)*R*0.99, y: cy + Math.sin(ang)*R*0.99 };
    const p0 = { x: s.x, y: s.y };
    const p1 = makeCtrl(s, p2.x, p2.y);
    let L = 0, prev = p0;
    for(let t=0.05;t<=1.001;t+=0.05){
      const p = bezierPt(p0,p1,p2,t);
      L += Math.hypot(p.x-prev.x, p.y-prev.y);
      prev = p;
    }
    particles.push({
      p0:p0, p1:p1, p2:p2, t:-Math.random()*.3,
      speed:(0.24 + Math.random()*0.22) / Math.max(L,1),
      col:col.c, kind:col.kind,
      size:1.3 + Math.random()*1.5,
      bypass:!!s.bypass, armed:false
    });
  }

  function absorb(pt, col, kind){
    absorbedColor=col;
    ripples.push({x:pt.x, y:pt.y, r:2, max:R*2.2, a:0.6, col:col});
    absorbPulse = 1;
    if(kind === 'bad'){
      coreFlash = 1;
      for(let n=0;n<18;n++){
        const a = Math.random()*Math.PI*2, v = 1.5 + Math.random()*3;
        bursts.push({x:pt.x, y:pt.y, vx:Math.cos(a)*v, vy:Math.sin(a)*v,
                     life:1, col:BAD, size:1.1 + Math.random()*1.7});
      }
      ripples.push({x:pt.x, y:pt.y, r:2, max:R*3.2, a:0.85, col:BAD});

    }
  }

  /* ================= 绘制 ================= */
  // Three clean orbital planes shared by luminous rings, beads and source nodes.
  const ORBITS=[{tilt:1.02,angle:-.30,size:1,color:CHANNELS[0]},
    {tilt:1.18,angle:-.78,size:.96,color:CHANNELS[1]},
    {tilt:.88,angle:.48,size:.82,color:CHANNELS[2]}];
  const SOURCE_ORBITS=[0,1,2,1,0];
  function orbitPoint(index, angle, radialScale=1){
    const orbit=ORBITS[index],radius=Math.min(W*.36,H*.37)*orbit.size*radialScale;
    const x=Math.cos(angle)*radius,y=Math.sin(angle)*radius*Math.cos(orbit.tilt);
    const z=Math.sin(angle)*radius*Math.sin(orbit.tilt);
    const p=proj(x*Math.cos(orbit.angle)-y*Math.sin(orbit.angle),
      x*Math.sin(orbit.angle)+y*Math.cos(orbit.angle),z);
    return {x:p.x,y:p.y,z,scale:p.s,near:(1-Math.sin(angle))/2};
  }
  const plasmaSprites=new Map();
  function plasmaSprite(color){
    if(plasmaSprites.has(color))return plasmaSprites.get(color);
    if(plasmaSprites.size>=8 || !document.createElement)return null;
    const sprite=document.createElement('canvas');sprite.width=sprite.height=128;
    const paint=sprite.getContext('2d');if(!paint)return null;
    const glow=paint.createRadialGradient(64,64,0,64,64,64);
    for(const [stop,alpha] of [[0,1],[.28,.72],[.62,.22],[1,0]])glow.addColorStop(stop,hexA(color,alpha));
    paint.fillStyle=glow;paint.fillRect(0,0,128,128);
    plasmaSprites.set(color,sprite);return sprite;
  }
  function plasmaGlow(x,y,radius,color,energy){
    // Spark endpoints can round slightly below zero; Canvas ignores invalid alpha.
    energy=Math.max(0,Math.min(1,energy));
    if(!Number.isFinite(energy)||energy===0)return;
    // Reuse a soft alpha sprite; radius and intensity remain continuous per sample.
    // The bounded cache avoids hundreds of new Canvas gradients every frame.
    const sprite=plasmaSprite(color);
    if(sprite){
      const alpha=ctx.globalAlpha;ctx.globalAlpha=alpha*energy;
      ctx.drawImage(sprite,x-radius,y-radius,radius*2,radius*2);
      ctx.globalAlpha=alpha;return;
    }
    // All stops fade to zero: no stroked spine and no hard-edged circle.
    const glow=ctx.createRadialGradient(x,y,0,x,y,radius);
    glow.addColorStop(0,hexA(color,energy));
    glow.addColorStop(.28,hexA(color,energy*.72));
    glow.addColorStop(.62,hexA(color,energy*.22));
    glow.addColorStop(1,hexA(color,0));
    ctx.fillStyle=glow;ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fill();
  }
  let orbitFrame=null;
  function orbitSamples(T){
    // Rear/front passes share precisely the same geometry within one frame.
    // Size is part of the key because reduced-motion time stays at zero.
    const key=[T,W,H,cx,cy,R].join(':');
    if(orbitFrame?.key===key)return orbitFrame.rings;
    const rings=ORBITS.map((orbit,ring)=>{
      const samples=[];
      for(let j=0;j<144;j++){
        const angle=j/144*Math.PI*2;
        const flow=angle*3-T*.00065*(ring%2?-1:1)+ring;
        const p=orbitPoint(ring,angle,1+.009*Math.sin(flow*1.7));
        samples.push({p,density:.80+.20*Math.sin(flow),
          width:Math.max(5,R*.19)*p.scale*(.90+.15*Math.sin(flow+1))});
      }
      return samples;
    });
    orbitFrame={key,rings};return rings;
  }
  function drawOrbits(T,front){
    const rings=orbitSamples(T);
    ctx.save();
    for(let ring=0;ring<ORBITS.length;ring++){
      const color=ORBITS[ring].color;
      // Overlapping soft density samples form a volume, not a collection of lines.
      // Samples stay close enough that individual blobs cannot resolve as beads.
      for(const {p,density,width} of rings[ring]){
        if((p.z<0)!==front)continue;
        plasmaGlow(p.x,p.y,width*1.8,color,(.055+p.near*.045)*density);
        plasmaGlow(p.x,p.y,width,color,(.075+p.near*.075)*density);
      }
      // Just three short-lived sparks per plane, fading before they become noise.
      if(T)for(let j=0;j<3;j++){
        const cycle=T/1600+j*.337+ring*.21,age=cycle-Math.floor(cycle);
        if(age>.68)continue;
        const angle=j*2.094+Math.floor(cycle)*1.71+ring;
        const p=orbitPoint(ring,angle,1+age*.13);
        if((p.z<0)!==front)continue;
        const fade=Math.sin(Math.PI*age/.68);
        plasmaGlow(p.x,p.y-age*3,2.6*p.scale,color,fade*.55);
      }
    }
    ctx.restore();
  }

  function drawInterorbitalDust(T,front){
    // Ambient stardust, not dark-matter detection or action traffic. Fixed population.
    const outer=Math.min(W*.36,H*.37)*.90,inner=R*1.20;
    if(outer<=inner)return;
    ctx.save();
    for(let i=0;i<28;i++){
      const fraction=((i*47+19)%101)/101;
      const radius=Math.sqrt(inner*inner+fraction*(outer*outer-inner*inner));
      const angle=i*2.399963+T*.000018*(i%2?-1:1);
      const z=Math.sin(angle+i*.7)*R*.55;
      if((z<0)!==front)continue;
      const p=proj(Math.cos(angle)*radius,Math.sin(angle)*radius*.90,z);
      // Keep the central sphere and the outer ring silhouette clean.
      const distance=Math.hypot(p.x-cx,p.y-cy);
      if(distance<R*1.16||distance>outer)continue;
      const depth=(1-z/(R*.55))/2;
      const breathe=.82+.18*Math.sin(T*.0007+i*1.7);
      const bright=i%7===0;
      const color=i%3===0?'#d1b7ff':i%3===1?'#9deaf2':'#e9e2cf';
      const alpha=(bright?.38:.13+depth*.12)*breathe;
      if(bright)plasmaGlow(p.x,p.y,3.6*p.s,color,alpha*.35);
      ctx.fillStyle=hexA(color,alpha);
      ctx.beginPath();ctx.arc(p.x,p.y,(bright?.80:.35+(i%3)*.12)*p.s,0,Math.PI*2);ctx.fill();
      // Two barely visible pockets connect the sparse points without a background sheet.
      if(i===4||i===17)plasmaGlow(p.x,p.y,R*.38,color,.018);
    }
    ctx.restore();
  }

  function drawSurfaceWeave(T,radius){
    // A rotating latitude/longitude weave ON the opaque surface, never a detached cage.
    const yaw=T*.00013,tilt=.30;
    function surface(lat,lon){
      const x=Math.cos(lat)*Math.cos(lon+yaw),z=Math.cos(lat)*Math.sin(lon+yaw),y=Math.sin(lat);
      return {x:cx+x*radius,y:cy+(y*Math.cos(tilt)-z*Math.sin(tilt))*radius,
        z:y*Math.sin(tilt)+z*Math.cos(tilt)};
    }
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,radius,0,Math.PI*2);ctx.clip();
    ctx.strokeStyle='rgba(152,235,255,.16)';ctx.lineWidth=.7;
    ctx.shadowBlur=2;ctx.shadowColor='rgba(90,220,255,.25)';
    for(let axis=0;axis<1;axis++){
      const lines=12,steps=56;
      for(let i=1;i<lines;i++){
        ctx.beginPath();let pen=false;
        for(let j=0;j<=steps;j++){
          const lat=axis?(-Math.PI/2+j/steps*Math.PI):(-Math.PI/2+i/lines*Math.PI);
          const lon=axis?i/lines*Math.PI*2:j/steps*Math.PI*2;
          const p=surface(lat+.018*Math.sin(lon*4-T*.0007+i*.4),lon);
          if(p.z>=0){pen=false;continue;}
          if(pen)ctx.lineTo(p.x,p.y);else ctx.moveTo(p.x,p.y);pen=true;
        }
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  function drawCore3D(T){

    const key = coreFlash > 0.05 ? BAD : absorbedColor;

    // Local glow only: transparent desktop corners stay completely clear.
    const g = ctx.createRadialGradient(cx, cy, R*.6, cx, cy, R*2.5);
    g.addColorStop(0, hexA(key, .14 + coreFlash*.15));
    g.addColorStop(.55, hexA(key, .035));
    g.addColorStop(1, hexA(key, 0));
    ctx.fillStyle=g;
    ctx.beginPath();ctx.arc(cx,cy,R*2.5,0,Math.PI*2);ctx.fill();

    const rr = R * (1 + Math.sin(T*.0022)*.02 + absorbPulse*.08);
    // Opaque spherical body occludes the rear shell and orbit segments.
    // Off-center light, narrow highlight and a deep terminator avoid a flat disc.
    const cg=ctx.createRadialGradient(cx-rr*.36,cy-rr*.40,rr*.015,cx-rr*.12,cy-rr*.12,rr*1.15);
    cg.addColorStop(0,'#ffffff');
    cg.addColorStop(.09,'#fffbd1');
    cg.addColorStop(.30,coreFlash>.05?BAD:'#ffd56b');
    cg.addColorStop(.51,'#38d9ef');
    cg.addColorStop(.74,'#375cbd');
    cg.addColorStop(.88,'#792ba2');
    cg.addColorStop(1,'#141031');
    ctx.fillStyle=cg;
    ctx.beginPath();ctx.arc(cx,cy,rr,0,Math.PI*2);ctx.fill();
    // Colored reflected light on the far rim, clipped to the spherical silhouette.
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,rr,0,Math.PI*2);ctx.clip();
    const rim=ctx.createRadialGradient(cx+rr*.85,cy+rr*.35,0,cx+rr*.85,cy+rr*.35,rr*.65);
    rim.addColorStop(0,hexA('#ec66ff',.85));rim.addColorStop(1,hexA(CHANNELS[1],0));
    ctx.fillStyle=rim;ctx.fillRect(cx-rr,cy-rr,rr*2,rr*2);ctx.restore();
    drawSurfaceWeave(T,rr);
    // White-gold energy focus, with short tapered rays rather than a dotted cage.
    const fx=cx-rr*.25,fy=cy-rr*.28;
    const flare=ctx.createRadialGradient(fx,fy,0,fx,fy,rr*1.3);
    flare.addColorStop(0,'rgba(255,255,255,1)');
    flare.addColorStop(.16,'rgba(255,255,239,.98)');
    flare.addColorStop(.35,hexA(coreFlash>.05?BAD:'#ffe695',.85));
    flare.addColorStop(.7,hexA('#ffd770',.12));
    flare.addColorStop(1,hexA(key,0));
    ctx.fillStyle=flare;ctx.beginPath();ctx.arc(fx,fy,rr*1.3,0,Math.PI*2);ctx.fill();
    ctx.save();ctx.strokeStyle=flare;
    for(let i=0;i<18;i++){
      const a=i*Math.PI/9+T*.000015,length=rr*(i%3===0?1.25:.72)*(1+absorbPulse*.24);
      ctx.lineWidth=i%3===0?1.2:.65;
      ctx.beginPath();ctx.moveTo(fx,fy);ctx.lineTo(fx+Math.cos(a)*length,fy+Math.sin(a)*length);ctx.stroke();
    }
    ctx.restore();

    // 吸收脉冲
    if(absorbPulse > 0.02){
      ctx.strokeStyle = hexA(key, absorbPulse*0.5);
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(cx, cy, rr*(1.4 + (1-absorbPulse)*0.9), 0, Math.PI*2); ctx.stroke();
      absorbPulse *= 0.90;
    }
  }

  // Each source keeps its color and phase; this motion is ambient, not traffic.
  function sourcePosition(index, T){
    const phase=index*Math.PI*2/SOURCES.length;
    const t=T*(.00016+index*.000019)*(index%2 ? -1 : 1)+phase;
    return orbitPoint(SOURCE_ORBITS[index%SOURCE_ORBITS.length],t);
  }
  function drawSourceTrails(T, front){
    if(!T)return;
    ctx.save();
    for(const s of srcPts){
      for(let j=28;j>0;j--){
        const p=sourcePosition(s.index,T-j*85);
        if((p.z<0)!==front)continue;
        const fade=Math.pow(1-j/29,1.8);
        plasmaGlow(p.x,p.y,(2+fade*3.5)*p.scale,s.color,fade*(.09+p.near*.10));
      }
    }
    ctx.restore();
  }
  function drawSource(s, T){
    const col=s.color||ACC, scale=s.scale||1, near=s.near??.5;
    const radius=5.4*scale*(.84+near*.22);
    ctx.save();
    const halo=ctx.createRadialGradient(s.x,s.y,radius*.6,s.x,s.y,radius*2.6);
    halo.addColorStop(0,hexA(col,.30+near*.18));halo.addColorStop(1,hexA(col,0));
    ctx.fillStyle=halo;ctx.beginPath();ctx.arc(s.x,s.y,radius*2.6,0,Math.PI*2);ctx.fill();
    // Solid tiny planet: directional light and dark terminator, not a flat luminous dot.
    const surface=ctx.createRadialGradient(s.x-radius*.36,s.y-radius*.40,radius*.02,
      s.x-radius*.15,s.y-radius*.15,radius*1.17);
    surface.addColorStop(0,'#f6ffff');surface.addColorStop(.13,'#d7f1ff');
    surface.addColorStop(.38,col);surface.addColorStop(.72,'#172b47');surface.addColorStop(1,'#030715');
    ctx.globalAlpha=.70+near*.30;
    ctx.fillStyle=surface;ctx.beginPath();ctx.arc(s.x,s.y,radius,0,Math.PI*2);ctx.fill();
    ctx.beginPath();ctx.arc(s.x,s.y,radius,0,Math.PI*2);ctx.clip();
    const rim=ctx.createRadialGradient(s.x+radius*.9,s.y+radius*.3,0,
      s.x+radius*.9,s.y+radius*.3,radius*.7);
    rim.addColorStop(0,hexA(col,.75));rim.addColorStop(1,hexA(col,0));
    ctx.fillStyle=rim;ctx.fillRect(s.x-radius,s.y-radius,radius*2,radius*2);
    const glint=ctx.createRadialGradient(s.x-radius*.32,s.y-radius*.37,0,
      s.x-radius*.32,s.y-radius*.37,radius*.24);
    glint.addColorStop(0,'rgba(255,255,255,.85)');glint.addColorStop(1,'rgba(255,255,255,0)');
    ctx.fillStyle=glint;ctx.fillRect(s.x-radius,s.y-radius,radius*2,radius*2);
    ctx.restore();
    ctx.font = '500 9px "JetBrains Mono", Consolas, monospace';
    ctx.fillStyle = 'rgba(140,140,150,.9)';
    ctx.textBaseline = 'middle';
    const left = s.x < cx;
    ctx.textAlign = left ? 'left' : 'right';
    if(typeof location!=='undefined' && location.pathname==='/overlay')return;
    ctx.fillText(s.name, s.x + (left ? 15 : -15), s.y);
  }

  /* ================= 尺寸 ================= */
  function ensureSize(){
    const r = canvas.getBoundingClientRect();
    if(r.width < 4 || r.height < 4) return false;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const pw = Math.round(r.width*dpr), ph = Math.round(r.height*dpr);
    // CSS size and DPR can change while backing pixels remain identical.
    if(canvas.width !== pw || canvas.height !== ph || W !== r.width || H !== r.height || canvasDpr !== dpr){
      if(canvas.width !== pw) canvas.width = pw;
      if(canvas.height !== ph) canvas.height = ph;
      ctx.setTransform(dpr,0,0,dpr,0,0);
      canvasDpr = dpr;
      W = r.width; H = r.height;
      cx = W/2; cy = H*(typeof location!=='undefined' && location.pathname==='/overlay'?.5:.43);
      R = typeof location!=='undefined' && ['/orb','/overlay'].includes(location.pathname) ? Math.min(W*.15,H*.19) : Math.min(W*0.073, H*0.18);
      srcPts = SOURCES.map(function(s,index){
        return {index,id:s.id,fx:s.fx, fy:s.fy, name:s.name, color:s.color, curve:s.curve, bypass:s.bypass,
                x:s.fx*W, y:s.fy*H};
      });
    }
    return true;
  }

  /* ================= 主循环 ================= */
  let last = performance.now(), spawnAcc = 0, frames = 0;

  const pending = [];
  let lastDraw = 0;
  window.guardianVizPush = function(e){
    if(pending.length<40) pending.push(e);
  };
  window.guardianVizSources = function(rows){
    if(!Array.isArray(rows)||!rows.length||rows.length>32||rows.some(r=>!r||typeof r.id!=='string'||!/^[-a-z0-9]+$/.test(r.id)||typeof r.name!=='string'||r.name.length>100))return;
    if(new Set(rows.map(r=>r.id)).size!==rows.length)return;
    const signature=JSON.stringify(rows);if(signature===sourceSignature)return;
    sourceSignature=signature;
    SOURCES=rows.map((r,index)=>{
      let hash=0;for(const ch of r.id)hash=(hash*31+ch.charCodeAt(0))>>>0;
      return {id:r.id,name:r.name,color:sourceColors.get(r.id)||CHANNELS[hash%CHANNELS.length],
              fx:index%2?.98:.02,fy:.5,curve:index%2?-1:1,bypass:false};
    });
    pending.length=0;particles.length=0;canvasDpr=0;
  };
  window.guardianVizClear = function(){ pending.length=0; particles.length=0; bursts.length=0; ripples.length=0; };
  function frame(now){
    requestAnimationFrame(frame);
    if(document.hidden) {last=now;return;}
    const reduced = document.getElementById('motion').value==='off' || matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(now-lastDraw < (reduced ? 250 : 33)) return;
    lastDraw=now;
    if(reduced){pending.length=0;particles.length=0;bursts.length=0;ripples.length=0;}
    frames++;
    try{
      const dt = Math.min(now - last, 40); last = now;
      if(!ensureSize()){ setDbg('canvas 尺寸为 0'); return; }
      ctx.clearRect(0,0,W,H);
      if(document.body?.classList?.contains?.('cosmic-stage')){
        // Stable, sparse distant stars only in the optional black presentation mode.
        for(let i=0;i<22;i++){
          const x=((i*137.51+29)%997)/997*W,y=((i*211.73+83)%991)/991*H;
          ctx.fillStyle=hexA('#b5c7ec',.10+(i%4)*.035);
          ctx.beginPath();ctx.arc(x,y,.35+(i%3)*.15,0,Math.PI*2);ctx.fill();
        }
      }

      const motionTime=reduced ? 0 : now;
      for(const s of srcPts) Object.assign(s,sourcePosition(s.index,motionTime));
      // Rear source nodes are occluded by the solid core, just like rear orbits.
      drawInterorbitalDust(motionTime,false);
      drawOrbits(motionTime,false);
      drawSourceTrails(motionTime,false);
      for(const s of srcPts) if(s.z>=0) drawSource(s,motionTime);

      // Event bursts are driven only by backend records.
      while(pending.length && particles.length < 120){
        const e = pending.shift();
        const index = typeof e.sourceId==='string' ? srcPts.findIndex(s=>s.id===e.sourceId) :
          Number.isInteger(e.sourceIndex)&&e.sourceIndex>=0&&e.sourceIndex<srcPts.length ? e.sourceIndex : -1;
        if(index<0)continue; // Unknown sources must never animate another client's node.
        for(let j=0;j<12 && particles.length<160;j++) spawnFrom(index, {c:srcPts[index].color,kind:e.kind});
      }
      // 粒子
      for(let i=particles.length-1;i>=0;i--){
        const b = particles[i];
        b.t += b.speed * dt;
        if(b.t<0)continue;

        for(let k=11;k>=0;k--){
          const tt = b.t - k*0.012;
          if(tt < 0) continue;
          if(tt > 1) break;
          const pt = bezierPt(b.p0,b.p1,b.p2,tt);
          ctx.fillStyle = hexA(b.col, (1 - k/12)*0.75);
          ctx.beginPath(); ctx.arc(pt.x, pt.y, b.size*(1 - k*.065), 0, Math.PI*2); ctx.fill();
        }

        const pt = bezierPt(b.p0,b.p1,b.p2,Math.min(b.t,1));
        ctx.fillStyle = hexA(b.col, 0.13);
        ctx.beginPath(); ctx.arc(pt.x, pt.y, b.size*4.6, 0, Math.PI*2); ctx.fill();

        const d = Math.hypot(pt.x-cx, pt.y-cy);
        const shield = R*2.18;
        if(!b.bypass && !b.armed && d < shield && b.kind === 'bad'){
          b.armed = true; absorb(pt, BAD, 'bad'); particles.splice(i,1); continue;
        }
        if(b.t >= 1){
          absorb(pt, b.col, b.kind);

          particles.splice(i,1);
        }
      }

      drawCore3D(reduced ? 0 : now);
      drawInterorbitalDust(motionTime,true);
      drawOrbits(motionTime,true);
      drawSourceTrails(motionTime,true);
      for(const s of srcPts) if(s.z<0) drawSource(s,motionTime);

      for(let i=ripples.length-1;i>=0;i--){
        const r = ripples[i]; r.r += 2.0; r.a *= 0.962;
        if(r.r > r.max || r.a < 0.02){ ripples.splice(i,1); continue; }
        ctx.strokeStyle = hexA(r.col, r.a*0.7);
        ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.arc(r.x, r.y, r.r, 0, Math.PI*2); ctx.stroke();
      }
      for(let i=bursts.length-1;i>=0;i--){
        const p = bursts[i];
        p.x += p.vx; p.y += p.vy; p.vx *= 0.94; p.vy *= 0.94; p.life *= 0.94;
        if(p.life < 0.05){ bursts.splice(i,1); continue; }
        ctx.fillStyle = hexA(p.col, p.life);
        ctx.beginPath(); ctx.arc(p.x, p.y, p.size*p.life, 0, Math.PI*2); ctx.fill();
      }

      coreFlash *= 0.93;


      if(frames % 15 === 0 && !errMsg){
        setDbg(reduced ? '静态视图' : '光轨巡航 · 事件触发流量', false);
      }
    }catch(ex){
      errMsg = ex.message || String(ex);
      setDbg('报错: ' + errMsg, true);
    }
  }


  requestAnimationFrame(frame);
})();
